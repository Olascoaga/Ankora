"""Synthetic API and lifecycle tests; GNINA is never invoked."""

from pathlib import Path
from threading import Event
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient
from test_gnina_campaign_link import _stub_input_stores
from test_gnina_screening_preflight import one_prepared as one_prepared
from test_gnina_screening_preflight import screening as screening

from ankora_backend.adapters.engines.gnina import GninaInstallation
from ankora_backend.api.app import create_app
from ankora_backend.execution.cancellable_subprocess import CancellableToolExecution


def test_api_cancels_queued_campaign_and_blocks_project_switch(tmp_path, one_prepared, monkeypatch):
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    app = create_app()
    screening_data, _conformer, _pdbqt = one_prepared
    _ligands, library, selection = screening_data
    receptors, sites, _ = _stub_input_stores(tmp_path)
    sites.project_root = tmp_path / "projects" / "default"
    service = app.state.gnina_screening
    service._receptors = receptors
    service._sites = sites
    monkeypatch.setattr(
        "ankora_backend.services.gnina_screening_admission._linux_host", lambda: True
    )
    monkeypatch.setattr(
        "ankora_backend.services.gnina_screening_admission.probe_gnina",
        lambda: GninaInstallation("/synthetic/gnina", "1.3.3", "a" * 64, "x86_64"),
    )
    monkeypatch.setattr(
        "ankora_backend.services.gnina_screening_admission.ProjectDependencyService.for_project_root",
        lambda _root: type("Fresh", (), {"require_current": lambda self, ids: None})(),
    )
    monkeypatch.setattr(app.state.resource_arbiter, "validate", lambda _claim: None)
    worker_entered, release = Event(), Event()

    def hold_worker():
        worker_entered.set()
        assert release.wait(10)

    service._executor.submit(hold_worker)
    assert worker_entered.wait(5)
    body = {
        "receptor_id": "receptor",
        "binding_site_id": "site",
        "library_id": library.artifact.library_id,
        "filter_run_id": selection.artifact.filter_run_id,
        "parameters": {"compute": "cpu"},
        "acknowledge_inputs_and_scoring": True,
    }
    try:
        with TestClient(app) as client:
            paths = client.get("/api/openapi.json").json()["paths"]
            assert "/api/v1/docking/gnina/screenings" in paths
            response = client.post("/api/v1/docking/gnina/screenings", json=body)
            assert response.status_code == 202, response.text
            record = response.json()
            campaign_id = record["campaign_id"]
            assert len(record["entries"]) == 2
            listed = client.get("/api/v1/docking/gnina/screenings").json()
            assert [item["campaign_id"] for item in listed] == [campaign_id]
            other = client.post("/api/v1/projects", json={"name": "Other"}).json()["project_id"]
            blocked = client.post(f"/api/v1/projects/{other}/activate")
            assert blocked.status_code == 409
            assert blocked.json()["code"] == "PROJECT_SWITCH_BLOCKED_BY_ACTIVE_WORK"
            canceled = client.post(f"/api/v1/docking/gnina/screenings/{campaign_id}/cancel")
            assert canceled.status_code == 200
            assert canceled.json()["status"] == "cancel_requested"
            release.set()
            deadline = monotonic() + 10
            while True:
                progress = client.get(
                    f"/api/v1/docking/gnina/screenings/{campaign_id}/progress"
                ).json()
                if (
                    progress["status"] in {"completed", "failed", "canceled"}
                    and not service.has_active_work()
                ):
                    break
                assert monotonic() < deadline
                sleep(0.02)
            assert progress["status"] == "canceled"
            assert (progress["canceled_count"], progress["failed_count"]) == (1, 1)
            changes = client.get(
                f"/api/v1/docking/gnina/screenings/{campaign_id}/entries?after_revision=0"
            ).json()
            assert any(entry["status"] == "canceled" for entry in changes)
            assert service._store.jobs.list_jobs() == []
            assert client.post(f"/api/v1/projects/{other}/activate").status_code == 200
            assert client.get(f"/api/v1/docking/gnina/screenings/{campaign_id}").status_code == 404
            assert client.get("/api/v1/docking/gnina/screenings").json() == []
    finally:
        release.set()


