"""Portable export of one completed GNINA single job (ADR-027).

Every fixture here is explicitly synthetic. The two poses deliberately put the
highest CNN pose score beside the *weakest* minimized energy, so an export that
re-sorted by kcal/mol — or that collapsed the three axes into one value column —
would produce the opposite table rather than merely exercising the code.

What these pin is what a bundle is allowed to claim: a single job is exported as
one ligand and its poses rather than as a screening library, the engine's own
preserved bytes travel unmodified and hash-verified, and anything missing or
altered fails the whole export instead of producing a bundle that looks
complete.
"""

import csv
import io
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from ankora_backend.adapters.engines.gnina import parse_gnina_pdbqt
from ankora_backend.api.app import create_app
from ankora_backend.domain.errors import AnkoraDomainError
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
from ankora_backend.services.campaign_export import CampaignExportService

RECEPTOR_BYTES = b"synthetic receptor pdbqt\n"
LIGAND_BYTES = b"synthetic ligand pdbqt\n"
CONFORMER_BYTES = b"synthetic conformer sdf\n"
STDOUT_TEXT = "synthetic gnina stdout\n"
STDERR_TEXT = "synthetic gnina stderr\n"
EXECUTABLE_SHA = "a" * 64

# Synthetic: descending CNN score, with the best-ranked pose carrying the
# *weakest* minimized affinity. (mode, CNNscore, CNNaffinity pK, kcal/mol)
POSES = ((1, 0.91, 8.25, -4.5), (2, 0.42, 7.1, -9.75))

RAW_POSES = b"".join(
    f"MODEL {mode}\nREMARK minimizedAffinity {energy}\n"
    f"REMARK CNNscore {score}\nREMARK CNNaffinity {affinity}\n"
    f"ATOM      1  C   UNL     1       0.000   0.000   0.000  1.00  0.00     0.000 C\n"
    f"ENDMDL\n".encode()
    for mode, score, affinity, energy in POSES
)


def _pose_bytes(mode: int) -> bytes:
    return parse_gnina_pdbqt(RAW_POSES)[mode - 1].pdbqt


def _job(store: GninaJobStore, **overrides: Any) -> GninaJobRecord:
    poses = [
        GninaPoseResult(
            mode=mode,
            cnn_score=score,
            cnn_affinity=affinity,
            minimized_affinity_kcal_mol=energy,
            artifact=GninaPoseArtifact(
                artifact_id=f"synthetic-pose-{mode}",
                mode=mode,
                filename=f"pose_{mode}.pdbqt",
                sha256=sha256(_pose_bytes(mode)).hexdigest(),
                size_bytes=len(_pose_bytes(mode)),
            ),
        )
        for mode, score, affinity, energy in POSES
    ]
    fields: dict[str, Any] = {
        "job_id": store.new_job_id(),
        "status": DockingJobStatus.COMPLETED,
        "phase": DockingJobPhase.COMPLETE,
        "created_at": datetime.now(UTC),
        "completed_at": datetime.now(UTC),
        "request": GninaDockingRequest(
            receptor_id="synthetic-receptor",
            binding_site_id="synthetic-site",
            ligand_id="synthetic-ligand",
            ligand_preparation_id="synthetic-preparation",
            parameters=GninaDockingParameters(compute="cpu"),
            acknowledge_inputs_and_scoring=True,
        ),
        "tool": GninaToolIdentity(version="1.3.3", sha256=EXECUTABLE_SHA, architecture="x86_64"),
        "box": BindingBox(
            center_x=1.5, center_y=2.25, center_z=3.75, size_x=10, size_y=12, size_z=14
        ),
        "receptor_output_artifact_id": "synthetic-receptor-pdbqt",
        "receptor_sha256": sha256(RECEPTOR_BYTES).hexdigest(),
        "ligand_sha256": sha256(LIGAND_BYTES).hexdigest(),
        "conformer_sha256": sha256(CONFORMER_BYTES).hexdigest(),
        "command": ["synthetic-gnina", "--no_gpu"],
        "execution": GninaExecutionEvidence(
            command=["synthetic-gnina", "--no_gpu"],
            exit_code=0,
            stdout=STDOUT_TEXT,
            stderr=STDERR_TEXT,
        ),
        "poses": poses,
    }
    fields.update(overrides)
    return GninaJobRecord(**fields)


def _store_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides: Any):
    """A durable GNINA job with every byte it preserved, as the service wrote them."""
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    store = GninaJobStore.from_environment()
    job = _job(store, **overrides)
    store.create_job(job)
    for name, content in (
        ("receptor.pdbqt", RECEPTOR_BYTES),
        ("ligand.pdbqt", LIGAND_BYTES),
        ("conformer.sdf", CONFORMER_BYTES),
        ("raw_poses.pdbqt", RAW_POSES),
        ("stdout.log", STDOUT_TEXT.encode()),
        ("stderr.log", STDERR_TEXT.encode()),
    ):
        store.write_artifact(job.job_id, name, content)
    for pose in job.poses:
        store.write_artifact(job.job_id, pose.artifact.filename, _pose_bytes(pose.mode))
    return store, job


def _service(tmp_path: Path, store: GninaJobStore) -> CampaignExportService:
    """A real service over this project; the other engines' stores are untouched."""
    return CampaignExportService(
        root=tmp_path,
        docking_store=None,  # type: ignore[arg-type]
        autodock4_store=None,  # type: ignore[arg-type]
        autodock_gpu_store=None,  # type: ignore[arg-type]
        binding_site_store=None,  # type: ignore[arg-type]
        gnina_store=store,
    )


def _export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides: Any):
    store, job = _store_job(tmp_path, monkeypatch, **overrides)
    exported = _service(tmp_path, store).export_campaign(
        source_kind="gnina_job", batch_id=job.job_id
    )
    return exported, job


