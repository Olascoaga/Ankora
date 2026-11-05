"""GNINA single-job redocking validation (ADR-027).

The molecules and poses here are retained real artifacts: the crystallographic
RV2 pose from 7AQF as Ankora preserved it, two poses AutoDock-GPU actually
produced against it - the one that engine ranked first, about 10.7 A from the
crystal, and the one that recovered it - and the retained real GNINA 1.3.3 CPU
output `gnina_real_1hsg_mk1.pdbqt`.

Everything wrapped around them is **explicitly synthetic routing metadata**: the
job identities, the receptor/structure identities, and each mode's CNN score,
CNN affinity and minimized affinity. Those score values are chosen so that the
CNN order and the energy order disagree, which is the condition under which a
ranking bug is visible at all. They are not GNINA measurements and no GNINA
docking result is implied by them. No scientific executable runs in this module.
"""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_redocking_workflow import REFERENCE_ID, STRUCTURE_ID, reference_record

from ankora_backend.adapters.chemistry.redocking_rmsd import (
    in_place_rmsd,
    load_pose,
    load_reference,
    pdbqt_to_pdb_block,
)
from ankora_backend.api.app import create_app
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.gnina_store import GninaJobStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.redocking_store import RedockingValidationStore
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.docking import DockingFailure, DockingJobPhase, DockingJobStatus
from ankora_backend.schemas.gnina import (
    GninaDockingParameters,
    GninaDockingRequest,
    GninaExecutionEvidence,
    GninaJobRecord,
    GninaPoseArtifact,
    GninaPoseResult,
    GninaToolIdentity,
)
from ankora_backend.schemas.redocking import (
    RedockingOutcome,
    RedockingRunRecord,
    RedockingValidationRequest,
)
from ankora_backend.services.redocking_validation import RedockingValidationService

FIXTURES = Path(__file__).parent / "fixtures"
CRYSTAL = FIXTURES / "redocking_7aqf_rv2_crystal.sdf"
TOP_RANKED = FIXTURES / "redocking_gpu_top_ranked_pose.pdbqt"
RECOVERING = FIXTURES / "redocking_gpu_recovering_pose.pdbqt"
REAL_GNINA_POSES = FIXTURES / "gnina_real_1hsg_mk1.pdbqt"
REAL_GNINA_INPUT = FIXTURES / "gnina_input_1hsg_mk1.sdf"

OTHER_STRUCTURE_ID = "00000000-0000-0000-0000-0000000000f1"

# Synthetic score metadata. Mode 1 holds the highest CNN score and the *weakest*
# minimized affinity, so any reordering by energy would put mode 2 first.
SYNTHETIC_MODES = (
    (1, 0.87, 8.4, -4.1, TOP_RANKED),
    (2, 0.42, 7.1, -9.3, RECOVERING),
)


def _job_record(
    store: GninaJobStore,
    *,
    modes: tuple[tuple[int, float, float, float, Path], ...] = SYNTHETIC_MODES,
    status: DockingJobStatus = DockingJobStatus.COMPLETED,
) -> GninaJobRecord:
    """A GNINA job record over retained pose files; identities are synthetic."""
    poses = []
    for mode, cnn_score, cnn_affinity, energy, source in modes:
        content = source.read_bytes()
        poses.append(
            GninaPoseResult(
                mode=mode,
                minimized_affinity_kcal_mol=energy,
                cnn_score=cnn_score,
                cnn_affinity=cnn_affinity,
                artifact=GninaPoseArtifact(
                    artifact_id=f"gnina-pose-{mode}",
                    mode=mode,
                    filename=f"pose_{mode}.pdbqt",
                    sha256=hashlib.sha256(content).hexdigest(),
                    size_bytes=len(content),
                ),
            )
        )
    completed = status is DockingJobStatus.COMPLETED
    return GninaJobRecord(
        job_id=store.new_job_id(),
        status=status,
        phase=DockingJobPhase.COMPLETE if completed else DockingJobPhase.DOCKING,
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC) if completed else None,
        request=GninaDockingRequest(
            receptor_id="synthetic-receptor",
            binding_site_id="synthetic-site",
            ligand_id="synthetic-ligand",
            ligand_preparation_id="synthetic-preparation",
            parameters=GninaDockingParameters(compute="cpu"),
            acknowledge_inputs_and_scoring=True,
        ),
        tool=GninaToolIdentity(version="1.3.3", sha256="1" * 64, architecture="x86_64"),
        box=BindingBox(center_x=1, center_y=2, center_z=3, size_x=10, size_y=12, size_z=14),
        receptor_output_artifact_id="synthetic-receptor-pdbqt",
        receptor_sha256="2" * 64,
        ligand_sha256="3" * 64,
        conformer_sha256="4" * 64,
        execution=(
            GninaExecutionEvidence(command=["gnina"], exit_code=0, stdout="", stderr="")
            if completed
            else None
        ),
        poses=poses if completed else [],
        failure=(
            None
            if status is not DockingJobStatus.FAILED
            else DockingFailure(
                code="GNINA_EXECUTION_FAILED",
                message="Synthetic unfinished job.",
                details={},
            )
        ),
    )


