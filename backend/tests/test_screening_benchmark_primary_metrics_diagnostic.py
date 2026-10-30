"""Contracts for the cross-platform primary-metric *diagnostic* (not the strict verifier).

Synthetic cases use an explicitly SYNTHETIC campaign; their metric values carry
no scientific meaning. One read-only case runs against the real frozen evidence.
The strict verifier and its tests are untouched; a strict failure stays a failure.
"""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from ankora_backend.validation import screening_benchmark_primary_metrics as metrics
from ankora_backend.validation import screening_benchmark_primary_metrics_diagnostic as diagnostic

REFERENCE_ROOT = Path(__file__).resolve().parents[2] / "docs" / "validation" / "reference_cases"
PREFIX = "LIT_PCBA_ANKORA_VS_V1"
# SHA-256 of the frozen manifest file bytes, recorded independently in the validation note.
FROZEN_MANIFEST_FILE_SHA256 = "47397d0581dc40b355c0d773677b4743f11069ecdf6a70539af09585a5ccff44"
FROZEN_MANIFEST_SHA256 = "30da8aebc3bc601204146416c51d3a17227229b96c3efd7b41087074d6e0f873"
ULP_SCALE_DIFFERENCE = 3 * 2.0**-55  # the largest difference observed on Linux
BEDROC_POINT = ("estimate", "targets", 0, "point", "bedroc")


def _synthetic_source() -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    index = 1
    for offset, target_id in enumerate(("synthetic-a", "synthetic-b", "synthetic-c")):
        for active, score in ((True, -9.0), (True, -8.0), (False, -5.0), (False, None)):
            entries.append(
                {
                    "target_id": target_id,
                    "class_label": "active" if active else "inactive",
                    "status": "completed" if score is not None else "docking_failed",
                    "best_affinity_kcal_mol": None if score is None else score + offset,
                    "canonical_isomeric_smiles_sha256": f"{index:064x}",
                    "source_smiles_sha256": f"{index + 10_000:064x}",
                    "error": None if score is not None else {"code": "SYNTHETIC_FAILURE"},
                }
            )
            index += 1
    return {
        "protocol_id": "SYNTHETIC_DIAGNOSTIC_FIXTURE",
        "manifest_sha256": "a" * 64,
        "source_vina_campaign_plan_sha256": "b" * 64,
        "result_status": "all_primary_vina_entries_terminal_failures_retained_metrics_not_computed",
        "execution_policy": {
            "failures_retained_as_unscored_worst_tie": True,
            "metrics_computed": False,
        },
        "campaign_census": {"requested": 12, "scored": 9, "unscored_worst_tie": 3},
        "target_census": [{"target_id": f"synthetic-{name}"} for name in "abc"],
        "entries": entries,
    }