def test_screening_rejected_on_windows_before_any_campaign(tmp_path, monkeypatch):
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "ankora_backend.services.gnina_screening_admission._linux_host", lambda: False
    )
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/docking/gnina/screenings",
            json={
                "receptor_id": "r",
                "binding_site_id": "s",
                "library_id": "l",
                "filter_run_id": "f",
                "parameters": {"compute": "cpu"},
                "acknowledge_inputs_and_scoring": True,
            },
        )
        assert response.status_code == 422
        assert response.json()["code"] == "GNINA_LINUX_ONLY"


def test_api_executes_synthetic_campaign_and_preserves_gnina_scores(
    tmp_path, one_prepared, monkeypatch
):
    """Synthetic execution and disabled topology do not establish scientific validity."""
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    app = create_app()
    screening_data, _conformer, _pdbqt = one_prepared
    ligands, library, selection = screening_data
    receptors, sites, _ = _stub_input_stores(tmp_path)
    sites.project_root = tmp_path / "projects" / "default"
    app.state.gnina_screening._receptors = receptors
    app.state.gnina_screening._sites = sites
    app.state.gnina_docking._receptors = receptors
    app.state.gnina_docking._sites = sites
    app.state.gnina_docking._ligands = ligands
    installation = GninaInstallation("/synthetic/gnina", "1.3.3", "a" * 64, "x86_64")
    for module in ("gnina_screening_admission", "gnina_docking"):
        monkeypatch.setattr(f"ankora_backend.services.{module}._linux_host", lambda: True)
        monkeypatch.setattr(f"ankora_backend.services.{module}.probe_gnina", lambda: installation)
    monkeypatch.setattr(
        "ankora_backend.services.gnina_screening_admission.ProjectDependencyService.for_project_root",
        lambda _root: type("Fresh", (), {"require_current": lambda self, ids: None})(),
    )
    monkeypatch.setattr(
        "ankora_backend.services.gnina_docking.require_current_inputs", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "ankora_backend.services.gnina_docking.require_matching_topology", lambda *_a: None
    )
    raw = (Path(__file__).parent / "fixtures" / "gnina_real_1hsg_mk1.pdbqt").read_bytes()

    def fake_execute(**kwargs):
        kwargs["output_path"].write_bytes(raw)
        return CancellableToolExecution(
            ["synthetic-gnina"], 0, "synthetic stdout", "", False, False
        )

    monkeypatch.setattr("ankora_backend.services.gnina_docking.execute_gnina", fake_execute)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/docking/gnina/screenings",
            json={
                "receptor_id": "receptor",
                "binding_site_id": "site",
                "library_id": library.artifact.library_id,
                "filter_run_id": selection.artifact.filter_run_id,
                "parameters": {"compute": "cpu", "cpu_threads": 1},
                "acknowledge_inputs_and_scoring": True,
            },
        )
        assert response.status_code == 202, response.text
        campaign_id = response.json()["campaign_id"]
        deadline = monotonic() + 15
        while True:
            progress = client.get(f"/api/v1/docking/gnina/screenings/{campaign_id}/progress").json()
            if progress["status"] in {"completed", "failed", "canceled"}:
                break
            assert monotonic() < deadline
            sleep(0.02)
        assert progress["status"] == "completed", progress
        assert (progress["succeeded_count"], progress["failed_count"]) == (1, 1)
        campaign = client.get(f"/api/v1/docking/gnina/screenings/{campaign_id}").json()
        entry = next(item for item in campaign["entries"] if item["status"] == "completed")
        job = client.get(f"/api/v1/docking/gnina/jobs/{entry['gnina_job_id']}").json()
        assert job["screening_campaign_id"] == campaign_id
        assert len(job["poses"]) == 2
        assert job["poses"][0]["cnn_score"] == pytest.approx(0.266823769)
        assert job["poses"][1]["cnn_score"] == pytest.approx(0.213049844)
        assert job["poses"][0]["cnn_affinity"] == pytest.approx(6.34318495)
        assert job["poses"][1]["cnn_affinity"] == pytest.approx(7.4227376)
        assert job["poses"][0]["minimized_affinity_kcal_mol"] == pytest.approx(27.0064907)
        assert job["poses"][1]["minimized_affinity_kcal_mol"] == pytest.approx(-9.32558155)
        assert (
            app.state.gnina_screening._store.jobs.output_path(
                job["job_id"], "raw_poses.pdbqt"
            ).read_bytes()
            == raw
        )
        catalog = client.get("/api/v1/results/campaigns?scoring_family=gnina").json()
        assert catalog["total"] == 1
        assert catalog["entries"][0]["catalog_id"] == f"gnina_screening:{campaign_id}"
        assert (
            client.get("/api/v1/results/campaigns?scoring_family=gnina&mode=single_ligand").json()[
                "total"
            ]
            == 0
        )


