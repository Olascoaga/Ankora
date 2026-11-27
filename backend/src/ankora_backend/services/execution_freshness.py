"""Effective project-scoped input freshness at scientific admission boundaries."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.services.project_dependencies import ProjectDependencyService, _references


def require_current_for_store(store: Any, node_ids: Iterable[str]) -> None:
    """Enforce ProjectDependencyService.require_current() for any persistence store (D5-008)."""
    filtered = [value for value in node_ids if value]
    if not filtered:
        return
    project_root = getattr(store, "project_root", None) or getattr(store, "_project_root", None)
    data_root = getattr(store, "_root", None)
    if isinstance(project_root, Path):
        if isinstance(data_root, Path) and data_root != project_root:
            ProjectDependencyService(
                root=data_root, project_id=project_root.name
            ).require_current(filtered)
            return
        ProjectDependencyService.for_project_root(project_root).require_current(filtered)
        return
    if isinstance(data_root, Path) and data_root.name == "calibrations":
        parent = data_root.parent
        if parent.parent.name == "projects":
            ProjectDependencyService(
                root=parent.parent.parent, project_id=parent.name
            ).require_current(filtered)


def require_current_inputs(
    request: BaseModel,
    *,
    binding_site_store: BindingSiteArtifactStore,
    ligand_store: LigandArtifactStore,
) -> None:
    payload = request.model_dump(mode="json")
    identities = set(_references(payload))
    library_id, filter_run_id = payload.get("library_id"), payload.get("filter_run_id")
    if library_id and filter_run_id:
        selection = ligand_store.load_filter_run(library_id, filter_run_id)
        preparation = ligand_store.load_preparation_status(library_id)
        for ligand_id in selection.selected_ligand_ids:
            identities.add(ligand_id)
            entry = preparation.entries.get(ligand_id)
            if entry is not None:
                identities.update(
                    value
                    for value in (
                        entry.chemical_state_id,
                        entry.conformer_id,
                        entry.pdbqt_preparation_id,
                    )
                    if value
                )
    ProjectDependencyService.for_project_root(binding_site_store.project_root).require_current(
        identities
    )
