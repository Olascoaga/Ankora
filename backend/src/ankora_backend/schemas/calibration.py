"""Contracts for the two-stage out-of-sample protocol calibration workflow.

`ADR-031` §3 fixes the discipline these models encode.  A protocol choice is
made on a Calibration split only, sealed by a hash before the locked
Confirmation split is ever opened, and the Confirmation split is single-use.
Every record here is therefore an append-only, hash-identified decision rather
than a mutable working state, and the physicochemical bias audit travels with
the split so an enrichment claim can never be read without the decoy-property
evidence that qualifies it.

Sign convention for every paired comparison in this module: the *reference* is
the comparator (the best point protocol, or the baseline), the *candidate* is
the protocol under test, and `point_delta` is always `candidate - reference`.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from statistics import median
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from ankora_backend.schemas.provenance import ProvenanceEvent
from ankora_backend.schemas.receptors import ReceptorFlexMode
from ankora_backend.schemas.screening_benchmark import ScreeningTargetMetrics
from ankora_backend.schemas.v02_contracts import (
    ProtocolSpec,
    ScoreObservation,
    canonical_contract_sha256,
)
from ankora_backend.schemas.warnings import StructuredWarning

type NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
type Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
type SplitName = Literal["calibration", "confirmation"]
type BiasPropertyName = Literal[
    "molecular_weight",
    "clogp",
    "hbd",
    "hba",
    "rotatable_bonds",
    "formal_charge",
]

#: Property order is fixed so a bias audit is comparable between splits.
BIAS_PROPERTY_NAMES: tuple[BiasPropertyName, ...] = (
    "molecular_weight",
    "clogp",
    "hbd",
    "hba",
    "rotatable_bonds",
    "formal_charge",
)

#: Prefix that keeps every acyclic compound in its own grouping unit.  An empty
#: Bemis-Murcko scaffold is not a shared scaffold, and collapsing all acyclic
#: compounds into one group would both destroy the split's stratification and
#: manufacture leakage between unrelated molecules.
ACYCLIC_SCAFFOLD_PREFIX = "ACYCLIC:"

#: `ADR-031` §3 fixes this exact phrase as the null verdict.
INSUFFICIENT_EVIDENCE_TEXT = "Insufficient evidence to prefer over baseline"

BASELINE_RETAINED_TEXT = (
    "Baseline protocol retained by 1-SE parsimony rule on calibration; "
    "confirmation evaluated for baseline audit."
)

#: Enrichment factor at a small top-`k` is dominated by integer hit counts, and
#: BEDROC over few actives is similarly unstable; both are flagged rather than
#: suppressed.
EF_CAUTION_MIN_TOP_COUNT = 10
EF_CAUTION_MIN_ACTIVE_COUNT = 20

#: A standardized mean difference at or above this magnitude is a medium effect
#: and is reported as a candidate property bias.
BIAS_SMD_THRESHOLD = 0.5
BIAS_KS_STATISTIC_THRESHOLD = 0.35
BIAS_KS_P_VALUE_THRESHOLD = 0.05

#: Tolerance for the `1-SE` comparison, so an exact arithmetic tie is inside
#: the rule rather than excluded by floating-point noise.
ONE_SE_TOLERANCE = 1e-12

_SPLIT_IDENTITY_SCHEMA = "ankora.calibration.split.v1"
_SELECTION_IDENTITY_SCHEMA = "ankora.calibration.selection.v1"
_CONFIRMATION_IDENTITY_SCHEMA = "ankora.calibration.confirmation.v1"


def property_bias_flagged(
    *, standardized_mean_difference: float, ks_statistic: float, ks_p_value: float
) -> bool:
    """Return whether one property separates actives from inactives.

    Either a medium standardized mean difference or a large *and* significant
    distributional shift is enough: a decoy set can be matched on means and
    still be separable on shape.
    """
    if abs(standardized_mean_difference) >= BIAS_SMD_THRESHOLD:
        return True
    return ks_statistic >= BIAS_KS_STATISTIC_THRESHOLD and ks_p_value < BIAS_KS_P_VALUE_THRESHOLD


def interpolated_quantile(values: Sequence[float], probability: float) -> float:
    """Return the `(n - 1) * p` linearly interpolated quantile.

    This is the percentile convention already recorded by
    `screening_benchmark.PERCENTILE_METHOD`, reused so calibration intervals
    and benchmark intervals are read on one definition.
    """
    if not values:
        raise ValueError("A quantile needs at least one value")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    weight = position - lower_index
    return ordered[lower_index] * (1 - weight) + ordered[upper_index] * weight


def interquartile_range(values: Sequence[float]) -> float:
    """Return the interquartile range under the recorded percentile method."""
    return interpolated_quantile(values, 0.75) - interpolated_quantile(values, 0.25)


def median_value(values: Sequence[float]) -> float:
    return float(median(values))


class SplitGroupingStrategy(StrEnum):
    """Grouping unit that must not appear on both sides of the split."""

    PARENT_AND_MURCKO_SCAFFOLD = "parent_and_murcko_scaffold"


class ConfirmationVerdict(StrEnum):
    PREFERRED_OVER_BASELINE = "preferred_over_baseline"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence_to_prefer_over_baseline"
    BASELINE_RETAINED_BY_ONE_SE = "baseline_retained_by_one_se"


class CalibrationSplitPolicy(BaseModel):
    """Everything about the split and its statistics that is fixed in advance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    grouping_strategy: SplitGroupingStrategy = SplitGroupingStrategy.PARENT_AND_MURCKO_SCAFFOLD
    calibration_fraction: float = Field(default=0.6, ge=0.4, le=0.8)
    split_seed: int = 20261119
    min_confirmation_actives: int = Field(default=10, ge=1)
    bedroc_alpha: float = Field(default=20.0, gt=0)
    top_fraction: float = Field(default=0.01, gt=0, le=1.0)
    bootstrap_replicates: int = Field(default=2000, ge=100)
    bootstrap_seed: int = 20261119
    confidence_level: float = Field(default=0.95, gt=0, lt=1)