@pytest.fixture
def source(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    synthetic = _synthetic_source()
    monkeypatch.setattr(metrics, "DEFAULT_BOOTSTRAP_REPLICATES", 20)
    for module in (metrics, diagnostic):
        monkeypatch.setattr(
            module, "verify_vina_campaign_manifest", lambda *_args, **_kwargs: synthetic
        )
    return synthetic


def _set(manifest: dict[str, Any], path: tuple[Any, ...], value: Any) -> None:
    target: Any = manifest
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def _get(manifest: dict[str, Any], path: tuple[Any, ...]) -> Any:
    target: Any = manifest
    for key in path:
        target = target[key]
    return target


def _rehash(manifest: dict[str, Any]) -> dict[str, Any]:
    manifest["manifest_sha256"] = metrics._digest(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    return manifest


def _write(tmp_path: Path, manifest: dict[str, Any] | str) -> tuple[Path, str]:
    path = tmp_path / "synthetic-primary-metrics.json"
    text = manifest if isinstance(manifest, str) else json.dumps(manifest, indent=2)
    path.write_text(text, encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _diagnose(path: Path, anchor: str) -> diagnostic.PrimaryMetricsDiagnostic:
    return diagnostic.diagnose_primary_metrics_manifest(
        path,
        expected_file_sha256=anchor,
        primary_result_path=path.with_name("synthetic-results.json"),
        primary_plan_path=path.with_name("synthetic-plan.json"),
    )


def _expected(source: dict[str, Any]) -> dict[str, Any]:
    return metrics.compute_primary_metrics(deepcopy(source))


# --- Classification --------------------------------------------------------------------


def test_exact_reproduction_is_identical(tmp_path: Path, source: dict[str, Any]) -> None:
    result = _diagnose(*_write(tmp_path, _expected(source)))

    assert result.classification == "identical"
    assert result.bounded_bedroc_differences == ()
    assert result.exact_discrepancies == ()
    assert result.recomputed_manifest_sha256 == result.recorded_manifest_sha256
    assert "not strict verification" in result.scope


def test_ulp_scale_bedroc_difference_is_reported_but_strict_verification_still_fails(
    tmp_path: Path, source: dict[str, Any]
) -> None:
    manifest = _expected(source)
    original = _get(manifest, BEDROC_POINT)
    shifted = original - ULP_SCALE_DIFFERENCE
    assert shifted != original
    _set(manifest, BEDROC_POINT, shifted)
    path, anchor = _write(tmp_path, _rehash(manifest))

    result = _diagnose(path, anchor)

    assert result.classification == "bounded_bedroc_float_differences_only"
    (difference,) = result.bounded_bedroc_differences
    assert difference.path == "estimate.targets[0].point.bedroc"
    assert difference.recomputed == original
    assert difference.absolute_difference <= diagnostic.DIAGNOSTIC_BEDROC_ABSOLUTE_TOLERANCE
    assert result.recomputed_manifest_sha256 != result.recorded_manifest_sha256
    with pytest.raises(metrics.ScreeningBenchmarkPrimaryMetricsError, match="do not reproduce"):
        metrics.verify_primary_metrics_manifest(
            path, primary_result_path=path, primary_plan_path=path
        )


@pytest.mark.parametrize(
    ("leaf", "delta"),
    [
        (BEDROC_POINT, -1e-12),
        (("estimate", "macro_intervals", "bedroc", "upper"), -4 * 2.0**-52),
        (("estimate", "targets", 0, "point", "roc_auc"), -(2.0**-52)),
        (("estimate", "targets", 0, "point", "bedroc_alpha"), 2.0**-48),
        (("metric_contract", "bedroc_alpha"), 2.0**-48),
    ],
)
def test_other_or_larger_differences_are_exact_discrepancies(
    tmp_path: Path, source: dict[str, Any], leaf: tuple[Any, ...], delta: float
) -> None:
    manifest = _expected(source)
    shifted = _get(manifest, leaf) + delta
    assert shifted != _get(manifest, leaf)
    _set(manifest, leaf, shifted)
    path, anchor = _write(tmp_path, _rehash(manifest))

    result = _diagnose(path, anchor)

    assert result.classification == "exact_discrepancy"
    assert result.bounded_bedroc_differences == ()
    assert len(result.exact_discrepancies) == 1


def test_non_numeric_value_change_is_an_exact_discrepancy(
    tmp_path: Path, source: dict[str, Any]
) -> None:
    manifest = _expected(source)
    manifest["result_status"] = "synthetic_changed_status"
    path, anchor = _write(tmp_path, _rehash(manifest))

    result = _diagnose(path, anchor)

    assert result.classification == "exact_discrepancy"
    assert result.exact_discrepancies[0].startswith("result_status:")


# --- Rejections -------------------------------------------------------------------------


def test_wrong_or_malformed_anchor_is_rejected(tmp_path: Path, source: dict[str, Any]) -> None:
    path, anchor = _write(tmp_path, _expected(source))

    for wrong in ("0" * 64, anchor.upper(), anchor[:-1], ""):
        with pytest.raises(diagnostic.PrimaryMetricsDiagnosticError, match="anchor"):
            _diagnose(path, wrong)


def test_bytes_changed_after_anchoring_are_rejected(tmp_path: Path, source: dict[str, Any]) -> None:
    path, anchor = _write(tmp_path, _expected(source))
    path.write_bytes(path.read_bytes() + b" ")

    with pytest.raises(diagnostic.PrimaryMetricsDiagnosticError, match="anchor"):
        _diagnose(path, anchor)


def test_tampered_content_without_rehash_is_rejected(
    tmp_path: Path, source: dict[str, Any]
) -> None:
    manifest = _expected(source)
    _set(manifest, BEDROC_POINT, _get(manifest, BEDROC_POINT) - ULP_SCALE_DIFFERENCE)

    with pytest.raises(diagnostic.PrimaryMetricsDiagnosticError, match="recorded manifest_sha256"):
        _diagnose(*_write(tmp_path, manifest))


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_numbers_are_rejected(
    tmp_path: Path, source: dict[str, Any], value: float
) -> None:
    manifest = _expected(source)
    _set(manifest, BEDROC_POINT, value)

    with pytest.raises(diagnostic.PrimaryMetricsDiagnosticError, match="Non-finite"):
        _diagnose(*_write(tmp_path, _rehash(manifest)))


def test_non_finite_recomputation_is_rejected(
    tmp_path: Path, source: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = _expected(source)
    poisoned = deepcopy(expected)
    _set(poisoned, BEDROC_POINT, math.nan)
    monkeypatch.setattr(diagnostic, "compute_primary_metrics", lambda _source: poisoned)

    with pytest.raises(diagnostic.PrimaryMetricsDiagnosticError, match="recomputed .*non-finite"):
        _diagnose(*_write(tmp_path, expected))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda m: m["estimate"]["macro_point"].update(target_count=3.0),
            "type float differs from recomputed int",
        ),
        (
            lambda m: m["estimate"]["macro_point"].update(target_count=True),
            "type bool differs from recomputed int",
        ),
        (
            lambda m: m["estimate"]["targets"][0]["point"].update(bedroc="0.15"),
            "type str differs from recomputed float",
        ),
        (
            lambda m: m["estimate"]["macro_point"].update(synthetic_extra=1),
            r"missing fields \[\], extra fields \['synthetic_extra'\]",
        ),
        (
            lambda m: m["estimate"]["macro_point"].pop("roc_auc"),
            r"missing fields \['roc_auc'\], extra fields \[\]",
        ),
        (lambda m: m["estimate"]["targets"].pop(), "recorded items"),
        (lambda m: m.update(source_vina_campaign_plan_sha256="c" * 64), "verified source"),
    ],
)
def test_structural_and_identity_mismatches_are_rejected(
    tmp_path: Path, source: dict[str, Any], change: Any, message: str
) -> None:
    manifest = _expected(source)
    change(manifest)

    with pytest.raises(diagnostic.PrimaryMetricsDiagnosticError, match=message):
        _diagnose(*_write(tmp_path, _rehash(manifest)))


def test_duplicate_json_keys_are_rejected(tmp_path: Path, source: dict[str, Any]) -> None:
    text = json.dumps(_expected(source))
    duplicated = text.replace('"scores_seen": true', '"scores_seen": true, "scores_seen": true')
    assert duplicated != text

    with pytest.raises(diagnostic.PrimaryMetricsDiagnosticError, match="Duplicate"):
        _diagnose(*_write(tmp_path, duplicated))


def test_strict_upstream_failure_propagates(
    tmp_path: Path, source: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_args: object, **_kwargs: object) -> dict[str, Any]:
        raise metrics.ScreeningBenchmarkPrimaryMetricsError("synthetic upstream refusal")

    monkeypatch.setattr(diagnostic, "verify_vina_campaign_manifest", refuse)

    with pytest.raises(metrics.ScreeningBenchmarkPrimaryMetricsError, match="upstream refusal"):
        _diagnose(*_write(tmp_path, _expected(source)))


# --- Declared constants -----------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "estimate.targets[0].point.bedroc",
        "estimate.targets[2].intervals.bedroc.lower",
        "estimate.targets[17].intervals.bedroc.upper",
        "estimate.macro_point.bedroc",
        "estimate.macro_intervals.bedroc.lower",
        "estimate.macro_intervals.bedroc.upper",
    ],
)
def test_only_the_known_bedroc_schema_paths_are_eligible(path: str) -> None:
    assert diagnostic.is_bedroc_float_leaf(path)


