"""Synthetic storage identities, not chemical or docking results."""

import json
from pathlib import Path
from uuid import uuid4

import pytest

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.project_context import project_scope
from ankora_backend.persistence.ligand_store import LigandArtifactStore, _preparation_lock
from ankora_backend.services.project_dependencies import ProjectDependencyService


@pytest.mark.parametrize("kind", ["state", "conformer", "filter", "preparation"])
def test_all_ligand_derivatives_are_project_scoped(tmp_path: Path, kind: str) -> None:
    parent, identity = str(uuid4()), str(uuid4())
    stores = [
        LigandArtifactStore(tmp_path, project_id=project) for project in ["default", "a", "b"]
    ]
    paths = []
    for store in stores:
        path = {
            "state": store._state_dir,
            "conformer": store._conformer_dir,
            "filter": store._filter_run_dir,
            "preparation": store._preparation_dir,
        }[kind](parent, identity)
        path.mkdir(parents=True)
        # Minimal synthetic graph record: exercises ownership, not model parsing.
        payload = {"synthetic": True, "artifact": {"artifact_id": identity}}
        (path / "record.json").write_text(json.dumps(payload), encoding="utf-8")
        paths.append(path)
    assert len(set(paths)) == 3
    for project, path in zip(["default", "a", "b"], paths, strict=True):
        assert path.is_relative_to(tmp_path / "projects" / project / "derived")
        graph = ProjectDependencyService(root=tmp_path, project_id=project).graph()
        assert [node.node_id for node in graph.nodes] == [identity]
        assert (path / "record.json").is_file()


def test_other_project_cannot_read_ligand_preparation_and_context_is_captured(
    tmp_path: Path,
) -> None:
    ligand_id, preparation_id = str(uuid4()), str(uuid4())
    with project_scope("a"):
        store = LigandArtifactStore(tmp_path)
    with project_scope("b"):
        assert store._preparation_dir(ligand_id, preparation_id).is_relative_to(
            tmp_path / "projects/a"
        )
        other = LigandArtifactStore(tmp_path)
    path = store._preparation_dir(ligand_id, preparation_id)
    path.mkdir(parents=True)
    (path / "record.json").write_text('{"synthetic": true}', encoding="utf-8")
    with pytest.raises(AnkoraDomainError) as failure:
        other.load_pdbqt_record(ligand_id, preparation_id)
    assert failure.value.code == "LIGAND_PREPARATION_NOT_FOUND"
    assert not (tmp_path / "projects/default").exists()
    assert _preparation_lock(path) is _preparation_lock(path)
    assert _preparation_lock(path) is not _preparation_lock(
        other._preparation_dir(ligand_id, preparation_id)
    )
