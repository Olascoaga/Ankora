"""Out-of-sample protocol calibration under `ADR-031` §3.

The service runs exactly two stages against one frozen, scaffold-grouped split.

Stage 1 evaluates every pre-declared candidate protocol on the **Calibration**
side only, applies the `1-SE` parsimony rule, and seals the decision behind a
hash.  Stage 2 then unlocks the **Confirmation** side once, compares only the
sealed selection against the baseline, and records a verdict that may well be
the exact null phrase of `ADR-031`.  Nothing here docks, scores, or re-ranks:
it consumes `ScoreObservation` records that already exist and decides which
protocol a comparison claim is allowed to use.

Three properties are load-bearing and are enforced rather than documented:

* **No leakage.** Candidate evaluation sees only its own split's parents, so an
  observation belonging to a Confirmation parent cannot influence Stage 1.
* **Invariant denominator.** Every parent of the split stays in the metric
  denominator.  A missing or failed observation becomes the worst-ranked tie,
  never a dropped row, and the failure census keeps actives and inactives
  apart so a decoy-only preparation failure is visible.
* **One ranking unit per parent.** A second observation for one parent is
  rejected, so microstate enumeration can never become an unrecorded
  best-of-`K` selection.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from importlib import import_module
from math import sqrt
from random import Random
from statistics import fmean, variance
from typing import Any, NamedTuple, NoReturn
from uuid import uuid4

from ankora_backend import __version__
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.calibration_store import CalibrationArtifactStore
from ankora_backend.schemas.calibration import (
    ACYCLIC_SCAFFOLD_PREFIX,
    BASELINE_RETAINED_TEXT,
    BIAS_PROPERTY_NAMES,
    EF_CAUTION_MIN_ACTIVE_COUNT,
    EF_CAUTION_MIN_TOP_COUNT,
    INSUFFICIENT_EVIDENCE_TEXT,
    ONE_SE_TOLERANCE,
    CalibrationCandidateProtocol,
    CalibrationCompoundInput,
    CalibrationRunRecord,
    CalibrationSelectionRecord,
    CalibrationSplitArtifact,
    CalibrationSplitPolicy,
    CompoundPropertyProfile,
    ConfirmationEvaluationRecord,
    ConfirmationVerdict,
    FailureCensusBreakdown,
    PairedBootstrapDelta,
    PhysicochemicalBiasAudit,
    PropertyBiasMetric,
    ProtocolEvaluationSummary,
    SplitName,
    compute_confirmation_identity_sha256,
    compute_selection_identity_sha256,
    compute_split_identity_sha256,
    interpolated_quantile,
    interquartile_range,
    median_value,
    property_bias_flagged,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.screening_benchmark import (
    ScoreDirection,
    ScreeningBenchmarkObservation,
    ScreeningTargetMetrics,
)
from ankora_backend.schemas.v02_contracts import (
    ObservationStatus,
    ScoreObservation,
    ScoringFunctionId,
)
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode
from ankora_backend.services.execution_freshness import require_current_for_store

# `_rank_groups` and `_bedroc` are v0.1 benchmark internals, reused verbatim
# rather than reimplemented: a bootstrap replicate holds repeated parents and
# therefore cannot pass `evaluate_target`'s one-row-per-parent gate, while it
# still has to apply the identical fractional-tie and worst-tie failure policy.
from ankora_backend.services.screening_benchmark import (
    _bedroc,
    _rank_groups,
    evaluate_target,
)

# RDKit is reached through `import_module` so a tracked top-level `rdkit`
# import never enters this package's import graph.
Chem: Any = import_module("rdkit.Chem")
Descriptors: Any = import_module("rdkit.Chem.Descriptors")
Lipinski: Any = import_module("rdkit.Chem.Lipinski")
MurckoScaffold: Any = import_module("rdkit.Chem.Scaffolds.MurckoScaffold")
rdmolops: Any = import_module("rdkit.Chem.rdmolops")

_STAGE = "protocol_calibration"
_TOOL_NAME = "ankora-protocol-calibration"

#: A split parent with no supplied observation at all is still a campaign row.
MISSING_OBSERVATION_FAILURE_CODE = "CALIBRATION_OBSERVATION_MISSING"

#: GNINA's neural outputs rank descending; every empirical `kcal/mol` function,
#: including `minimizedAffinity`, ranks ascending.
_HIGHER_IS_BETTER_FUNCTIONS = frozenset(
    {
        ScoringFunctionId.GNINA_CNN_SCORE,
        ScoringFunctionId.GNINA_CNN_AFFINITY,
        ScoringFunctionId.GNINA_CNN_VS,
    }
)


def _invalid(
    code: str,
    message: str,
    *,
    status_code: int = 422,
    details: dict[str, object] | None = None,
) -> NoReturn:
    raise AnkoraDomainError(
        code=code,
        stage=_STAGE,
        message=message,
        status_code=status_code,
        details=details or {},
    )


def extract_compound_properties(
    compounds: Sequence[CalibrationCompoundInput],
) -> tuple[CompoundPropertyProfile, ...]:
    """Derive the grouping key and physicochemical profile of every parent.

    Profiles come back ordered by `parent_id`, so neither the split nor the
    recorded artifact can depend on the order the caller supplied.
    """
    if not compounds:
        _invalid(
            "CALIBRATION_SPLIT_INFEASIBLE",
            "A calibration split needs at least one parent compound.",
        )

    seen: set[str] = set()
    profiles: list[CompoundPropertyProfile] = []
    for compound in compounds:
        if compound.parent_id in seen:
            _invalid(
                "CALIBRATION_DUPLICATE_PARENT_ID",
                "A calibration compound set may list each parent compound once.",
                details={"parent_id": compound.parent_id},
            )
        seen.add(compound.parent_id)

        molecule = Chem.MolFromSmiles(compound.canonical_smiles)
        if molecule is None:
            _invalid(
                "CALIBRATION_INVALID_SMILES",
                "A calibration compound carries SMILES that RDKit cannot parse.",
                details={
                    "parent_id": compound.parent_id,
                    "canonical_smiles": compound.canonical_smiles,
                },
            )

        scaffold = str(MurckoScaffold.MurckoScaffoldSmiles(mol=molecule, includeChirality=False))
        is_acyclic = not scaffold
        profiles.append(
            CompoundPropertyProfile(
                parent_id=compound.parent_id,
                canonical_smiles=compound.canonical_smiles,
                is_active=compound.is_active,
                murcko_scaffold=(
                    f"{ACYCLIC_SCAFFOLD_PREFIX}{compound.parent_id}" if is_acyclic else scaffold
                ),
                is_acyclic=is_acyclic,
                molecular_weight=float(Descriptors.MolWt(molecule)),
                clogp=float(Descriptors.MolLogP(molecule)),
                hbd=int(Lipinski.NumHDonors(molecule)),
                hba=int(Lipinski.NumHAcceptors(molecule)),
                rotatable_bonds=int(Lipinski.NumRotatableBonds(molecule)),
                formal_charge=int(rdmolops.GetFormalCharge(molecule)),
            )
        )
    return tuple(sorted(profiles, key=lambda profile: profile.parent_id))


def _standardized_mean_difference(active: Sequence[float], inactive: Sequence[float]) -> float:
    """Return Cohen's `d` on pooled SD, or combined-SD separation when within-class SD vanishes."""
    mean_diff = fmean(active) - fmean(inactive)
    active_n = len(active)
    inactive_n = len(inactive)
    pooled_variance = (
        (active_n - 1) * variance(active) + (inactive_n - 1) * variance(inactive)
    ) / (active_n + inactive_n - 2)
    pooled_sd = sqrt(pooled_variance) if pooled_variance > 0 else 0.0
    if pooled_sd == 0.0:
        if mean_diff == 0.0:
            return 0.0
        # Within-class degeneracy with distinct class means (e.g., all actives charge +1
        # vs all inactives charge 0): normalize by finite combined sample SD so perfect
        # property separation always flags bias while preserving `allow_inf_nan=False`.
        combined_sd = sqrt(variance([*active, *inactive]))
        return mean_diff / combined_sd
    return mean_diff / pooled_sd


