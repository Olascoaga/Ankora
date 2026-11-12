"""Tests for the zero-dependency Export v4 bundle verifier (scripts/verify_export_bundle.py)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from ankora_backend.adapters.engines.gnina import parse_gnina_pdbqt
from ankora_backend.persistence.gnina_store import GninaJobStore
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.docking import DockingJobPhase, DockingJobStatus
from ankora_backend.schemas.gnina import (
    GninaDockingParameters,
    GninaDockingRequest,
    GninaExecutionEvidence,
    GninaJobRecord,
    GninaPoseArtifact,
    GninaPoseResult,
    GninaToolIdentity,
)
from ankora_backend.schemas.results_catalog import ReproducibilityAssessment
from ankora_backend.services.campaign_export import (
    CampaignExportService,
    ExportedCampaign,
    _bundle_identity,
    _write_portable_bundle,
    manifest,
    readme,
    results_csv,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "verify_export_bundle.py"


def _load_verifier() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_export_bundle", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MOD = _load_verifier()
BundleVerificationError = _MOD.BundleVerificationError
verify_bundle = _MOD.verify_bundle


def _write_synthetic_screening_bundle(
    dest: Path,
    *,
    engine: str = "AutoDock4",
    engine_version: str = "4.2.6",
    backend: str | None = "autodock4_cpu",
    value_column: str = "autodock4_binding_energy_kcal_mol",
) -> tuple[Path, Path]:
    """Write a synthetic screening Export v4 folder + portable ZIP."""
    dest.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = [
        {
            "rank": 1,
            "molecule": "Synthetic-A",
            "source_index": 0,
            "ligand_id": "synthetic-lig-a",
            "canonical_smiles": "CCO",
            "molecular_weight_g_mol": "46.069",
            "status": "completed",
            "failure_code": "",
            "failure_message": "",
            value_column: "-6.250",
            **({"clusters": 2, "top_cluster_runs": 8} if engine != "AutoDock Vina" else {}),
        },
        {
            "rank": 2,
            "molecule": "Synthetic-B",
            "source_index": 1,
            "ligand_id": "synthetic-lig-b",
            "canonical_smiles": "",
            "molecular_weight_g_mol": "",
            "status": "failed",
            "failure_code": "SYNTHETIC_PREP_MISSING",
            "failure_message": "Synthetic failure fixture.",
            value_column: "",
            **({"clusters": 0, "top_cluster_runs": ""} if engine != "AutoDock Vina" else {}),
        },
    ]
    campaign = ExportedCampaign(
        engine=engine,
        engine_version=engine_version,
        backend=backend,
        value_column=value_column,
        reproducibility=ReproducibilityAssessment(),
        receptor_id="synthetic-receptor",
        receptor_sha256="1" * 64,
        binding_site_id="synthetic-site",
        box={
            "center_x": 0.0,
            "center_y": 0.0,
            "center_z": 0.0,
            "size_x": 20.0,
            "size_y": 20.0,
            "size_z": 20.0,
        },
        map_set_id="synthetic-maps" if engine != "AutoDock Vina" else None,
        map_set_identity_key="2" * 64 if engine != "AutoDock Vina" else None,
        selection_manifest_sha256="3" * 64,
        library_id="synthetic-lib",
        filter_run_id="synthetic-filter",
        parameters={"seed": 20261112},
        executable_sha256="4" * 64,
        device_name=None,
        selected_count=2,
        succeeded_count=1,
        failed_count=1,
        rows=rows,
    )
    exported_at = datetime(2026, 11, 12, 12, 0, 0, tzinfo=UTC)
    source_kind = "vina_batch" if engine == "AutoDock Vina" else "autodock4_batch"
    identity = _bundle_identity(
        campaign=campaign,
        export_id="11111111-2222-3333-4444-555555555555",
        source_kind=source_kind,
        source_id="synthetic-batch-01",
        exported_at=exported_at,
        display_name="Synthetic Benchmark Run",
    )
    (dest / "results.csv").write_text(results_csv(campaign), encoding="utf-8", newline="\n")
    (dest / "manifest.json").write_text(
        manifest(
            campaign,
            exported_at=exported_at,
            source_kind=source_kind,
            source_id="synthetic-batch-01",
            bundle_identity=identity,
        ),
        encoding="utf-8",
        newline="\n",
    )
    (dest / "README.txt").write_text(
        readme(campaign, exported_at=exported_at, bundle_identity=identity),
        encoding="utf-8",
        newline="\n",
    )
    zip_path = _write_portable_bundle(dest, identity.archive_filename)
    return dest, zip_path


def _export_synthetic_gnina_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    """Export a synthetic GNINA single job via CampaignExportService."""
    data_dir = tmp_path / "ankora-data"
    monkeypatch.setenv("ANKORA_DATA_DIR", str(data_dir))
    store = GninaJobStore.from_environment()

    raw_poses = (
        b"MODEL 1\nREMARK minimizedAffinity -5.10\n"
        b"REMARK CNNscore 0.9200\nREMARK CNNaffinity 7.800\n"
        b"ATOM      1  C   UNL     1       0.000   0.000   0.000  1.00  0.00     0.000 C\n"
        b"ENDMDL\n"
    )
    pose_bytes = parse_gnina_pdbqt(raw_poses)[0].pdbqt
    rec_bytes = b"synthetic receptor pdbqt\n"
    lig_bytes = b"synthetic ligand pdbqt\n"
    conf_bytes = b"synthetic conformer sdf\n"
    stdout_txt = "synthetic stdout\n"
    stderr_txt = "synthetic stderr\n"

    job = GninaJobRecord(
        job_id=store.new_job_id(),
        status=DockingJobStatus.COMPLETED,
        phase=DockingJobPhase.COMPLETE,
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        request=GninaDockingRequest(
            receptor_id="synthetic-receptor",
            binding_site_id="synthetic-site",
            ligand_id="synthetic-ligand",
            ligand_preparation_id="synthetic-prep",
            parameters=GninaDockingParameters(compute="cpu"),
            acknowledge_inputs_and_scoring=True,
        ),
        tool=GninaToolIdentity(version="1.3.3", sha256="a" * 64, architecture="x86_64"),
        box=BindingBox(
            center_x=0.0, center_y=0.0, center_z=0.0, size_x=16, size_y=16, size_z=16
        ),
        receptor_output_artifact_id="synthetic-rec-out",
        receptor_sha256=sha256(rec_bytes).hexdigest(),
        ligand_sha256=sha256(lig_bytes).hexdigest(),
        conformer_sha256=sha256(conf_bytes).hexdigest(),
        command=["synthetic-gnina", "--no_gpu"],
        execution=GninaExecutionEvidence(
            command=["synthetic-gnina", "--no_gpu"],
            exit_code=0,
            stdout=stdout_txt,
            stderr=stderr_txt,
        ),
        poses=[
            GninaPoseResult(
                mode=1,
                cnn_score=0.92,
                cnn_affinity=7.8,
                minimized_affinity_kcal_mol=-5.1,
                artifact=GninaPoseArtifact(
                    artifact_id="synthetic-pose-1",
                    mode=1,
                    filename="pose_1.pdbqt",
                    sha256=sha256(pose_bytes).hexdigest(),
                    size_bytes=len(pose_bytes),
                ),
            )
        ],
    )
    store.create_job(job)
    for name, content in (
        ("receptor.pdbqt", rec_bytes),
        ("ligand.pdbqt", lig_bytes),
        ("conformer.sdf", conf_bytes),
        ("raw_poses.pdbqt", raw_poses),
        ("stdout.log", stdout_txt.encode("utf-8")),
        ("stderr.log", stderr_txt.encode("utf-8")),
        ("pose_1.pdbqt", pose_bytes),
    ):
        store.output_path(job.job_id, name).write_bytes(content)

    service = CampaignExportService.from_environment()
    receipt = service.export_campaign(
        source_kind="gnina_job",
        batch_id=job.job_id,
        display_name="Synthetic GNINA Export",
    )
    export_dir = Path(receipt["record_directory"])
    zip_path = export_dir / receipt["archive_filename"]
    return export_dir, zip_path


def test_verifier_accepts_vina_and_autodock4_export_v4_directory_and_zip(tmp_path: Path) -> None:
    vina_dir, vina_zip = _write_synthetic_screening_bundle(
        tmp_path / "vina",
        engine="AutoDock Vina",
        engine_version="1.2.7",
        backend=None,
        value_column="vina_score_kcal_mol",
    )
    ad4_dir, ad4_zip = _write_synthetic_screening_bundle(tmp_path / "ad4")

    # AutoDock4 manifest table.columns must match results.csv including cluster columns
    ad4_manifest = json.loads((ad4_dir / "manifest.json").read_text(encoding="utf-8"))
    assert ad4_manifest["table"]["columns"][-2:] == ["clusters", "top_cluster_runs"]

    vina_dir_rep = verify_bundle(vina_dir, require_format=4)
    vina_zip_rep = verify_bundle(vina_zip, require_format=4)
    ad4_dir_rep = verify_bundle(ad4_dir, require_format=4)
    ad4_zip_rep = verify_bundle(ad4_zip, require_format=4)

    assert vina_dir_rep["embedded_zip_verified"] is True
    assert vina_zip_rep["bundle_container"] == "zip"
    assert ad4_dir_rep["embedded_zip_verified"] is True
    assert ad4_zip_rep["row_count"] == 2


def test_verifier_accepts_gnina_service_export_and_runs_standalone_via_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, zip_path = _export_synthetic_gnina_job(tmp_path, monkeypatch)

    report = verify_bundle(zip_path, require_format=4)
    assert report["verified"] is True
    assert report["row_kind"] == "pose"
    assert report["row_count"] == 1
    assert report["verified_source_files"] == 8
    assert report["matched_recorded_hashes"] == 4

    # Run as an isolated subprocess with -S (no site/PYTHONPATH Ankora packages required)
    proc = subprocess.run(
        [sys.executable, "-S", str(SCRIPT_PATH), "--require-format", "4", "--json", str(zip_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    cli_payload = json.loads(proc.stdout)
    assert cli_payload["verified"] is True
    assert cli_payload["bundle_identity_sha256"] == report["bundle_identity_sha256"]


def test_verifier_detects_manifest_input_and_bundle_identity_tampering(tmp_path: Path) -> None:
    export_dir, _ = _write_synthetic_screening_bundle(tmp_path / "tamper")
    manifest_path = export_dir / "manifest.json"
    original = json.loads(manifest_path.read_text(encoding="utf-8"))

    # 1. Tamper with inputs -> caught by input_identity_sha256
    tampered_inputs = json.loads(json.dumps(original))
    tampered_inputs["inputs"]["search_box"]["size_x"] = 99.0
    manifest_path.write_text(json.dumps(tampered_inputs, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(BundleVerificationError, match="input_identity_sha256 mismatch"):
        verify_bundle(export_dir)

    # 2. Tamper with display_name -> caught by bundle_identity_sha256
    tampered_bundle = json.loads(json.dumps(original))
    tampered_bundle["bundle"]["display_name"] = "Altered Title"
    manifest_path.write_text(json.dumps(tampered_bundle, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(BundleVerificationError, match="bundle_identity_sha256 mismatch"):
        verify_bundle(export_dir)


def test_verifier_detects_csv_row_deletion_and_directory_vs_zip_drift(tmp_path: Path) -> None:
    export_dir, _ = _write_synthetic_screening_bundle(tmp_path / "drift")
    csv_path = export_dir / "results.csv"
    lines = csv_path.read_text(encoding="utf-8").splitlines()

    # Dropping the failed molecule row breaks manifest selected/failed accounting
    csv_path.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")
    with pytest.raises(BundleVerificationError, match="Molecule row count"):
        verify_bundle(export_dir)

    # Restore row count & status, but alter score in directory only -> embedded ZIP drift caught!
    altered = lines[1].replace("-6.250", "-9.999")
    csv_path.write_text("\n".join([lines[0], altered, lines[2]]) + "\n", encoding="utf-8")
    with pytest.raises(
        BundleVerificationError, match="Embedded archive .* differs from directory"
    ):
        verify_bundle(export_dir)


def test_verifier_detects_source_file_tamper_and_unsafe_zip_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, zip_path = _export_synthetic_gnina_job(tmp_path, monkeypatch)

    # Corrupt 1 byte inside poses/pose_1.pdbqt in a copied ZIP
    corrupted_zip = tmp_path / "corrupted_pose.zip"
    with zipfile.ZipFile(zip_path, "r") as zin, zipfile.ZipFile(corrupted_zip, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "poses/pose_1.pdbqt":
                data = data[:-1] + (b"X" if data[-1:] != b"X" else b"Y")
            zout.writestr(item.filename, data)
    with pytest.raises(BundleVerificationError, match="SHA-256 mismatch for source_file"):
        verify_bundle(corrupted_zip)

    # Inject a path-traversal member into a ZIP
    traversal_zip = tmp_path / "traversal.zip"
    with zipfile.ZipFile(zip_path, "r") as zin, zipfile.ZipFile(traversal_zip, "w") as zout:
        for item in zin.infolist():
            zout.writestr(item.filename, zin.read(item.filename))
        zout.writestr("../escape.txt", b"nope")
    with pytest.raises(BundleVerificationError, match="Non-normalized bundle member path"):
        verify_bundle(traversal_zip)