class CalibrationCompoundInput(BaseModel):
    """One parent compound offered to the split, with its frozen class label.

    Enumerated microstates stay bound to their parent: they are carried as
    `state_ids` rather than as rows, so state enumeration can never become an
    unrecorded selection over a parent's best score.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    parent_id: NonBlankStr
    canonical_smiles: NonBlankStr
    is_active: bool
    state_ids: tuple[NonBlankStr, ...] = ()

    @model_validator(mode="after")
    def validate_state_ids(self) -> Self:
        if len(set(self.state_ids)) != len(self.state_ids):
            raise ValueError("Microstate identifiers of one parent must be unique")
        return self


class CompoundPropertyProfile(BaseModel):
    """Recorded grouping key and physicochemical profile of one parent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    parent_id: NonBlankStr
    canonical_smiles: NonBlankStr
    is_active: bool
    murcko_scaffold: NonBlankStr
    is_acyclic: bool
    molecular_weight: float = Field(gt=0, allow_inf_nan=False)
    clogp: float = Field(allow_inf_nan=False)
    hbd: int = Field(ge=0)
    hba: int = Field(ge=0)
    rotatable_bonds: int = Field(ge=0)
    formal_charge: int

    @model_validator(mode="after")
    def validate_acyclic_group(self) -> Self:
        expected = f"{ACYCLIC_SCAFFOLD_PREFIX}{self.parent_id}"
        if self.is_acyclic and self.murcko_scaffold != expected:
            raise ValueError("An acyclic compound must carry its own unique scaffold group")
        if not self.is_acyclic and self.murcko_scaffold.startswith(ACYCLIC_SCAFFOLD_PREFIX):
            raise ValueError("A cyclic compound cannot claim an acyclic scaffold group")
        return self

    def property_value(self, name: BiasPropertyName) -> float:
        return float(getattr(self, name))


class PropertyBiasMetric(BaseModel):
    """Active-versus-inactive separation on one physicochemical property."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    property_name: BiasPropertyName
    active_median: float = Field(allow_inf_nan=False)
    active_iqr: float = Field(ge=0, allow_inf_nan=False)
    inactive_median: float = Field(allow_inf_nan=False)
    inactive_iqr: float = Field(ge=0, allow_inf_nan=False)
    standardized_mean_difference: float = Field(allow_inf_nan=False)
    ks_statistic: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    ks_p_value: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    flagged_bias: bool

    @model_validator(mode="after")
    def validate_flag(self) -> Self:
        expected = property_bias_flagged(
            standardized_mean_difference=self.standardized_mean_difference,
            ks_statistic=self.ks_statistic,
            ks_p_value=self.ks_p_value,
        )
        if self.flagged_bias != expected:
            raise ValueError("flagged_bias must follow the recorded bias rule")
        return self


class PhysicochemicalBiasAudit(BaseModel):
    """Decoy-property audit that qualifies every enrichment read on this set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    active_count: int = Field(ge=2)
    inactive_count: int = Field(ge=2)
    metrics: tuple[PropertyBiasMetric, ...] = Field(min_length=1)
    any_bias_flagged: bool
    flagged_properties: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_audit(self) -> Self:
        names = [metric.property_name for metric in self.metrics]
        if len(set(names)) != len(names):
            raise ValueError("A bias audit cannot report one property twice")
        flagged = tuple(metric.property_name for metric in self.metrics if metric.flagged_bias)
        if self.flagged_properties != flagged:
            raise ValueError("flagged_properties must list the flagged metrics in metric order")
        if self.any_bias_flagged != bool(flagged):
            raise ValueError("any_bias_flagged must follow the individual property flags")
        return self


