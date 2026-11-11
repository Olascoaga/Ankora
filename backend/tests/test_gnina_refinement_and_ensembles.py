"""Unit tests for ADR-028 GNINA refinement mode, built-in ensembles, and VRAM scheduling.

Every score, pose, and `nvidia-smi` output in this module is explicitly synthetic
and exercises schema validation, CLI construction, ensemble provenance, resource
arbitration, Methods rendering, and Campaign Export v4 invariants without claiming
empirical benchmarking.
"""

from __future__ import annotations

import json
import subprocess
import threading
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError
from test_gnina_export import _manifest as _export_manifest
from test_gnina_export import _service as _export_service
from test_gnina_export import _store_job as _store_export_job
from test_gnina_methods import _render as _render_single_methods
from test_gnina_screening_admission import _setup as _setup_admission
from test_gnina_screening_preflight import one_prepared as one_prepared
from test_gnina_screening_preflight import screening as screening

from ankora_backend.adapters.engines.gnina import (
    VERIFIED_GNINA_1_3_3_SHA256,
    GninaInstallation,
    build_gnina_arguments,
    resolve_cnn_model_identity,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.gnina_screening_store import GninaScreeningStore
from ankora_backend.persistence.gnina_store import GninaJobStore
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.docking import DockingJobPhase, DockingJobStatus
from ankora_backend.schemas.gnina import (
    GninaCnnModelIdentity,
    GninaDockingParameters,
    GninaDockingRequest,
    GninaExecutionEvidence,
    GninaJobRecord,
    GninaPoseArtifact,
    GninaPoseResult,
    GninaToolIdentity,
)
from ankora_backend.schemas.gnina_screening import (
    GninaScreeningCampaignRecord,
    GninaScreeningEntry,
    GninaScreeningRequest,
    GninaScreeningSelection,
)
from ankora_backend.schemas.ligands import (
    LigandFilterDisposition,
    LigandLibraryFilterPlan,
    LigandMicrostatePlan,
)
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode
from ankora_backend.services.campaign_export import CampaignExportService
from ankora_backend.services.gnina_gpu_observer import query_single_gpu_memory_bytes
from ankora_backend.services.gnina_screening_admission import admit_screening
from ankora_backend.services.methods_report import MethodsReportService
from ankora_backend.services.resource_arbiter import (
    ResourceArbiter,
    ResourceClaim,
    gnina_claim,
)
from ankora_backend.services.result_catalog import ResultCatalogService

_MIB = 1024 * 1024
_GIB = 1024 * _MIB
_SYNTHETIC_UUID = "GPU-11111111-2222-3333-4444-555555555555"


def test_gnina_parameters_enforce_cuda_and_timeout_floor_for_refinement() -> None:
    params = GninaDockingParameters(
        compute="cuda",
        cnn_scoring="refinement",
        cnn_model="default_1_3_ensemble",
        timeout_minutes=10,
    )
    assert params.cnn_scoring == "refinement"
    assert params.cnn_model == "default_1_3_ensemble"
    assert params.timeout_minutes == 10

    for selector in ("dense_1_3", "default_1_3_ensemble", "default1.0"):
        rescore = GninaDockingParameters(compute="cpu", cnn_scoring="rescore", cnn_model=selector)
        assert rescore.cnn_model == selector

    with pytest.raises(ValidationError, match="compute='cuda'"):
        GninaDockingParameters(compute="cpu", cnn_scoring="refinement", timeout_minutes=30)

    with pytest.raises(ValidationError, match="timeout_minutes >= 10"):
        GninaDockingParameters(compute="cuda", cnn_scoring="refinement", timeout_minutes=9)


def test_build_gnina_arguments_omits_cnn_flag_only_for_default_1_3_ensemble(
    tmp_path: Path,
) -> None:
    box = BindingBox(
        center_x=1.0, center_y=2.0, center_z=3.0, size_x=12.0, size_y=14.0, size_z=16.0
    )
    rec = tmp_path / "receptor.pdbqt"
    lig = tmp_path / "ligand.pdbqt"
    out = tmp_path / "out.pdbqt"

    args_1_3 = build_gnina_arguments(
        receptor_path=rec,
        ligand_path=lig,
        output_path=out,
        box=box,
        parameters=GninaDockingParameters(
            compute="cuda",
            cnn_scoring="refinement",
            cnn_model="default_1_3_ensemble",
            timeout_minutes=15,
        ),
    )
    assert "--cnn" not in args_1_3
    assert args_1_3[args_1_3.index("--cnn_scoring") + 1] == "refinement"
    assert "--device" in args_1_3

    args_1_0 = build_gnina_arguments(
        receptor_path=rec,
        ligand_path=lig,
        output_path=out,
        box=box,
        parameters=GninaDockingParameters(
            compute="cuda",
            cnn_scoring="refinement",
            cnn_model="default1.0",
            timeout_minutes=15,
        ),
    )
    assert args_1_0[args_1_0.index("--cnn") + 1] == "default1.0"
    assert args_1_0[args_1_0.index("--cnn_scoring") + 1] == "refinement"

    args_dense = build_gnina_arguments(
        receptor_path=rec,
        ligand_path=lig,
        output_path=out,
        box=box,
        parameters=GninaDockingParameters(
            compute="cpu",
            cnn_scoring="rescore",
            cnn_model="dense_1_3",
        ),
    )
    assert args_dense[args_dense.index("--cnn") + 1] == "dense_1_3"
    assert args_dense[args_dense.index("--cnn_scoring") + 1] == "rescore"
    assert "--no_gpu" in args_dense


def test_resolve_cnn_model_identity_pins_ensembles_to_verified_binary() -> None:
    dense = resolve_cnn_model_identity("dense_1_3", binary_sha256="a" * 64)
    assert dense == GninaCnnModelIdentity(
        selector="dense_1_3",
        cli_argument="dense_1_3",
        member_names=("dense_1_3",),
        member_count=1,
    )

    ensemble_1_3 = resolve_cnn_model_identity(
        "default_1_3_ensemble", binary_sha256=VERIFIED_GNINA_1_3_3_SHA256
    )
    assert ensemble_1_3 == GninaCnnModelIdentity(
        selector="default_1_3_ensemble",
        cli_argument=None,
        member_names=("dense_1_3", "dense_1_3_PT_KD_3", "crossdock_default2018_KD_4"),
        member_count=3,
    )

    ensemble_1_0 = resolve_cnn_model_identity(
        "default1.0", binary_sha256=VERIFIED_GNINA_1_3_3_SHA256.upper()
    )
    assert ensemble_1_0 == GninaCnnModelIdentity(
        selector="default1.0",
        cli_argument="default1.0",
        member_names=(
            "dense",
            "general_default2018_3",
            "dense_3",
            "crossdock_default2018",
            "redock_default2018_2",
        ),
        member_count=5,
    )

    for selector in ("default_1_3_ensemble", "default1.0"):
        with pytest.raises(AnkoraDomainError) as error:
            resolve_cnn_model_identity(selector, binary_sha256="a" * 64)
        assert error.value.code == "GNINA_CNN_ENSEMBLE_UNVERIFIED_BINARY"
        assert error.value.details["selector"] == selector


def test_gnina_claim_scales_host_ram_and_cuda_vram() -> None:
    cpu_rescore = gnina_claim("synthetic-1", GninaDockingParameters(compute="cpu"))
    assert cpu_rescore.memory_bytes == 2 * _GIB
    assert cpu_rescore.gpu_slots == 0
    assert cpu_rescore.gpu_memory_bytes == 0

    cpu_ensemble = gnina_claim(
        "synthetic-2",
        GninaDockingParameters(compute="cpu", cnn_model="default_1_3_ensemble"),
    )
    assert cpu_ensemble.memory_bytes == (5 * _GIB) // 2
    assert cpu_ensemble.gpu_slots == 0
    assert cpu_ensemble.gpu_memory_bytes == 0

    cuda_rescore_single = gnina_claim("synthetic-3", GninaDockingParameters(compute="cuda"))
    assert cuda_rescore_single.memory_bytes == 2 * _GIB
    assert cuda_rescore_single.gpu_slots == 1
    assert cuda_rescore_single.gpu_memory_bytes == 1 * _GIB

    cuda_rescore_ensemble = gnina_claim(
        "synthetic-4",
        GninaDockingParameters(compute="cuda", cnn_model="default_1_3_ensemble"),
    )
    assert cuda_rescore_ensemble.memory_bytes == (5 * _GIB) // 2
    assert cuda_rescore_ensemble.gpu_memory_bytes == (3 * _GIB) // 2

    cuda_refine_single = gnina_claim(
        "synthetic-5",
        GninaDockingParameters(
            compute="cuda", cnn_scoring="refinement", cnn_model="dense_1_3", timeout_minutes=15
        ),
    )
    assert cuda_refine_single.memory_bytes == (5 * _GIB) // 2
    assert cuda_refine_single.gpu_memory_bytes == (3 * _GIB) // 2

    cuda_refine_ensemble = gnina_claim(
        "synthetic-6",
        GninaDockingParameters(
            compute="cuda",
            cnn_scoring="refinement",
            cnn_model="default1.0",
            timeout_minutes=15,
        ),
    )
    assert cuda_refine_ensemble.memory_bytes == (5 * _GIB) // 2
    assert cuda_refine_ensemble.gpu_memory_bytes == 2 * _GIB


def test_query_single_gpu_memory_bytes_handles_single_gpu_and_ambiguous_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    monkeypatch.delenv("NVIDIA_VISIBLE_DEVICES", raising=False)

    monkeypatch.setattr(
        "ankora_backend.services.gnina_gpu_observer.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=f"{_SYNTHETIC_UUID}, Disabled, 8151, 7600\n",
            stderr="",
        ),
    )
    assert query_single_gpu_memory_bytes() == (8151 * _MIB, 7600 * _MIB)

    # Visibility remapping disables single-GPU VRAM inference cleanly.
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    assert query_single_gpu_memory_bytes() is None
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES")

    # MIG enabled or multi-GPU output returns None rather than raising.
    for bad_stdout in (
        f"{_SYNTHETIC_UUID}, Enabled, 8151, 7600\n",
        f"{_SYNTHETIC_UUID}, Disabled, 8151, 7600\n{_SYNTHETIC_UUID}, Disabled, 8151, 7600\n",
    ):
        monkeypatch.setattr(
            "ankora_backend.services.gnina_gpu_observer.subprocess.run",
            lambda *args, _out=bad_stdout, **kwargs: subprocess.CompletedProcess(
                args=args[0],
                returncode=0,
                stdout=_out,
                stderr="",
            ),
        )
        assert query_single_gpu_memory_bytes() is None


