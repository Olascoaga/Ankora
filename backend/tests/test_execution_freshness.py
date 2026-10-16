"""Stale-admission tests use synthetic records and recorded-log replay fixtures."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from test_autodock4_docking import _batch_fixture as cpu_batch_fixture
from test_autodock4_docking import _docking_fixture as cpu_fixture
from test_autodock_gpu_docking import _batch_fixture as gpu_batch_fixture
from test_autodock_gpu_docking import _fixture as gpu_fixture
from test_autogrid_maps import _service as map_fixture
from test_vina_docking import _batch_request as vina_batch_request
from test_vina_docking import _service as vina_fixture

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.services.project_dependencies import ProjectDependencyService


def test_library_outputs_do_not_make_their_parent_or_siblings_stale(tmp_path: Path) -> None:
    root = tmp_path / "projects" / "other"
    library, a, b, initial, state = [str(uuid4()) for _ in range(5)]
    records = {
        root / f"original/ligand_libraries/{library}/record.json": {
            "artifact": {"library_id": library},
            "entries": [
                {"ligand": {"artifact": {"ligand_id": a, "library_id": library}}},
                {"ligand": {"artifact": {"ligand_id": b, "library_id": library}}},
            ],
        },
        root / f"original/ligands/{a}/record.json": {
            "artifact": {"ligand_id": a, "library_id": library},
            "state": {"state_id": initial},
        },
        root / f"original/ligands/{b}/record.json": {
            "artifact": {"ligand_id": b, "library_id": library}
        },
        root / f"derived/ligands/{a}/states/{state}/record.json": {
            "artifact": {"ligand_id": a, "state_id": state},
            "parent_state_id": initial,
        },
    }
    for path, record in records.items():
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(record), encoding="utf-8")
    service = ProjectDependencyService(root=tmp_path, project_id="other")
    graph = service.graph()
    assert graph.unresolved_reference_count == 0
    assert not any(edge.child_id == library for edge in graph.edges)
    assert not any(edge.parent_id == state and edge.child_id == a for edge in graph.edges)
    service.mark_stale(state, "Synthetic derived-state invalidation")
    service.require_current([a, b, library])
    with pytest.raises(AnkoraDomainError):
        service.require_current([state])
    service.mark_stale(a, "Synthetic original-ligand invalidation")
    service.require_current([b, library])
    with pytest.raises(AnkoraDomainError):
        service.require_current([initial])
    assert ProjectDependencyService(root=tmp_path, project_id="default").graph().stale_count == 0


@pytest.mark.parametrize(
    "engine,marked_input",
    [
        (engine, field)
        for engine in ["vina", "maps", "cpu", "gpu"]
        for field in ["binding_site_id", "receptor_id"]
    ]
    + [(engine, "ligand_preparation_id") for engine in ["vina", "cpu", "gpu"]]
    + [(engine, "map_set_id") for engine in ["cpu", "gpu"]],
)
def test_execution_rejects_effective_stale_site_before_creating_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    engine: str,
    marked_input: str,
) -> None:
    fixture = {"vina": vina_fixture, "maps": map_fixture, "cpu": cpu_fixture, "gpu": gpu_fixture}[
        engine
    ]
    if engine == "vina":
        service, request = fixture(tmp_path)
        monkeypatch.setattr("ankora_backend.services.vina_docking.probe_vina", lambda: object())
    else:
        service, request = fixture(tmp_path, monkeypatch)
    try:
        dependencies = ProjectDependencyService(root=tmp_path)
        dependencies.mark_stale(
            getattr(request, marked_input), "Synthetic input was explicitly invalidated"
        )
        before = {path for path in tmp_path.rglob("record.json")}
        with pytest.raises(AnkoraDomainError) as failure:
            if engine == "maps":
                service.ensure_map_set(request)
            else:
                service.start(request)
        assert failure.value.code == "PROJECT_INPUT_STALE"
        assert {path for path in tmp_path.rglob("record.json")} == before
    finally:
        service.shutdown()


@pytest.mark.parametrize("engine", ["vina", "cpu", "gpu"])
def test_batch_rejects_a_stale_selected_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: str
) -> None:
    if engine == "vina":
        service, single = vina_fixture(tmp_path)
        request = vina_batch_request(tmp_path, service, single, monkeypatch)
    else:
        service, request = {"cpu": cpu_batch_fixture, "gpu": gpu_batch_fixture}[engine](
            tmp_path, monkeypatch
        )
    try:
        store = LigandArtifactStore(tmp_path)
        selected = store.load_filter_run(
            request.library_id, request.filter_run_id
        ).selected_ligand_ids
        status = store.load_preparation_status(request.library_id)
        prepared = next(
            status.entries[item].pdbqt_preparation_id
            for item in selected
            if status.entries[item].pdbqt_preparation_id
        )
        ProjectDependencyService(root=tmp_path).mark_stale(
            prepared, "Synthetic stale selected PDBQT"
        )
        with pytest.raises(AnkoraDomainError) as failure:
            service.start_batch(request)
        assert failure.value.code == "PROJECT_INPUT_STALE"
    finally:
        service.shutdown()
