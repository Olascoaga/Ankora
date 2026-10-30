"""GNINA API scope and lifecycle tests using synthetic job metadata."""

from datetime import UTC, datetime
from threading import Event
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient

from ankora_backend.api.app import create_app
from ankora_backend.schemas.docking import DockingFailure, DockingJobStatus
from ankora_backend.schemas.work_recovery import WorkKind, WorkRetryRequest
from ankora_backend.services.work_retry import WorkRetryService


def test_gnina_routes_are_typed_and_windows_is_explicitly_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("ankora_backend.services.gnina_docking._linux_host", lambda: False)
    with TestClient(create_app()) as client:
        schema = client.get("/api/openapi.json").json()
        assert "/api/v1/docking/gnina/jobs" in schema["paths"]
        request = {
            "receptor_id": "r",
            "binding_site_id": "s",
            "ligand_id": "l",
            "ligand_preparation_id": "p",
            "parameters": {"compute": "cpu"},
            "acknowledge_inputs_and_scoring": True,
        }
        response = client.post("/api/v1/docking/gnina/jobs", json=request)
        assert response.status_code == 422
        assert response.json()["code"] == "GNINA_LINUX_ONLY"
        request["acknowledge_inputs_and_scoring"] = False
        assert client.post("/api/v1/docking/gnina/jobs", json=request).status_code == 422


def test_project_switch_waits_for_active_gnina_work(tmp_path, monkeypatch):
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Other"}).json()
        app.state.gnina_docking._events["synthetic-active"] = Event()
        response = client.post(f"/api/v1/projects/{project['project_id']}/activate")
        assert response.status_code == 409
        assert response.json()["code"] == "PROJECT_SWITCH_BLOCKED_BY_ACTIVE_WORK"
        app.state.gnina_docking._events.clear()
        assert client.post(f"/api/v1/projects/{project['project_id']}/activate").status_code == 200


def test_gnina_retry_creates_a_new_attempt_only_for_interrupted_work():
    gnina, store = MagicMock(), MagicMock()
    service = WorkRetryService(
        docking_store=MagicMock(),
        autogrid_store=MagicMock(),
        autodock4_store=MagicMock(),
        autodock_gpu_store=MagicMock(),
        vina=MagicMock(),
        autogrid=MagicMock(),
        autodock4=MagicMock(),
        autodock_gpu=MagicMock(),
        gnina=gnina,
        gnina_store=store,
    )
    old_id, new_id = str(uuid4()), str(uuid4())
    old = MagicMock()
    old.failure = DockingFailure(code="GNINA_EXECUTION_INTERRUPTED", message="interrupted")
    store.load_job.return_value = old
    gnina.start.return_value = MagicMock(
        job_id=new_id, status=DockingJobStatus.QUEUED, created_at=datetime.now(UTC)
    )
    response = service.retry(
        WorkKind.GNINA_JOB, old_id, WorkRetryRequest(acknowledge_new_immutable_attempt=True)
    )
    assert response.interrupted_work_id == old_id and response.new_work_id == new_id
    gnina.start.assert_called_once_with(old.request)