def audit_physicochemical_bias(
    profiles: Sequence[CompoundPropertyProfile],
) -> PhysicochemicalBiasAudit:
    """Report how far the decoys are separable from the actives on plain properties.

    An enrichment result over decoys that differ systematically in size or
    lipophilicity measures property discrimination as much as it measures
    binding-mode discrimination, so the audit travels with the split instead of
    being computed on request.
    """
    actives = [profile for profile in profiles if profile.is_active]
    inactives = [profile for profile in profiles if not profile.is_active]
    if len(actives) < 2 or len(inactives) < 2:
        _invalid(
            "CALIBRATION_BIAS_AUDIT_INFEASIBLE",
            "A decoy property audit needs at least two actives and two inactives.",
            details={"active_count": len(actives), "inactive_count": len(inactives)},
        )

    # scipy lives in the pinned `receptor` extra; it is imported here so the
    # module stays importable where only the core closure is installed.
    stats: Any = import_module("scipy.stats")

    metrics: list[PropertyBiasMetric] = []
    for name in BIAS_PROPERTY_NAMES:
        active_values = [profile.property_value(name) for profile in actives]
        inactive_values = [profile.property_value(name) for profile in inactives]
        difference = _standardized_mean_difference(active_values, inactive_values)
        result = stats.ks_2samp(active_values, inactive_values)
        ks_statistic = min(1.0, max(0.0, float(result.statistic)))
        ks_p_value = min(1.0, max(0.0, float(result.pvalue)))
        metrics.append(
            PropertyBiasMetric(
                property_name=name,
                active_median=median_value(active_values),
                active_iqr=interquartile_range(active_values),
                inactive_median=median_value(inactive_values),
                inactive_iqr=interquartile_range(inactive_values),
                standardized_mean_difference=difference,
                ks_statistic=ks_statistic,
                ks_p_value=ks_p_value,
                flagged_bias=property_bias_flagged(
                    standardized_mean_difference=difference,
                    ks_statistic=ks_statistic,
                    ks_p_value=ks_p_value,
                ),
            )
        )

    flagged = tuple(metric.property_name for metric in metrics if metric.flagged_bias)
    return PhysicochemicalBiasAudit(
        active_count=len(actives),
        inactive_count=len(inactives),
        metrics=tuple(metrics),
        any_bias_flagged=bool(flagged),
        flagged_properties=flagged,
    )


def score_direction_for(candidate: CalibrationCandidateProtocol) -> ScoreDirection:
    """Return the ranking direction fixed by the candidate's scoring function."""
    if candidate.protocol_spec.scoring_function in _HIGHER_IS_BETTER_FUNCTIONS:
        return ScoreDirection.HIGHER_IS_BETTER
    return ScoreDirection.LOWER_IS_BETTER