def compute_split_identity_sha256(
    *,
    policy: CalibrationSplitPolicy,
    calibration_parent_ids: Sequence[str],
    confirmation_parent_ids: Sequence[str],
    calibration_scaffolds: Sequence[str],
    confirmation_scaffolds: Sequence[str],
    active_parent_ids: Sequence[str],
) -> str:
    """Hash the split membership, its class labels, and the policy that fixed it."""
    return canonical_contract_sha256(
        {
            "schema": _SPLIT_IDENTITY_SCHEMA,
            "policy": policy.model_dump(mode="json"),
            "calibration_parent_ids": sorted(calibration_parent_ids),
            "confirmation_parent_ids": sorted(confirmation_parent_ids),
            "calibration_scaffolds": sorted(calibration_scaffolds),
            "confirmation_scaffolds": sorted(confirmation_scaffolds),
            "active_parent_ids": sorted(active_parent_ids),
        }
    )


class CalibrationSplitArtifact(BaseModel):
    """The frozen grouped split, constructed before any comparison number exists."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    split_id: NonBlankStr
    created_at: datetime
    policy: CalibrationSplitPolicy
    calibration_parent_ids: tuple[NonBlankStr, ...] = Field(min_length=2)
    confirmation_parent_ids: tuple[NonBlankStr, ...] = Field(min_length=2)
    calibration_scaffolds: tuple[NonBlankStr, ...] = Field(min_length=1)
    confirmation_scaffolds: tuple[NonBlankStr, ...] = Field(min_length=1)
    calibration_active_count: int = Field(ge=1)
    calibration_inactive_count: int = Field(ge=1)
    confirmation_active_count: int = Field(ge=1)
    confirmation_inactive_count: int = Field(ge=1)
    confirmation_underpowered: bool
    compounds: tuple[CompoundPropertyProfile, ...] = Field(min_length=4)
    bias_audit: PhysicochemicalBiasAudit
    split_identity_sha256: Sha256

    @model_validator(mode="after")
    def validate_split(self) -> Self:
        calibration = set(self.calibration_parent_ids)
        confirmation = set(self.confirmation_parent_ids)
        if len(calibration) != len(self.calibration_parent_ids) or len(confirmation) != len(
            self.confirmation_parent_ids
        ):
            raise ValueError("Split parent identifiers must be unique within each side")
        if calibration & confirmation:
            raise ValueError("No parent compound may appear on both sides of the split")
        if self.calibration_parent_ids != tuple(sorted(self.calibration_parent_ids)):
            raise ValueError("Calibration parent identifiers must be sorted")
        if self.confirmation_parent_ids != tuple(sorted(self.confirmation_parent_ids)):
            raise ValueError("Confirmation parent identifiers must be sorted")

        calibration_scaffolds = set(self.calibration_scaffolds)
        confirmation_scaffolds = set(self.confirmation_scaffolds)
        if calibration_scaffolds & confirmation_scaffolds:
            raise ValueError("No Bemis-Murcko scaffold may appear on both sides of the split")
        if self.calibration_scaffolds != tuple(sorted(set(self.calibration_scaffolds))):
            raise ValueError("Calibration scaffolds must be sorted and unique")
        if self.confirmation_scaffolds != tuple(sorted(set(self.confirmation_scaffolds))):
            raise ValueError("Confirmation scaffolds must be sorted and unique")

        profiles = {profile.parent_id: profile for profile in self.compounds}
        if len(profiles) != len(self.compounds):
            raise ValueError("Compound profiles must be unique per parent compound")
        if set(profiles) != calibration | confirmation:
            raise ValueError("Compound profiles must cover exactly the split's parents")

        for side, parents, scaffolds, actives, inactives in (
            (
                "calibration",
                calibration,
                calibration_scaffolds,
                self.calibration_active_count,
                self.calibration_inactive_count,
            ),
            (
                "confirmation",
                confirmation,
                confirmation_scaffolds,
                self.confirmation_active_count,
                self.confirmation_inactive_count,
            ),
        ):
            members = [profiles[parent_id] for parent_id in parents]
            observed_scaffolds = {member.murcko_scaffold for member in members}
            if observed_scaffolds != scaffolds:
                raise ValueError(f"Recorded {side} scaffolds must match the assigned compounds")
            observed_actives = sum(member.is_active for member in members)
            if observed_actives != actives or len(members) - observed_actives != inactives:
                raise ValueError(f"Recorded {side} class counts must match the assigned compounds")

        if self.confirmation_underpowered != (
            self.confirmation_active_count < self.policy.min_confirmation_actives
        ):
            raise ValueError("confirmation_underpowered must follow the recorded minimum")

        expected = compute_split_identity_sha256(
            policy=self.policy,
            calibration_parent_ids=self.calibration_parent_ids,
            confirmation_parent_ids=self.confirmation_parent_ids,
            calibration_scaffolds=self.calibration_scaffolds,
            confirmation_scaffolds=self.confirmation_scaffolds,
            active_parent_ids=[
                profile.parent_id for profile in self.compounds if profile.is_active
            ],
        )
        if self.split_identity_sha256 != expected:
            raise ValueError("split_identity_sha256 must seal the recorded split and policy")
        return self

    @property
    def active_parent_ids(self) -> frozenset[str]:
        return frozenset(profile.parent_id for profile in self.compounds if profile.is_active)

    def parent_ids_for(self, split_name: SplitName) -> tuple[str, ...]:
        if split_name == "calibration":
            return self.calibration_parent_ids
        return self.confirmation_parent_ids


class CalibrationCandidateProtocol(BaseModel):
    """One pre-declared protocol competing on the Calibration split."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_id: NonBlankStr
    label: NonBlankStr
    protocol_spec: ProtocolSpec
    added_chi_torsion_count: int = Field(default=0, ge=0)
    fitted_parameter_count: int = Field(default=0, ge=0)
    engine_count: int = Field(default=1, ge=1)
    is_neural_scoring: bool = False

    @property
    def is_sidechain_flex(self) -> bool:
        return self.protocol_spec.receptor_flexibility.mode is ReceptorFlexMode.SIDECHAIN_FLEX

    @property
    def flex_residue_count(self) -> int:
        return len(self.protocol_spec.receptor_flexibility.flex_residues)

    @property
    def parsimony_rank_key(self) -> tuple[int, int, int, int, int, int, str]:
        """Order simpler protocols first, as the `1-SE` rule requires.

        Rigid receptor before `FlexRes`, then fewer flexible residues, fewer
        added `chi` torsions, fewer fitted parameters, fewer engines, and
        empirical scoring before neural scoring.  The protocol identity hash is
        the final tie-break so the ordering is total and reproducible.
        """
        return (
            1 if self.is_sidechain_flex else 0,
            self.flex_residue_count,
            self.added_chi_torsion_count,
            self.fitted_parameter_count,
            self.engine_count,
            1 if self.is_neural_scoring else 0,
            self.protocol_spec.protocol_identity_sha256,
        )