def _write_poses(store: GninaJobStore, job: GninaJobRecord) -> list[Path]:
    paths = []
    for pose, (*_, source) in zip(job.poses, SYNTHETIC_MODES, strict=False):
        paths.append(store.write_artifact(job.job_id, pose.artifact.filename, source.read_bytes()))
    return paths


def _service(
    tmp_path: Path, project_id: str = "default", gnina_project_id: str | None = None
) -> tuple[RedockingValidationService, GninaJobStore, SimpleNamespace]:
    """A service for `project_id`, plus the store jobs are written through.

    `gnina_project_id` points that store at a *different* project than the one
    the service reads, which is how project isolation is exercised.
    """
    ligand_store = LigandArtifactStore(tmp_path, project_id)
    ligand_store.create(REFERENCE_ID, CRYSTAL.read_bytes(), reference_record())
    writable_store = GninaJobStore(tmp_path, gnina_project_id or project_id)
    # Synthetic receptor/structure identities: the reference-frame rule under
    # test is identity of the immutable source structure, not chemistry.
    receptor = SimpleNamespace(source_artifact_id=STRUCTURE_ID)
    structure_hashes = {STRUCTURE_ID: "a" * 64, OTHER_STRUCTURE_ID: "b" * 64}
    service = RedockingValidationService(
        store=RedockingValidationStore(tmp_path, project_id),
        ligand_store=ligand_store,
        docking_store=SimpleNamespace(),  # type: ignore[arg-type]
        autodock4_store=SimpleNamespace(),  # type: ignore[arg-type]
        autodock_gpu_store=SimpleNamespace(),  # type: ignore[arg-type]
        receptor_store=SimpleNamespace(load_record=lambda _: receptor),  # type: ignore[arg-type]
        structure_store=SimpleNamespace(
            load_record=lambda identity: SimpleNamespace(
                artifact=SimpleNamespace(sha256=structure_hashes[identity])
            )
        ),  # type: ignore[arg-type]
        gnina_store=GninaJobStore(tmp_path, project_id),
    )
    return service, writable_store, receptor


def _request(job: GninaJobRecord, **overrides: object) -> RedockingValidationRequest:
    payload: dict[str, object] = {
        "source_kind": "gnina_job",
        "source_id": job.job_id,
        "reference_ligand_id": REFERENCE_ID,
    }
    payload.update(overrides)
    return RedockingValidationRequest.model_validate(payload)


# --- the ranking GNINA actually produced ----------------------------------


def test_the_cnn_order_is_measured_even_though_the_energy_order_disagrees(tmp_path):  # type: ignore[no-untyped-def]
    """GNINA ranks by descending CNN score, never by the minimized affinity.

    Mode 1 carries the higher CNN score and the weaker energy, so a validator
    that re-sorted by energy would report the recovering pose as rank 1 and call
    the ranking a success. The engine's own order says otherwise.
    """
    service, store, _ = _service(tmp_path)
    job = _job_record(store)
    store.create_job(job)
    _write_poses(store, job)

    record = service.validate(_request(job))

    assert [pose.rank for pose in record.poses] == [1, 2]
    assert [pose.run for pose in record.poses] == [1, 2]
    assert [pose.cnn_score for pose in record.poses] == [0.87, 0.42]
    assert [pose.cnn_affinity_pk for pose in record.poses] == [8.4, 7.1]
    # The minimized empirical affinity is kept as such and did not rank anything:
    # the most favourable energy sits at rank 2.
    assert [pose.binding_energy_kcal_mol for pose in record.poses] == [-4.1, -9.3]
    assert record.poses[1].binding_energy_kcal_mol == min(
        pose.binding_energy_kcal_mol for pose in record.poses
    )
    # Real measurements of the retained poses, in place and not superimposed.
    assert record.metrics.top1_rmsd_angstrom > 10
    assert record.metrics.best_overall_rmsd_angstrom < 2
    assert record.metrics.sampling_success is True
    assert record.metrics.ranking_success is False
    assert record.metrics.outcome is RedockingOutcome.RECOVERED_BUT_MISRANKED
    assert record.metrics.first_recovering_rank == 2


