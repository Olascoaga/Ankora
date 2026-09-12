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


class ScreeningMetricInterval(BaseModel):
    """One deterministic percentile interval over parent-level resamples."""

    model_config = ConfigDict(extra="forbid")

    lower: float = Field(ge=0)
    upper: float = Field(ge=0)

    @model_validator(mode="after")
    def lower_does_not_exceed_upper(self) -> "ScreeningMetricInterval":
        if self.lower > self.upper:
            raise ValueError("a confidence interval lower bound cannot exceed its upper bound")
        return self


class ScreeningMetricIntervals(BaseModel):
    """Intervals for the four preregistered ranking measures."""

    model_config = ConfigDict(extra="forbid")

    enrichment_factor: ScreeningMetricInterval
    bedroc: ScreeningMetricInterval
    roc_auc: ScreeningMetricInterval
    pr_auc: ScreeningMetricInterval


class ScreeningBenchmarkReport(BaseModel):
    """Per-target evidence plus a deliberately unweighted macro summary."""

    model_config = ConfigDict(extra="forbid")

    targets: list[ScreeningTargetMetrics] = Field(min_length=2)
    macro: ScreeningMacroMetrics


class ScreeningTargetEstimate(BaseModel):
    """One target's point estimates and parent-bootstrap uncertainty."""

    model_config = ConfigDict(extra="forbid")

    point: ScreeningTargetMetrics
    intervals: ScreeningMetricIntervals


class ScreeningBenchmarkEstimate(BaseModel):
    """A complete multi-target estimate under one immutable metric protocol."""

    model_config = ConfigDict(extra="forbid")

    targets: list[ScreeningTargetEstimate] = Field(min_length=2)
    macro_point: ScreeningMacroMetrics
    macro_intervals: ScreeningMetricIntervals
    bootstrap_replicates: int = Field(ge=1)
    bootstrap_seed: int
    confidence_level: float = Field(gt=0, lt=1)
    bootstrap_method: str = Field(min_length=1)
    percentile_method: str = Field(min_length=1)