class FailureCensusBreakdown(BaseModel):
    """Scored and unscored parents, kept separate for actives and inactives.

    A decoy that fails to prepare and an active that fails to prepare have
    opposite consequences for an enrichment metric, so one pooled failure count
    would hide the bias that matters most.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    total_parents: int = Field(ge=2)
    scored_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    scored_active_count: int = Field(ge=0)
    failed_active_count: int = Field(ge=0)
    scored_inactive_count: int = Field(ge=0)
    failed_inactive_count: int = Field(ge=0)
    failure_codes_active: dict[str, int] = Field(default_factory=dict)
    failure_codes_inactive: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_census(self) -> Self:
        if self.total_parents != self.scored_count + self.failed_count:
            raise ValueError("Scored and failed parents must sum to the total parent denominator")
        if self.total_parents != (
            self.scored_active_count
            + self.failed_active_count
            + self.scored_inactive_count
            + self.failed_inactive_count
        ):
            raise ValueError("Per-class census counts must sum to the total parent denominator")
        if self.scored_count != self.scored_active_count + self.scored_inactive_count:
            raise ValueError("Scored actives and inactives must sum to the scored count")
        if self.failed_count != self.failed_active_count + self.failed_inactive_count:
            raise ValueError("Failed actives and inactives must sum to the failed count")
        for codes, expected, label in (
            (self.failure_codes_active, self.failed_active_count, "active"),
            (self.failure_codes_inactive, self.failed_inactive_count, "inactive"),
        ):
            if any(not code.strip() for code in codes):
                raise ValueError("Every recorded failure code must be non-empty")
            if any(count < 1 for count in codes.values()):
                raise ValueError("Every recorded failure code must count at least one parent")
            if sum(codes.values()) != expected:
                raise ValueError(f"Recorded {label} failure codes must sum to its failure count")
        return self


class _FrozenTargetMetrics(ScreeningTargetMetrics):
    """Snapshot of the v0.1 metric contract that cannot be edited in place."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _freeze_metrics(metrics: ScreeningTargetMetrics) -> ScreeningTargetMetrics:
    return _FrozenTargetMetrics.model_validate(metrics.model_dump())


