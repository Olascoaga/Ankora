"""Side-by-side comparison of two docking engines (ADR-015 item 4).

Vina's empirical score and AutoDock4's semi-empirical binding energy are
produced by different scoring functions on different scales. This module
therefore compares only what is comparable: each engine's own ranking of the
same molecules, and how much those rankings agree.

There is deliberately no combined, averaged, or consensus score anywhere in
this contract. `DOCKING_POLICY.md` requires that the two result models stay
independent, and a merged number would invent an agreement the science does not
support.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EngineComparisonRow(BaseModel):
    """One molecule, with each engine's own score and its own rank.

    The two score columns are never combined. `rank_difference` is derived from
    the ranks alone, so it carries no scoring-function units.
    """

    model_config = ConfigDict(extra="forbid")

    ligand_id: str = Field(min_length=1)
    source_index: int = Field(ge=0)
    name: str = Field(min_length=1)
    canonical_smiles: str | None = None
    vina_best_score_kcal_mol: float | None = None
    vina_rank: int | None = Field(default=None, ge=1)
    autodock4_best_energy_kcal_mol: float | None = None
    autodock4_rank: int | None = Field(default=None, ge=1)
    autodock4_top_cluster_run_count: int | None = Field(default=None, ge=1)
    rank_difference: int | None = Field(default=None, ge=0)
    docked_by_both: bool = False


class RankAgreement(BaseModel):
    """How much the two independent rankings agree.

    This measures agreement between orderings; it is not a score for any
    molecule and must never be presented as one.
    """

    model_config = ConfigDict(extra="forbid")

    comparable_count: int = Field(ge=0)
    # Spearman's rank correlation over molecules both engines docked. None when
    # fewer than three molecules are comparable, where the coefficient would be
    # meaningless rather than merely uncertain.
    spearman_rho: float | None = Field(default=None, ge=-1, le=1)
    top_n: int = Field(ge=1)
    top_n_overlap: int = Field(ge=0)
    top_n_shared_ligand_ids: list[str] = Field(default_factory=list)


class EngineComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    receptor_id: str = Field(min_length=1)
    binding_site_id: str = Field(min_length=1)
    library_id: str = Field(min_length=1)
    filter_run_id: str = Field(min_length=1)
    selection_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    vina_batch_id: str = Field(min_length=1)
    vina_version: str = Field(min_length=1)
    autodock4_batch_id: str = Field(min_length=1)
    autodock4_version: str = Field(min_length=1)
    selected_count: int = Field(ge=1)
    docked_by_both_count: int = Field(ge=0)
    vina_only_count: int = Field(ge=0)
    autodock4_only_count: int = Field(ge=0)
    docked_by_neither_count: int = Field(ge=0)
    agreement: RankAgreement
    rows: list[EngineComparisonRow] = Field(default_factory=list)