def _rows(directory: Path) -> list[dict[str, str]]:
    text = (directory / "results.csv").read_text(encoding="utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def _manifest(directory: Path) -> dict[str, Any]:
    return json.loads((directory / "manifest.json").read_text(encoding="utf-8"))


# --- the table keeps three axes and the engine's own order -----------------


def test_poses_are_exported_in_cnn_order_not_energy_order(tmp_path, monkeypatch) -> None:
    """The fixture's best CNN pose has the worst energy, so order is the test.

    Re-sorting by kcal/mol would publish a ranking GNINA never produced and
    reverse these two rows.
    """
    exported, _ = _export(tmp_path, monkeypatch)
    rows = _rows(Path(str(exported["record_directory"])))

    assert [row["mode"] for row in rows] == ["1", "2"]
    assert [row["gnina_cnn_score"] for row in rows] == ["0.91", "0.42"]
    # Descending CNN score, ascending (more favourable) energy: the two
    # orderings disagree, and the engine's own order is the one written.
    assert [row["gnina_minimized_affinity_kcal_mol"] for row in rows] == ["-4.5", "-9.75"]
    assert float(rows[0]["gnina_cnn_score"]) > float(rows[1]["gnina_cnn_score"])
    assert float(rows[0]["gnina_minimized_affinity_kcal_mol"]) > float(
        rows[1]["gnina_minimized_affinity_kcal_mol"]
    )


def test_the_three_score_axes_stay_three_columns(tmp_path, monkeypatch) -> None:
    exported, _ = _export(tmp_path, monkeypatch)
    directory = Path(str(exported["record_directory"]))
    header = (directory / "results.csv").read_text(encoding="utf-8").splitlines()[0]
    rows = _rows(directory)

    assert "gnina_cnn_score" in header
    assert "gnina_cnn_affinity_pk" in header
    assert "gnina_minimized_affinity_kcal_mol" in header
    # No bare column a reader could sort two engines together on.
    assert ",score," not in f",{header},"
    assert ",affinity," not in f",{header},"
    assert ",energy," not in f",{header},"
    # Each axis holds its own recorded value, unrounded.
    assert rows[0]["gnina_cnn_affinity_pk"] == "8.25"
    assert rows[0]["gnina_cnn_score"] != rows[0]["gnina_cnn_affinity_pk"]


def test_a_single_job_is_not_described_as_a_screening_library(tmp_path, monkeypatch) -> None:
    """No library, filter run or selection identity is invented for one job."""
    exported, job = _export(tmp_path, monkeypatch)
    directory = Path(str(exported["record_directory"]))
    payload = _manifest(directory)
    header = (directory / "results.csv").read_text(encoding="utf-8").splitlines()[0]

    assert "library_id" not in payload["inputs"]
    assert "filter_run_id" not in payload["inputs"]
    assert "selection_manifest_sha256" not in payload["inputs"]
    assert payload["inputs"]["ligand_id"] == "synthetic-ligand"
    # Nor as empty columns, which would invite concatenation with a screening
    # table. The row is a pose, and the header says so.
    for absent in ("library_id", "filter_run_id", "canonical_smiles", "source_index"):
        assert absent not in header
    assert payload["table"]["row"] == "pose"
    assert payload["counts"] == {"ligands": 1, "poses": 2}
    assert "screening library" in " ".join(payload["scientific_notes"])
    assert exported["row_count"] == 2


def test_the_bundle_claims_no_measured_affinity_and_no_shared_scale(tmp_path, monkeypatch) -> None:
    exported, _ = _export(tmp_path, monkeypatch)
    directory = Path(str(exported["record_directory"]))
    notes = " ".join(_manifest(directory)["scientific_notes"])
    readme = (directory / "README.txt").read_text(encoding="utf-8")

    assert "dimensionless" in notes and "bounded between 0 and 1" in notes
    assert "pK units" in notes
    assert "not an energy" in notes
    assert "experimentally measured binding affinity" in notes
    assert "none is evidence of biological activity" in notes
    assert "must not be merged" in notes
    assert "did not rank by it" in notes
    assert "not necessarily" in notes
    for claim in ("measured affinity of", "experimentally validated", "confirmed binder"):
        assert claim not in readme.lower()


def test_engine_identity_and_the_exact_recorded_box_travel(tmp_path, monkeypatch) -> None:
    """The box is the run's own, never a binding site that may have moved since."""
    exported, job = _export(tmp_path, monkeypatch)
    payload = _manifest(Path(str(exported["record_directory"])))

    assert payload["engine"]["name"] == "GNINA"
    assert payload["engine"]["version"] == "1.3.3"
    assert payload["engine"]["executable_sha256"] == EXECUTABLE_SHA
    assert payload["inputs"]["search_box"] == {
        "center_x": 1.5,
        "center_y": 2.25,
        "center_z": 3.75,
        "size_x": 10.0,
        "size_y": 12.0,
        "size_z": 14.0,
    }
    # The complete protocol that was actually asked for.
    assert payload["protocol"]["seed"] == job.request.parameters.seed
    assert payload["protocol"]["cnn_model"] == "dense_1_3"
    assert payload["protocol"]["pose_sort_order"] == "cnn_score_descending"
    assert exported["engine"] == "GNINA"
    assert exported["engine_version"] == "1.3.3"


def test_repeatability_is_not_assessed_rather_than_claimed(tmp_path, monkeypatch) -> None:
    """No GNINA repeat evidence exists, and an export must not invent any."""
    exported, _ = _export(tmp_path, monkeypatch)
    payload = _manifest(Path(str(exported["record_directory"])))

    assert payload["reproducibility"]["status"] == "not_assessed"
    assert payload["reproducibility"]["executions"] == []
    assert "not assessed" in payload["reproducibility"]["note"]
    assert exported["reproducibility"]["status"] == "not_assessed"
    readme = (Path(str(exported["record_directory"])) / "README.txt").read_text(encoding="utf-8")
    assert "were identical" not in readme


# --- the engine's own bytes travel, verified ------------------------------


REQUIRED_BASENAMES = {
    "receptor.pdbqt",
    "ligand.pdbqt",
    "conformer.sdf",
    "raw_poses.pdbqt",
    "stdout.log",
    "stderr.log",
    "record.json",
    "pose_1.pdbqt",
    "pose_2.pdbqt",
}


def test_the_zip_carries_every_required_input_byte_for_byte(tmp_path, monkeypatch) -> None:
    """A bundle missing the raw output or one pose is not reproducible.

    Matched by basename and digest, which is how a reader without Ankora
    checks that these are the exact bytes the job preserved.
    """
    exported, job = _export(tmp_path, monkeypatch)
    directory = Path(str(exported["record_directory"]))
    archive_name = str(exported["archive_filename"])

    with ZipFile(directory / archive_name) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}

    assert {Path(name).name for name in members} >= REQUIRED_BASENAMES
    expected = {
        "receptor.pdbqt": RECEPTOR_BYTES,
        "ligand.pdbqt": LIGAND_BYTES,
        "conformer.sdf": CONFORMER_BYTES,
        "raw_poses.pdbqt": RAW_POSES,
        "stdout.log": STDOUT_TEXT.encode(),
        "stderr.log": STDERR_TEXT.encode(),
        "pose_1.pdbqt": _pose_bytes(1),
        "pose_2.pdbqt": _pose_bytes(2),
    }
    for basename, content in expected.items():
        assert any(
            Path(name).name == basename and payload == content for name, payload in members.items()
        ), basename
    # The job record itself, so the bundle names the run it came from.
    stored_record = (
        tmp_path / "projects" / "default" / "results" / "gnina_jobs" / job.job_id / "record.json"
    ).read_bytes()
    assert any(
        Path(name).name == "record.json" and payload == stored_record
        for name, payload in members.items()
    )
    assert any(name.endswith("manifest.json") for name in members)
    assert all(not Path(name).is_absolute() and ".." not in name for name in members)