def observations_for_split(
    *,
    candidate: CalibrationCandidateProtocol,
    observations: Sequence[ScoreObservation],
    split_parent_ids: Sequence[str],
    active_parent_ids: frozenset[str],
) -> tuple[tuple[ScreeningBenchmarkObservation, ...], FailureCensusBreakdown]:
    """Project one protocol's observations onto one split, keeping every parent.

    Observations outside `split_parent_ids` are discarded, which is what keeps
    Stage 1 blind to the Confirmation side.  Rows come back in `parent_id`
    order so two protocols evaluated on the same split are index-aligned and
    can be bootstrapped as pairs.
    """
    expected_identity = candidate.protocol_spec.protocol_identity_sha256
    direction = score_direction_for(candidate)
    split_parents = set(split_parent_ids)

    by_parent: dict[str, ScoreObservation] = {}
    for observation in observations:
        if observation.protocol_identity_sha256 != expected_identity:
            _invalid(
                "CALIBRATION_PROTOCOL_IDENTITY_MISMATCH",
                "An observation does not belong to the candidate protocol it was supplied for.",
                details={
                    "protocol_id": candidate.protocol_id,
                    "expected_protocol_identity_sha256": expected_identity,
                    "observed_protocol_identity_sha256": observation.protocol_identity_sha256,
                    "parent_compound_id": observation.parent_compound_id,
                },
            )
        if observation.parent_compound_id not in split_parents:
            continue
        if observation.direction is not direction:
            _invalid(
                "CALIBRATION_SCORE_DIRECTION_MISMATCH",
                "An observation ranks in the opposite direction to its scoring function.",
                details={
                    "protocol_id": candidate.protocol_id,
                    "parent_compound_id": observation.parent_compound_id,
                    "expected_direction": direction.value,
                    "observed_direction": observation.direction.value,
                },
            )
        if observation.parent_compound_id in by_parent:
            _invalid(
                "CALIBRATION_DUPLICATE_PARENT_OBSERVATION",
                "A parent compound is one ranking unit and may carry one observation.",
                details={
                    "protocol_id": candidate.protocol_id,
                    "parent_compound_id": observation.parent_compound_id,
                },
            )
        by_parent[observation.parent_compound_id] = observation

    rows: list[ScreeningBenchmarkObservation] = []
    scored_active = scored_inactive = failed_active = failed_inactive = 0
    codes_active: dict[str, int] = {}
    codes_inactive: dict[str, int] = {}

    for parent_id in sorted(split_parents):
        is_active = parent_id in active_parent_ids
        recorded = by_parent.get(parent_id)
        if recorded is not None and recorded.status is ObservationStatus.SCORED:
            rows.append(
                ScreeningBenchmarkObservation(
                    parent_id=parent_id,
                    is_active=is_active,
                    score=recorded.raw_score,
                    state_id=recorded.parent_state_id,
                )
            )
            if is_active:
                scored_active += 1
            else:
                scored_inactive += 1
            continue

        failure_code = (
            recorded.failure_code
            if recorded is not None and recorded.failure_code
            else MISSING_OBSERVATION_FAILURE_CODE
        )
        rows.append(
            ScreeningBenchmarkObservation(
                parent_id=parent_id,
                is_active=is_active,
                score=None,
                # A parent with no observation at all has no prepared state to
                # name, so the parent identifier stands in for it.
                state_id=recorded.parent_state_id if recorded is not None else parent_id,
                failure_code=failure_code,
            )
        )
        codes = codes_active if is_active else codes_inactive
        codes[failure_code] = codes.get(failure_code, 0) + 1
        if is_active:
            failed_active += 1
        else:
            failed_inactive += 1

    census = FailureCensusBreakdown(
        total_parents=len(rows),
        scored_count=scored_active + scored_inactive,
        failed_count=failed_active + failed_inactive,
        scored_active_count=scored_active,
        failed_active_count=failed_active,
        scored_inactive_count=scored_inactive,
        failed_inactive_count=failed_inactive,
        failure_codes_active=dict(sorted(codes_active.items())),
        failure_codes_inactive=dict(sorted(codes_inactive.items())),
    )
    return tuple(rows), census