class ProtocolEvaluationSummary(BaseModel):
    """One protocol evaluated on exactly one side of the split."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_id: NonBlankStr
    protocol_identity_sha256: Sha256
    label: NonBlankStr
    split_name: SplitName
    metrics: Annotated[ScreeningTargetMetrics, AfterValidator(_freeze_metrics)]
    bedroc_ci_lower: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    bedroc_ci_upper: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    bedroc_bootstrap_se: float = Field(ge=0.0, allow_inf_nan=False)
    ef_small_sample_caution: bool
    failure_census: FailureCensusBreakdown

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        if self.bedroc_ci_lower > self.bedroc_ci_upper:
            raise ValueError("A BEDROC interval lower bound cannot exceed its upper bound")
        if self.ef_small_sample_caution != (
            self.metrics.top_count < EF_CAUTION_MIN_TOP_COUNT
            or self.metrics.active_count < EF_CAUTION_MIN_ACTIVE_COUNT
        ):
            raise ValueError("ef_small_sample_caution must follow the recorded sample thresholds")

        census = self.failure_census
        if census.total_parents != self.metrics.total_count:
            raise ValueError("The failure census must retain the metric parent denominator")
        if census.scored_count != self.metrics.scored_count:
            raise ValueError("The failure census scored count must match the metrics")
        if census.failed_count != self.metrics.failed_count:
            raise ValueError("The failure census failed count must match the metrics")
        if census.scored_active_count + census.failed_active_count != self.metrics.active_count:
            raise ValueError("The failure census active census must match the metric active count")
        if (
            census.scored_inactive_count + census.failed_inactive_count
            != self.metrics.inactive_count
        ):
            raise ValueError("The failure census inactive census must match the metrics")
        return self


class PairedBootstrapDelta(BaseModel):
    """Paired parent-bootstrap difference in `BEDROC_alpha`, `candidate - reference`.

    Resampling is over parent compounds, the independent unit, and the same
    resampled parent indices are applied to both protocols in every replicate.
    An unpaired interval would carry the between-compound variance that pairing
    is there to remove.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_protocol_id: NonBlankStr
    reference_protocol_id: NonBlankStr
    split_name: SplitName
    metric_name: Literal["bedroc"] = "bedroc"
    bedroc_alpha: float = Field(gt=0, allow_inf_nan=False)
    point_delta: float = Field(ge=-1.0, le=1.0, allow_inf_nan=False)
    bootstrap_se: float = Field(ge=0.0, allow_inf_nan=False)
    ci_lower: float = Field(ge=-1.0, le=1.0, allow_inf_nan=False)
    ci_upper: float = Field(ge=-1.0, le=1.0, allow_inf_nan=False)
    confidence_level: float = Field(gt=0, lt=1)
    replicates: int = Field(ge=100)
    bootstrap_seed: int
    excludes_zero_positively: bool
    within_one_se_of_reference: bool

    @model_validator(mode="after")
    def validate_delta(self) -> Self:
        if self.ci_lower > self.ci_upper:
            raise ValueError("A paired interval lower bound cannot exceed its upper bound")
        if self.excludes_zero_positively != (self.ci_lower > 0.0):
            raise ValueError("excludes_zero_positively must follow the recorded interval")
        within_one_se = -self.point_delta <= self.bootstrap_se + ONE_SE_TOLERANCE
        if self.within_one_se_of_reference != within_one_se:
            raise ValueError("within_one_se_of_reference must follow the recorded point delta")
        return self