def test_copied_bytes_match_the_hashes_the_job_recorded(tmp_path, monkeypatch) -> None:
    exported, job = _export(tmp_path, monkeypatch)
    directory = Path(str(exported["record_directory"]))
    carried = {item["filename"]: item for item in _manifest(directory)["source_files"]["files"]}

    for filename, recorded in (
        ("receptor.pdbqt", job.receptor_sha256),
        ("ligand.pdbqt", job.ligand_sha256),
        ("conformer.sdf", job.conformer_sha256),
        ("pose_1.pdbqt", job.poses[0].artifact.sha256),
        ("pose_2.pdbqt", job.poses[1].artifact.sha256),
    ):
        item = carried[filename]
        assert item["sha256"] == recorded
        assert item["recorded_sha256"] == recorded
        assert item["integrity"] == "matches_recorded_sha256"
        # And the copy on disk is those same bytes.
        assert sha256((directory / item["path"]).read_bytes()).hexdigest() == recorded


def test_an_export_time_digest_is_not_presented_as_a_recorded_hash(tmp_path, monkeypatch) -> None:
    """The job records no hash for its raw output or logs; the bundle says so.

    Calling those digests "recorded" would make the bundle evidence of an
    integrity check that never ran at execution time.
    """
    exported, _ = _export(tmp_path, monkeypatch)
    directory = Path(str(exported["record_directory"]))
    source_files = _manifest(directory)["source_files"]
    carried = {item["filename"]: item for item in source_files["files"]}

    for filename in ("raw_poses.pdbqt", "stdout.log", "stderr.log", "record.json"):
        item = carried[filename]
        assert item["integrity"] == "export_time_digest_only"
        assert item["recorded_sha256"] is None
        assert item["sha256"] == sha256((directory / item["path"]).read_bytes()).hexdigest()
    assert "export_time_digest_only" in " ".join(source_files["notes"])
    assert "not evidence of a check made at run time" in " ".join(source_files["notes"])


def test_the_raw_output_is_comparable_with_the_execution_record(tmp_path, monkeypatch) -> None:
    """Preserved, not reparsed: the logs still equal the recorded text.

    This is a comparison against what the record holds, which is the only
    integrity statement available for a file the job never hashed.
    """
    exported, job = _export(tmp_path, monkeypatch)
    directory = Path(str(exported["record_directory"]))

    assert job.execution is not None
    assert (directory / "raw" / "stdout.log").read_text(encoding="utf-8") == job.execution.stdout
    assert (directory / "raw" / "stderr.log").read_text(encoding="utf-8") == job.execution.stderr
    raw = (directory / "raw" / "raw_poses.pdbqt").read_bytes()
    assert raw == RAW_POSES
    # Each published pose's recorded scores are still findable in the raw file.
    for pose in job.poses:
        assert f"CNNscore {pose.cnn_score}".encode() in raw
        assert f"minimizedAffinity {pose.minimized_affinity_kcal_mol}".encode() in raw


# --- failing closed -------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    ["receptor.pdbqt", "ligand.pdbqt", "conformer.sdf", "pose_1.pdbqt", "pose_2.pdbqt"],
)
def test_a_tampered_input_refuses_the_whole_export(tmp_path, monkeypatch, filename) -> None:
    """A changed input is a different run; a bundle would misattribute it."""
    store, job = _store_job(tmp_path, monkeypatch)
    target = store.output_path(job.job_id, filename)
    target.write_bytes(b"altered synthetic content\n")

    with pytest.raises(AnkoraDomainError) as error:
        _service(tmp_path, store).export_campaign(source_kind="gnina_job", batch_id=job.job_id)

    assert error.value.code == "EXPORT_SOURCE_TAMPERED"
    assert error.value.details["filename"] == filename
    # No ZIP, and nothing a reader could mistake for a complete bundle.
    assert not list((tmp_path / "projects" / "default" / "exports").rglob("*.zip"))


@pytest.mark.parametrize(
    "filename", ["raw_poses.pdbqt", "stdout.log", "stderr.log", "pose_2.pdbqt"]
)
def test_a_missing_required_input_refuses_the_whole_export(tmp_path, monkeypatch, filename) -> None:
    """Silently omitting the raw output would make the bundle look complete."""
    store, job = _store_job(tmp_path, monkeypatch)
    store.output_path(job.job_id, filename).unlink()

    with pytest.raises(AnkoraDomainError) as error:
        _service(tmp_path, store).export_campaign(source_kind="gnina_job", batch_id=job.job_id)

    assert error.value.code == "EXPORT_SOURCE_INCOMPLETE"
    assert error.value.details["filename"] == filename
    assert not list((tmp_path / "projects" / "default" / "exports").rglob("*.zip"))


@pytest.mark.parametrize(
    "status",
    [
        DockingJobStatus.QUEUED,
        DockingJobStatus.RUNNING,
        DockingJobStatus.FAILED,
        DockingJobStatus.CANCELED,
    ],
)
def test_an_incomplete_job_is_not_exportable(tmp_path, monkeypatch, status) -> None:
    """A job with no published poses has no result to describe."""
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    store = GninaJobStore.from_environment()
    job = _job(
        store,
        status=status,
        phase=DockingJobPhase.QUEUED,
        poses=[],
        execution=None,
        completed_at=None,
    )
    store.create_job(job)

    with pytest.raises(AnkoraDomainError) as error:
        _service(tmp_path, store).export_campaign(source_kind="gnina_job", batch_id=job.job_id)

    assert error.value.code == "EXPORT_SOURCE_INCOMPLETE"
    assert error.value.details["status"] == status.value
    assert not (tmp_path / "projects" / "default" / "exports").exists()


def test_an_unknown_job_identifier_is_refused(tmp_path, monkeypatch) -> None:
    store, _ = _store_job(tmp_path, monkeypatch)

    with pytest.raises(AnkoraDomainError) as error:
        _service(tmp_path, store).export_campaign(
            source_kind="gnina_job",
            batch_id="00000000-0000-4000-8000-000000000000",
        )

    assert error.value.code == "GNINA_JOB_NOT_FOUND"


# --- the Methods section and the recorded evidence beside it ---------------


