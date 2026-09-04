"""Typed contract for the durable, aggregated preparation status of a ligand library.

Individual conformer/PDBQT generation calls are per-ligand and already persist their
own immutable derivatives. This record is the backend-owned rollup of those results
across an entire library, so the frontend never has to reconstruct "which of these
N ligands are docking-ready" from in-memory state that a navigation or restart would
lose.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class LigandPreparationStatus(StrEnum):
    NEEDS_DECISION = "needs_decision"
    GENERATING = "generating"
    MINIMIZED = "minimized"
    NONCONVERGED = "nonconverged"
    PREPARED = "prepared"
    FAILED = "failed"


class LigandPreparationEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ligand_id: str = Field(min_length=1)
    parent_compound_id: str | None = None
    chemical_state_id: str | None = None
    chemical_state_formal_charge: int | None = None
    status: LigandPreparationStatus
    conformer_id: str | None = None
    pdbqt_preparation_id: str | None = None
    initial_energy_kcal_mol: float | None = None
    final_energy_kcal_mol: float | None = None
    error_message: str | None = None
    updated_at: datetime


class LigandLibraryPreparationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    library_id: str = Field(min_length=1)
    updated_at: datetime
    entries: dict[str, LigandPreparationEntry] = Field(default_factory=dict)