def test_the_verdict_keeps_gnina_repeatability_unassessed_and_names_its_inputs(tmp_path):  # type: ignore[no-untyped-def]
    service, store, _ = _service(tmp_path)
    job = _job_record(store)
    store.create_job(job)
    _write_poses(store, job)

    record = service.validate(_request(job))

    # Not assessed, which is a different claim from "repeats differ".
    assert record.bitwise_reproducible is None
    assert record.engine == "GNINA" and record.engine_version == "1.3.3"
    identity = record.provenance.parameters["source_identity"]
    assert identity == {
        "executable_sha256": job.tool.sha256,
        "receptor_sha256": job.receptor_sha256,
        "ligand_sha256": job.ligand_sha256,
        "conformer_sha256": job.conformer_sha256,
        "pose_order": "cnn_score_descending",
        "cnn_scoring": "rescore",
        "cnn_model": "dense_1_3",
        "compute": "cpu",
    }
    assert record.provenance.parameters["bitwise_reproducible"] is None
    assert record.provenance.parameters["pose_sha256"] == [
        pose.artifact.sha256 for pose in job.poses
    ]
    assert service.get(record.validation_id) == record


def test_an_existing_record_keeps_the_boolean_it_was_written_with(tmp_path):  # type: ignore[no-untyped-def]
    """`bool | None` widened the field; it did not rewrite earlier verdicts."""
    service, store, _ = _service(tmp_path)
    job = _job_record(store)
    store.create_job(job)
    _write_poses(store, job)
    written = service.validate(_request(job))

    earlier = written.model_copy(update={"bitwise_reproducible": True})

    reloaded = RedockingRunRecord.model_validate_json(earlier.model_dump_json())

    assert reloaded.bitwise_reproducible is True
    assert reloaded.poses[0].cnn_score == 0.87


# --- what cannot become a verdict -----------------------------------------


@pytest.mark.parametrize("status", ["running", "failed", "canceled"])
def test_an_unfinished_gnina_job_is_not_a_validation_input(tmp_path, status):  # type: ignore[no-untyped-def]
    service, store, _ = _service(tmp_path)
    job = _job_record(store, status=DockingJobStatus(status))
    store.create_job(job)

    for call in (
        lambda: service.references("gnina_job", job.job_id),
        lambda: service.validate(_request(job)),
    ):
        with pytest.raises(AnkoraDomainError) as failure:
            call()
        assert failure.value.code == "REDOCKING_SOURCE_NOT_COMPLETE"
    assert service.list_runs() == []


@pytest.mark.parametrize("tampered", ["pose", "reference"])
def test_a_changed_pose_or_reference_produces_no_verdict(tmp_path, tampered):  # type: ignore[no-untyped-def]
    service, store, _ = _service(tmp_path)
    job = _job_record(store)
    store.create_job(job)
    poses = _write_poses(store, job)
    target = poses[0] if tampered == "pose" else service._ligand_store.content_path(REFERENCE_ID)
    target.write_bytes(target.read_bytes() + b"\n")

    with pytest.raises(AnkoraDomainError) as failure:
        service.validate(_request(job))

    assert failure.value.code == "REDOCKING_INPUT_HASH_MISMATCH"
    assert service.list_runs() == []


def test_a_truncated_pose_of_the_recorded_size_is_still_refused(tmp_path):  # type: ignore[no-untyped-def]
    """Size alone is not identity; the recorded SHA-256 is what must agree."""
    service, store, _ = _service(tmp_path)
    job = _job_record(store)
    store.create_job(job)
    poses = _write_poses(store, job)
    original = poses[0].read_bytes()
    poses[0].write_bytes(original[:-1] + b" ")

    with pytest.raises(AnkoraDomainError) as failure:
        service.validate(_request(job))

    assert failure.value.code == "REDOCKING_INPUT_HASH_MISMATCH"
    assert failure.value.details["filename"] == "pose_1.pdbqt"
    assert service.list_runs() == []


def test_a_reference_outside_the_receptors_own_frame_cannot_measure_a_gnina_job(tmp_path):  # type: ignore[no-untyped-def]
    service, store, receptor = _service(tmp_path)
    job = _job_record(store)
    store.create_job(job)
    _write_poses(store, job)
    assert service.references("gnina_job", job.job_id).total == 1
    # A different original structure, by source SHA-256 rather than by name.
    receptor.source_artifact_id = OTHER_STRUCTURE_ID

    assert service.references("gnina_job", job.job_id).total == 0
    with pytest.raises(AnkoraDomainError) as failure:
        service.validate(_request(job))
    assert failure.value.code == "REDOCKING_REFERENCE_FRAME_MISMATCH"
    assert service.list_runs() == []