def compute_selection_identity_sha256(
    *,
    schema_version: int,
    selected_at: datetime,
    split_identity_sha256: str,
    baseline_protocol_id: str,
    best_point_protocol_id: str,
    selected_protocol_id: str,
    selected_by_one_se_parsimony: bool,
    evaluations: Sequence[ProtocolEvaluationSummary],
    deltas_vs_best: Sequence[PairedBootstrapDelta],
    deltas_vs_baseline: Sequence[PairedBootstrapDelta],
) -> str:
    """Seal the Calibration decision before the Confirmation split is unlocked."""
    return canonical_contract_sha256(
        {
            "schema": _SELECTION_IDENTITY_SCHEMA,
            "schema_version": schema_version,
            "selected_at": selected_at.isoformat(),
            "split_identity_sha256": split_identity_sha256,
            "baseline_protocol_id": baseline_protocol_id,
            "best_point_protocol_id": best_point_protocol_id,
            "selected_protocol_id": selected_protocol_id,
            "selected_by_one_se_parsimony": selected_by_one_se_parsimony,
            "evaluations": [item.model_dump(mode="json") for item in evaluations],
            "deltas_vs_best": [item.model_dump(mode="json") for item in deltas_vs_best],
            "deltas_vs_baseline": [item.model_dump(mode="json") for item in deltas_vs_baseline],
        }
    )


