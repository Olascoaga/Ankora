"""Evaluate already-produced virtual-screening rankings without hiding loss.

This module does not dock or choose protocols.  It evaluates a frozen set of
parent compounds.  Failed molecules remain in the denominator and form one
worst-ranked tie group, while equal engine scores are handled fractionally so
file order cannot change a scientific result.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from math import ceil, exp, expm1
from statistics import fmean

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.screening_benchmark import (
    ScoreDirection,
    ScreeningBenchmarkObservation,
    ScreeningBenchmarkReport,
    ScreeningMacroMetrics,
    ScreeningTargetMetrics,
)

_STAGE = "screening_benchmark"
DEFAULT_TOP_FRACTION = 0.01
DEFAULT_BEDROC_ALPHA = 20.0
TIE_POLICY = "fractional membership and expected rank within exact score ties"
FAILURE_POLICY = "unscored parents retained as one worst-ranked tie group"
PR_AUC_DEFINITION = "non-interpolated average precision at distinct score thresholds"


def evaluate_target(
    target_id: str,
    observations: Sequence[ScreeningBenchmarkObservation],
    *,
    score_direction: ScoreDirection = ScoreDirection.LOWER_IS_BETTER,
    top_fraction: float = DEFAULT_TOP_FRACTION,
    bedroc_alpha: float = DEFAULT_BEDROC_ALPHA,
) -> ScreeningTargetMetrics:
    """Evaluate one target using every frozen parent, including failures."""

    if not target_id.strip():
        _invalid("A benchmark target needs a non-empty identifier.")
    if not 0 < top_fraction <= 1:
        _invalid("The enrichment fraction must be greater than zero and at most one.")
    if bedroc_alpha <= 0:
        _invalid("BEDROC alpha must be greater than zero.")
    if len(observations) < 2:
        _invalid("A benchmark target needs at least two parent compounds.")

    parent_ids = [observation.parent_id for observation in observations]
    duplicate_ids = sorted(
        parent_id for parent_id, count in _counts(parent_ids).items() if count > 1
    )
    if duplicate_ids:
        _invalid(
            "A benchmark may contain only one ranking unit per parent compound.",
            details={"duplicate_parent_ids": duplicate_ids},
        )

    active_count = sum(observation.is_active for observation in observations)
    inactive_count = len(observations) - active_count
    if active_count == 0 or inactive_count == 0:
        _invalid(
            "ROC-AUC, PR-AUC, enrichment, and BEDROC require both classes.",
            details={"active_count": active_count, "inactive_count": inactive_count},
        )

    groups = _rank_groups(observations, score_direction)
    total_count = len(observations)
    top_count = min(total_count, ceil(total_count * top_fraction))
    hits = _fractional_top_hits(groups, top_count)
    enrichment = (hits / top_count) / (active_count / total_count)

    return ScreeningTargetMetrics(
        target_id=target_id,
        total_count=total_count,
        active_count=active_count,
        inactive_count=inactive_count,
        scored_count=sum(observation.score is not None for observation in observations),
        failed_count=sum(observation.score is None for observation in observations),
        top_fraction=top_fraction,
        top_count=top_count,
        expected_active_hits_at_top_fraction=hits,
        enrichment_factor=enrichment,
        bedroc_alpha=bedroc_alpha,
        bedroc=_bedroc(groups, total_count, active_count, bedroc_alpha),
        roc_auc=_roc_auc(groups, active_count, inactive_count),
        pr_auc=_average_precision(groups, active_count),
        score_direction=score_direction,
        tie_policy=TIE_POLICY,
        failure_policy=FAILURE_POLICY,
        pr_auc_definition=PR_AUC_DEFINITION,
    )


def summarize_targets(targets: Sequence[ScreeningTargetMetrics]) -> ScreeningBenchmarkReport:
    """Return an equal-target macro average without pooling unlike assays."""

    if len(targets) < 2:
        _invalid("A multi-target benchmark report needs at least two targets.")
    target_ids = [target.target_id for target in targets]
    duplicates = sorted(
        target_id for target_id, count in _counts(target_ids).items() if count > 1
    )
    if duplicates:
        _invalid(
            "A multi-target report cannot repeat a target.",
            details={"duplicate_target_ids": duplicates},
        )
    return ScreeningBenchmarkReport(
        targets=list(targets),
        macro=ScreeningMacroMetrics(
            target_count=len(targets),
            enrichment_factor=fmean(target.enrichment_factor for target in targets),
            bedroc=fmean(target.bedroc for target in targets),
            roc_auc=fmean(target.roc_auc for target in targets),
            pr_auc=fmean(target.pr_auc for target in targets),
        ),
    )


def _counts(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        counts[value] += 1
    return counts


def _rank_groups(
    observations: Sequence[ScreeningBenchmarkObservation],
    direction: ScoreDirection,
) -> list[tuple[int, int]]:
    scored: dict[float, list[ScreeningBenchmarkObservation]] = defaultdict(list)
    failed: list[ScreeningBenchmarkObservation] = []
    for observation in observations:
        if observation.score is None:
            failed.append(observation)
        else:
            scored[observation.score].append(observation)

    reverse = direction is ScoreDirection.HIGHER_IS_BETTER
    groups = [
        (len(scored[score]), sum(item.is_active for item in scored[score]))
        for score in sorted(scored, reverse=reverse)
    ]
    if failed:
        groups.append((len(failed), sum(item.is_active for item in failed)))
    return groups


def _fractional_top_hits(groups: Sequence[tuple[int, int]], top_count: int) -> float:
    remaining = top_count
    hits = 0.0
    for group_size, group_actives in groups:
        if remaining <= 0:
            break
        included = min(remaining, group_size)
        hits += group_actives * included / group_size
        remaining -= included
    return hits


def _roc_auc(
    groups: Sequence[tuple[int, int]], active_count: int, inactive_count: int
) -> float:
    favorable_pairs = 0.0
    inactives_seen = 0
    for group_size, group_actives in groups:
        group_inactives = group_size - group_actives
        inactives_worse = inactive_count - inactives_seen - group_inactives
        favorable_pairs += group_actives * (inactives_worse + 0.5 * group_inactives)
        inactives_seen += group_inactives
    return favorable_pairs / (active_count * inactive_count)


def _average_precision(groups: Sequence[tuple[int, int]], active_count: int) -> float:
    retrieved = 0
    true_positives = 0
    area = 0.0
    for group_size, group_actives in groups:
        retrieved += group_size
        true_positives += group_actives
        if group_actives:
            area += (group_actives / active_count) * (true_positives / retrieved)
    return area


def _bedroc(
    groups: Sequence[tuple[int, int]],
    total_count: int,
    active_count: int,
    alpha: float,
) -> float:
    rank = 1
    weighted_active_sum = 0.0
    decay = exp(-alpha / total_count)
    for group_size, group_actives in groups:
        if group_actives:
            positional_sum = (
                decay**rank * (-expm1(-alpha * group_size / total_count))
                / (-expm1(-alpha / total_count))
            )
            weighted_active_sum += (group_actives / group_size) * positional_sum
        rank += group_size

    normalization = (
        (-expm1(-alpha)) / total_count / expm1(alpha / total_count)
    )
    rie = weighted_active_sum / (active_count * normalization)
    ratio = active_count / total_count
    rie_max = (-expm1(-alpha * ratio)) / (ratio * -expm1(-alpha))
    rie_min = expm1(alpha * ratio) / (ratio * expm1(alpha))
    value = (rie - rie_min) / (rie_max - rie_min)
    return min(1.0, max(0.0, value))


def _invalid(message: str, *, details: dict[str, object] | None = None) -> None:
    raise AnkoraDomainError(
        code="SCREENING_BENCHMARK_INVALID",
        stage=_STAGE,
        message=message,
        status_code=422,
        details=details or {},
    )
