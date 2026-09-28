"""Compute and verify preregistered metrics from one closed Vina campaign.

The source campaign is already immutable, path-free evidence.  This module
never docks, repairs, filters, or selects molecules.  It maps every frozen
parent to exactly one ranking observation and retains all unscored outcomes as
the single worst tie defined before results were seen.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from ankora_backend.schemas.screening_benchmark import (
    ScoreDirection,
    ScreeningBenchmarkObservation,
)
from ankora_backend.services.screening_benchmark import (
    BOOTSTRAP_METHOD,
    DEFAULT_BEDROC_ALPHA,
    DEFAULT_BOOTSTRAP_REPLICATES,
    DEFAULT_BOOTSTRAP_SEED,
    DEFAULT_CONFIDENCE_LEVEL,
    DEFAULT_TOP_FRACTION,
    FAILURE_POLICY,
    PERCENTILE_METHOD,
    PR_AUC_DEFINITION,
    TIE_POLICY,
    bootstrap_benchmark,
)
from ankora_backend.validation.screening_benchmark_vina_execution import (
    verify_vina_campaign_manifest,
)

SCHEMA_VERSION = 1
RESULT_STATUS = "primary_vina_metrics_complete_sensitivity_not_executed"
AGGREGATE_POLICY = "equal-target macro average"
TOP_COUNT_ROUNDING = "ceil"


class ScreeningBenchmarkPrimaryMetricsError(ValueError):
    """Raised when metric evidence differs from the frozen primary boundary."""


def create_primary_metrics_manifest(
    *,
    primary_result_path: Path,
    primary_plan_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Create one deterministic metric manifest without modifying its source."""

    source = verify_vina_campaign_manifest(
        primary_result_path,
        plan_manifest_path=primary_plan_path,
    )
    manifest = compute_primary_metrics(source)
    serialized = _serialized(manifest)
    if output_path.exists():
        if output_path.read_bytes() != serialized:
            raise ScreeningBenchmarkPrimaryMetricsError(
                "The primary metric manifest already exists with different bytes."
            )
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(serialized)
    return verify_primary_metrics_manifest(
        output_path,
        primary_result_path=primary_result_path,
        primary_plan_path=primary_plan_path,
    )


def verify_primary_metrics_manifest(
    path: Path,
    *,
    primary_result_path: Path,
    primary_plan_path: Path,
) -> dict[str, Any]:
    """Recompute every estimate and reject any metric or identity drift."""

    recorded = _load_object(path, "primary metric manifest")
    if recorded.get("schema_version") != SCHEMA_VERSION:
        raise ScreeningBenchmarkPrimaryMetricsError(
            "Unsupported primary metric manifest schema."
        )
    recorded_sha256 = _required_sha256(recorded, "manifest_sha256")
    unsigned = dict(recorded)
    unsigned.pop("manifest_sha256")
    if _digest(unsigned) != recorded_sha256:
        raise ScreeningBenchmarkPrimaryMetricsError(
            "The primary metric manifest differs from its SHA-256."
        )

    source = verify_vina_campaign_manifest(
        primary_result_path,
        plan_manifest_path=primary_plan_path,
    )
    expected = compute_primary_metrics(source)
    if recorded != expected:
        raise ScreeningBenchmarkPrimaryMetricsError(
            "The primary metrics do not reproduce from the exact Vina result manifest."
        )
    return recorded


