"""What screening campaigns exist on disk, for either engine.

A campaign outlives the session that launched it. The interface can already
reconnect to the most recent one, but a project accumulates campaigns - a first
attempt, a re-run with more exhaustiveness, a different selection - and the
scientist has to be able to go back to any of them, not only the newest.

These are summaries, not results. A completed campaign record is measured in
megabytes because it carries every pose of every molecule; listing a project's
history must not download all of that just to show which campaigns exist. Each
summary therefore carries what identifies a campaign and what it produced, and
the full record is fetched only for the one actually opened.

`best_result_kcal_mol` is the campaign's own best number from its own engine.
Vina's empirical score and AutoDock4's semi-empirical binding energy are not on
the same scale, so this field is only ever meaningful next to the `engine` that
produced it, and is never compared across engines. `DOCKING_POLICY.md` governs
that separation; `engine_comparison.py` is the only place two engines meet, and
it compares ranks rather than these numbers.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CampaignEngine(StrEnum):
    AUTODOCK_VINA = "autodock_vina"
    AUTODOCK4 = "autodock4"


class CampaignSummary(BaseModel):
    """One persisted campaign, described without its results."""

    model_config = ConfigDict(extra="forbid")

    batch_id: str = Field(min_length=1)
    engine: CampaignEngine
    engine_version: str = Field(min_length=1)
    status: str = Field(min_length=1)
    is_running: bool = False
    created_at: datetime
    completed_at: datetime | None = None
    receptor_id: str = Field(min_length=1)
    binding_site_id: str = Field(min_length=1)
    # False when this campaign ran against a different binding-site record
    # defining the identical box. Confirming a pocket twice writes two
    # records for one search space, and that reuse is stated rather than
    # hidden.
    same_site_record: bool = True
    library_id: str = Field(min_length=1)
    filter_run_id: str = Field(min_length=1)
    # The selection is identified by the manifest hash rather than by the
    # filter run alone: two runs can select the same molecules, and a scientist
    # comparing campaigns needs to know whether they docked the same set.
    selection_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_count: int = Field(ge=1)
    succeeded_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    canceled_count: int = Field(ge=0)
    best_result_kcal_mol: float | None = None
    best_ligand_name: str | None = None


class CampaignHistory(BaseModel):
    """Every campaign one engine has run against a receptor and site."""

    model_config = ConfigDict(extra="forbid")

    engine: CampaignEngine
    receptor_id: str = Field(min_length=1)
    binding_site_id: str = Field(min_length=1)
    campaigns: list[CampaignSummary] = Field(default_factory=list)