def test_a_pose_that_is_not_the_reference_molecule_is_refused(tmp_path):  # type: ignore[no-untyped-def]
    """The retained real GNINA output is a 45-heavy-atom ligand, RV2 has 27.

    Deliberately mismatched: an RMSD between two different molecules would be a
    number with no meaning, so the measurement refuses instead of producing one.
    """
    service, store, _ = _service(tmp_path)
    foreign = tmp_path / "foreign_pose.pdbqt"
    first_mode = REAL_GNINA_POSES.read_text(encoding="utf-8").split("MODEL")[1]
    foreign.write_text(f"MODEL{first_mode}", encoding="utf-8", newline="\n")
    job = _job_record(store, modes=((1, 0.9, 6.3, -3.0, foreign),))
    store.create_job(job)
    store.write_artifact(job.job_id, "pose_1.pdbqt", foreign.read_bytes())

    with pytest.raises(AnkoraDomainError) as failure:
        service.validate(_request(job))

    assert failure.value.code == "REDOCKING_POSE_NOT_THE_REFERENCE_MOLECULE"
    assert service.list_runs() == []


def test_another_projects_gnina_job_cannot_be_validated(tmp_path):  # type: ignore[no-untyped-def]
    service, other_project_store, _ = _service(tmp_path, "default", gnina_project_id="other")
    job = _job_record(other_project_store)
    other_project_store.create_job(job)
    _write_poses(other_project_store, job)

    with pytest.raises(AnkoraDomainError) as failure:
        service.validate(_request(job))

    assert failure.value.code == "GNINA_JOB_NOT_FOUND"
    assert service.list_runs() == []


# --- the API and the dependent-record lifecycle ----------------------------


def test_the_api_validates_a_gnina_job_and_trash_moves_its_verdict(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    service, store, _ = _service(tmp_path)
    job = _job_record(store)
    store.create_job(job)
    _write_poses(store, job)
    monkeypatch.setattr(
        RedockingValidationService, "from_environment", classmethod(lambda _: service)
    )
    url = "/api/v1/validation/redocking"

    with TestClient(create_app()) as client:
        references = client.get(
            url + "/references", params={"source_kind": "gnina_job", "source_id": job.job_id}
        )
        assert references.status_code == 200
        assert references.json()["references"][0]["ligand_id"] == REFERENCE_ID
        # A GNINA campaign is not a single redocking experiment.
        assert (
            client.get(
                url + "/references",
                params={"source_kind": "gnina_batch", "source_id": job.job_id},
            ).status_code
            == 422
        )
        saved = client.post(
            url,
            json={
                "source_kind": "gnina_job",
                "source_id": job.job_id,
                "reference_ligand_id": REFERENCE_ID,
                "reference_case": "synthetic-gnina-routing",
            },
        )
        assert saved.status_code == 201
        body = saved.json()
        assert body["source_kind"] == "gnina_job"
        assert body["bitwise_reproducible"] is None
        assert [pose["cnn_score"] for pose in body["poses"]] == [0.87, 0.42]
        assert [pose["binding_energy_kcal_mol"] for pose in body["poses"]] == [-4.1, -9.3]
        validation_id = body["validation_id"]
        assert client.get(f"{url}/{validation_id}").json() == body

        trashed = client.post(
            "/api/v1/results/campaigns/trash",
            json={"catalog_ids": [f"gnina_job:{job.job_id}"], "acknowledge_removal": True},
        )
        assert trashed.status_code == 200
        # The verdict names this result; leaving it behind would describe a
        # measurement of something the project no longer holds.
        assert trashed.json()["redocking_validation_count"] == 1
        assert client.get(f"{url}/{validation_id}").status_code == 404
        assert client.get(url).json() == []
        assert client.get(f"/api/v1/docking/gnina/jobs/{job.job_id}").status_code == 404


# --- the real recorded GNINA output format ---------------------------------


def test_real_recorded_gnina_output_is_measurable_in_place(tmp_path):  # type: ignore[no-untyped-def]
    """A format check against the retained real GNINA 1.3.3 CPU output.

    GNINA writes its own PDBQT with `REMARK`/`ROOT`/`BRANCH` records and
    AutoDock atom types, so this pins that the redocking adapter maps that exact
    output onto the molecular graph of the conformer GNINA was given, for both
    recorded modes. The input conformer is the recorded docking input, not a
    crystallographic extraction, so these numbers are a measurement of the
    retained fixtures and not a redocking verdict. Measured with RDKit 2025.09.6
    and recorded in `docs/validation/GNINA_REDOCKING.md`.
    """
    reference = load_reference(REAL_GNINA_INPUT)
    documents = REAL_GNINA_POSES.read_text(encoding="utf-8").split("MODEL")[1:]
    assert len(documents) == 2

    measured = []
    for document in documents:
        assert len(pdbqt_to_pdb_block(document).splitlines()) == reference.GetNumAtoms() == 45
        measured.append(in_place_rmsd(load_pose(document, reference), reference))

    assert measured[0] == pytest.approx(26.199, abs=0.01)
    assert measured[1] == pytest.approx(27.245, abs=0.01)
