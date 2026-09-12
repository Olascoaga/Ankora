"""Synthetic ranking tests for the point-26 evaluation contract.

These rows are deliberately synthetic software fixtures.  They verify metric
arithmetic and loss accounting; they are not virtual-screening evidence.
"""

import pytest
from pydantic import ValidationError

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.screening_benchmark import (
    ScoreDirection,
    ScreeningBenchmarkObservation,
)
from ankora_backend.services.screening_benchmark import (
    DEFAULT_BEDROC_ALPHA,
    evaluate_target,
    summarize_targets,
)


def _row(index: int, active: bool, score: float | None) -> ScreeningBenchmarkObservation:
    return ScreeningBenchmarkObservation(
        parent_id=f"parent-{index}",
        state_id=f"state-{index}",
        is_active=active,
        score=score,
        failure_code=None if score is not None else "SYNTHETIC_DOCKING_FAILURE",
    )


def test_perfect_ranking_has_exact_auc_and_ef1() -> None:
    rows = [_row(index, index < 10, float(index)) for index in range(100)]

    metrics = evaluate_target("synthetic-perfect", rows)

    assert metrics.roc_auc == pytest.approx(1.0)
    assert metrics.pr_auc == pytest.approx(1.0)
    assert metrics.enrichment_factor == pytest.approx(10.0)
    assert metrics.top_count == 1
    assert metrics.expected_active_hits_at_top_fraction == pytest.approx(1.0)
    assert metrics.bedroc_alpha == DEFAULT_BEDROC_ALPHA
    assert metrics.bedroc > 0.99


def test_reverse_ranking_exposes_failure_instead_of_flattering_it() -> None:
    rows = [_row(index, index >= 90, float(index)) for index in range(100)]

    metrics = evaluate_target("synthetic-reverse", rows)

    assert metrics.roc_auc == pytest.approx(0.0)
    assert metrics.enrichment_factor == pytest.approx(0.0)
    assert metrics.pr_auc < 0.1
    assert metrics.bedroc < 0.001


def test_score_ties_are_independent_of_source_order() -> None:
    rows = [_row(index, index < 2, 0.0) for index in range(10)]

    first = evaluate_target("synthetic-tie", rows)
    second = evaluate_target("synthetic-tie", list(reversed(rows)))

    assert first == second
    assert first.roc_auc == pytest.approx(0.5)
    assert first.pr_auc == pytest.approx(0.2)
    assert first.enrichment_factor == pytest.approx(1.0)
    assert first.expected_active_hits_at_top_fraction == pytest.approx(0.2)


def test_a_tie_crossing_the_one_percent_boundary_is_fractional() -> None:
    rows = [
        _row(0, True, -8.0),
        _row(1, False, -8.0),
        *[_row(index, False, float(index)) for index in range(2, 100)],
    ]

    metrics = evaluate_target("synthetic-boundary-tie", rows)

    assert metrics.top_count == 1
    assert metrics.expected_active_hits_at_top_fraction == pytest.approx(0.5)
    assert metrics.enrichment_factor == pytest.approx(50.0)


def test_unscored_parents_remain_as_one_worst_ranked_tie() -> None:
    rows = [
        _row(0, True, -8.0),
        _row(1, False, -7.0),
        _row(2, True, None),
        _row(3, False, None),
    ]

    metrics = evaluate_target("synthetic-failures", rows, top_fraction=0.5)

    assert metrics.total_count == 4
    assert metrics.scored_count == 2
    assert metrics.failed_count == 2
    assert metrics.roc_auc == pytest.approx(0.625)
    assert metrics.enrichment_factor == pytest.approx(1.0)


def test_higher_scores_can_be_declared_more_favorable() -> None:
    rows = [_row(0, True, 10.0), _row(1, False, 1.0)]

    metrics = evaluate_target(
        "synthetic-higher", rows, score_direction=ScoreDirection.HIGHER_IS_BETTER
    )

    assert metrics.roc_auc == pytest.approx(1.0)


def test_missing_or_nonfinite_scores_are_refused() -> None:
    with pytest.raises(ValidationError, match="failure_code"):
        ScreeningBenchmarkObservation(
            parent_id="parent", state_id="state", is_active=True
        )
    with pytest.raises(ValidationError, match="finite"):
        ScreeningBenchmarkObservation(
            parent_id="parent", state_id="state", is_active=True, score=float("nan")
        )


def test_duplicate_parents_and_one_class_inputs_are_refused() -> None:
    duplicate = [_row(0, True, -8.0), _row(0, False, -7.0)]
    one_class = [_row(0, True, -8.0), _row(1, True, -7.0)]

    with pytest.raises(AnkoraDomainError, match="one ranking unit"):
        evaluate_target("synthetic-duplicate", duplicate)
    with pytest.raises(AnkoraDomainError, match="require both classes"):
        evaluate_target("synthetic-one-class", one_class)


def test_multi_target_summary_is_an_equal_target_macro_average() -> None:
    perfect = evaluate_target(
        "target-a", [_row(0, True, -8.0), _row(1, False, -7.0)]
    )
    reverse = evaluate_target(
        "target-b", [_row(2, True, -7.0), _row(3, False, -8.0)]
    )

    report = summarize_targets([perfect, reverse])

    assert report.macro.target_count == 2
    assert report.macro.roc_auc == pytest.approx(0.5)
    assert report.macro.enrichment_factor == pytest.approx(
        (perfect.enrichment_factor + reverse.enrichment_factor) / 2
    )