def compute_primary_metrics(source: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic point estimates and parent-bootstrap intervals."""

    protocol_id = _required_string(source, "protocol_id")
    source_manifest_sha256 = _required_sha256(source, "manifest_sha256")
    source_plan_sha256 = _required_sha256(
        source, "source_vina_campaign_plan_sha256"
    )
    if source.get("result_status") != (
        "all_primary_vina_entries_terminal_failures_retained_metrics_not_computed"
    ):
        raise ScreeningBenchmarkPrimaryMetricsError(
            "Primary metrics require the independently closed pre-metric result boundary."
        )
    policy = _required_object(source.get("execution_policy"), "execution policy")
    if (
        policy.get("failures_retained_as_unscored_worst_tie") is not True
        or policy.get("metrics_computed") is not False
    ):
        raise ScreeningBenchmarkPrimaryMetricsError(
            "The source campaign does not retain the preregistered loss policy."
        )

    entries = [
        _required_object(raw, "primary result entry")
        for raw in _required_list(source, "entries")
    ]
    target_order = [
        _required_string(_required_object(raw, "target census"), "target_id")
        for raw in _required_list(source, "target_census")
    ]
    if len(target_order) < 2 or len(set(target_order)) != len(target_order):
        raise ScreeningBenchmarkPrimaryMetricsError(
            "Primary metrics require distinct frozen target identifiers."
        )

    by_target: dict[str, list[ScreeningBenchmarkObservation]] = {
        target_id: [] for target_id in target_order
    }
    class_census: dict[str, Counter[str]] = {
        target_id: Counter() for target_id in target_order
    }
    unscored_class_census: dict[str, Counter[str]] = {
        target_id: Counter() for target_id in target_order
    }
    failure_codes: Counter[str] = Counter()
    for entry in entries:
        target_id = _required_string(entry, "target_id")
        if target_id not in by_target:
            raise ScreeningBenchmarkPrimaryMetricsError(
                f"Primary result entry names an unknown target: {target_id}."
            )
        class_label = _required_string(entry, "class_label")
        if class_label not in {"active", "inactive"}:
            raise ScreeningBenchmarkPrimaryMetricsError(
                f"Unsupported primary class label: {class_label}."
            )
        class_census[target_id][class_label] += 1
        status = _required_string(entry, "status")
        score: float | None
        failure_code: str | None
        if status == "completed":
            score = _required_number(entry, "best_affinity_kcal_mol")
            failure_code = None
        else:
            if entry.get("best_affinity_kcal_mol") is not None:
                raise ScreeningBenchmarkPrimaryMetricsError(
                    "An unscored primary result unexpectedly carries an affinity."
                )
            error = _required_object(entry.get("error"), "primary result error")
            failure_code = _required_string(error, "code")
            score = None
            unscored_class_census[target_id][class_label] += 1
            failure_codes[failure_code] += 1
        by_target[target_id].append(
            ScreeningBenchmarkObservation(
                parent_id=_required_sha256(
                    entry, "canonical_isomeric_smiles_sha256"
                ),
                is_active=class_label == "active",
                score=score,
                state_id=_required_sha256(entry, "source_smiles_sha256"),
                failure_code=failure_code,
            )
        )

    estimate = bootstrap_benchmark(
        [(target_id, by_target[target_id]) for target_id in target_order],
        score_direction=ScoreDirection.LOWER_IS_BETTER,
        top_fraction=DEFAULT_TOP_FRACTION,
        bedroc_alpha=DEFAULT_BEDROC_ALPHA,
        replicates=DEFAULT_BOOTSTRAP_REPLICATES,
        seed=DEFAULT_BOOTSTRAP_SEED,
        confidence_level=DEFAULT_CONFIDENCE_LEVEL,
    )
    source_census = _required_object(source.get("campaign_census"), "campaign census")
    if _required_positive_int(source_census, "requested") != len(entries):
        raise ScreeningBenchmarkPrimaryMetricsError(
            "The primary metric population differs from the source census."
        )

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": protocol_id,
        "source_primary_vina_result_manifest_sha256": source_manifest_sha256,
        "source_vina_campaign_plan_sha256": source_plan_sha256,
        "scores_seen": True,
        "metrics_computed": True,
        "sensitivity_executed": False,
        "metric_contract": {
            "score_direction": ScoreDirection.LOWER_IS_BETTER.value,
            "top_fraction": DEFAULT_TOP_FRACTION,
            "top_count_rounding": TOP_COUNT_ROUNDING,
            "bedroc_alpha": DEFAULT_BEDROC_ALPHA,
            "tie_policy": TIE_POLICY,
            "failure_policy": FAILURE_POLICY,
            "pr_auc_definition": PR_AUC_DEFINITION,
            "aggregate": AGGREGATE_POLICY,
            "bootstrap": {
                "method": BOOTSTRAP_METHOD,
                "replicates": DEFAULT_BOOTSTRAP_REPLICATES,
                "seed": DEFAULT_BOOTSTRAP_SEED,
                "confidence_level": DEFAULT_CONFIDENCE_LEVEL,
                "percentile_method": PERCENTILE_METHOD,
            },
        },
        "input_census": {
            "requested": len(entries),
            "scored": _required_nonnegative_int(source_census, "scored"),
            "unscored_worst_tie": _required_nonnegative_int(
                source_census, "unscored_worst_tie"
            ),
            "by_target_and_class": [
                {
                    "target_id": target_id,
                    "active": class_census[target_id]["active"],
                    "inactive": class_census[target_id]["inactive"],
                    "unscored_active": unscored_class_census[target_id]["active"],
                    "unscored_inactive": unscored_class_census[target_id]["inactive"],
                }
                for target_id in target_order
            ],
            "failure_codes": dict(sorted(failure_codes.items())),
        },
        "estimate": estimate.model_dump(mode="json"),
        "result_status": RESULT_STATUS,
    }
    manifest["manifest_sha256"] = _digest(manifest)
    return manifest


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScreeningBenchmarkPrimaryMetricsError(
            f"Could not read {label}: {path}."
        ) from error
    return _required_object(value, label)


def _required_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScreeningBenchmarkPrimaryMetricsError(f"{label} must be an object.")
    return value


def _required_list(value: dict[str, Any], key: str) -> list[Any]:
    item = value.get(key)
    if not isinstance(item, list):
        raise ScreeningBenchmarkPrimaryMetricsError(f"{key} must be an array.")
    return item


def _required_string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ScreeningBenchmarkPrimaryMetricsError(
            f"{key} must be a non-empty string."
        )
    return item


def _required_sha256(value: dict[str, Any], key: str) -> str:
    item = _required_string(value, key)
    if len(item) != 64 or item != item.lower() or any(
        character not in "0123456789abcdef" for character in item
    ):
        raise ScreeningBenchmarkPrimaryMetricsError(
            f"{key} must be a lowercase SHA-256."
        )
    return item


def _required_number(value: dict[str, Any], key: str) -> float:
    item = value.get(key)
    if not isinstance(item, (int, float)) or isinstance(item, bool):
        raise ScreeningBenchmarkPrimaryMetricsError(f"{key} must be numeric.")
    return float(item)


def _required_positive_int(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 1:
        raise ScreeningBenchmarkPrimaryMetricsError(
            f"{key} must be a positive integer."
        )
    return item


def _required_nonnegative_int(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise ScreeningBenchmarkPrimaryMetricsError(
            f"{key} must be a non-negative integer."
        )
    return item


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _serialized(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
