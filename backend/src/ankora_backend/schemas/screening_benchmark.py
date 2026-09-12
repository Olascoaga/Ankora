"""Contracts for virtual-screening benchmark evaluation.

The ranking unit is one parent compound.  Prepared chemical states remain
traceable inputs, but evaluating several states of one parent and retaining
the best score would turn state enumeration into an unrecorded optimization.
"""

from enum import StrEnum
from math import isfinite

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScoreDirection(StrEnum):
    """Which numerical direction an engine ranks more favorably."""

    LOWER_IS_BETTER = "lower_is_better"
    HIGHER_IS_BETTER = "higher_is_better"


class ScreeningBenchmarkObservation(BaseModel):
    """One parent compound and its frozen experimental class and result."""

    model_config = ConfigDict(extra="forbid")

    parent_id: str = Field(min_length=1)
    is_active: bool
    score: float | None = None
    state_id: str = Field(min_length=1)
    failure_code: str | None = None

    @model_validator(mode="after")
    def score_and_failure_are_exclusive(self) -> "ScreeningBenchmarkObservation":
        if self.score is None and not self.failure_code:
            raise ValueError("an unscored observation must retain a failure_code")
        if self.score is not None and self.failure_code is not None:
            raise ValueError("a scored observation cannot also be marked failed")
        if self.score is not None and not isfinite(self.score):
            raise ValueError("benchmark scores must be finite")
        return self


class ScreeningTargetMetrics(BaseModel):
    """Tie-aware enrichment metrics for one target and one exact protocol."""

    model_config = ConfigDict(extra="forbid")

    target_id: str = Field(min_length=1)
    total_count: int = Field(ge=2)
    active_count: int = Field(ge=1)
    inactive_count: int = Field(ge=1)
    scored_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    top_fraction: float = Field(gt=0, le=1)
    top_count: int = Field(ge=1)
    expected_active_hits_at_top_fraction: float = Field(ge=0)
    enrichment_factor: float = Field(ge=0)
    bedroc_alpha: float = Field(gt=0)
    bedroc: float = Field(ge=0, le=1)
    roc_auc: float = Field(ge=0, le=1)
    pr_auc: float = Field(ge=0, le=1)
    score_direction: ScoreDirection
    tie_policy: str = Field(min_length=1)
    failure_policy: str = Field(min_length=1)
    pr_auc_definition: str = Field(min_length=1)


class ScreeningMacroMetrics(BaseModel):
    """Equal-target macro average; library sizes never weight target claims."""

    model_config = ConfigDict(extra="forbid")

    target_count: int = Field(ge=2)
    enrichment_factor: float = Field(ge=0)
    bedroc: float = Field(ge=0, le=1)
    roc_auc: float = Field(ge=0, le=1)
    pr_auc: float = Field(ge=0, le=1)


class ScreeningBenchmarkReport(BaseModel):
    """Per-target evidence plus a deliberately unweighted macro summary."""

    model_config = ConfigDict(extra="forbid")

    targets: list[ScreeningTargetMetrics] = Field(min_length=2)
    macro: ScreeningMacroMetrics