class CalibrationSelectionRecord(BaseModel):
    """Stage 1 — the sealed protocol choice, made on Calibration data only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    selected_at: datetime
    split_identity_sha256: Sha256
    baseline_protocol_id: NonBlankStr
    best_point_protocol_id: NonBlankStr
    selected_protocol_id: NonBlankStr
    selected_by_one_se_parsimony: bool
    evaluations: tuple[ProtocolEvaluationSummary, ...] = Field(min_length=1)
    deltas_vs_best: tuple[PairedBootstrapDelta, ...] = Field(min_length=1)
    deltas_vs_baseline: tuple[PairedBootstrapDelta, ...] = Field(min_length=1)
    selection_identity_sha256: Sha256

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        evaluated = {item.protocol_id for item in self.evaluations}
        if len(evaluated) != len(self.evaluations):
            raise ValueError("A calibration selection cannot evaluate one protocol twice")
        if any(item.split_name != "calibration" for item in self.evaluations):
            raise ValueError("Stage 1 may only record calibration-split evaluations")
        missing = {
            self.baseline_protocol_id,
            self.best_point_protocol_id,
            self.selected_protocol_id,
        } - evaluated
        if missing:
            raise ValueError("Every referenced protocol must carry a calibration evaluation")
        for deltas, reference in (
            (self.deltas_vs_best, self.best_point_protocol_id),
            (self.deltas_vs_baseline, self.baseline_protocol_id),
        ):
            if any(item.reference_protocol_id != reference for item in deltas):
                raise ValueError("Recorded paired deltas must share their declared reference")
            if any(item.split_name != "calibration" for item in deltas):
                raise ValueError("Stage 1 paired deltas must be measured on calibration")
        if self.selected_by_one_se_parsimony != (
            self.selected_protocol_id != self.best_point_protocol_id
        ):
            raise ValueError("selected_by_one_se_parsimony must follow the selected protocol")

        expected = compute_selection_identity_sha256(
            schema_version=self.schema_version,
            selected_at=self.selected_at,
            split_identity_sha256=self.split_identity_sha256,
            baseline_protocol_id=self.baseline_protocol_id,
            best_point_protocol_id=self.best_point_protocol_id,
            selected_protocol_id=self.selected_protocol_id,
            selected_by_one_se_parsimony=self.selected_by_one_se_parsimony,
            evaluations=self.evaluations,
            deltas_vs_best=self.deltas_vs_best,
            deltas_vs_baseline=self.deltas_vs_baseline,
        )
        if self.selection_identity_sha256 != expected:
            raise ValueError("selection_identity_sha256 must seal the recorded decision")
        return self


def compute_confirmation_identity_sha256(
    *,
    schema_version: int,
    evaluated_at: datetime,
    split_identity_sha256: str,
    selection_identity_sha256: str,
    baseline_protocol_id: str,
    selected_protocol_id: str,
    verdict: ConfirmationVerdict,
    verdict_text: str,
    selected_evaluation: ProtocolEvaluationSummary,
    baseline_evaluation: ProtocolEvaluationSummary,
    paired_delta_vs_baseline: PairedBootstrapDelta,
    all_candidate_audit_evaluations: Sequence[ProtocolEvaluationSummary],
) -> str:
    """Seal the single-use Confirmation outcome, including a null verdict."""
    return canonical_contract_sha256(
        {
            "schema": _CONFIRMATION_IDENTITY_SCHEMA,
            "schema_version": schema_version,
            "evaluated_at": evaluated_at.isoformat(),
            "split_identity_sha256": split_identity_sha256,
            "selection_identity_sha256": selection_identity_sha256,
            "baseline_protocol_id": baseline_protocol_id,
            "selected_protocol_id": selected_protocol_id,
            "verdict": verdict.value,
            "verdict_text": verdict_text,
            "selected_evaluation": selected_evaluation.model_dump(mode="json"),
            "baseline_evaluation": baseline_evaluation.model_dump(mode="json"),
            "paired_delta_vs_baseline": paired_delta_vs_baseline.model_dump(mode="json"),
            "all_candidate_audit_evaluations": [
                item.model_dump(mode="json") for item in all_candidate_audit_evaluations
            ],
        }
    )


class ConfirmationEvaluationRecord(BaseModel):
    """Stage 2 — the single-use unlock of the locked Confirmation split."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    evaluated_at: datetime
    split_identity_sha256: Sha256
    selection_identity_sha256: Sha256
    baseline_protocol_id: NonBlankStr
    selected_protocol_id: NonBlankStr
    verdict: ConfirmationVerdict
    verdict_text: NonBlankStr
    selected_evaluation: ProtocolEvaluationSummary
    baseline_evaluation: ProtocolEvaluationSummary
    paired_delta_vs_baseline: PairedBootstrapDelta
    all_candidate_audit_evaluations: tuple[ProtocolEvaluationSummary, ...] = ()
    confirmation_identity_sha256: Sha256

    @model_validator(mode="after")
    def validate_confirmation(self) -> Self:
        evaluations = (
            self.selected_evaluation,
            self.baseline_evaluation,
            *self.all_candidate_audit_evaluations,
        )
        if any(item.split_name != "confirmation" for item in evaluations):
            raise ValueError("Stage 2 may only record confirmation-split evaluations")
        if self.selected_evaluation.protocol_id != self.selected_protocol_id:
            raise ValueError("The selected evaluation must describe the selected protocol")
        if self.baseline_evaluation.protocol_id != self.baseline_protocol_id:
            raise ValueError("The baseline evaluation must describe the baseline protocol")
        audit_ids = [item.protocol_id for item in self.all_candidate_audit_evaluations]
        if len(set(audit_ids)) != len(audit_ids):
            raise ValueError("The audit table cannot evaluate one protocol twice")
        delta = self.paired_delta_vs_baseline
        if (
            delta.candidate_protocol_id != self.selected_protocol_id
            or delta.reference_protocol_id != self.baseline_protocol_id
            or delta.split_name != "confirmation"
        ):
            raise ValueError("The paired delta must compare the selected protocol to the baseline")
        if (
            self.verdict is ConfirmationVerdict.INSUFFICIENT_EVIDENCE
            and self.verdict_text != INSUFFICIENT_EVIDENCE_TEXT
        ):
            raise ValueError(
                "A null verdict must record the exact ADR-031 phrase "
                f"{INSUFFICIENT_EVIDENCE_TEXT!r}"
            )
        if (
            self.verdict is not ConfirmationVerdict.INSUFFICIENT_EVIDENCE
            and self.verdict_text == INSUFFICIENT_EVIDENCE_TEXT
        ):
            raise ValueError("Only a null verdict may record the ADR-031 null phrase")
        if self.verdict is ConfirmationVerdict.BASELINE_RETAINED_BY_ONE_SE and (
            self.selected_protocol_id != self.baseline_protocol_id
        ):
            raise ValueError("A baseline-retained verdict requires the baseline to be selected")
        if self.verdict is ConfirmationVerdict.PREFERRED_OVER_BASELINE and (
            self.selected_protocol_id == self.baseline_protocol_id
            or not delta.excludes_zero_positively
        ):
            raise ValueError(
                "A preference verdict requires a non-baseline protocol and an interval "
                "that excludes zero positively"
            )

        expected = compute_confirmation_identity_sha256(
            schema_version=self.schema_version,
            evaluated_at=self.evaluated_at,
            split_identity_sha256=self.split_identity_sha256,
            selection_identity_sha256=self.selection_identity_sha256,
            baseline_protocol_id=self.baseline_protocol_id,
            selected_protocol_id=self.selected_protocol_id,
            verdict=self.verdict,
            verdict_text=self.verdict_text,
            selected_evaluation=self.selected_evaluation,
            baseline_evaluation=self.baseline_evaluation,
            paired_delta_vs_baseline=self.paired_delta_vs_baseline,
            all_candidate_audit_evaluations=self.all_candidate_audit_evaluations,
        )
        if self.confirmation_identity_sha256 != expected:
            raise ValueError("confirmation_identity_sha256 must seal the recorded outcome")
        return self


