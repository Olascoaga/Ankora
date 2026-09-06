import json
from hashlib import sha256
from pathlib import Path
from threading import Event

from fastapi.testclient import TestClient

from ankora_backend.api.app import create_app
from ankora_backend.persistence.project_store import ProjectStore
from ankora_backend.services.project_dependencies import ProjectDependencyService

FIXTURES = Path(__file__).parent / "fixtures"


def test_legacy_default_is_registered_without_rewriting_its_evidence(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "projects" / "default" / "results" / "legacy.bin"
    evidence.parent.mkdir(parents=True)
    evidence.write_bytes(b"immutable legacy evidence\x00\xff")
    before = (sha256(evidence.read_bytes()).hexdigest(), evidence.stat().st_mtime_ns)

    store = ProjectStore(tmp_path)

    catalog = store.catalog()
    default = next(item for item in catalog.projects if item.project_id == "default")
    after = (sha256(evidence.read_bytes()).hexdigest(), evidence.stat().st_mtime_ns)
    assert catalog.active_project_id == "default"
    assert default.name == "Default project"
    assert default.migrated_legacy is True
    assert after == before
    assert not (tmp_path / "projects" / "default" / "project.json").exists()
    assert (tmp_path / "workspace" / "projects.json").is_file()


def test_project_api_creates_switches_and_isolates_structure_artifacts(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    content = (FIXTURES / "synthetic_m1.pdb").read_bytes()

    with TestClient(create_app()) as client:
        client.headers["Origin"] = "tauri://localhost"
        default_import = client.post(
            "/api/v1/structures/import",
            files={"file": ("default.pdb", content, "chemical/x-pdb")},
        )
        assert default_import.status_code == 201
        default_id = default_import.json()["artifact"]["artifact_id"]

        created = client.post("/api/v1/projects", json={"name": "Screen 6OCO"})
        assert created.status_code == 201
        project = created.json()
        assert project["name"] == "Screen 6OCO"
        assert project["project_id"] != "default"

        activated = client.post(
            f"/api/v1/projects/{project['project_id']}/activate"
        )
        assert activated.status_code == 200
        assert client.get(f"/api/v1/structures/{default_id}").status_code == 404

        project_import = client.post(
            "/api/v1/structures/import",
            files={"file": ("project.pdb", content, "chemical/x-pdb")},
        )
        assert project_import.status_code == 201
        project_id = project_import.json()["artifact"]["artifact_id"]

        assert client.post("/api/v1/projects/default/activate").status_code == 200
        assert client.get(f"/api/v1/structures/{default_id}").status_code == 200
        assert client.get(f"/api/v1/structures/{project_id}").status_code == 404

        catalog = client.get("/api/v1/projects").json()
        assert catalog["active_project_id"] == "default"
        assert [item["name"] for item in catalog["projects"]] == [
            "Default project",
            "Screen 6OCO",
        ]


def test_project_switch_is_blocked_while_scientific_work_is_active(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    app = create_app()

    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Other"}).json()
        app.state.vina_docking._cancel_events["synthetic-active-work"] = Event()

        response = client.post(
            f"/api/v1/projects/{project['project_id']}/activate"
        )

        assert response.status_code == 409
        assert response.json()["code"] == "PROJECT_SWITCH_BLOCKED_BY_ACTIVE_WORK"
        assert client.get("/api/v1/projects").json()["active_project_id"] == "default"
        app.state.vina_docking._cancel_events.clear()


def test_unknown_project_activation_creates_no_project_directory(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))

    with TestClient(create_app()) as client:
        response = client.post("/api/v1/projects/not-registered/activate")

    assert response.status_code == 404
    assert response.json()["code"] == "PROJECT_NOT_FOUND"
    assert not (tmp_path / "projects" / "not-registered").exists()


def test_explicit_stale_state_propagates_without_editing_evidence(tmp_path: Path) -> None:
    project = tmp_path / "projects" / "default"
    structure_id = "00000000-0000-0000-0000-000000000001"
    receptor_id = "00000000-0000-0000-0000-000000000002"
    receptor_output_id = "00000000-0000-0000-0000-000000000003"
    site_id = "00000000-0000-0000-0000-000000000004"
    job_id = "00000000-0000-0000-0000-000000000005"
    pose_id = "00000000-0000-0000-0000-000000000006"
    analysis_id = "00000000-0000-0000-0000-000000000007"
    export_id = "00000000-0000-0000-0000-000000000008"
    records = {
        project / "original" / "structures" / structure_id / "record.json": {
            "artifact": {"artifact_id": structure_id},
            "metadata": {"entry_id": "SYN1"},
        },
        project / "derived" / "receptors" / receptor_id / "record.json": {
            "receptor_id": receptor_id,
            "source_artifact_id": structure_id,
            "outputs": [{"artifact_id": receptor_output_id}],
        },
        project / "derived" / "binding_sites" / site_id / "record.json": {
            "binding_site_id": site_id,
            "receptor_id": receptor_id,
            "source_artifact_id": structure_id,
            "stale": False,
        },
        project / "results" / "docking" / job_id / "record.json": {
            "job_id": job_id,
            "request": {
                "receptor_id": receptor_id,
                "binding_site_id": site_id,
            },
            "receptor_output_artifact_id": receptor_output_id,
            "poses": [{"artifact_id": pose_id}],
        },
        project / "analysis" / "pose_interactions" / analysis_id / "record.json": {
            "analysis_id": analysis_id,
            "catalog_id": f"vina_job:{job_id}",
            "record_id": job_id,
            "receptor_id": receptor_id,
            "pose": {"artifact_id": pose_id},
        },
        project / "exports" / "figures" / export_id / "figure.json": {
            "figure_id": export_id,
            "result": {
                "catalog_id": f"vina_job:{job_id}",
                "interaction_analysis_id": analysis_id,
            },
        },
    }
    for path, payload in records.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    before = {
        path: sha256(path.read_bytes()).hexdigest()
        for path in records
    }
    service = ProjectDependencyService(root=tmp_path, project_id="default")

    initial = service.graph(limit=100)
    assert initial.total_nodes == 6
    assert initial.stale_count == 0
    assert initial.unresolved_reference_count == 0

    result = service.mark_stale(receptor_id, "The scientist replaced this preparation.")
    graph = service.graph(limit=100)
    stale = {node.node_id: node for node in graph.nodes if node.stale}

    assert result.marked_node_id == receptor_id
    assert set(result.affected_node_ids) == {
        receptor_id,
        site_id,
        job_id,
        analysis_id,
        export_id,
    }
    assert structure_id not in stale
    assert "Depends on stale artifact" in stale[site_id].stale_reasons[0]
    assert {
        path: sha256(path.read_bytes()).hexdigest()
        for path in records
    } == before
    assert (tmp_path / "workspace" / "stale" / "default.json").is_file()
