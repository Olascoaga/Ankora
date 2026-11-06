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
    """Only the single-job kind is implemented; a screening kind is not."""
    store, _ = _store_job(tmp_path, monkeypatch)

    with pytest.raises(AnkoraDomainError) as error:
        _service(tmp_path, store).export_campaign(source_kind="gnina_batch", batch_id="whatever")

    assert error.value.code == "EXPORT_SOURCE_UNKNOWN"