def test_the_bundle_carries_the_methods_section_for_this_job(tmp_path, monkeypatch) -> None:
    """Rendered by GNINA's own path, never another engine's procedure."""
    exported, _ = _export(tmp_path, monkeypatch)
    directory = Path(str(exported["record_directory"]))

    assert "methods.md" in exported["files"]
    methods = (directory / "methods.md").read_text(encoding="utf-8")
    assert "GNINA 1.3.3" in methods
    assert "descending CNN pose score" in methods
    for borrowed in ("Lamarckian", "AutoGrid", "clustered by AutoDock", "energy range"):
        assert borrowed not in methods


def test_an_existing_redocking_verdict_travels_byte_for_byte(tmp_path, monkeypatch) -> None:
    """A verdict already recorded about this job is copied, never re-measured."""
    store, job = _store_job(tmp_path, monkeypatch)
    from test_redocking_workflow import FIXTURES, REFERENCE_ID, reference_record

    from ankora_backend.persistence.ligand_store import LigandArtifactStore

    reference = reference_record()
    reference_bytes = (FIXTURES / "redocking_7aqf_rv2_crystal.sdf").read_bytes()
    LigandArtifactStore(tmp_path).create(REFERENCE_ID, reference_bytes, reference)
    verdict_id = "00000000-0000-0000-0000-0000000000a1"
    verdict = {
        "validation_id": verdict_id,
        "created_at": "2026-11-04T12:00:00Z",
        "receptor_id": "synthetic-receptor",
        "binding_site_id": "synthetic-site",
        "source_kind": "gnina_job",
        "source_id": job.job_id,
        "engine": "GNINA",
        "engine_version": "1.3.3",
        # Null, not false: GNINA repeat behavior has never been assessed.
        "bitwise_reproducible": None,
        "reference_ligand_id": REFERENCE_ID,
        "reference_sha256": sha256(reference_bytes).hexdigest(),
        "reference_heavy_atom_count": 45,
        "metrics": {
            "threshold_angstrom": 2.0,
            "pose_count": 2,
            "top1_rmsd_angstrom": 1.25,
            "best_top5_rmsd_angstrom": 1.25,
            "best_overall_rmsd_angstrom": 1.25,
            "first_recovering_rank": 1,
            "recovered_pose_count": 1,
            "sampling_success": True,
            "ranking_success": True,
            "outcome": "recovered_and_ranked",
        },
        "poses": [
            {
                "run": 1,
                "rank": 1,
                "binding_energy_kcal_mol": -4.5,
                "rmsd_angstrom": 1.25,
                "recovered": True,
                "cnn_score": 0.91,
                "cnn_affinity_pk": 8.25,
            }
        ],
    }
    verdict_dir = tmp_path / "projects" / "default" / "validation" / "redocking" / verdict_id
    verdict_dir.mkdir(parents=True)
    recorded = json.dumps(verdict, indent=2).encode("utf-8")
    (verdict_dir / "record.json").write_bytes(recorded)

    exported = _service(tmp_path, store).export_campaign(
        source_kind="gnina_job", batch_id=job.job_id
    )
    directory = Path(str(exported["record_directory"]))
    payload = _manifest(directory)

    assert exported["redocking_validation_count"] == 1
    carried = payload["recorded_evidence"]["redocking_validations"][0]
    assert carried["validation_id"] == verdict_id
    assert carried["outcome"] == "recovered_and_ranked"
    # Null stays null rather than being read as a measured `false`.
    assert carried["bitwise_reproducible"] is None
    copied = directory / carried["path"]
    assert copied.read_bytes() == recorded
    assert carried["sha256"] == sha256(recorded).hexdigest()
    assert (directory / carried["reference"]["path"]).read_bytes() == reference_bytes
    assert carried["reference"]["sha256"] == sha256(reference_bytes).hexdigest()
    with ZipFile(directory / str(exported["archive_filename"])) as archive:
        assert any(
            archive.read(name) == recorded
            for name in archive.namelist()
            if Path(name).name == "record.json"
        )
    assert "not validation of the engine in general" in " ".join(
        payload["recorded_evidence"]["notes"]
    )
    LigandArtifactStore(tmp_path).content_path(REFERENCE_ID).write_bytes(b"tampered reference")
    second = _service(tmp_path, store).export_campaign(source_kind="gnina_job", batch_id=job.job_id)
    second_manifest = _manifest(Path(str(second["record_directory"])))
    evidence = second_manifest["recorded_evidence"]
    assert evidence["redocking_validations"][0]["reference"] is None
    assert any(
        warning["kind"] == "redocking_reference_unavailable"
        for warning in evidence["collection_warnings"]
    )


