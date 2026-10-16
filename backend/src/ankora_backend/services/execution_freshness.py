"""Effective project-scoped input freshness at scientific admission boundaries."""

from pydantic import BaseModel

from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.services.project_dependencies import ProjectDependencyService, _references


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