@pytest.mark.parametrize(
    "path",
    [
        # Unknown containers below estimate.
        "estimate.other.bedroc",
        "estimate.bedroc",
        "estimate.targets[0].extra.bedroc",
        "estimate.targets[0].bedroc",
        "estimate.macro_point.intervals.bedroc.lower",
        "estimate.macro_intervals.bedroc",
        # Nested or misleading continuations.
        "estimate.targets[0].point.bedroc.lower",
        "estimate.targets[0].point.extra.bedroc",
        "estimate.targets[0].intervals.bedroc.lower.bedroc",
        "estimate.targets[0].intervals.extra.bedroc.lower",
        "estimate.targets[0].intervals.bedroc.middle",
        "estimate.macro_point.bedroc.upper",
        "estimate.macro_intervals.extra.bedroc.upper",
        "estimate.targets[0].point.bedroc ",
        "prefix.estimate.macro_point.bedroc",
        "estimate.macro_point.bedroc\n",
        # Malformed or negative indices.
        "estimate.targets[-1].point.bedroc",
        "estimate.targets[01].point.bedroc",
        "estimate.targets[+1].point.bedroc",
        "estimate.targets[].point.bedroc",
        "estimate.targets[a].point.bedroc",
        "estimate.targets[0][1].point.bedroc",
        "estimate.targets.0.point.bedroc",
        "estimate.targets[1.0].point.bedroc",
        # Other fields that must stay exact.
        "estimate.targets[0].point.bedroc_alpha",
        "estimate.macro_point.bedroc_alpha",
        "metric_contract.bedroc_alpha",
        "estimate.targets[0].point.roc_auc",
        "estimate.macro_intervals.roc_auc.lower",
        "bedroc",
        "input_census.bedroc",
        "",
    ],
)
def test_other_bedroc_like_paths_are_not_eligible(path: str) -> None:
    assert not diagnostic.is_bedroc_float_leaf(path)


