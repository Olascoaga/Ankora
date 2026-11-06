"""Synthetic GNINA records: preserve score semantics and fail on identity drift."""

import pytest
from test_gnina_catalog import _completed
from test_pose_interactions import LIGAND, PREPARATION, RECEPTOR, _hash, _service

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.gnina_store import GninaJobStore
from ankora_backend.schemas.pose_interactions import InteractionAnalysisRequest


def _gnina_service(tmp_path):
    service, pose_path, detector = _service(tmp_path)
    store = GninaJobStore(tmp_path)
    job = _completed(store)
    job = job.model_copy(
        update={
            "request": job.request.model_copy(
                update={
                    "ligand_id": LIGAND,
                    "ligand_preparation_id": PREPARATION,
                    "receptor_id": RECEPTOR,
                }
            ),
            "receptor_sha256": _hash(tmp_path / "receptor.pdbqt"),
            "ligand_sha256": _hash(tmp_path / "ligand.pdbqt"),
            "conformer_sha256": _hash(tmp_path / "conformer.sdf"),
        }
    )
    store.create_job(job)
    for pose in job.poses:
        store.write_artifact(
            job.job_id, pose.artifact.filename, f"synthetic pose {pose.mode}".encode()
        )
    service._gnina = store
    service._ligands.pdbqt_content_path = lambda ligand, preparation: tmp_path / "ligand.pdbqt"
    return service, job, detector


def test_gnina_inventory_and_analysis_keep_score_axes(tmp_path):
    service, job, detector = _gnina_service(tmp_path)
    inventory = service.list_poses(f"gnina_job:{job.job_id}", LIGAND)
    assert [pose.cnn_score for pose in inventory.poses] == [0.9, 0.7]
    assert [pose.result_kcal_mol for pose in inventory.poses] == [-4, -9]
    assert inventory.poses[0].cnn_affinity_pk == 8
    result = service.analyze(
        f"gnina_job:{job.job_id}", LIGAND, "pose-1", InteractionAnalysisRequest()
    )
    assert result.pose.cnn_score == 0.9
    assert result.pose.value_label == "GNINA minimized affinity"
    assert detector.calls == 1


@pytest.mark.parametrize("field", ["ligand_sha256", "conformer_sha256"])
def test_gnina_rejects_docking_input_identity_drift(tmp_path, field):
    service, job, detector = _gnina_service(tmp_path)
    service._gnina.update_job(job.model_copy(update={field: "f" * 64}))
    with pytest.raises(AnkoraDomainError) as captured:
        service.analyze(f"gnina_job:{job.job_id}", LIGAND, "pose-1", InteractionAnalysisRequest())
    assert captured.value.code == "POSE_INTERACTION_LIGAND_IDENTITY_MISMATCH"
    assert detector.calls == 0


def test_gnina_refuses_another_ligand(tmp_path):
    service, job, _ = _gnina_service(tmp_path)
    with pytest.raises(AnkoraDomainError) as captured:
        service.list_poses(f"gnina_job:{job.job_id}", "different-ligand")
    assert captured.value.code == "RESULT_LIGAND_NOT_FOUND"


def test_gnina_rejects_a_tampered_saved_pose(tmp_path):
    service, job, detector = _gnina_service(tmp_path)
    service._gnina.pose_content_path(job.job_id, "pose-1").write_bytes(b"tampered synthetic pose")
    with pytest.raises(AnkoraDomainError):
        service.analyze(f"gnina_job:{job.job_id}", LIGAND, "pose-1", InteractionAnalysisRequest())
    assert detector.calls == 0


def test_gnina_complex_rejects_a_changed_docking_receptor(tmp_path):
    service, job, _ = _gnina_service(tmp_path)
    (tmp_path / "receptor.pdbqt").write_bytes(b"tampered synthetic receptor")
    with pytest.raises(AnkoraDomainError) as captured:
        service.complex_pdb(f"gnina_job:{job.job_id}", LIGAND, "pose-1")
    assert captured.value.code == "POSE_INTERACTION_INPUT_HASH_MISMATCH"