def test_another_results_verdict_is_not_pulled_into_this_bundle(tmp_path, monkeypatch) -> None:
    """Evidence travels with the result it judged, not with any result."""
    store, job = _store_job(tmp_path, monkeypatch)
    other_id = "00000000-0000-0000-0000-0000000000b2"
    other_dir = tmp_path / "projects" / "default" / "validation" / "redocking" / other_id
    other_dir.mkdir(parents=True)
    (other_dir / "record.json").write_text(
        json.dumps(
            {
                "validation_id": other_id,
                "created_at": "2026-11-04T12:00:00Z",
                "receptor_id": "synthetic-receptor",
                "binding_site_id": "synthetic-site",
                "source_kind": "vina_job",
                "source_id": "another-result",
                "engine": "AutoDock Vina",
                "engine_version": "1.2.7",
                "bitwise_reproducible": True,
                "reference_ligand_id": "synthetic-reference",
                "reference_sha256": "c" * 64,
                "reference_heavy_atom_count": 45,
                "metrics": {
                    "threshold_angstrom": 2.0,
                    "pose_count": 1,
                    "top1_rmsd_angstrom": 0.5,
                    "best_top5_rmsd_angstrom": 0.5,
                    "best_overall_rmsd_angstrom": 0.5,
                    "first_recovering_rank": 1,
                    "recovered_pose_count": 1,
                    "sampling_success": True,
                    "ranking_success": True,
                    "outcome": "recovered_and_ranked",
                },
                "poses": [
                    {
                        "run": 1,
                        "rank": 1,
                        "binding_energy_kcal_mol": -7.5,
                        "rmsd_angstrom": 0.5,
                        "recovered": True,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    exported = _service(tmp_path, store).export_campaign(
        source_kind="gnina_job", batch_id=job.job_id
    )

    assert exported["redocking_validation_count"] == 0
    payload = _manifest(Path(str(exported["record_directory"])))
    assert payload["recorded_evidence"]["redocking_validations"] == []


# --- the endpoint and the project boundary --------------------------------


def test_the_endpoint_exports_a_gnina_job_on_the_same_contract(tmp_path, monkeypatch) -> None:
    """Same route, same response shape, and the ZIP is served back."""
    _store, job = _store_job(tmp_path, monkeypatch)

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/exports/campaigns",
            params={"source_kind": "gnina_job", "source_id": job.job_id},
        )

        assert response.status_code == 201
        exported = response.json()
        assert exported["source_kind"] == "gnina_job"
        assert exported["source_id"] == job.job_id
        assert exported["catalog_id"] == f"gnina_job:{job.job_id}"
        # The contract every other campaign export answers on.
        for key in (
            "export_id",
            "exported_at",
            "display_name",
            "input_identity_sha256",
            "bundle_identity_sha256",
            "archive_filename",
            "engine",
            "engine_version",
            "reproducibility",
            "row_count",
            "interaction_analysis_count",
            "figure_count",
            "directory",
            "outside_project",
            "record_directory",
            "files",
        ):
            assert key in exported, key

        archive = str(exported["archive_filename"])
        download = client.get(f"/api/v1/exports/{exported['export_id']}/{archive}")
        assert download.status_code == 200
        with ZipFile(io.BytesIO(download.content)) as opened:
            assert {Path(name).name for name in opened.namelist()} >= REQUIRED_BASENAMES

        listed = client.get("/api/v1/exports").json()
        entry = next(
            item for item in listed["entries"] if item["export_id"] == exported["export_id"]
        )
        # Counted in the units it was actually counted in.
        assert entry["subtitle"] == "1 ligand · 2 poses"
        assert entry["source_kind"] == "gnina_job"
        assert entry["reproducibility"]["status"] == "not_assessed"


def test_a_gnina_job_in_another_project_is_not_exportable(tmp_path, monkeypatch) -> None:
    """Export resolves its store per request, so a switch narrows the view."""
    _store, job = _store_job(tmp_path, monkeypatch)

    with TestClient(create_app()) as client:
        first = client.post(
            "/api/v1/exports/campaigns",
            params={"source_kind": "gnina_job", "source_id": job.job_id},
        )
        assert first.status_code == 201

        created = client.post("/api/v1/projects", json={"name": "Synthetic other project"})
        assert created.status_code == 201
        other = created.json()["project_id"]
        assert client.post(f"/api/v1/projects/{other}/activate").status_code == 200

        # Same identifier, different project: the record is simply not there.
        response = client.post(
            "/api/v1/exports/campaigns",
            params={"source_kind": "gnina_job", "source_id": job.job_id},
        )
        assert response.status_code == 404
        assert client.get("/api/v1/exports").json()["total"] == 0


def test_a_batch_shaped_gnina_source_is_still_unknown(tmp_path, monkeypatch) -> None:
    """`gnina_batch` is never a valid source kind; screening uses `gnina_screening`."""
    store, _ = _store_job(tmp_path, monkeypatch)

    with pytest.raises(AnkoraDomainError) as error:
        _service(tmp_path, store).export_campaign(source_kind="gnina_batch", batch_id="whatever")

    assert error.value.code == "EXPORT_SOURCE_UNKNOWN"


# --- multi-ligand GNINA screening campaign export (`gnina_screening`) ------


def _store_screening_campaign(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    finalize: bool = True,
) -> tuple[GninaJobStore, Any, Any, str, Path]:
    """Synthetic 5-entry GNINA screening campaign (3 hits, 1 engine fail, 1 preflight)."""
    from types import SimpleNamespace

    from ankora_backend.persistence.gnina_screening_store import GninaScreeningStore
    from ankora_backend.schemas.docking import DockingFailure
    from ankora_backend.schemas.gnina_screening import (
        GninaScreeningCampaignRecord,
        GninaScreeningEntry,
        GninaScreeningPreflightCode,
        GninaScreeningRequest,
        GninaScreeningSelection,
    )
    from ankora_backend.schemas.ligands import (
        LigandFilterDisposition,
        LigandLibraryFilterPlan,
        LigandMicrostatePlan,
    )

    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    job_store = GninaJobStore.from_environment()
    screening_store = GninaScreeningStore.from_environment()
    campaign_id = screening_store.new_campaign_id()
    now = datetime.now(UTC)

    parameters = GninaDockingParameters(compute="cuda", device_index=0)
    box = BindingBox(
        center_x=1.5, center_y=2.25, center_z=3.75, size_x=10, size_y=12, size_z=14
    )
    tool = GninaToolIdentity(version="1.3.3", sha256=EXECUTABLE_SHA, architecture="x86_64")

    def _make_child(
        lig_id: str,
        prep_id: str,
        lig_bytes: bytes,
        conf_bytes: bytes,
        *,
        cnn_score: float,
        cnn_affinity: float,
        energy: float,
    ) -> GninaJobRecord:
        raw_poses = (
            f"MODEL 1\nREMARK minimizedAffinity {energy}\n"
            f"REMARK CNNscore {cnn_score}\nREMARK CNNaffinity {cnn_affinity}\n"
            f"ATOM      1  C   UNL     1       0.000   0.000   0.000  1.00  0.00     0.000 C\n"
            f"ENDMDL\n"
        ).encode()
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
                ligand_id=lig_id,
                ligand_preparation_id=prep_id,
                parameters=parameters,
                acknowledge_inputs_and_scoring=True,
            ),
            tool=tool,
            box=box,
            receptor_output_artifact_id="synthetic-receptor-pdbqt",
            receptor_sha256=sha256(RECEPTOR_BYTES).hexdigest(),
            ligand_sha256=sha256(lig_bytes).hexdigest(),
            conformer_sha256=sha256(conf_bytes).hexdigest(),
            command=["synthetic-gnina", "--device", "0"],
            execution=GninaExecutionEvidence(
                command=["synthetic-gnina", "--device", "0"],
                exit_code=0,
                stdout=STDOUT_TEXT,
                stderr=STDERR_TEXT,
                gpu_process_observed=True,
                gpu_observation="synthetic nvidia-smi",
                requested_gpu_uuid="GPU-synthetic-0",
                observed_gpu_uuid="GPU-synthetic-0",
            ),
            poses=[
                GninaPoseResult(
                    mode=1,
                    cnn_score=cnn_score,
                    cnn_affinity=cnn_affinity,
                    minimized_affinity_kcal_mol=energy,
                    artifact=GninaPoseArtifact(
                        artifact_id=f"pose-{lig_id}-1",
                        mode=1,
                        filename="pose_1.pdbqt",
                        sha256=sha256(pose_bytes).hexdigest(),
                        size_bytes=len(pose_bytes),
                    ),
                )
            ],
        )
        job_store.create_job(child)
        for fname, payload in (
            ("receptor.pdbqt", RECEPTOR_BYTES),
            ("ligand.pdbqt", lig_bytes),
            ("conformer.sdf", conf_bytes),
            ("raw_poses.pdbqt", raw_poses),
            ("stdout.log", STDOUT_TEXT.encode()),
            ("stderr.log", STDERR_TEXT.encode()),
            ("pose_1.pdbqt", pose_bytes),
        ):
            job_store.write_artifact(child.job_id, fname, payload)
        return child

    # Alpha has better kcal/mol (-9.8) than Beta (-4.1), while Beta has higher CNNscore (0.94).
    # Gamma ties Alpha's CNNscore (0.85) later in selection order, testing tie-breaking.
    lig_a = b"synthetic ligand alpha pdbqt\n"
    conf_a = b"synthetic conformer alpha sdf\n"
    lig_b = b"synthetic ligand beta pdbqt\n"
    conf_b = b"synthetic conformer beta sdf\n"
    lig_c = b"synthetic ligand gamma pdbqt\n"
    conf_c = b"synthetic conformer gamma sdf\n"
    lig_d = b"synthetic ligand delta pdbqt\n"
    conf_d = b"synthetic conformer delta sdf\n"

    job_a = _make_child(
        "synthetic-lig-a", "prep-a", lig_a, conf_a, cnn_score=0.85, cnn_affinity=7.1, energy=-9.8
    )
    job_b = _make_child(
        "synthetic-lig-b", "prep-b", lig_b, conf_b, cnn_score=0.94, cnn_affinity=8.4, energy=-4.1
    )
    job_c = _make_child(
        "synthetic-lig-c", "prep-c", lig_c, conf_c, cnn_score=0.85, cnn_affinity=6.9, energy=-10.2
    )
    failed_child = GninaJobRecord(
        job_id=job_store.new_job_id(),
        screening_campaign_id=campaign_id,
        status=DockingJobStatus.FAILED,
        phase=DockingJobPhase.COMPLETE,
        created_at=now,
        completed_at=now,
        request=GninaDockingRequest(
            receptor_id="synthetic-receptor",
            binding_site_id="synthetic-site",
            ligand_id="synthetic-lig-d",
            ligand_preparation_id="prep-d",
            parameters=parameters,
            acknowledge_inputs_and_scoring=True,
        ),
        tool=tool,
        box=box,
        receptor_output_artifact_id="synthetic-receptor-pdbqt",
        receptor_sha256=sha256(RECEPTOR_BYTES).hexdigest(),
        ligand_sha256=sha256(lig_d).hexdigest(),
        conformer_sha256=sha256(conf_d).hexdigest(),
        command=["synthetic-gnina", "--device", "0"],
        failure=DockingFailure(code="GNINA_EXECUTION_FAILED", message="Synthetic engine failure."),
    )
    job_store.create_job(failed_child)
    job_store.write_artifact(failed_child.job_id, "stderr.log", b"synthetic engine stderr\n")

    entries = [
        GninaScreeningEntry(
            ligand_id="synthetic-lig-a",
            chemical_state_id="state-a",
            source_index=10,
            name="Synthetic Alpha",
            ligand_preparation_id="prep-a",
            conformer_id="conf-a",
            ligand_sha256=sha256(lig_a).hexdigest(),
            conformer_sha256=sha256(conf_a).hexdigest(),
            status=DockingJobStatus.QUEUED,
            phase=DockingJobPhase.QUEUED,
        ),
        GninaScreeningEntry(
            ligand_id="synthetic-lig-b",
            chemical_state_id="state-b",
            source_index=20,
            name="Synthetic Beta",
            ligand_preparation_id="prep-b",
            conformer_id="conf-b",
            ligand_sha256=sha256(lig_b).hexdigest(),
            conformer_sha256=sha256(conf_b).hexdigest(),
            status=DockingJobStatus.QUEUED,
            phase=DockingJobPhase.QUEUED,
        ),
        GninaScreeningEntry(
            ligand_id="synthetic-lig-c",
            chemical_state_id="state-c",
            source_index=30,
            name="Synthetic Gamma",
            ligand_preparation_id="prep-c",
            conformer_id="conf-c",
            ligand_sha256=sha256(lig_c).hexdigest(),
            conformer_sha256=sha256(conf_c).hexdigest(),
            status=DockingJobStatus.QUEUED,
            phase=DockingJobPhase.QUEUED,
        ),
        GninaScreeningEntry(
            ligand_id="synthetic-lig-d",
            chemical_state_id="state-d",
            source_index=40,
            name="Synthetic EngineFail",
            ligand_preparation_id="prep-d",
            conformer_id="conf-d",
            ligand_sha256=sha256(lig_d).hexdigest(),
            conformer_sha256=sha256(conf_d).hexdigest(),
            status=DockingJobStatus.QUEUED,
            phase=DockingJobPhase.QUEUED,
        ),
        GninaScreeningEntry(
            ligand_id="synthetic-lig-e",
            chemical_state_id="state-e",
            source_index=50,
            name="Synthetic PreflightRefused",
            status=DockingJobStatus.FAILED,
            phase=DockingJobPhase.COMPLETE,
            completed_at=now,
            failure=DockingFailure(
                code=GninaScreeningPreflightCode.LIGAND_NOT_PREPARED,
                message="Synthetic preflight refusal.",
            ),
        ),
    ]

    plan = LigandLibraryFilterPlan()
    microstate_plan = LigandMicrostatePlan()
    summary_dict = {
        "imported_count": 6,
        "eligible_count": 5,
        "excluded_count": 1,
        "needs_decision_count": 0,
        "pains_match_count": 0,
        "brenk_match_count": 0,
        "duplicate_count": 0,
    }
    eval_dicts = [
        {
            "ligand_id": item.ligand_id,
            "state_id": item.chemical_state_id,
            "record_index": item.source_index,
            "disposition": LigandFilterDisposition.ELIGIBLE.value,
        }
        for item in entries
    ]
    manifest_payload = {
        "filter_run_id": "synthetic-filter",
        "library_id": "synthetic-library",
        "created_at": now.isoformat(),
        "rdkit_version": "2025.09.6",
        "worker_count": 1,
        "plan": plan.model_dump(mode="json"),
        "microstate_plan": microstate_plan.model_dump(mode="json"),
        "summary": summary_dict,
        "selected_ligand_ids": [item.ligand_id for item in entries],
        "evaluations": eval_dicts,
    }
    manifest_file = tmp_path / "selection_manifest.json"
    manifest_bytes = json.dumps(manifest_payload).encode("utf-8")
    manifest_file.write_bytes(manifest_bytes)
    manifest_sha = sha256(manifest_bytes).hexdigest()

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
        selected_ligand_ids=[item.ligand_id for item in entries],
        evaluations=[
            SimpleNamespace(
                ligand_id=item["ligand_id"],
                state_id=item["state_id"],
                record_index=item["record_index"],
                disposition=LigandFilterDisposition.ELIGIBLE,
                model_dump=lambda mode="json", row=item: dict(row),
            )
            for item in eval_dicts
        ],
    )
    ligand_stub = SimpleNamespace(
        load_filter_run=lambda _lib, _run: filter_run_record,
        filter_run_content_path=lambda _lib, _run: manifest_file,
        load_record=lambda lig_id: SimpleNamespace(
            inspection=SimpleNamespace(
                name=lig_id,
                canonical_smiles="CCO",
                molecular_weight_g_mol=46.068,
            ),
            state=SimpleNamespace(state_id=f"state-{lig_id[-1]}"),
        ),
    )

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
            acknowledge_inputs_and_scoring=True,
        ),
        tool=tool,
        selection=GninaScreeningSelection(
            library_id="synthetic-library",
            filter_run_id="synthetic-filter",
            manifest_artifact_id="synthetic-filter",
            manifest_sha256=manifest_sha,
        ),
        receptor_output_artifact_id="synthetic-receptor-pdbqt",
        receptor_sha256=sha256(RECEPTOR_BYTES).hexdigest(),
        box=box,
        selected_count=5,
        completed_count=1,
        failed_count=1,
        entries=entries,
    )
    monkeypatch.setattr(
        "ankora_backend.persistence.gnina_screening_store.verified_screening_selection",
        lambda **_kwargs: filter_run_record,
    )
    monkeypatch.setattr(
        GninaScreeningStore, "_verify_entry_preparation", lambda *_args, **_kwargs: None
    )
    screening_store.create_campaign(campaign)

    for lig_id, child_job in (
        ("synthetic-lig-a", job_a),
        ("synthetic-lig-b", job_b),
        ("synthetic-lig-c", job_c),
    ):
        stored = screening_store.load_entry(campaign_id, lig_id)
        assert stored is not None
        running = screening_store.update_entry(
            campaign_id,
            stored.model_copy(
                update={
                    "status": DockingJobStatus.RUNNING,
                    "phase": DockingJobPhase.DOCKING,
                    "gnina_job_id": child_job.job_id,
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

    stored_d = screening_store.load_entry(campaign_id, "synthetic-lig-d")
    assert stored_d is not None
    running_d = screening_store.update_entry(
        campaign_id,
        stored_d.model_copy(
            update={
                "status": DockingJobStatus.RUNNING,
                "phase": DockingJobPhase.DOCKING,
                "gnina_job_id": failed_child.job_id,
                "started_at": now,
            }
        ),
    )
    if finalize:
        screening_store.update_entry(
            campaign_id,
            running_d.model_copy(
                update={
                    "status": DockingJobStatus.FAILED,
                    "phase": DockingJobPhase.COMPLETE,
                    "completed_at": now,
                    "failure": DockingFailure(
                        code="GNINA_EXECUTION_FAILED",
                        message="Synthetic engine failure.",
                    ),
                }
            ),
        )
        screening_store.finalize_campaign(campaign_id)

    return job_store, screening_store, ligand_stub, campaign_id, manifest_file


def _screening_export_service(
    tmp_path: Path,
    job_store: GninaJobStore,
    screening_store: Any,
    ligand_stub: Any,
) -> CampaignExportService:
    return CampaignExportService(
        root=tmp_path,
        docking_store=None,  # type: ignore[arg-type]
        autodock4_store=None,  # type: ignore[arg-type]
        autodock_gpu_store=None,  # type: ignore[arg-type]
        binding_site_store=None,  # type: ignore[arg-type]
        gnina_store=job_store,
        gnina_screening_store=screening_store,
        ligand_store=ligand_stub,
    )


def test_gnina_screening_bundle_preserves_three_axes_tie_order_and_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Screening rows rank by CNNscore, tie-break by selection order, and keep failures."""
    job_store, screening_store, ligand_stub, campaign_id, _ = _store_screening_campaign(
        tmp_path, monkeypatch
    )
    exported = _screening_export_service(
        tmp_path, job_store, screening_store, ligand_stub
    ).export_campaign(
        source_kind="gnina_screening",
        batch_id=campaign_id,
        display_name="Synthetic GNINA screen",
    )
    directory = Path(str(exported["record_directory"]))
    rows = _rows(directory)
    payload = _manifest(directory)
    header = (directory / "results.csv").read_text(encoding="utf-8").splitlines()[0]
    readme_text = (directory / "README.txt").read_text(encoding="utf-8")

    assert exported["row_count"] == 5
    assert payload["table"]["row"] == "molecule"
    assert "gnina_cnn_score" in header
    assert "gnina_cnn_affinity_pk" in header
    assert "gnina_minimized_affinity_kcal_mol" in header
    assert "clusters" not in header
    assert "top_cluster_runs" not in header

    # Ranked by descending CNNscore (Beta 0.94 first), then selection order on exact tie
    # (Alpha 0.85 before Gamma 0.85 even though Gamma has lower kcal/mol -10.2 < -9.8),
    # followed by unranked failed/preflight-refused molecules in selection order.
    assert [row["molecule"] for row in rows] == [
        "Synthetic Beta",
        "Synthetic Alpha",
        "Synthetic Gamma",
        "Synthetic EngineFail",
        "Synthetic PreflightRefused",
    ]
    assert [row["rank"] for row in rows] == ["1", "2", "3", "", ""]
    assert [row["gnina_cnn_score"] for row in rows] == ["0.94", "0.85", "0.85", "", ""]
    assert [row["gnina_minimized_affinity_kcal_mol"] for row in rows] == [
        "-4.1",
        "-9.8",
        "-10.2",
        "",
        "",
    ]
    assert rows[3]["failure_code"] == "GNINA_EXECUTION_FAILED"
    assert rows[3]["gnina_job_id"] != ""
    assert rows[4]["failure_code"] == "GNINA_SCREENING_LIGAND_NOT_PREPARED"
    assert rows[4]["gnina_job_id"] == ""

    assert payload["counts"] == {"selected": 5, "succeeded": 3, "failed": 2}
    assert payload["inputs"]["library_id"] == "synthetic-library"
    assert payload["inputs"]["filter_run_id"] == "synthetic-filter"
    assert payload["engine"]["device"] == "GPU-synthetic-0"
    assert "computational estimate in kcal/mol" not in readme_text
    assert "gnina_cnn_score is dimensionless (0-1)" in readme_text

    # Shared receptor and pinned selection manifest travel once with verified hashes,
    # alongside campaign records and per-job artifacts inside the portable ZIP.
    paths_by_integrity = {
        item["path"]: item["integrity"] for item in payload["source_files"]["files"]
    }
    assert paths_by_integrity["inputs/receptor.pdbqt"] == "matches_recorded_sha256"
    assert paths_by_integrity["inputs/selection_manifest.json"] == "matches_recorded_sha256"
    assert paths_by_integrity["campaign/record.json"] == "export_time_digest_only"
    assert paths_by_integrity["campaign/campaign_state.sqlite3"] == "export_time_digest_only"
    with ZipFile(directory / str(exported["archive_filename"])) as archive:
        names = set(archive.namelist())
        assert "inputs/receptor.pdbqt" in names
        assert "inputs/selection_manifest.json" in names
        assert "campaign/record.json" in names
        assert "campaign/campaign_state.sqlite3" in names
        assert f"jobs/{rows[0]['gnina_job_id']}/poses/pose_1.pdbqt" in names
        assert f"jobs/{rows[3]['gnina_job_id']}/job/record.json" in names


def test_gnina_screening_export_fails_closed_before_writing_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Incomplete campaigns or tampered manifest/child bytes write no export folder."""
    exports_root = tmp_path / "projects" / "default" / "exports"

    # 1. Incomplete (still running) campaign -> 409 EXPORT_SOURCE_INCOMPLETE.
    inc_dir = tmp_path / "incomplete"
    job_store, screening_store, ligand_stub, campaign_id, _ = _store_screening_campaign(
        inc_dir, monkeypatch, finalize=False
    )
    with pytest.raises(AnkoraDomainError) as inc_err:
        _screening_export_service(
            inc_dir, job_store, screening_store, ligand_stub
        ).export_campaign(source_kind="gnina_screening", batch_id=campaign_id)
    assert inc_err.value.code == "EXPORT_SOURCE_INCOMPLETE"
    assert not (inc_dir / "projects" / "default" / "exports").exists()

    # 2. Tampered pinned selection manifest -> 409 EXPORT_SOURCE_TAMPERED.
    job_store, screening_store, ligand_stub, campaign_id, manifest_file = (
        _store_screening_campaign(tmp_path, monkeypatch)
    )
    original_manifest = manifest_file.read_bytes()
    manifest_file.write_bytes(b'{"tampered": true}')
    with pytest.raises(AnkoraDomainError) as manifest_err:
        _screening_export_service(
            tmp_path, job_store, screening_store, ligand_stub
        ).export_campaign(source_kind="gnina_screening", batch_id=campaign_id)
    assert manifest_err.value.code == "EXPORT_SOURCE_TAMPERED"
    assert not exports_root.exists()
    manifest_file.write_bytes(original_manifest)

    # 3. Tampered child pose bytes -> 409 EXPORT_SOURCE_TAMPERED.
    completed_entry = screening_store.load_campaign(campaign_id).entries[0]
    assert completed_entry.gnina_job_id is not None
    pose_path = job_store.output_path(completed_entry.gnina_job_id, "pose_1.pdbqt")
    pose_path.write_bytes(b"tampered pose bytes")
    with pytest.raises(AnkoraDomainError) as pose_err:
        _screening_export_service(
            tmp_path, job_store, screening_store, ligand_stub
        ).export_campaign(source_kind="gnina_screening", batch_id=campaign_id)
    assert pose_err.value.code == "EXPORT_SOURCE_TAMPERED"
    assert not exports_root.exists()


def test_the_endpoint_exports_preserved_gnina_cuda_screening_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Isolated copy of real 11-molecule CUDA campaign exports end-to-end via API."""
    import shutil

    source_data = (
        Path(__file__).resolve().parents[2]
        / "logs/linux-gnina-investigation/v1.3.3/screening-api-cuda-01/data"
    )
    if not source_data.is_dir():
        pytest.skip("Local recorded GNINA CUDA screening evidence is not present in this checkout.")
    isolated_data = tmp_path / "isolated-data"
    shutil.copytree(source_data, isolated_data)
    monkeypatch.setenv("ANKORA_DATA_DIR", str(isolated_data))

    with TestClient(create_app()) as client:
        campaigns = client.get(
            "/api/v1/results/campaigns?scoring_family=gnina&mode=screening"
        ).json()
        campaign_id = campaigns["entries"][0]["record_id"]

        response = client.post(
            "/api/v1/exports/campaigns",
            params={"source_kind": "gnina_screening", "source_id": campaign_id},
        )
        assert response.status_code == 201
        exported = response.json()
        assert exported["source_kind"] == "gnina_screening"
        assert exported["source_id"] == campaign_id
        assert exported["catalog_id"] == f"gnina_screening:{campaign_id}"
        assert exported["row_count"] == 11
        assert "methods.md" in exported["files"]

        csv_res = client.get(f"/api/v1/exports/{exported['export_id']}/results.csv")
        assert csv_res.status_code == 200
        parsed_rows = list(csv.DictReader(io.StringIO(csv_res.text)))
        assert len(parsed_rows) == 11
        assert parsed_rows[0]["rank"] == "1"
        assert parsed_rows[0]["molecule"] == "NCI-68"

        methods_res = client.get(f"/api/v1/exports/{exported['export_id']}/methods.md")
        assert methods_res.status_code == 200
        assert "doi:10.1186/s13321-021-00522-2" in methods_res.text

        archive = str(exported["archive_filename"])
        zip_res = client.get(f"/api/v1/exports/{exported['export_id']}/{archive}")
        assert zip_res.status_code == 200
        with ZipFile(io.BytesIO(zip_res.content)) as opened:
            zip_names = set(opened.namelist())
            assert {
                "results.csv",
                "manifest.json",
                "README.txt",
                "methods.md",
                "inputs/receptor.pdbqt",
                "inputs/selection_manifest.json",
                "campaign/record.json",
                "campaign/campaign_state.sqlite3",
            } <= zip_names

        listed = client.get("/api/v1/exports").json()
        entry = next(
            item for item in listed["entries"] if item["export_id"] == exported["export_id"]
        )
        assert entry["subtitle"] == "11/11 molecules docked"
        assert entry["source_kind"] == "gnina_screening"
        served_names = {item["filename"] for item in entry["files"] if item["content_url"]}
        assert {"results.csv", "manifest.json", "README.txt", "methods.md", archive} <= served_names

