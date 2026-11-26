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
    BOOTSTRAP_METHOD,
    DEFAULT_BEDROC_ALPHA,
    PERCENTILE_METHOD,
    _quantile,
    bootstrap_benchmark,
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


def test_stratified_bootstrap_is_deterministic_and_records_its_method() -> None:
    target_a = [
        _row(index, index < 3, float(index % 4)) for index in range(12)
    ]
    target_b = [
        _row(index + 20, index < 4, float((11 - index) % 5)) for index in range(12)
    ]

    first = bootstrap_benchmark(
        [("target-a", target_a), ("target-b", target_b)],
        replicates=40,
        seed=71,
    )
    second = bootstrap_benchmark(
        [("target-a", target_a), ("target-b", target_b)],
        replicates=40,
        seed=71,
    )

    assert first == second
    assert first.bootstrap_replicates == 40
    assert first.bootstrap_seed == 71
    assert first.bootstrap_method == BOOTSTRAP_METHOD
    assert first.percentile_method == PERCENTILE_METHOD
    assert first.macro_point.target_count == 2


def test_perfect_rankings_have_degenerate_perfect_auc_intervals() -> None:
    first_rows = [_row(index, index < 4, float(index)) for index in range(20)]
    second_rows = [
        _row(index + 30, index < 5, float(index)) for index in range(20)
    ]

    estimate = bootstrap_benchmark(
        [("target-a", first_rows), ("target-b", second_rows)],
        replicates=25,
        seed=72,
    )

    for target in estimate.targets:
        assert target.intervals.roc_auc.lower == pytest.approx(1.0)
        assert target.intervals.roc_auc.upper == pytest.approx(1.0)
        assert target.intervals.pr_auc.lower == pytest.approx(1.0)
        assert target.intervals.pr_auc.upper == pytest.approx(1.0)
    assert estimate.macro_intervals.roc_auc.lower == pytest.approx(1.0)
    assert estimate.macro_intervals.roc_auc.upper == pytest.approx(1.0)


def test_bootstrap_rejects_invalid_sampling_contracts() -> None:
    targets = [
        ("target-a", [_row(0, True, -8.0), _row(1, False, -7.0)]),
        ("target-b", [_row(2, True, -8.0), _row(3, False, -7.0)]),
    ]

    with pytest.raises(AnkoraDomainError, match="replicate count"):
        bootstrap_benchmark(targets, replicates=0)
    with pytest.raises(AnkoraDomainError, match="confidence level"):
        bootstrap_benchmark(targets, confidence_level=1.0)


def test_d2_013_bootstrap_is_invariant_to_input_row_order_by_default() -> None:
    """Default bootstrap canonicalizes rows by parent_id so permutations match verbatim (D2-013)."""
    target_a = [_row(index, index < 4, float((index * 7) % 11)) for index in range(16)]
    target_b = [_row(index + 50, index < 5, float((index * 5) % 9)) for index in range(16)]

    forward = bootstrap_benchmark(
        [("target-a", target_a), ("target-b", target_b)],
        replicates=40,
        seed=101,
    )
    reversed_input = bootstrap_benchmark(
        [("target-a", list(reversed(target_a))), ("target-b", list(reversed(target_b)))],
        replicates=40,
        seed=101,
    )
    assert forward == reversed_input


def test_d2_022_bedroc_handles_large_alpha_without_overflow() -> None:
    """Large BEDROC alpha (e.g. 800.0) must not raise OverflowError in expm1(alpha) (D2-022)."""
    perfect = [_row(index, index < 2, float(index)) for index in range(20)]
    reverse = [_row(index, index >= 18, float(index)) for index in range(20)]

    m_perf = evaluate_target("large-alpha-perfect", perfect, bedroc_alpha=800.0)
    m_rev = evaluate_target("large-alpha-reverse", reverse, bedroc_alpha=800.0)
    assert m_perf.bedroc == pytest.approx(1.0, abs=1e-12)
    assert m_rev.bedroc == pytest.approx(0.0, abs=1e-12)


def test_d2_018_boundary_and_quantile_interpolation_oracles() -> None:
    """Boundary and quantile interpolation tests killing screening_benchmark mutants (D2-018)."""
    rows = [_row(0, True, -9.0), _row(1, False, -5.0)]
    # M01: bedroc_alpha == 0.0 must be refused (boundary_lte_to_lt)
    with pytest.raises(AnkoraDomainError):
        evaluate_target("alpha-zero", rows, bedroc_alpha=0.0)

    # M06: replicates == 1 must be accepted (boundary_lt_to_lte)
    # M07: confidence_level == 0.5 must be accepted (const_0.0_to_0.5)
    targets = [
        ("target-a", [_row(index, index < 3, float((index * 3) % 7)) for index in range(10)]),
        ("target-b", [_row(index + 20, index < 3, float((index * 5) % 7)) for index in range(10)]),
    ]
    one_rep = bootstrap_benchmark(targets, replicates=1, seed=7, confidence_level=0.5)
    assert one_rep.bootstrap_replicates == 1
    assert one_rep.confidence_level == 0.5

    # M12: _quantile weight = position - lower_index (arith_sub_to_add)
    assert _quantile([10.0, 20.0, 30.0, 40.0], 0.5) == pytest.approx(25.0, abs=1e-12)
    assert _quantile([10.0, 20.0, 30.0, 40.0], 0.95) == pytest.approx(38.5, abs=1e-12)
    four_rep = bootstrap_benchmark(targets, replicates=4, seed=13, confidence_level=0.9)
    for target in four_rep.targets:
        assert 0.0 <= target.intervals.roc_auc.lower <= target.intervals.roc_auc.upper <= 1.0
        assert 0.0 <= target.intervals.bedroc.lower <= target.intervals.bedroc.upper <= 1.0
    macro_roc = four_rep.macro_intervals.roc_auc
    assert 0.0 <= macro_roc.lower <= macro_roc.upper <= 1.0