def _class_indices(
    rows: Sequence[ScreeningBenchmarkObservation],
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    actives = tuple(index for index, row in enumerate(rows) if row.is_active)
    inactives = tuple(index for index, row in enumerate(rows) if not row.is_active)
    return actives, inactives


def _replicate_bedroc(
    rows: Sequence[ScreeningBenchmarkObservation],
    *,
    direction: ScoreDirection,
    alpha: float,
    active_count: int,
) -> float:
    """Return `BEDROC_alpha` under the v0.1 tie and failure policy."""
    return _bedroc(_rank_groups(rows, direction), len(rows), active_count, alpha)


def _stratified_parent_picks(
    generator: Random, active_indices: Sequence[int], inactive_indices: Sequence[int]
) -> list[int]:
    """Resample parents with replacement, holding both class counts fixed."""
    picks = generator.choices(list(active_indices), k=len(active_indices))
    picks.extend(generator.choices(list(inactive_indices), k=len(inactive_indices)))
    return picks


def _sample_standard_error(values: Sequence[float]) -> float:
    mean_value = fmean(values)
    return sqrt(sum((value - mean_value) ** 2 for value in values) / (len(values) - 1))


def paired_parent_bootstrap_delta(
    *,
    candidate_protocol_id: str,
    reference_protocol_id: str,
    split_name: SplitName,
    candidate_observations: Sequence[ScreeningBenchmarkObservation],
    reference_observations: Sequence[ScreeningBenchmarkObservation],
    candidate_direction: ScoreDirection,
    reference_direction: ScoreDirection,
    policy: CalibrationSplitPolicy,
) -> PairedBootstrapDelta:
    """Bootstrap `Δ BEDROC_alpha = candidate - reference` over parent compounds.

    Both protocols are resampled with the **same** parent indices in every
    replicate.  Pairing removes the between-compound variance the two
    protocols share, which is the variance component that would otherwise
    swamp a genuine protocol difference.
    """
    if len(candidate_observations) != len(reference_observations):
        _invalid(
            "CALIBRATION_PAIRED_ALIGNMENT_MISMATCH",
            "A paired bootstrap needs the same parent compounds on both sides.",
            details={
                "candidate_protocol_id": candidate_protocol_id,
                "reference_protocol_id": reference_protocol_id,
                "candidate_count": len(candidate_observations),
                "reference_count": len(reference_observations),
            },
        )
    for candidate_row, reference_row in zip(
        candidate_observations, reference_observations, strict=True
    ):
        if (
            candidate_row.parent_id != reference_row.parent_id
            or candidate_row.is_active != reference_row.is_active
        ):
            _invalid(
                "CALIBRATION_PAIRED_ALIGNMENT_MISMATCH",
                "A paired bootstrap needs identically ordered parents and class labels.",
                details={
                    "candidate_protocol_id": candidate_protocol_id,
                    "reference_protocol_id": reference_protocol_id,
                    "candidate_parent_id": candidate_row.parent_id,
                    "reference_parent_id": reference_row.parent_id,
                },
            )

    active_indices, inactive_indices = _class_indices(candidate_observations)
    if not active_indices or not inactive_indices:
        _invalid(
            "CALIBRATION_PAIRED_CLASS_MISSING",
            "A paired bootstrap requires at least one active and one inactive parent compound.",
            details={
                "candidate_protocol_id": candidate_protocol_id,
                "reference_protocol_id": reference_protocol_id,
                "active_count": len(active_indices),
                "inactive_count": len(inactive_indices),
            },
        )
    alpha = policy.bedroc_alpha
    active_count = len(active_indices)
    point_delta = _replicate_bedroc(
        candidate_observations,
        direction=candidate_direction,
        alpha=alpha,
        active_count=active_count,
    ) - _replicate_bedroc(
        reference_observations,
        direction=reference_direction,
        alpha=alpha,
        active_count=active_count,
    )

    generator = Random(policy.bootstrap_seed)
    deltas: list[float] = []
    for _ in range(policy.bootstrap_replicates):
        picks = _stratified_parent_picks(generator, active_indices, inactive_indices)
        deltas.append(
            _replicate_bedroc(
                [candidate_observations[index] for index in picks],
                direction=candidate_direction,
                alpha=alpha,
                active_count=active_count,
            )
            - _replicate_bedroc(
                [reference_observations[index] for index in picks],
                direction=reference_direction,
                alpha=alpha,
                active_count=active_count,
            )
        )

    bootstrap_se = _sample_standard_error(deltas)
    tail = (1 - policy.confidence_level) / 2
    ci_lower = interpolated_quantile(deltas, tail)
    ci_upper = interpolated_quantile(deltas, 1 - tail)
    return PairedBootstrapDelta(
        candidate_protocol_id=candidate_protocol_id,
        reference_protocol_id=reference_protocol_id,
        split_name=split_name,
        bedroc_alpha=alpha,
        point_delta=point_delta,
        bootstrap_se=bootstrap_se,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        confidence_level=policy.confidence_level,
        replicates=policy.bootstrap_replicates,
        bootstrap_seed=policy.bootstrap_seed,
        excludes_zero_positively=ci_lower > 0.0,
        within_one_se_of_reference=-point_delta <= bootstrap_se + ONE_SE_TOLERANCE,
    )


class _Evaluated(NamedTuple):
    """One candidate's metrics plus the aligned rows that produced them."""

    candidate: CalibrationCandidateProtocol
    direction: ScoreDirection
    rows: tuple[ScreeningBenchmarkObservation, ...]
    summary: ProtocolEvaluationSummary


class ProtocolCalibrationService:
    """Builds the frozen split, seals the Stage 1 choice, consumes Stage 2 once."""

    def __init__(self, store: CalibrationArtifactStore) -> None:
        self._store = store

    @classmethod
    def from_environment(cls, project_id: str | None = None) -> ProtocolCalibrationService:
        return cls(CalibrationArtifactStore.from_environment(project_id=project_id))

    def get_run(self, calibration_id: str) -> CalibrationRunRecord:
        return self._store.get_run(calibration_id)

    def list_runs(self) -> list[CalibrationRunRecord]:
        return self._store.list_runs()

    # -- Step 1: the frozen, scaffold-grouped split -----------------------

    def create_split(
        self,
        *,
        project_id: str,
        receptor_id: str,
        binding_site_id: str,
        compounds: Sequence[CalibrationCompoundInput],
        policy: CalibrationSplitPolicy | None = None,
        created_at: datetime | None = None,
    ) -> CalibrationRunRecord:
        """Construct and persist the split before any comparison number exists."""
        require_current_for_store(self._store, (receptor_id, binding_site_id))
        split_policy = policy if policy is not None else CalibrationSplitPolicy()
        timestamp = created_at if created_at is not None else datetime.now(UTC)
        profiles = extract_compound_properties(compounds)
        groups = _scaffold_groups(profiles)
        assignment = _assign_scaffold_groups(groups, split_policy)

        sides: dict[SplitName, list[CompoundPropertyProfile]] = {
            "calibration": [],
            "confirmation": [],
        }
        for scaffold, side in assignment.items():
            sides[side].extend(groups[scaffold])

        calibration = sides["calibration"]
        confirmation = sides["confirmation"]
        calibration_parents = tuple(sorted(item.parent_id for item in calibration))
        confirmation_parents = tuple(sorted(item.parent_id for item in confirmation))
        calibration_scaffolds = tuple(sorted({item.murcko_scaffold for item in calibration}))
        confirmation_scaffolds = tuple(sorted({item.murcko_scaffold for item in confirmation}))

        # The assignment is group-exclusive by construction; this is the
        # explicit leakage re-check the ADR asks for, not an assumption.
        if set(calibration_parents) & set(confirmation_parents) or set(
            calibration_scaffolds
        ) & set(confirmation_scaffolds):
            _invalid(
                "CALIBRATION_SPLIT_INFEASIBLE",
                "The constructed split shares a parent compound or a scaffold across sides.",
            )

        calibration_actives = sum(item.is_active for item in calibration)
        confirmation_actives = sum(item.is_active for item in confirmation)
        bias_audit = audit_physicochemical_bias(profiles)
        underpowered = confirmation_actives < split_policy.min_confirmation_actives

        split = CalibrationSplitArtifact(
            split_id=str(uuid4()),
            created_at=timestamp,
            policy=split_policy,
            calibration_parent_ids=calibration_parents,
            confirmation_parent_ids=confirmation_parents,
            calibration_scaffolds=calibration_scaffolds,
            confirmation_scaffolds=confirmation_scaffolds,
            calibration_active_count=calibration_actives,
            calibration_inactive_count=len(calibration) - calibration_actives,
            confirmation_active_count=confirmation_actives,
            confirmation_inactive_count=len(confirmation) - confirmation_actives,
            confirmation_underpowered=underpowered,
            compounds=profiles,
            bias_audit=bias_audit,
            split_identity_sha256=compute_split_identity_sha256(
                policy=split_policy,
                calibration_parent_ids=calibration_parents,
                confirmation_parent_ids=confirmation_parents,
                calibration_scaffolds=calibration_scaffolds,
                confirmation_scaffolds=confirmation_scaffolds,
                active_parent_ids=[item.parent_id for item in profiles if item.is_active],
            ),
        )

        warnings: list[StructuredWarning] = []
        if underpowered:
            warnings.append(
                StructuredWarning(
                    code=WarningCode.CALIBRATION_CONFIRMATION_UNDERPOWERED,
                    stage=_STAGE,
                    message=(
                        "The locked confirmation split holds fewer actives than the recorded "
                        "minimum, so a null verdict there is expected rather than informative."
                    ),
                    details={
                        "confirmation_active_count": confirmation_actives,
                        "min_confirmation_actives": split_policy.min_confirmation_actives,
                    },
                )
            )
        if bias_audit.any_bias_flagged:
            warnings.append(
                StructuredWarning(
                    code=WarningCode.CALIBRATION_DECOY_PROPERTY_BIAS,
                    stage=_STAGE,
                    message=(
                        "Actives and inactives separate on plain physicochemical properties, "
                        "so enrichment on this set partly measures property discrimination."
                    ),
                    details={"flagged_properties": list(bias_audit.flagged_properties)},
                )
            )

        record = CalibrationRunRecord(
            calibration_id=self._store.new_calibration_id(),
            project_id=project_id,
            receptor_id=receptor_id,
            binding_site_id=binding_site_id,
            created_at=timestamp,
            status="split_locked",
            confirmation_locked=True,
            confirmation_consumed=False,
            split=split,
            warnings=tuple(warnings),
            provenance=(
                _provenance_event(
                    "protocol_calibration_split_locked",
                    timestamp=timestamp,
                    parameters={
                        "grouping_strategy": split_policy.grouping_strategy.value,
                        "calibration_fraction": split_policy.calibration_fraction,
                        "split_seed": split_policy.split_seed,
                        "scaffold_group_count": len(groups),
                        "split_identity_sha256": split.split_identity_sha256,
                    },
                    warnings=warnings,
                ),
            ),
        )
        return self._store.create_run(record)

    # -- Step 2: the sealed Calibration decision --------------------------

    def select_protocol_on_calibration(
        self,
        *,
        calibration_id: str,
        baseline_protocol_id: str,
        candidates: Sequence[CalibrationCandidateProtocol],
        observations_by_protocol: Mapping[str, Sequence[ScoreObservation]],
        selected_at: datetime | None = None,
    ) -> CalibrationRunRecord:
        """Choose a protocol on Calibration alone and seal the decision."""
        run = self._store.get_run(calibration_id)
        require_current_for_store(
            self._store, (calibration_id, run.receptor_id, run.binding_site_id)
        )
        if run.status != "split_locked":
            _invalid(
                "CALIBRATION_SELECTION_ALREADY_SEALED",
                "The calibration selection is already sealed and cannot be chosen again.",
                status_code=409,
                details={"calibration_id": calibration_id, "status": run.status},
            )
        by_id = _validated_candidates(
            candidates=candidates,
            baseline_protocol_id=baseline_protocol_id,
            observations_by_protocol=observations_by_protocol,
        )

        timestamp = selected_at if selected_at is not None else datetime.now(UTC)
        policy = run.split.policy
        evaluated = [
            self._evaluate(
                candidate=by_id[protocol_id],
                observations=observations_by_protocol[protocol_id],
                split_name="calibration",
                run=run,
            )
            for protocol_id in sorted(by_id)
        ]

        best = min(
            evaluated,
            key=lambda item: (-item.summary.metrics.bedroc, item.candidate.parsimony_rank_key),
        )
        baseline = next(
            item for item in evaluated if item.candidate.protocol_id == baseline_protocol_id
        )
        deltas_vs_best = tuple(
            _paired_delta(item, best, split_name="calibration", policy=policy)
            for item in evaluated
        )
        deltas_vs_baseline = tuple(
            _paired_delta(item, baseline, split_name="calibration", policy=policy)
            for item in evaluated
        )

        # `1-SE` parsimony: anything the paired bootstrap cannot separate from
        # the best point estimate is admissible, and the simplest admissible
        # protocol wins.  The best protocol is always admissible against
        # itself, so this selection is never empty.
        admissible = [
            item
            for item, delta in zip(evaluated, deltas_vs_best, strict=True)
            if delta.within_one_se_of_reference
        ]
        selected = min(admissible, key=lambda item: item.candidate.parsimony_rank_key)

        evaluations = tuple(item.summary for item in evaluated)
        selection = CalibrationSelectionRecord(
            selected_at=timestamp,
            split_identity_sha256=run.split.split_identity_sha256,
            baseline_protocol_id=baseline_protocol_id,
            best_point_protocol_id=best.candidate.protocol_id,
            selected_protocol_id=selected.candidate.protocol_id,
            selected_by_one_se_parsimony=(
                selected.candidate.protocol_id != best.candidate.protocol_id
            ),
            evaluations=evaluations,
            deltas_vs_best=deltas_vs_best,
            deltas_vs_baseline=deltas_vs_baseline,
            selection_identity_sha256=compute_selection_identity_sha256(
                schema_version=1,
                selected_at=timestamp,
                split_identity_sha256=run.split.split_identity_sha256,
                baseline_protocol_id=baseline_protocol_id,
                best_point_protocol_id=best.candidate.protocol_id,
                selected_protocol_id=selected.candidate.protocol_id,
                selected_by_one_se_parsimony=(
                    selected.candidate.protocol_id != best.candidate.protocol_id
                ),
                evaluations=evaluations,
                deltas_vs_best=deltas_vs_best,
                deltas_vs_baseline=deltas_vs_baseline,
            ),
        )

        warnings = list(run.warnings)
        caution = _small_sample_warning(evaluations, split_name="calibration")
        if caution is not None:
            warnings.append(caution)

        updated = run.model_copy(
            update={
                "status": "calibration_selected",
                "baseline_protocol_id": baseline_protocol_id,
                "candidates": tuple(by_id[protocol_id] for protocol_id in sorted(by_id)),
                "calibration_selection": selection,
                "warnings": tuple(warnings),
                "provenance": (
                    *run.provenance,
                    _provenance_event(
                        "protocol_calibration_selection_sealed",
                        timestamp=timestamp,
                        parameters={
                            "baseline_protocol_id": baseline_protocol_id,
                            "best_point_protocol_id": best.candidate.protocol_id,
                            "selected_protocol_id": selected.candidate.protocol_id,
                            "selection_identity_sha256": selection.selection_identity_sha256,
                        },
                        warnings=[] if caution is None else [caution],
                    ),
                ),
            }
        )
        # `model_copy` bypasses validation, so the sealed record is re-validated
        # before it is written.
        validated = CalibrationRunRecord.model_validate(updated.model_dump())
        return self._store.save_selection(calibration_id, validated, selection)

    # -- Step 3: the single-use Confirmation unlock ------------------------

    def evaluate_locked_confirmation(
        self,
        *,
        calibration_id: str,
        observations_by_protocol: Mapping[str, Sequence[ScoreObservation]],
        evaluated_at: datetime | None = None,
    ) -> CalibrationRunRecord:
        """Unlock, evaluate, and permanently consume the Confirmation split."""
        run = self._store.get_run(calibration_id)
        require_current_for_store(
            self._store, (calibration_id, run.receptor_id, run.binding_site_id)
        )
        if run.status == "split_locked":
            _invalid(
                "CALIBRATION_SELECTION_REQUIRED",
                "The confirmation split cannot be read before the calibration choice is sealed.",
                status_code=409,
                details={"calibration_id": calibration_id, "status": run.status},
            )
        if run.confirmation_consumed or run.status == "confirmation_completed":
            _invalid(
                "CALIBRATION_CONFIRMATION_ALREADY_CONSUMED",
                "The locked confirmation split is single-use and has already been consumed.",
                status_code=409,
                details={"calibration_id": calibration_id, "status": run.status},
            )

        selection = run.calibration_selection
        baseline_protocol_id = run.baseline_protocol_id
        if selection is None or baseline_protocol_id is None:
            _invalid(
                "CALIBRATION_SELECTION_REQUIRED",
                "The confirmation split cannot be read before the calibration choice is sealed.",
                status_code=409,
                details={"calibration_id": calibration_id, "status": run.status},
            )
        _verify_sealed_identities(run.split, selection)

        selected_protocol_id = selection.selected_protocol_id
        candidates = run.candidates_by_id()
        required = {selected_protocol_id, baseline_protocol_id}
        missing = sorted(required - set(observations_by_protocol))
        if missing:
            _invalid(
                "CALIBRATION_OBSERVATIONS_REQUIRED",
                "Confirmation needs observations for the selected protocol and the baseline.",
                details={"missing_protocol_ids": missing},
            )

        timestamp = evaluated_at if evaluated_at is not None else datetime.now(UTC)
        policy = run.split.policy
        selected = self._evaluate(
            candidate=candidates[selected_protocol_id],
            observations=observations_by_protocol[selected_protocol_id],
            split_name="confirmation",
            run=run,
        )
        baseline = (
            selected
            if selected_protocol_id == baseline_protocol_id
            else self._evaluate(
                candidate=candidates[baseline_protocol_id],
                observations=observations_by_protocol[baseline_protocol_id],
                split_name="confirmation",
                run=run,
            )
        )
        # Every other candidate with supplied observations is evaluated too, so
        # a null or unfavorable outcome is published rather than discarded.
        audit = tuple(
            self._evaluate(
                candidate=candidates[protocol_id],
                observations=observations_by_protocol[protocol_id],
                split_name="confirmation",
                run=run,
            ).summary
            for protocol_id in sorted(set(observations_by_protocol) & set(candidates) - required)
        )

        paired_delta = _paired_delta(selected, baseline, split_name="confirmation", policy=policy)
        verdict, verdict_text = _confirmation_verdict(
            selected_protocol_id=selected_protocol_id,
            baseline_protocol_id=baseline_protocol_id,
            selected_by_one_se_parsimony=selection.selected_by_one_se_parsimony,
            paired_delta=paired_delta,
            confirmation_underpowered=run.split.confirmation_underpowered,
        )

        confirmation = ConfirmationEvaluationRecord(
            evaluated_at=timestamp,
            split_identity_sha256=run.split.split_identity_sha256,
            selection_identity_sha256=selection.selection_identity_sha256,
            baseline_protocol_id=baseline_protocol_id,
            selected_protocol_id=selected_protocol_id,
            verdict=verdict,
            verdict_text=verdict_text,
            selected_evaluation=selected.summary,
            baseline_evaluation=baseline.summary,
            paired_delta_vs_baseline=paired_delta,
            all_candidate_audit_evaluations=audit,
            confirmation_identity_sha256=compute_confirmation_identity_sha256(
                schema_version=1,
                evaluated_at=timestamp,
                split_identity_sha256=run.split.split_identity_sha256,
                selection_identity_sha256=selection.selection_identity_sha256,
                baseline_protocol_id=baseline_protocol_id,
                selected_protocol_id=selected_protocol_id,
                verdict=verdict,
                verdict_text=verdict_text,
                selected_evaluation=selected.summary,
                baseline_evaluation=baseline.summary,
                paired_delta_vs_baseline=paired_delta,
                all_candidate_audit_evaluations=audit,
            ),
        )

        warnings = list(run.warnings)
        caution = _small_sample_warning(
            (selected.summary, baseline.summary, *audit), split_name="confirmation"
        )
        if caution is not None:
            warnings.append(caution)

        updated = run.model_copy(
            update={
                "status": "confirmation_completed",
                "confirmation_locked": False,
                "confirmation_consumed": True,
                "confirmation_evaluation": confirmation,
                "warnings": tuple(warnings),
                "provenance": (
                    *run.provenance,
                    _provenance_event(
                        "protocol_calibration_confirmation_consumed",
                        timestamp=timestamp,
                        parameters={
                            "verdict": verdict.value,
                            "verdict_text": verdict_text,
                            "point_delta_bedroc": paired_delta.point_delta,
                            "ci_lower": paired_delta.ci_lower,
                            "ci_upper": paired_delta.ci_upper,
                            "confirmation_identity_sha256": (
                                confirmation.confirmation_identity_sha256
                            ),
                        },
                        warnings=[] if caution is None else [caution],
                    ),
                ),
            }
        )
        validated = CalibrationRunRecord.model_validate(updated.model_dump())
        return self._store.save_confirmation(calibration_id, validated, confirmation)

    # -- Shared evaluation -------------------------------------------------

    def _evaluate(
        self,
        *,
        candidate: CalibrationCandidateProtocol,
        observations: Sequence[ScoreObservation],
        split_name: SplitName,
        run: CalibrationRunRecord,
    ) -> _Evaluated:
        split = run.split
        policy = split.policy
        direction = score_direction_for(candidate)
        rows, census = observations_for_split(
            candidate=candidate,
            observations=observations,
            split_parent_ids=split.parent_ids_for(split_name),
            active_parent_ids=split.active_parent_ids,
        )
        metrics = evaluate_target(
            f"{run.calibration_id}:{split_name}:{candidate.protocol_id}",
            rows,
            score_direction=direction,
            top_fraction=policy.top_fraction,
            bedroc_alpha=policy.bedroc_alpha,
        )
        lower, upper, standard_error = _bedroc_interval(rows, direction=direction, policy=policy)
        summary = ProtocolEvaluationSummary(
            protocol_id=candidate.protocol_id,
            protocol_identity_sha256=candidate.protocol_spec.protocol_identity_sha256,
            label=candidate.label,
            split_name=split_name,
            metrics=metrics,
            bedroc_ci_lower=lower,
            bedroc_ci_upper=upper,
            bedroc_bootstrap_se=standard_error,
            ef_small_sample_caution=_ef_caution(metrics),
            failure_census=census,
        )
        return _Evaluated(
            candidate=candidate, direction=direction, rows=rows, summary=summary
        )


def _scaffold_groups(
    profiles: Sequence[CompoundPropertyProfile],
) -> dict[str, list[CompoundPropertyProfile]]:
    """Group parents by Bemis-Murcko scaffold and reject infeasible label layouts."""
    groups: dict[str, list[CompoundPropertyProfile]] = {}
    for profile in profiles:
        groups.setdefault(profile.murcko_scaffold, []).append(profile)

    active_groups = [
        scaffold
        for scaffold, members in groups.items()
        if any(member.is_active for member in members)
    ]
    inactive_groups = [
        scaffold
        for scaffold, members in groups.items()
        if any(not member.is_active for member in members)
    ]
    actives = sum(profile.is_active for profile in profiles)
    inactives = len(profiles) - actives
    # Both sides must end up with both classes.  With every active inside one
    # scaffold group that is impossible without leaking the group, so the
    # split is refused rather than silently relaxed.
    if actives < 2 or inactives < 2 or len(active_groups) < 2 or len(inactive_groups) < 2:
        _invalid(
            "CALIBRATION_SPLIT_INFEASIBLE",
            "A leakage-free split needs actives and inactives spread over at least two "
            "Bemis-Murcko scaffold groups each.",
            details={
                "active_count": actives,
                "inactive_count": inactives,
                "scaffold_group_count": len(groups),
                "active_scaffold_group_count": len(active_groups),
                "inactive_scaffold_group_count": len(inactive_groups),
            },
        )
    return groups


def _assign_scaffold_groups(
    groups: Mapping[str, list[CompoundPropertyProfile]], policy: CalibrationSplitPolicy
) -> dict[str, SplitName]:
    """Assign whole scaffold groups to one side each, deterministically.

    Groups are ordered by active count, then size, then a seeded hash of the
    scaffold, so a permutation of the input compound list can never change the
    split.  Two phases follow: both sides are first seeded so each is
    guaranteed one active and one inactive, then the remaining groups are
    assigned greedily to whichever side leaves the running active share and
    total share closer to `calibration_fraction`.
    """
    total_parents = sum(len(members) for members in groups.values())
    total_actives = sum(
        sum(member.is_active for member in members) for members in groups.values()
    )

    def order_key(scaffold: str) -> tuple[int, int, str]:
        members = groups[scaffold]
        digest = sha256(f"{policy.split_seed}:{scaffold}".encode()).hexdigest()
        return (-sum(member.is_active for member in members), -len(members), digest)

    ordered = sorted(groups, key=order_key)
    assignment: dict[str, SplitName] = {}
    both_sides: tuple[SplitName, SplitName] = ("calibration", "confirmation")

    active_seeds = [
        scaffold for scaffold in ordered if any(member.is_active for member in groups[scaffold])
    ][:2]
    assignment[active_seeds[0]] = "calibration"
    assignment[active_seeds[1]] = "confirmation"

    for side in both_sides:
        if any(
            not member.is_active
            for scaffold, assigned in assignment.items()
            if assigned == side
            for member in groups[scaffold]
        ):
            continue
        filler = next(
            (
                scaffold
                for scaffold in ordered
                if scaffold not in assignment
                and any(not member.is_active for member in groups[scaffold])
            ),
            None,
        )
        if filler is None:
            _invalid(
                "CALIBRATION_SPLIT_INFEASIBLE",
                "No remaining scaffold group can give both sides an inactive compound.",
                details={"side": side},
            )
        assignment[filler] = side

    calibration_actives = sum(
        sum(member.is_active for member in groups[scaffold])
        for scaffold, side in assignment.items()
        if side == "calibration"
    )
    calibration_total = sum(
        len(groups[scaffold]) for scaffold, side in assignment.items() if side == "calibration"
    )

    def deviation(actives: int, parents: int) -> float:
        return abs(actives / total_actives - policy.calibration_fraction) + abs(
            parents / total_parents - policy.calibration_fraction
        )

    for scaffold in ordered:
        if scaffold in assignment:
            continue
        members = groups[scaffold]
        group_actives = sum(member.is_active for member in members)
        if deviation(
            calibration_actives + group_actives, calibration_total + len(members)
        ) <= deviation(calibration_actives, calibration_total):
            assignment[scaffold] = "calibration"
            calibration_actives += group_actives
            calibration_total += len(members)
        else:
            assignment[scaffold] = "confirmation"
    return assignment


def _validated_candidates(
    *,
    candidates: Sequence[CalibrationCandidateProtocol],
    baseline_protocol_id: str,
    observations_by_protocol: Mapping[str, Sequence[ScoreObservation]],
) -> dict[str, CalibrationCandidateProtocol]:
    if not candidates:
        _invalid(
            "CALIBRATION_CANDIDATES_REQUIRED",
            "A calibration selection needs at least one pre-declared candidate protocol.",
        )
    by_id = {candidate.protocol_id: candidate for candidate in candidates}
    if len(by_id) != len(candidates):
        _invalid(
            "CALIBRATION_DUPLICATE_CANDIDATE",
            "Candidate protocol identifiers must be unique.",
        )
    if baseline_protocol_id not in by_id:
        _invalid(
            "CALIBRATION_BASELINE_NOT_A_CANDIDATE",
            "The baseline protocol must be one of the candidate protocols.",
            details={"baseline_protocol_id": baseline_protocol_id},
        )
    missing = sorted(set(by_id) - set(observations_by_protocol))
    if missing:
        _invalid(
            "CALIBRATION_OBSERVATIONS_REQUIRED",
            "Every candidate protocol needs its own supplied observations.",
            details={"missing_protocol_ids": missing},
        )
    return by_id


def _bedroc_interval(
    rows: Sequence[ScreeningBenchmarkObservation],
    *,
    direction: ScoreDirection,
    policy: CalibrationSplitPolicy,
) -> tuple[float, float, float]:
    """Stratified parent-bootstrap interval and standard error for one protocol."""
    active_indices, inactive_indices = _class_indices(rows)
    generator = Random(policy.bootstrap_seed)
    samples = [
        _replicate_bedroc(
            [
                rows[index]
                for index in _stratified_parent_picks(
                    generator, active_indices, inactive_indices
                )
            ],
            direction=direction,
            alpha=policy.bedroc_alpha,
            active_count=len(active_indices),
        )
        for _ in range(policy.bootstrap_replicates)
    ]
    tail = (1 - policy.confidence_level) / 2
    return (
        interpolated_quantile(samples, tail),
        interpolated_quantile(samples, 1 - tail),
        _sample_standard_error(samples),
    )


def _paired_delta(
    candidate: _Evaluated,
    reference: _Evaluated,
    *,
    split_name: SplitName,
    policy: CalibrationSplitPolicy,
) -> PairedBootstrapDelta:
    return paired_parent_bootstrap_delta(
        candidate_protocol_id=candidate.candidate.protocol_id,
        reference_protocol_id=reference.candidate.protocol_id,
        split_name=split_name,
        candidate_observations=candidate.rows,
        reference_observations=reference.rows,
        candidate_direction=candidate.direction,
        reference_direction=reference.direction,
        policy=policy,
    )


def _ef_caution(metrics: ScreeningTargetMetrics) -> bool:
    return (
        metrics.top_count < EF_CAUTION_MIN_TOP_COUNT
        or metrics.active_count < EF_CAUTION_MIN_ACTIVE_COUNT
    )


def _small_sample_warning(
    evaluations: Sequence[ProtocolEvaluationSummary], *, split_name: SplitName
) -> StructuredWarning | None:
    flagged = sorted(
        {item.protocol_id for item in evaluations if item.ef_small_sample_caution}
    )
    if not flagged:
        return None
    return StructuredWarning(
        code=WarningCode.CALIBRATION_SMALL_SAMPLE_EF_CAUTION,
        stage=_STAGE,
        message=(
            "The enrichment factor rests on few top-ranked parents or few actives, so it "
            "moves in large discrete steps and should be read with its interval."
        ),
        details={"split_name": split_name, "protocol_ids": flagged},
    )


def _confirmation_verdict(
    *,
    selected_protocol_id: str,
    baseline_protocol_id: str,
    selected_by_one_se_parsimony: bool,
    paired_delta: PairedBootstrapDelta,
    confirmation_underpowered: bool,
) -> tuple[ConfirmationVerdict, str]:
    """Return the recorded verdict; a null outcome is first-class, not a failure."""
    if selected_protocol_id == baseline_protocol_id:
        if selected_by_one_se_parsimony:
            return ConfirmationVerdict.BASELINE_RETAINED_BY_ONE_SE, BASELINE_RETAINED_TEXT
        return ConfirmationVerdict.INSUFFICIENT_EVIDENCE, INSUFFICIENT_EVIDENCE_TEXT
    if paired_delta.excludes_zero_positively and not confirmation_underpowered:
        return (
            ConfirmationVerdict.PREFERRED_OVER_BASELINE,
            f"Selected protocol {selected_protocol_id} outperforms baseline on locked "
            "confirmation (paired delta BEDROC_20 95% CI excludes zero).",
        )
    return ConfirmationVerdict.INSUFFICIENT_EVIDENCE, INSUFFICIENT_EVIDENCE_TEXT


def _verify_sealed_identities(
    split: CalibrationSplitArtifact, selection: CalibrationSelectionRecord
) -> None:
    """Recompute both seals before the Confirmation split is opened."""
    expected_split = compute_split_identity_sha256(
        policy=split.policy,
        calibration_parent_ids=split.calibration_parent_ids,
        confirmation_parent_ids=split.confirmation_parent_ids,
        calibration_scaffolds=split.calibration_scaffolds,
        confirmation_scaffolds=split.confirmation_scaffolds,
        active_parent_ids=sorted(split.active_parent_ids),
    )
    if split.split_identity_sha256 != expected_split:
        _invalid(
            "CALIBRATION_SPLIT_IDENTITY_MISMATCH",
            "The recorded split no longer matches its sealed identity hash.",
            status_code=409,
            details={"split_id": split.split_id},
        )
    expected_selection = compute_selection_identity_sha256(
        schema_version=selection.schema_version,
        selected_at=selection.selected_at,
        split_identity_sha256=selection.split_identity_sha256,
        baseline_protocol_id=selection.baseline_protocol_id,
        best_point_protocol_id=selection.best_point_protocol_id,
        selected_protocol_id=selection.selected_protocol_id,
        selected_by_one_se_parsimony=selection.selected_by_one_se_parsimony,
        evaluations=selection.evaluations,
        deltas_vs_best=selection.deltas_vs_best,
        deltas_vs_baseline=selection.deltas_vs_baseline,
    )
    if selection.selection_identity_sha256 != expected_selection:
        _invalid(
            "CALIBRATION_SELECTION_IDENTITY_MISMATCH",
            "The sealed calibration selection no longer matches its identity hash.",
            status_code=409,
            details={"split_id": split.split_id},
        )
    if selection.split_identity_sha256 != split.split_identity_sha256:
        _invalid(
            "CALIBRATION_SPLIT_IDENTITY_MISMATCH",
            "The sealed calibration selection was made against a different split.",
            status_code=409,
            details={"split_id": split.split_id},
        )


def _provenance_event(
    event_type: str,
    *,
    timestamp: datetime,
    parameters: dict[str, object],
    warnings: Sequence[StructuredWarning],
) -> ProvenanceEvent:
    return ProvenanceEvent(
        event_id=str(uuid4()),
        event_type=event_type,
        timestamp=timestamp,
        tool=ToolIdentity(name=_TOOL_NAME, version=__version__),
        parameters=parameters,
        warnings=list(warnings),
    )


__all__ = [
    "MISSING_OBSERVATION_FAILURE_CODE",
    "ProtocolCalibrationService",
    "audit_physicochemical_bias",
    "extract_compound_properties",
    "observations_for_split",
    "paired_parent_bootstrap_delta",
    "score_direction_for",
]