def test_ulp_difference_at_an_unknown_bedroc_field_is_an_exact_discrepancy(
    tmp_path: Path, source: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Same misleading structure on both sides, so only the path predicate decides.
    recomputed = _expected(source)
    recomputed["estimate"]["other"] = {"bedroc": 0.25}
    recorded = deepcopy(recomputed)
    recorded["estimate"]["other"]["bedroc"] = 0.25 - ULP_SCALE_DIFFERENCE
    _rehash(recomputed)
    monkeypatch.setattr(diagnostic, "compute_primary_metrics", lambda _source: recomputed)

    result = _diagnose(*_write(tmp_path, _rehash(recorded)))

    assert result.classification == "exact_discrepancy"
    assert result.bounded_bedroc_differences == ()
    assert result.exact_discrepancies[0].startswith("estimate.other.bedroc:")


def test_tolerance_is_finite_fixed_and_above_the_observed_maximum() -> None:
    tolerance = diagnostic.DIAGNOSTIC_BEDROC_ABSOLUTE_TOLERANCE

    assert math.isfinite(tolerance) and tolerance == 2.0**-52
    assert 8.326672684688674e-17 == ULP_SCALE_DIFFERENCE < tolerance


# --- Real frozen evidence (read-only) ---------------------------------------------------


def test_frozen_evidence_diagnostic_reports_no_exact_discrepancy() -> None:
    files = {
        name: REFERENCE_ROOT / f"{PREFIX}.vina-primary-{name}.json"
        for name in ("metrics", "results", "plan")
    }
    before = {name: path.read_bytes() for name, path in files.items()}

    result = diagnostic.diagnose_primary_metrics_manifest(
        files["metrics"],
        expected_file_sha256=FROZEN_MANIFEST_FILE_SHA256,
        primary_result_path=files["results"],
        primary_plan_path=files["plan"],
    )

    assert {name: path.read_bytes() for name, path in files.items()} == before
    assert result.recorded_manifest_sha256 == FROZEN_MANIFEST_SHA256
    assert result.exact_discrepancies == ()
    assert result.classification in {"identical", "bounded_bedroc_float_differences_only"}
    assert (result.classification == "identical") == (
        result.recomputed_manifest_sha256 == FROZEN_MANIFEST_SHA256
    )
    for difference in result.bounded_bedroc_differences:
        assert diagnostic.is_bedroc_float_leaf(difference.path)
        assert 0 < difference.absolute_difference <= result.tolerance