def test_api_rejects_stale_gnina_screening_inputs_with_real_dependency_gate(
    tmp_path, one_prepared, monkeypatch
):
    """D3-006: Verify unmodified ProjectDependencyService rejects stale screening inputs."""
    from datetime import UTC, datetime
    from hashlib import sha256

    from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
    from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
    from ankora_backend.schemas.binding_sites import (
        BindingBox,
        BindingSiteRecord,
        BindingSiteRequest,
        BindingSiteSource,
    )
    from ankora_backend.schemas.receptors import (
        ComponentAction,
        ProtonationSettings,
        ReceptorOutputArtifact,
        ReceptorOutputStage,
        ReceptorPreparationRecord,
        ReceptorPreparationRequest,
        ReceptorPreparationStatus,
    )
    from ankora_backend.services.project_dependencies import ProjectDependencyService

    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    screening_data, _conformer, _pdbqt = one_prepared
    _ligands, library, selection = screening_data
    now = datetime.now(UTC)

    receptors = ReceptorArtifactStore(tmp_path)
    rec_id = receptors.new_receptor_id()
    receptors.create_receptor(rec_id)
    rec_bytes = b"REMARK synthetic receptor\n"
    receptors.write_bytes(rec_id, "receptor.pdbqt", rec_bytes)
    rec_out = ReceptorOutputArtifact(
        artifact_id=f"{rec_id}-pdbqt",
        stage=ReceptorOutputStage.PDBQT,
        filename="receptor.pdbqt",
        format="pdbqt",
        sha256=sha256(rec_bytes).hexdigest(),
        size_bytes=len(rec_bytes),
        created_at=now,
        content_url="/synthetic/receptor",
    )
    receptors.save_record(
        ReceptorPreparationRecord(
            receptor_id=rec_id,
            source_artifact_id="src-1",
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
            outputs=[rec_out],
            warnings=[],
            provenance=[],
            display_output_artifact_id=rec_out.artifact_id,
        )
    )
    sites = BindingSiteArtifactStore(tmp_path)
    site_id = sites.new_binding_site_id()
    box = BindingBox(center_x=0, center_y=0, center_z=0, size_x=15, size_y=15, size_z=15)
    sites.save_record(
        BindingSiteRecord(
            binding_site_id=site_id,
            receptor_id=rec_id,
            source_artifact_id="src-1",
            created_at=now,
            decisions=BindingSiteRequest(source=BindingSiteSource.MANUAL, manual_box=box),
            box=box,
            stale=False,
            warnings=[],
            provenance=[],
        )
    )
    ProjectDependencyService.for_project_root(sites.project_root).mark_stale(
        site_id, reason="Synthetic stale site for D3-006 gate test"
    )
    installation = GninaInstallation("/synthetic/gnina", "1.3.3", "a" * 64, "x86_64")
    monkeypatch.setattr(
        "ankora_backend.services.gnina_screening_admission._linux_host", lambda: True
    )
    monkeypatch.setattr(
        "ankora_backend.services.gnina_screening_admission.probe_gnina", lambda: installation
    )
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/docking/gnina/screenings",
            json={
                "receptor_id": rec_id,
                "binding_site_id": site_id,
                "library_id": library.artifact.library_id,
                "filter_run_id": selection.artifact.filter_run_id,
                "parameters": {"compute": "cpu", "cpu_threads": 1},
                "acknowledge_inputs_and_scoring": True,
            },
        )
        assert response.status_code == 409
        assert response.json()["code"] == "PROJECT_INPUT_STALE"
