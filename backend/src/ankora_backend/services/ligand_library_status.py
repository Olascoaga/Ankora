"""Side-effect helper: keep a ligand library's aggregate preparation status current.

Called from the conformer and PDBQT preparation services after each per-ligand
outcome. It is a deliberate no-op for ligands imported outside a library
(``LigandArtifact.library_id is None``), since single-ligand preparation has no
aggregate to update.
"""

from datetime import UTC, datetime

from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligand_library_preparation import (
    LigandPreparationEntry,
    LigandPreparationStatus,
)
from ankora_backend.schemas.ligands import LigandRecord


def record_library_status(
    store: LigandArtifactStore,
    original: LigandRecord,
    *,
    status: LigandPreparationStatus,
    conformer_id: str | None = None,
    pdbqt_preparation_id: str | None = None,
    chemical_state_id: str | None = None,
    chemical_state_formal_charge: int | None = None,
    initial_energy_kcal_mol: float | None = None,
    final_energy_kcal_mol: float | None = None,
    error_message: str | None = None,
) -> None:
    library_id = original.artifact.library_id
    if library_id is None:
        return
    store.upsert_preparation_entry(
        library_id,
        LigandPreparationEntry(
            ligand_id=original.artifact.ligand_id,
            parent_compound_id=original.artifact.ligand_id,
            chemical_state_id=chemical_state_id,
            chemical_state_formal_charge=chemical_state_formal_charge,
            status=status,
            conformer_id=conformer_id,
            pdbqt_preparation_id=pdbqt_preparation_id,
            initial_energy_kcal_mol=initial_energy_kcal_mol,
            final_energy_kcal_mol=final_energy_kcal_mol,
            error_message=error_message,
            updated_at=datetime.now(UTC),
        ),
    )