def test_resource_arbiter_enforces_vram_axis_while_keeping_zero_vram_claims_compatible(
    tmp_path: Path,
) -> None:
    # Synthetic arbiter with 3 GiB total VRAM and 512 MiB reserve -> 2.5 GiB usable VRAM.
    arbiter = ResourceArbiter(
        cpu_threads=8,
        gpu_slots=2,
        memory_total_bytes=16 * _GIB,
        memory_reserve_bytes=2 * _GIB,
        disk_path=tmp_path,
        disk_total_bytes=64 * _GIB,
        disk_reserve_bytes=2 * _GIB,
        memory_available=lambda: 16 * _GIB,
        disk_free=lambda: 64 * _GIB,
        gpu_memory_total_bytes=3 * _GIB,
        gpu_memory_reserve_bytes=512 * _MIB,
        gpu_memory_free=lambda: 3 * _GIB,
    )

    impossible = ResourceClaim(
        workload="gnina_job",
        owner_id="synthetic-too-big",
        cpu_threads=1,
        memory_bytes=1 * _GIB,
        disk_bytes=64 * _MIB,
        gpu_slots=1,
        gpu_memory_bytes=3 * _GIB,
    )
    with pytest.raises(AnkoraDomainError) as exc_info:
        arbiter.validate(impossible)
    assert exc_info.value.code == "RESOURCE_REQUEST_EXCEEDS_CAPACITY"
    assert exc_info.value.details["resources"] == {
        "gpu_memory_bytes": {
            "requested": 3 * _GIB,
            "capacity": 3 * _GIB - 512 * _MIB,
        }
    }

    # Zero-VRAM GPU claims (e.g., AutoDock-GPU) bypass VRAM limits even if VRAM were 0.
    zero_vram_arbiter = ResourceArbiter(
        cpu_threads=4,
        gpu_slots=1,
        memory_total_bytes=8 * _GIB,
        memory_reserve_bytes=1 * _GIB,
        disk_path=tmp_path,
        disk_total_bytes=16 * _GIB,
        disk_reserve_bytes=1 * _GIB,
        memory_available=lambda: 8 * _GIB,
        disk_free=lambda: 16 * _GIB,
        gpu_memory_total_bytes=256 * _MIB,
        gpu_memory_reserve_bytes=256 * _MIB,
    )
    ad_gpu_lease = zero_vram_arbiter.acquire(
        ResourceClaim(
            workload="autodock_gpu",
            owner_id="synthetic-ad-gpu",
            cpu_threads=1,
            memory_bytes=1 * _GIB,
            disk_bytes=16 * _MIB,
            gpu_slots=1,
            gpu_memory_bytes=0,
        )
    )
    ad_gpu_lease.release()

    # Unknown VRAM host (Windows / CPU-only where gpu_memory_total_bytes is None) skips VRAM checks.
    unknown_vram_arbiter = ResourceArbiter(
        cpu_threads=4,
        gpu_slots=1,
        memory_total_bytes=8 * _GIB,
        memory_reserve_bytes=1 * _GIB,
        disk_path=tmp_path,
        disk_total_bytes=16 * _GIB,
        disk_reserve_bytes=1 * _GIB,
        memory_available=lambda: 8 * _GIB,
        disk_free=lambda: 16 * _GIB,
        gpu_memory_total_bytes=None,
    )
    unknown_lease = unknown_vram_arbiter.acquire(
        ResourceClaim(
            workload="gnina_job",
            owner_id="synthetic-unknown-vram",
            cpu_threads=1,
            memory_bytes=1 * _GIB,
            disk_bytes=16 * _MIB,
            gpu_slots=1,
            gpu_memory_bytes=2 * _GIB,
        )
    )
    unknown_lease.release()

    # Concurrent VRAM gating: two 1.5 GiB claims fit individually in 2.5 GiB usable VRAM,
    # so the second waits even though gpu_slots=2 has a spare slot.
    claim_one = ResourceClaim(
        workload="gnina_job",
        owner_id="synthetic-vram-1",
        cpu_threads=1,
        memory_bytes=1 * _GIB,
        disk_bytes=16 * _MIB,
        gpu_slots=1,
        gpu_memory_bytes=(3 * _GIB) // 2,
    )
    claim_two = ResourceClaim(
        workload="gnina_job",
        owner_id="synthetic-vram-2",
        cpu_threads=1,
        memory_bytes=1 * _GIB,
        disk_bytes=16 * _MIB,
        gpu_slots=1,
        gpu_memory_bytes=(3 * _GIB) // 2,
    )
    first_lease = arbiter.acquire(claim_one)
    snap = arbiter.snapshot()
    assert snap.gpu_memory_reserved_bytes == (3 * _GIB) // 2
    assert snap.active_allocations[0].gpu_memory_bytes == (3 * _GIB) // 2
    assert arbiter.try_acquire(claim_two) is None

    second_granted = threading.Event()
    release_second = threading.Event()

    def _acquire_second() -> None:
        lease = arbiter.acquire(claim_two)
        second_granted.set()
        release_second.wait(timeout=2)
        lease.release()

    worker = threading.Thread(target=_acquire_second)
    worker.start()
    assert not second_granted.wait(timeout=0.1)
    assert arbiter.snapshot().queued_requests == 1

    first_lease.release()
    assert second_granted.wait(timeout=1.5)
    assert arbiter.snapshot().gpu_memory_reserved_bytes == (3 * _GIB) // 2
    release_second.set()
    worker.join(timeout=1.5)
    assert arbiter.snapshot().gpu_memory_reserved_bytes == 0


