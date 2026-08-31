"""Service tests for immutable AutoGrid map sets (ADR-015 Phase 1).

Every receptor, ligand, and map here is synthetic. Real AutoGrid execution is
captured separately as Windows validation evidence in
`docs/validation/AUTODOCK4_PHASE0_WINDOWS.md`.
"""

import threading
import time
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from ankora_backend.adapters.engines.autogrid import (
    GRID_LOG_FILENAME,
    GRID_PARAMETER_FILENAME,
    MAP_PREFIX,
    AutoGridInstallation,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.cancellable_subprocess import CancellableToolExecution
from ankora_backend.execution.subprocess_runner import ToolExecution
from ankora_backend.persistence.autogrid_store import AutoGridMapStore
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.autogrid import (
    AutoGridJobPhase,
    AutoGridJobStatus,
    AutoGridLigandSource,
    AutoGridMapJobRecord,
    AutoGridMapKind,
    AutoGridMapSetRequest,
    AutoGridParameters,
)
from ankora_backend.schemas.binding_sites import (
    BindingBox,
    BindingSiteRecord,
    BindingSiteRequest,
    BindingSiteSource,
)
from ankora_backend.schemas.ligands import (
    ApplyLigandLibraryFilterRequest,
    GenerateLigandConformerRequest,
    PrepareLigandPdbqtRequest,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import (
    ComponentAction,
    ProtonationSettings,
    ReceptorOutputArtifact,
    ReceptorOutputStage,
    ReceptorPreparationRecord,
    ReceptorPreparationRequest,
    ReceptorPreparationStatus,
)
from ankora_backend.services import autogrid_maps as autogrid_module
from ankora_backend.services.autogrid_maps import AutoGridMapService
from ankora_backend.services.ligand_filtering import apply_library_filters
from ankora_backend.services.ligand_import import import_local_ligand_library
from ankora_backend.services.ligand_minimization import generate_ligand_conformer
from ankora_backend.services.ligand_preparation import prepare_ligand_pdbqt

SYNTHETIC_RECEPTOR = (
    b"REMARK synthetic receptor PDBQT\n"
    b"ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00    -0.300 N\n"
    b"ATOM      2  C   ALA A   1       1.400   0.000   0.000  1.00  0.00     0.100 C\n"
    b"ATOM      3  O   ALA A   1       2.000   1.000   0.000  1.00  0.00    -0.300 OA\n"
)
SYNTHETIC_LIGAND = (
    b"REMARK synthetic ligand PDBQT\n"
    b"ROOT\n"
    b"ATOM      1  C   LIG A   1       0.000   0.000   0.000  1.00  0.00     0.000 C\n"
    b"ATOM      2  O   LIG A   1       1.400   0.000   0.000  1.00  0.00    -0.300 OA\n"
    b"ENDROOT\n"
    b"TORSDOF 0\n"
)
# Meeko emits these pseudoatoms when it closes a macrocycle; stock AutoDock4
# 4.2.6 has no parameters for them.
GLUE_LIGAND = (
    b"REMARK synthetic macrocycle ligand PDBQT\n"
    b"ROOT\n"
    b"ATOM      1  C   LIG A   1       0.000   0.000   0.000  1.00  0.00     0.000 C\n"
    b"ATOM      2  CG0 LIG A   1       1.400   0.000   0.000  1.00  0.00     0.000 CG0\n"
    b"ATOM      3  G0  LIG A   1       2.400   0.000   0.000  1.00  0.00     0.000 G0\n"
    b"ENDROOT\n"
    b"TORSDOF 0\n"
)

# Captured verbatim from the real `autogrid4.exe --version` on the authoritative
# Windows machine, so the parser is pinned to genuine output rather than a guess.
REAL_AUTOGRID_VERSION_OUTPUT = """AutoGrid 4.2.6
compilation options:
  Double-precision calculations (USE_DOUBLE):  yes
  Non-bond cutoff for internal energy calculation (NBC): 8.00
  Optimize internal energy scoring (USE_8A_NBCUTOFF):  yes
  Maximum number of receptor atom types (NUM_RECEPTOR_TYPES): 20
  Maximum number of atom types (MAX_ATOM_TYPES): 14
  Maximum number of maps (MAX_MAPS): 16
  Maximum dimension of map x, y, or z (MAX_GRID_PTS): 1025
  Size of int 4, long 4, float 4, double 8, Real 8 bytes.

 Copyright (C) 2009 The Scripps Research Institute.
 License GPLv2+: GNU GPL version 2 or later <http://gnu.org/licenses/gpl.html>
"""


def _installation() -> AutoGridInstallation:
    return AutoGridInstallation(
        executable="synthetic-autogrid4.exe",
        version="4.2.6",
        sha256="a" * 64,
        architecture="x86",
        max_receptor_types=20,
        max_ligand_types=14,
        max_maps=16,
        max_grid_points=1025,
    )


def _ligand_types_from_gpf(job_directory: Path) -> list[str]:
    gpf = (job_directory / GRID_PARAMETER_FILENAME).read_text(encoding="ascii")
    for line in gpf.splitlines():
        if line.startswith("ligand_types "):
            return line.split()[1:]
    raise AssertionError("the generated GPF declared no ligand_types")


def _fake_autogrid_success(**kwargs: object) -> CancellableToolExecution:
    """Write exactly the maps the generated GPF declares, like AutoGrid would."""
    job_directory = kwargs["job_directory"]
    assert isinstance(job_directory, Path)
    for atom_type in _ligand_types_from_gpf(job_directory):
        (job_directory / f"{MAP_PREFIX}.{atom_type}.map").write_text(
            f"synthetic {atom_type} affinity map\n", encoding="utf-8"
        )
    (job_directory / f"{MAP_PREFIX}.e.map").write_text("synthetic e\n", encoding="utf-8")
    (job_directory / f"{MAP_PREFIX}.d.map").write_text("synthetic d\n", encoding="utf-8")
    (job_directory / f"{MAP_PREFIX}.maps.fld").write_text("synthetic fld\n", encoding="utf-8")
    (job_directory / f"{MAP_PREFIX}.maps.xyz").write_text("synthetic xyz\n", encoding="utf-8")
    (job_directory / GRID_LOG_FILENAME).write_text(
        "autogrid synthetic log\nSuccessful Completion\n", encoding="utf-8"
    )
    return _execution(exit_code=0, stdout="synthetic autogrid stdout")


def _execution(
    *,
    exit_code: int,
    stdout: str = "",
    stderr: str = "",
    canceled: bool = False,
    timed_out: bool = False,
) -> CancellableToolExecution:
    return CancellableToolExecution(
        command=["synthetic-autogrid4.exe", "-p", GRID_PARAMETER_FILENAME],
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        canceled=canceled,
        timed_out=timed_out,
    )


def _install_synthetic_autogrid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(autogrid_module, "probe_autogrid4", _installation)
    monkeypatch.setattr(
        autogrid_module, "execute_autogrid_cancellable", _fake_autogrid_success
    )


def _provenance(event_id: str) -> ProvenanceEvent:
    return ProvenanceEvent(
        event_id=event_id,
        event_type="synthetic_fixture",
        timestamp=datetime.now(UTC),
        tool=ToolIdentity(name="synthetic test fixture", version="1"),
    )


def _service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, glue_second_ligand: bool = False
) -> tuple[AutoGridMapService, AutoGridMapSetRequest]:
    receptor_store = ReceptorArtifactStore(tmp_path)
    ligand_store = LigandArtifactStore(tmp_path)
    binding_store = BindingSiteArtifactStore(tmp_path)
    map_store = AutoGridMapStore(tmp_path)
    now = datetime.now(UTC)

    receptor_id = receptor_store.new_receptor_id()
    receptor_store.create_receptor(receptor_id)
    receptor_store.write_bytes(receptor_id, "receptor.pdbqt", SYNTHETIC_RECEPTOR)
    receptor_output = ReceptorOutputArtifact(
        artifact_id=f"{receptor_id}-pdbqt",
        stage=ReceptorOutputStage.PDBQT,
        filename="receptor.pdbqt",
        format="pdbqt",
        sha256=sha256(SYNTHETIC_RECEPTOR).hexdigest(),
        size_bytes=len(SYNTHETIC_RECEPTOR),
        created_at=now,
        content_url="/synthetic/receptor",
    )
    receptor_store.save_record(
        ReceptorPreparationRecord(
            receptor_id=receptor_id,
            source_artifact_id="synthetic-source",
            created_at=now,
            status=ReceptorPreparationStatus.DOCKING_READY,
            decisions=ReceptorPreparationRequest(
                selected_chains=["A"],
                water_action=ComponentAction.REMOVE,
                component_decisions=[],
                issue_decisions=[],
                protonation=ProtonationSettings(enabled=True),
                generate_pdbqt=True,
            ),
            outputs=[receptor_output],
            warnings=[],
            provenance=[],
            display_output_artifact_id=receptor_output.artifact_id,
        )
    )

    binding_id = binding_store.new_binding_site_id()
    box = BindingBox(
        center_x=0, center_y=0, center_z=0, size_x=20, size_y=20, size_z=20
    )
    binding_store.save_record(
        BindingSiteRecord(
            binding_site_id=binding_id,
            receptor_id=receptor_id,
            source_artifact_id=receptor_output.artifact_id,
            created_at=now,
            decisions=BindingSiteRequest(source=BindingSiteSource.MANUAL, manual_box=box),
            box=box,
            warnings=[],
            provenance=[_provenance("synthetic-binding-site")],
        )
    )

    library = import_local_ligand_library(
        content=b"CCO synthetic_alpha\nCCN synthetic_beta\n",
        filename="synthetic_grid_library.smi",
        store=ligand_store,
    )
    filter_run = apply_library_filters(
        library_id=library.artifact.library_id,
        request=ApplyLigandLibraryFilterRequest(acknowledge_selection=True),
        store=ligand_store,
    )
    prepared: list[bytes] = []

    def synthetic_meeko(**kwargs: object) -> tuple[object, str]:
        output_path = kwargs["output_pdbqt_path"]
        assert isinstance(output_path, Path)
        content = (
            GLUE_LIGAND if glue_second_ligand and len(prepared) == 1 else SYNTHETIC_LIGAND
        )
        prepared.append(content)
        output_path.write_bytes(content)
        return ToolExecution(
            command=["synthetic-meeko"], exit_code=0, stdout="", stderr=""
        ), "0.7.1"

    monkeypatch.setattr(
        "ankora_backend.services.ligand_preparation.execute_meeko_ligand",
        synthetic_meeko,
    )
    for ligand_id in filter_run.selected_ligand_ids:
        ligand = ligand_store.load_record(ligand_id)
        assert ligand.state is not None
        conformer = generate_ligand_conformer(
            ligand_id=ligand_id,
            request=GenerateLigandConformerRequest(
                acknowledge_current_chemical_state=True,
                state_id=ligand.state.state_id,
                random_seed=991,
            ),
            store=ligand_store,
        )
        prepare_ligand_pdbqt(
            ligand_id=ligand_id,
            conformer_id=conformer.artifact.conformer_id,
            request=PrepareLigandPdbqtRequest(),
            store=ligand_store,
        )

    service = AutoGridMapService(
        map_store=map_store,
        receptor_store=receptor_store,
        binding_site_store=binding_store,
        ligand_store=ligand_store,
    )
    request = AutoGridMapSetRequest(
        receptor_id=receptor_id,
        binding_site_id=binding_id,
        source=AutoGridLigandSource.FILTER_RUN,
        library_id=library.artifact.library_id,
        filter_run_id=filter_run.artifact.filter_run_id,
    )
    return service, request


def test_map_set_is_generated_once_and_reused_by_exact_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _service(tmp_path, monkeypatch)
    _install_synthetic_autogrid(monkeypatch)

    first = service.ensure_map_set(request)
    second = service.ensure_map_set(request)

    assert first.reused_existing_map_set is False
    assert second.reused_existing_map_set is True
    assert second.record.map_set_id == first.record.map_set_id
    assert second.record.identity_key == first.record.identity_key
    # The affinity maps cover exactly the compatible ligand union plus the
    # electrostatic and desolvation maps AutoGrid always writes.
    affinity = [
        item for item in first.record.artifacts if item.kind is AutoGridMapKind.AFFINITY
    ]
    assert sorted(item.atom_type or "" for item in affinity) == ["C", "OA"]
    assert first.record.preflight.receptor_atom_types == ["C", "N", "OA"]
    assert first.record.execution.successful_completion_logged is True
    assert first.record.geometry.npts == (54, 54, 54)


def test_changed_spacing_creates_a_second_map_set_without_touching_the_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _service(tmp_path, monkeypatch)
    _install_synthetic_autogrid(monkeypatch)

    original = service.ensure_map_set(request).record
    coarse = service.ensure_map_set(
        request.model_copy(
            update={"parameters": AutoGridParameters(spacing_angstrom=0.5)}
        )
    )

    assert coarse.reused_existing_map_set is False
    assert coarse.record.map_set_id != original.map_set_id
    assert coarse.record.identity_key != original.identity_key
    assert coarse.record.geometry.npts == (40, 40, 40)
    # The first map set remains byte-identical and independently readable.
    reloaded = service.get(original.map_set_id)
    assert reloaded.model_dump(mode="json") == original.model_dump(mode="json")


def test_two_spacings_covering_the_same_volume_are_still_different_map_sets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 20 A box realizes exactly 20 A at both 0.5 A and 0.25 A spacing, but
    those are different grid resolutions and therefore different maps. Identity
    must not collapse them just because the covered volume matches.
    """
    service, request = _service(tmp_path, monkeypatch)
    _install_synthetic_autogrid(monkeypatch)

    coarse = service.ensure_map_set(
        request.model_copy(
            update={"parameters": AutoGridParameters(spacing_angstrom=0.5)}
        )
    ).record
    fine = service.ensure_map_set(
        request.model_copy(
            update={"parameters": AutoGridParameters(spacing_angstrom=0.25)}
        )
    )

    assert coarse.geometry.realized_size_angstrom == fine.record.geometry.realized_size_angstrom
    assert coarse.geometry.npts == (40, 40, 40)
    assert fine.record.geometry.npts == (80, 80, 80)
    assert fine.reused_existing_map_set is False
    assert fine.record.identity_key != coarse.identity_key


def test_timeout_alone_does_not_fragment_the_map_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`timeout_minutes` bounds how long Ankora waits, never what AutoGrid
    computes, so it must not create a second identical map set."""
    service, request = _service(tmp_path, monkeypatch)
    _install_synthetic_autogrid(monkeypatch)

    original = service.ensure_map_set(request).record
    patient = service.ensure_map_set(
        request.model_copy(
            update={"parameters": AutoGridParameters(timeout_minutes=999)}
        )
    )

    assert patient.reused_existing_map_set is True
    assert patient.record.map_set_id == original.map_set_id


def test_macrocycle_glue_ligand_stays_a_visible_incompatible_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unsupported molecule must neither abort the campaign nor vanish from
    it, and its glue pseudoatoms must never reach the affinity maps."""
    service, request = _service(tmp_path, monkeypatch, glue_second_ligand=True)
    _install_synthetic_autogrid(monkeypatch)

    record = service.ensure_map_set(request).record

    assert record.preflight.selected_count == 2
    assert record.preflight.compatible_count == 1
    assert record.preflight.incompatible_count == 1
    incompatible = [row for row in record.preflight.ligands if not row.compatible]
    assert len(incompatible) == 1
    assert "CG0, G0" in (incompatible[0].reason or "")
    assert incompatible[0].atom_types == ["C", "CG0", "G0"]
    assert record.preflight.ligand_atom_types == ["C", "OA"]
    assert not any(
        (item.atom_type or "").startswith(("CG", "G")) for item in record.artifacts
    )


def test_failed_autogrid_run_preserves_raw_evidence_and_writes_no_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _service(tmp_path, monkeypatch)
    monkeypatch.setattr(autogrid_module, "probe_autogrid4", _installation)

    def failing_autogrid(**kwargs: object) -> CancellableToolExecution:
        job_directory = kwargs["job_directory"]
        assert isinstance(job_directory, Path)
        (job_directory / GRID_LOG_FILENAME).write_text(
            "autogrid synthetic log\nfatal: receptor unreadable\n", encoding="utf-8"
        )
        return _execution(exit_code=1, stderr="synthetic autogrid failure")

    monkeypatch.setattr(
        autogrid_module, "execute_autogrid_cancellable", failing_autogrid
    )

    with pytest.raises(AnkoraDomainError) as failure:
        service.ensure_map_set(request)

    assert failure.value.code == "AUTOGRID_EXECUTION_FAILED"
    evidence_directory = Path(str(failure.value.details["evidence_directory"]))
    assert (evidence_directory / GRID_LOG_FILENAME).is_file()
    assert (evidence_directory / GRID_PARAMETER_FILENAME).is_file()
    assert not (evidence_directory / "record.json").exists()


def test_zero_exit_without_a_success_log_is_still_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AutoGrid can exit zero on a partial run, so the log is the real verdict."""
    service, request = _service(tmp_path, monkeypatch)
    monkeypatch.setattr(autogrid_module, "probe_autogrid4", _installation)

    def silent_autogrid(**kwargs: object) -> CancellableToolExecution:
        job_directory = kwargs["job_directory"]
        assert isinstance(job_directory, Path)
        (job_directory / GRID_LOG_FILENAME).write_text(
            "autogrid synthetic log\n", encoding="utf-8"
        )
        return _execution(exit_code=0)

    monkeypatch.setattr(
        autogrid_module, "execute_autogrid_cancellable", silent_autogrid
    )

    with pytest.raises(AnkoraDomainError) as failure:
        service.ensure_map_set(request)

    assert failure.value.code == "AUTOGRID_EXECUTION_FAILED"
    assert failure.value.details["exit_code"] == 0
    assert failure.value.details["successful_completion_logged"] is False


def _wait_for_terminal(
    service: AutoGridMapService, job_id: str, *, deadline_seconds: float = 10.0
) -> AutoGridMapJobRecord:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        record = service.get_job(job_id)
        if record.status in {
            AutoGridJobStatus.COMPLETED,
            AutoGridJobStatus.CANCELED,
            AutoGridJobStatus.FAILED,
        }:
            return record
        time.sleep(0.01)
    raise AssertionError("the synthetic AutoGrid job did not terminate")


def test_async_job_completes_and_publishes_its_map_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _service(tmp_path, monkeypatch)
    _install_synthetic_autogrid(monkeypatch)

    queued = service.start_map_set(request)
    assert queued.status is AutoGridJobStatus.QUEUED
    assert queued.map_set_id is None
    # Geometry and preflight are known before the job runs, because validation
    # is synchronous; only AutoGrid itself is deferred.
    assert queued.geometry.npts == (54, 54, 54)
    assert queued.preflight.ligand_atom_types == ["C", "OA"]

    finished = _wait_for_terminal(service, queued.job_id)

    assert finished.status is AutoGridJobStatus.COMPLETED
    assert finished.phase is AutoGridJobPhase.COMPLETE
    assert finished.reused_existing_map_set is False
    assert finished.map_set_id is not None
    assert finished.execution is not None
    assert finished.execution.successful_completion_logged is True
    assert service.get(finished.map_set_id).identity_key == finished.identity_key
    service.shutdown()


def test_async_job_reuses_an_existing_map_set_without_running_autogrid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _service(tmp_path, monkeypatch)
    _install_synthetic_autogrid(monkeypatch)
    existing = service.ensure_map_set(request).record

    def must_not_run(**_kwargs: object) -> CancellableToolExecution:
        raise AssertionError("AutoGrid must not run for an already-generated identity")

    monkeypatch.setattr(autogrid_module, "execute_autogrid_cancellable", must_not_run)
    job = service.start_map_set(request)

    assert job.status is AutoGridJobStatus.COMPLETED
    assert job.reused_existing_map_set is True
    assert job.map_set_id == existing.map_set_id
    service.shutdown()


def test_canceling_a_running_job_stops_it_and_publishes_no_map_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A canceled run leaves its partial directory as evidence, but without a
    record it can never be mistaken for a reusable map set."""
    service, request = _service(tmp_path, monkeypatch)
    monkeypatch.setattr(autogrid_module, "probe_autogrid4", _installation)
    entered = threading.Event()

    def blocking_autogrid(**kwargs: object) -> CancellableToolExecution:
        cancel_event = kwargs["cancel_event"]
        assert isinstance(cancel_event, threading.Event)
        job_directory = kwargs["job_directory"]
        assert isinstance(job_directory, Path)
        entered.set()
        cancel_event.wait(timeout=5)
        (job_directory / GRID_LOG_FILENAME).write_text(
            "autogrid synthetic log\n", encoding="utf-8"
        )
        return _execution(exit_code=1, canceled=True)

    monkeypatch.setattr(
        autogrid_module, "execute_autogrid_cancellable", blocking_autogrid
    )

    job = service.start_map_set(request)
    assert entered.wait(timeout=5)
    response = service.cancel_job(job.job_id)
    assert response.status is AutoGridJobStatus.CANCEL_REQUESTED

    finished = _wait_for_terminal(service, job.job_id)

    assert finished.status is AutoGridJobStatus.CANCELED
    assert finished.map_set_id is None
    assert finished.evidence_directory is not None
    evidence = Path(finished.evidence_directory)
    assert evidence.is_dir()
    assert not (evidence / "record.json").exists()
    # The identity remains uncached, so a later request regenerates rather than
    # serving the abandoned partial run.
    store = AutoGridMapStore(tmp_path)
    assert store.find_by_identity(finished.identity_key) is None
    service.shutdown()


def test_a_failed_job_records_structured_failure_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request = _service(tmp_path, monkeypatch)
    monkeypatch.setattr(autogrid_module, "probe_autogrid4", _installation)

    def failing(**kwargs: object) -> CancellableToolExecution:
        job_directory = kwargs["job_directory"]
        assert isinstance(job_directory, Path)
        (job_directory / GRID_LOG_FILENAME).write_text(
            "autogrid synthetic log\nfatal\n", encoding="utf-8"
        )
        return _execution(exit_code=1, stderr="synthetic failure")

    monkeypatch.setattr(autogrid_module, "execute_autogrid_cancellable", failing)

    job = service.start_map_set(request)
    finished = _wait_for_terminal(service, job.job_id)

    assert finished.status is AutoGridJobStatus.FAILED
    assert finished.map_set_id is None
    assert finished.failure is not None
    assert finished.failure.code == "AUTOGRID_EXECUTION_FAILED"
    assert finished.evidence_directory is not None
    service.shutdown()


def test_an_unusable_request_fails_immediately_instead_of_queueing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validation is synchronous so the caller gets a structured error rather
    than a queued job that could never succeed."""
    service, request = _service(tmp_path, monkeypatch)
    _install_synthetic_autogrid(monkeypatch)

    with pytest.raises(AnkoraDomainError) as failure:
        service.start_map_set(
            request.model_copy(update={"binding_site_id": "not-a-binding-site"})
        )

    assert failure.value.status_code in {404, 422}
    service.shutdown()
