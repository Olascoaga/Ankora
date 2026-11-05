"""Synthetic GNINA catalog records: score axes never become kcal/mol."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256

from fastapi.testclient import TestClient

from ankora_backend.api.app import create_app
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


def _completed(store: GninaJobStore) -> GninaJobRecord:
    request = GninaDockingRequest(
        receptor_id="synthetic-receptor",
        binding_site_id="synthetic-site",
        ligand_id="synthetic-ligand",
        ligand_preparation_id="synthetic-preparation",
        parameters=GninaDockingParameters(compute="cpu"),
        acknowledge_inputs_and_scoring=True,
    )
    poses = []
    for mode, score, energy in ((1, 0.9, -4.0), (2, 0.7, -9.0)):
        raw = f"synthetic pose {mode}".encode()
        poses.append(
            GninaPoseResult(
                mode=mode,
                cnn_score=score,
                cnn_affinity=7 + mode,
                minimized_affinity_kcal_mol=energy,
                artifact=GninaPoseArtifact(
                    artifact_id=f"pose-{mode}",
                    mode=mode,
                    filename=f"pose_{mode}.pdbqt",
                    sha256=sha256(raw).hexdigest(),
                    size_bytes=len(raw),
                ),
            )
        )
    return GninaJobRecord(
        job_id=store.new_job_id(),
        status=DockingJobStatus.COMPLETED,
        phase=DockingJobPhase.COMPLETE,
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        request=request,
        tool=GninaToolIdentity(version="1.3.3", sha256="a" * 64, architecture="x86_64"),
        box=BindingBox(center_x=1, center_y=2, center_z=3, size_x=10, size_y=12, size_z=14),
        receptor_output_artifact_id="receptor-pdbqt",
        receptor_sha256="b" * 64,
        ligand_sha256="c" * 64,
        conformer_sha256="d" * 64,
        execution=GninaExecutionEvidence(
            command=["synthetic-gnina"], exit_code=0, stdout="", stderr=""
        ),
        poses=poses,
    )


def test_catalog_keeps_gnina_score_axes_and_renders_methods(tmp_path, monkeypatch):
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    store = GninaJobStore.from_environment()
    job = _completed(store)
    store.create_job(job)
    for pose in job.poses:
        store.write_artifact(
            job.job_id, pose.artifact.filename, f"synthetic pose {pose.mode}".encode()
        )
    with TestClient(create_app()) as client:
        page = client.get("/api/v1/results/campaigns?scoring_family=gnina").json()
        assert page["total"] == 1
        entry = page["entries"][0]
        assert entry["engine_key"] == "gnina_job" and entry["succeeded_count"] == 1
        assert entry["best_result_kcal_mol"] is None
        assert entry["primary_cnn_score"] == 0.9
        assert entry["cnn_affinity_pk"] == 8 and entry["minimized_affinity_kcal_mol"] == -4
        assert entry["box"]["center_x"] == 1
        detail = client.get(f"/api/v1/results/campaigns/gnina_job/{job.job_id}")
        assert detail.status_code == 200
        assert detail.json()["reproducibility"]["status"] == "not_assessed"
        compounds = client.get(f"/api/v1/results/campaigns/gnina_job/{job.job_id}/compounds").json()
        assert compounds["value_label"].startswith("CNN score")
        assert compounds["rows"][0]["primary_cnn_score"] == 0.9
        assert compounds["rows"][0]["best_result_kcal_mol"] is None
        # Methods used to fail closed here; it now renders GNINA's own protocol.
        # The axes must stay apart in the prose exactly as they do in the catalog.
        methods = client.get(f"/api/v1/results/campaigns/gnina_job/{job.job_id}/methods")
        assert methods.status_code == 200
        markdown = methods.json()["markdown"]
        assert "descending CNN pose score" in markdown
        assert "not an energy and has no kcal/mol interpretation" in markdown
        assert "CNN pose score of 0.9" in markdown
        assert "minimized affinity of -4 kcal mol⁻¹" in markdown
        assert "Lamarckian" not in markdown and "AutoGrid" not in markdown
        assert (
            client.get(f"/api/v1/docking/gnina/jobs/{job.job_id}").json()["poses"][0]["mode"] == 1
        )


def test_catalog_deletes_gnina_job_as_a_complete_recoverable_result(tmp_path, monkeypatch):
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    store = GninaJobStore.from_environment()
    job = _completed(store)
    store.create_job(job)
    store.write_artifact(job.job_id, "pose_1.pdbqt", b"synthetic pose 1")
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/results/campaigns/trash",
            json={
                "catalog_ids": [f"gnina_job:{job.job_id}"],
                "acknowledge_removal": True,
            },
        )
        assert response.status_code == 200
        assert response.json()["recoverable"] is True
        assert client.get(f"/api/v1/docking/gnina/jobs/{job.job_id}").status_code == 404
        assert client.get("/api/v1/results/campaigns?scoring_family=gnina").json()["total"] == 0


def test_group_delete_rejects_active_job_without_moving_any_result(tmp_path, monkeypatch):
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    store = GninaJobStore.from_environment()
    first, second = _completed(store), _completed(store)
    running = _completed(store).model_copy(
        update={
            "status": DockingJobStatus.RUNNING,
            "phase": DockingJobPhase.DOCKING,
            "poses": [],
            "execution": None,
            "completed_at": None,
        }
    )
    for job in (first, second, running):
        store.create_job(job)
    with TestClient(create_app()) as client:
        # Recovery reconciles abandoned work; restore the active record after startup.
        store.update_job(running)
        active_selection = [f"gnina_job:{first.job_id}", f"gnina_job:{running.job_id}"]
        rejected = client.post(
            "/api/v1/results/campaigns/trash",
            json={
                "catalog_ids": active_selection,
                "acknowledge_removal": True,
            },
        )
        assert rejected.status_code == 409 and rejected.json()["code"] == "RESULT_TRASH_ACTIVE"
        assert store.load_job(first.job_id).status is DockingJobStatus.COMPLETED
        removed = client.post(
            "/api/v1/results/campaigns/trash",
            json={
                "catalog_ids": [f"gnina_job:{first.job_id}", f"gnina_job:{second.job_id}"],
                "acknowledge_removal": True,
            },
        )
        assert removed.status_code == 200 and len(removed.json()["campaigns"]) == 2
        assert store.load_job(running.job_id).status is DockingJobStatus.RUNNING


def test_catalog_orders_gnina_jobs_by_time_not_cnn_score(tmp_path, monkeypatch):
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    store = GninaJobStore.from_environment()
    older = _completed(store)
    newer = _completed(store)
    newer_pose = newer.poses[0].model_copy(update={"cnn_score": 0.8})
    newer = newer.model_copy(
        update={
            "created_at": older.created_at + timedelta(seconds=1),
            "poses": [newer_pose, newer.poses[1]],
        }
    )
    store.create_job(older)
    store.create_job(newer)
    with TestClient(create_app()) as client:
        entries = client.get("/api/v1/results/campaigns?scoring_family=gnina").json()["entries"]
        assert [entry["record_id"] for entry in entries] == [newer.job_id, older.job_id]
        assert [entry["primary_cnn_score"] for entry in entries] == [0.8, 0.9]