def test_screening_admission_records_refinement_duration_warning_and_verifies_ensemble_binary(
    tmp_path: Path, one_prepared: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    args, _selection, seen = _setup_admission(tmp_path, one_prepared, monkeypatch)
    args["request"] = args["request"].model_copy(
        update={
            "parameters": GninaDockingParameters(
                compute="cuda",
                cnn_scoring="refinement",
                cnn_model="default_1_3_ensemble",
                timeout_minutes=15,
            )
        }
    )

    # Unverified binary SHA ("a" * 64 in _setup_admission) must fail closed for ensembles.
    with pytest.raises(AnkoraDomainError) as unverified_err:
        admit_screening(**args)
    assert unverified_err.value.code == "GNINA_CNN_ENSEMBLE_UNVERIFIED_BINARY"
    assert args["store"].list_campaign_ids() == []

    monkeypatch.setattr(
        "ankora_backend.services.gnina_screening_admission.probe_gnina",
        lambda: GninaInstallation(
            "/synthetic/gnina", "1.3.3", VERIFIED_GNINA_1_3_3_SHA256, "x86_64"
        ),
    )
    record = admit_screening(**args)
    assert record.cnn_model_identity == GninaCnnModelIdentity(
        selector="default_1_3_ensemble",
        cli_argument=None,
        member_names=("dense_1_3", "dense_1_3_PT_KD_3", "crossdock_default2018_KD_4"),
        member_count=3,
    )
    assert [w.code for w in record.warnings] == [
        WarningCode.GNINA_SCREENING_REFINEMENT_DURATION_BUDGET
    ]
    warning = record.warnings[0]
    assert warning.details["ensemble_member_count"] == 3
    assert warning.details["prepared_entry_count"] == 1
    assert warning.details["timeout_minutes_per_ligand"] == 15
    persisted = args["store"].load_campaign(record.campaign_id)
    assert persisted.cnn_model_identity == record.cnn_model_identity
    assert seen[-1].gpu_memory_bytes == 2 * _GIB


def test_single_job_methods_and_export_disclose_ensemble_members_and_refinement_coupling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parameters = GninaDockingParameters(
        compute="cuda",
        device_index=0,
        cnn_scoring="refinement",
        cnn_model="default_1_3_ensemble",
        timeout_minutes=15,
    )
    identity = resolve_cnn_model_identity(
        "default_1_3_ensemble", binary_sha256=VERIFIED_GNINA_1_3_3_SHA256
    )

    report, _ = _render_single_methods(
        tmp_path / "methods",
        monkeypatch,
        job_overrides={
            "parameters": parameters,
            "tool": GninaToolIdentity(
                version="1.3.3", sha256=VERIFIED_GNINA_1_3_3_SHA256, architecture="x86_64"
            ),
            "cnn_model_identity": identity,
            "execution": GninaExecutionEvidence(
                command=["synthetic-gnina", "--cnn_scoring", "refinement"],
                exit_code=0,
                stdout="",
                stderr="",
                gpu_process_observed=True,
                gpu_observation="synthetic observation",
                requested_gpu_uuid="GPU-synthetic-0",
                observed_gpu_uuid="GPU-synthetic-0",
            ),
        },
    )
    assert report.gaps == []
    assert "scoring mode `refinement`" in report.markdown
    assert "`default_1_3_ensemble`" in report.markdown
    assert "`dense_1_3`, `dense_1_3_PT_KD_3`, `crossdock_default2018_KD_4`" in report.markdown
    assert "invoked by omitting `--cnn`" in report.markdown
    assert "combined 3D CNN and empirical scoring gradients" in report.markdown
    assert "not an independent empirical energy check" in report.markdown
    lowered = report.markdown.lower()
    for forbidden in ("measured affinity of", "experimentally", "validated"):
        assert forbidden not in lowered

    export_root = tmp_path / "export"
    store, job = _store_export_job(
        export_root,
        monkeypatch,
        request=GninaDockingRequest(
            receptor_id="synthetic-receptor",
            binding_site_id="synthetic-site",
            ligand_id="synthetic-ligand",
            ligand_preparation_id="synthetic-preparation",
            parameters=parameters,
            acknowledge_inputs_and_scoring=True,
        ),
        tool=GninaToolIdentity(
            version="1.3.3", sha256=VERIFIED_GNINA_1_3_3_SHA256, architecture="x86_64"
        ),
        cnn_model_identity=identity,
        command=["synthetic-gnina", "--cnn_scoring", "refinement", "--device", "0"],
        execution=GninaExecutionEvidence(
            command=["synthetic-gnina", "--cnn_scoring", "refinement", "--device", "0"],
            exit_code=0,
            stdout="synthetic gnina stdout\n",
            stderr="synthetic gnina stderr\n",
            gpu_process_observed=True,
            gpu_observation="synthetic observation",
            requested_gpu_uuid="GPU-synthetic-0",
            observed_gpu_uuid="GPU-synthetic-0",
        ),
    )
    exported = _export_service(export_root, store).export_campaign(
        source_kind="gnina_job", batch_id=job.job_id
    )
    bundle_dir = Path(str(exported["record_directory"]))
    manifest = _export_manifest(bundle_dir)
    assert manifest["ankora_export_format"] == 4
    assert manifest["engine"]["cnn_model_identity"] == {
        "selector": "default_1_3_ensemble",
        "cli_argument": None,
        "member_names": ["dense_1_3", "dense_1_3_PT_KD_3", "crossdock_default2018_KD_4"],
        "member_count": 3,
    }
    notes_joined = " ".join(manifest["scientific_notes"])
    assert "dense_1_3, dense_1_3_PT_KD_3, crossdock_default2018_KD_4" in notes_joined
    assert "not an independent empirical energy check" in notes_joined
    readme = (bundle_dir / "README.txt").read_text(encoding="utf-8")
    assert (
        "CNN ensemble  default_1_3_ensemble "
        "(dense_1_3, dense_1_3_PT_KD_3, crossdock_default2018_KD_4)"
    ) in readme
    assert "Refinement note:" in readme


def test_screening_methods_and_export_disclose_default1_0_ensemble_and_refinement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_gnina_methods import _Missing, _receptor, _site, _structures

    from ankora_backend.adapters.engines.gnina import parse_gnina_pdbqt

    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    job_store = GninaJobStore.from_environment()
    screening_store = GninaScreeningStore.from_environment()
    now = datetime(2026, 11, 11, 20, 0, tzinfo=UTC)

    receptor_bytes = b"synthetic receptor pdbqt\n"
    ligand_bytes = b"synthetic ligand alpha pdbqt\n"
    conformer_bytes = b"synthetic conformer alpha sdf\n"
    rec_sha = sha256(receptor_bytes).hexdigest()
    lig_sha = sha256(ligand_bytes).hexdigest()
    conf_sha = sha256(conformer_bytes).hexdigest()

    rec_path = tmp_path / "rec.pdbqt"
    lig_path = tmp_path / "lig.pdbqt"
    conf_path = tmp_path / "conf.sdf"
    rec_path.write_bytes(receptor_bytes)
    lig_path.write_bytes(ligand_bytes)
    conf_path.write_bytes(conformer_bytes)

    parameters = GninaDockingParameters(
        compute="cuda",
        device_index=0,
        cnn_scoring="refinement",
        cnn_model="default1.0",
        timeout_minutes=15,
    )
    identity = resolve_cnn_model_identity(
        "default1.0", binary_sha256=VERIFIED_GNINA_1_3_3_SHA256
    )
    tool = GninaToolIdentity(
        version="1.3.3", sha256=VERIFIED_GNINA_1_3_3_SHA256, architecture="x86_64"
    )
    box = BindingBox(center_x=1, center_y=2, center_z=3, size_x=10, size_y=12, size_z=14)

    campaign_id = screening_store.new_campaign_id()
    raw_poses = (
        b"MODEL 1\nREMARK minimizedAffinity 4.125\n"
        b"REMARK CNNscore 0.965\nREMARK CNNaffinity 8.2\n"
        b"ATOM      1  C   UNL     1       0.000   0.000   0.000  1.00  0.00     0.000 C\n"
        b"ENDMDL\n"
    )
    pose_bytes = parse_gnina_pdbqt(raw_poses)[0].pdbqt
    child = GninaJobRecord(
        job_id=job_store.new_job_id(),
        screening_campaign_id=campaign_id,
        status=DockingJobStatus.COMPLETED,
        phase=DockingJobPhase.COMPLETE,
        created_at=now,
        completed_at=now,
        request=GninaDockingRequest(
            receptor_id="synthetic-receptor",
            binding_site_id="synthetic-site",
            ligand_id="synthetic-lig-a",
            ligand_preparation_id="prep-a",
            parameters=parameters,
            acknowledge_inputs_and_scoring=True,
        ),
        tool=tool,
        cnn_model_identity=identity,
        box=box,
        receptor_output_artifact_id="synthetic-receptor-pdbqt",
        receptor_sha256=rec_sha,
        ligand_sha256=lig_sha,
        conformer_sha256=conf_sha,
        command=["synthetic-gnina", "--cnn_scoring", "refinement", "--cnn", "default1.0"],
        execution=GninaExecutionEvidence(
            command=["synthetic-gnina", "--cnn_scoring", "refinement", "--cnn", "default1.0"],
            exit_code=0,
            stdout="synthetic stdout\n",
            stderr="synthetic stderr\n",
            gpu_process_observed=True,
            gpu_observation="synthetic nvidia-smi",
            requested_gpu_uuid="GPU-synthetic-0",
            observed_gpu_uuid="GPU-synthetic-0",
        ),
        poses=[
            GninaPoseResult(
                mode=1,
                cnn_score=0.965,
                cnn_affinity=8.2,
                cnn_vs=0.965 * 8.2,
                cnn_vs_source="derived_from_recorded_axes",
                minimized_affinity_kcal_mol=4.125,
                artifact=GninaPoseArtifact(
                    artifact_id="pose-a-1",
                    mode=1,
                    filename="pose_1.pdbqt",
                    sha256=sha256(pose_bytes).hexdigest(),
                    size_bytes=len(pose_bytes),
                ),
            )
        ],
    )
    job_store.create_job(child)
    for fname, content in (
        ("receptor.pdbqt", receptor_bytes),
        ("ligand.pdbqt", ligand_bytes),
        ("conformer.sdf", conformer_bytes),
        ("raw_poses.pdbqt", raw_poses),
        ("stdout.log", b"synthetic stdout\n"),
        ("stderr.log", b"synthetic stderr\n"),
        ("pose_1.pdbqt", pose_bytes),
    ):
        job_store.write_artifact(child.job_id, fname, content)

    entry = GninaScreeningEntry(
        ligand_id="synthetic-lig-a",
        chemical_state_id="state-a",
        source_index=0,
        name="Synthetic Refined Alpha",
        ligand_preparation_id="prep-a",
        conformer_id="conf-a",
        ligand_sha256=lig_sha,
        conformer_sha256=conf_sha,
        status=DockingJobStatus.QUEUED,
        phase=DockingJobPhase.QUEUED,
    )
    plan = LigandLibraryFilterPlan()
    microstate_plan = LigandMicrostatePlan()
    summary_dict = {
        "imported_count": 1,
        "eligible_count": 1,
        "excluded_count": 0,
        "needs_decision_count": 0,
        "pains_match_count": 0,
        "brenk_match_count": 0,
        "duplicate_count": 0,
    }
    manifest_payload = {
        "filter_run_id": "synthetic-filter",
        "library_id": "synthetic-library",
        "created_at": now.isoformat(),
        "rdkit_version": "2025.09.6",
        "worker_count": 1,
        "plan": plan.model_dump(mode="json"),
        "microstate_plan": microstate_plan.model_dump(mode="json"),
        "summary": summary_dict,
        "selected_ligand_ids": ["synthetic-lig-a"],
        "evaluations": [
            {
                "ligand_id": "synthetic-lig-a",
                "state_id": "state-a",
                "record_index": 0,
                "disposition": LigandFilterDisposition.ELIGIBLE.value,
            }
        ],
    }
    manifest_bytes = json.dumps(manifest_payload).encode("utf-8")
    manifest_file = tmp_path / "selection_manifest.json"
    manifest_file.write_bytes(manifest_bytes)
    manifest_sha = sha256(manifest_bytes).hexdigest()

    eval_row = {
        "ligand_id": "synthetic-lig-a",
        "state_id": "state-a",
        "record_index": 0,
        "disposition": LigandFilterDisposition.ELIGIBLE.value,
    }
    filter_run_record = SimpleNamespace(
        artifact=SimpleNamespace(
            library_id="synthetic-library",
            filter_run_id="synthetic-filter",
            created_at=now,
            size_bytes=len(manifest_bytes),
            sha256=manifest_sha,
        ),
        rdkit_version="2025.09.6",
        worker_count=1,
        plan=plan,
        microstate_plan=microstate_plan,
        summary=SimpleNamespace(**summary_dict, model_dump=lambda mode="json": dict(summary_dict)),
        selected_ligand_ids=["synthetic-lig-a"],
        evaluations=[
            SimpleNamespace(
                ligand_id="synthetic-lig-a",
                state_id="state-a",
                record_index=0,
                disposition=LigandFilterDisposition.ELIGIBLE,
                model_dump=lambda mode="json", row=eval_row: dict(row),
            )
        ],
    )

    class _StubLigands:
        def load_library_record(self, lib_id: str) -> Any:
            return SimpleNamespace(
                artifact=SimpleNamespace(
                    library_id=lib_id,
                    filename="synthetic_library.sdf",
                    format="sdf",
                    record_count=1,
                ),
                imported_count=1,
                failed_count=0,
                entries=[
                    SimpleNamespace(
                        ligand_id="synthetic-lig-a",
                        state_id="state-a",
                        record_index=0,
                        name="Synthetic Refined Alpha",
                        canonical_smiles="CCO",
                        molecular_weight_g_mol=46.07,
                    )
                ],
            )

        def load_filter_run(self, lib_id: str, run_id: str) -> Any:
            return filter_run_record

        def load_filter_run_record(self, lib_id: str, run_id: str) -> Any:
            return filter_run_record

        def filter_run_content_path(self, lib_id: str, run_id: str) -> Path:
            return manifest_file

        def load_pdbqt_record(self, lig_id: str, prep_id: str) -> Any:
            return SimpleNamespace(
                artifact=SimpleNamespace(
                    ligand_id=lig_id,
                    preparation_id=prep_id,
                    conformer_id="conf-a",
                    sha256=lig_sha,
                    size_bytes=len(ligand_bytes),
                ),
                charge_model="gasteiger",
                tool=SimpleNamespace(name="Meeko", version="0.7.1"),
            )

        def pdbqt_content_path(self, lig_id: str, prep_id: str) -> Path:
            return lig_path

        def load_conformer_record(self, lig_id: str, conf_id: str) -> Any:
            return SimpleNamespace(
                artifact=SimpleNamespace(
                    ligand_id=lig_id,
                    conformer_id=conf_id,
                    chemical_state_id="state-a",
                    sha256=conf_sha,
                    size_bytes=len(conformer_bytes),
                ),
                minimization=SimpleNamespace(
                    embedding_method="ETKDGv3",
                    force_field="MMFF94s",
                    max_iterations=500,
                    random_seed=20260819,
                    conformer_pool_size=20,
                    independent_from_source_coordinates=True,
                ),
                provenance=SimpleNamespace(
                    input_artifacts=["state-a"],
                    tool=SimpleNamespace(name="RDKit ETKDG/MMFF", version="2025.09.6"),
                ),
            )

        def conformer_content_path(self, lig_id: str, conf_id: str) -> Path:
            return conf_path

        def load_record(self, lig_id: str) -> Any:
            return SimpleNamespace(
                state=SimpleNamespace(state_id="state-a", source="library_import"),
                state_decisions=[],
                inspection=SimpleNamespace(
                    name="Synthetic Refined Alpha",
                    canonical_smiles="CCO",
                    molecular_weight_g_mol=46.07,
                ),
            )

    stub_ligands = _StubLigands()
    screening_store._ligands = stub_ligands  # type: ignore[assignment]

    campaign = GninaScreeningCampaignRecord(
        campaign_id=campaign_id,
        status=DockingJobStatus.QUEUED,
        phase=DockingJobPhase.QUEUED,
        created_at=now,
        request=GninaScreeningRequest(
            receptor_id="synthetic-receptor",
            binding_site_id="synthetic-site",
            library_id="synthetic-library",
            filter_run_id="synthetic-filter",
            parameters=parameters,
            hit_ranking_metric="cnn_vs",
            acknowledge_inputs_and_scoring=True,
        ),
        hit_ranking_metric="cnn_vs",
        tool=tool,
        cnn_model_identity=identity,
        selection=GninaScreeningSelection(
            library_id="synthetic-library",
            filter_run_id="synthetic-filter",
            manifest_artifact_id="synthetic-filter",
            manifest_sha256=manifest_sha,
        ),
        receptor_output_artifact_id="synthetic-receptor-pdbqt",
        receptor_sha256=rec_sha,
        box=box,
        selected_count=1,
        entries=[entry],
        warnings=[
            StructuredWarning(
                code=WarningCode.GNINA_SCREENING_REFINEMENT_DURATION_BUDGET,
                stage="gnina_screening",
                message="Synthetic duration warning.",
                details={"ensemble_member_count": 5},
            )
        ],
    )
    screening_store.create_campaign(campaign)
    running = screening_store.update_entry(
        campaign_id,
        entry.model_copy(
            update={
                "status": DockingJobStatus.RUNNING,
                "phase": DockingJobPhase.DOCKING,
                "gnina_job_id": child.job_id,
                "started_at": now,
            }
        ),
    )
    screening_store.update_entry(
        campaign_id,
        running.model_copy(
            update={
                "status": DockingJobStatus.COMPLETED,
                "phase": DockingJobPhase.COMPLETE,
                "completed_at": now,
            }
        ),
    )
    screening_store.finalize_campaign(campaign_id)

    receptor_store = SimpleNamespace(
        load_record=lambda _: _receptor(sha=rec_sha),
        content_path=lambda *_: rec_path,
    )
    methods_service = MethodsReportService(
        catalog=ResultCatalogService.from_environment(),
        structures=_structures(),  # type: ignore[arg-type]
        receptors=receptor_store,  # type: ignore[arg-type]
        binding_sites=SimpleNamespace(load_record=lambda _: _site(box=box)),  # type: ignore[arg-type]
        pockets=_Missing(),  # type: ignore[arg-type]
        ligands=stub_ligands,  # type: ignore[arg-type]
        maps=_Missing(),  # type: ignore[arg-type]
        docking=_Missing(),  # type: ignore[arg-type]
        autodock4=_Missing(),  # type: ignore[arg-type]
        autodock_gpu=_Missing(),  # type: ignore[arg-type]
        gnina=job_store,
        gnina_screening=screening_store,
    )
    methods = methods_service.render(f"gnina_screening:{campaign_id}")
    assert methods.gaps == []
    for member in (
        "`dense`",
        "`general_default2018_3`",
        "`dense_3`",
        "`crossdock_default2018`",
        "`redock_default2018_2`",
    ):
        assert member in methods.markdown
    assert "`--cnn default1.0`" in methods.markdown
    assert "not an independent empirical energy check" in methods.markdown
    lowered = methods.markdown.lower()
    for forbidden in ("measured affinity of", "experimentally", "validated"):
        assert forbidden not in lowered

    export_service = CampaignExportService(
        root=tmp_path,
        docking_store=None,  # type: ignore[arg-type]
        autodock4_store=None,  # type: ignore[arg-type]
        autodock_gpu_store=None,  # type: ignore[arg-type]
        binding_site_store=None,  # type: ignore[arg-type]
        gnina_store=job_store,
        gnina_screening_store=screening_store,
        ligand_store=stub_ligands,  # type: ignore[arg-type]
    )
    exported = export_service.export_campaign(
        source_kind="gnina_screening", batch_id=campaign_id
    )
    bundle_dir = Path(str(exported["record_directory"]))
    manifest = _export_manifest(bundle_dir)
    assert manifest["ankora_export_format"] == 4
    assert manifest["table"]["ranking_metric"] == "gnina_cnn_vs"
    assert manifest["engine"]["cnn_model_identity"] == {
        "selector": "default1.0",
        "cli_argument": "default1.0",
        "member_names": [
            "dense",
            "general_default2018_3",
            "dense_3",
            "crossdock_default2018",
            "redock_default2018_2",
        ],
        "member_count": 5,
    }
    readme = (bundle_dir / "README.txt").read_text(encoding="utf-8")
    assert (
        "CNN ensemble  default1.0 "
        "(dense, general_default2018_3, dense_3, crossdock_default2018, redock_default2018_2)"
    ) in readme
    assert "Refinement note:" in readme