#: Which stage records each status requires: (selection present, confirmation present).
_STAGE_RECORDS_BY_STATUS: Mapping[str, tuple[bool, bool]] = {
    "split_locked": (False, False),
    "calibration_selected": (True, False),
    "confirmation_completed": (True, True),
}


class CalibrationRunRecord(BaseModel):
    """The whole calibration campaign: split, sealed selection, and verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    calibration_id: NonBlankStr
    project_id: NonBlankStr
    receptor_id: NonBlankStr
    binding_site_id: NonBlankStr
    created_at: datetime
    status: Literal["split_locked", "calibration_selected", "confirmation_completed"]
    confirmation_locked: bool
    confirmation_consumed: bool
    split: CalibrationSplitArtifact
    baseline_protocol_id: NonBlankStr | None = None
    candidates: tuple[CalibrationCandidateProtocol, ...] = ()
    calibration_selection: CalibrationSelectionRecord | None = None
    confirmation_evaluation: ConfirmationEvaluationRecord | None = None
    warnings: tuple[StructuredWarning, ...] = ()
    provenance: tuple[ProvenanceEvent, ...] = ()

    @model_validator(mode="after")
    def validate_run(self) -> Self:
        protocol_ids = [candidate.protocol_id for candidate in self.candidates]
        if len(set(protocol_ids)) != len(protocol_ids):
            raise ValueError("Candidate protocol identifiers must be unique")
        if self.baseline_protocol_id is not None and self.baseline_protocol_id not in protocol_ids:
            raise ValueError("The baseline protocol must be one of the recorded candidates")
        if self.confirmation_locked == self.confirmation_consumed:
            raise ValueError("A confirmation split is locked until, and only until, it is consumed")

        has_selection = self.calibration_selection is not None
        has_confirmation = self.confirmation_evaluation is not None
        expected = _STAGE_RECORDS_BY_STATUS[self.status]
        if (has_selection, has_confirmation) != expected:
            raise ValueError(f"Status {self.status} does not match the recorded stage records")
        if self.confirmation_consumed != (self.status == "confirmation_completed"):
            raise ValueError("A consumed confirmation split requires a completed status")

        selection = self.calibration_selection
        if selection is not None:
            if selection.split_identity_sha256 != self.split.split_identity_sha256:
                raise ValueError("The sealed selection must reference this run's split identity")
            if selection.baseline_protocol_id != self.baseline_protocol_id:
                raise ValueError("The sealed selection must reference this run's baseline")
            if not {item.protocol_id for item in selection.evaluations} <= set(protocol_ids):
                raise ValueError("Every evaluated protocol must be a recorded candidate")
        confirmation = self.confirmation_evaluation
        if confirmation is not None:
            if selection is None:
                raise ValueError("A confirmation outcome requires a sealed calibration selection")
            if confirmation.split_identity_sha256 != self.split.split_identity_sha256:
                raise ValueError("The confirmation outcome must reference this run's split")
            if confirmation.selection_identity_sha256 != selection.selection_identity_sha256:
                raise ValueError("The confirmation outcome must reference the sealed selection")
            if confirmation.selected_protocol_id != selection.selected_protocol_id:
                raise ValueError("The confirmation outcome must evaluate the selected protocol")
        return self

    def candidate(self, protocol_id: str) -> CalibrationCandidateProtocol | None:
        return next(
            (item for item in self.candidates if item.protocol_id == protocol_id),
            None,
        )

    def candidates_by_id(self) -> Mapping[str, CalibrationCandidateProtocol]:
        return {candidate.protocol_id: candidate for candidate in self.candidates}


class CalibrationRunListResponse(BaseModel):
    """Envelope listing saved calibration runs for the active project."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    runs: tuple[CalibrationRunRecord, ...] = ()


class CalibrationSplitRequest(BaseModel):
    """HTTP request to create and lock a scaffold-grouped calibration split."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    receptor_id: NonBlankStr
    binding_site_id: NonBlankStr
    compounds: tuple[CalibrationCompoundInput, ...] = Field(min_length=4)
    policy: CalibrationSplitPolicy | None = None


class CalibrationSelectRequest(BaseModel):
    """HTTP request to evaluate candidates on Calibration and seal 1-SE selection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline_protocol_id: NonBlankStr
    candidates: tuple[CalibrationCandidateProtocol, ...] = Field(min_length=1)
    observations_by_protocol: dict[str, tuple[ScoreObservation, ...]]


class CalibrationConfirmRequest(BaseModel):
    """HTTP request for single-use unlock and evaluation of locked Confirmation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    observations_by_protocol: dict[str, tuple[ScoreObservation, ...]]
