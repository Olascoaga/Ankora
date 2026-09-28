"""Synthetic contracts for the post-campaign primary metric boundary."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from ankora_backend.validation import screening_benchmark_primary_metrics as metrics


def _entry(
    target_id: str,
    index: int,
    *,
    active: bool,
    score: float | None,
) -> dict[str, object]:
    return {
        "target_id": target_id,
        "class_label": "active" if active else "inactive",
        "status": "completed" if score is not None else "docking_failed",
        "best_affinity_kcal_mol": score,
        "canonical_isomeric_smiles_sha256": f"{index:064x}",
        "source_smiles_sha256": f"{index + 10_000:064x}",
        "error": None
        if score is not None
        else {"code": "SYNTHETIC_FAILURE", "message": "synthetic fixture"},
    }


def _source() -> dict[str, object]:
    entries: list[dict[str, object]] = []
    target_census: list[dict[str, object]] = []
    index = 1
    for target_index, target_id in enumerate(("target-a", "target-b", "target-c")):
        target_entries = [
            _entry(target_id, index, active=True, score=-9.0 + target_index),
            _entry(target_id, index + 1, active=True, score=-8.0 + target_index),
            _entry(target_id, index + 2, active=False, score=-5.0 + target_index),
            _entry(target_id, index + 3, active=False, score=None),
        ]
        entries.extend(target_entries)
        target_census.append({"target_id": target_id})
        index += 4
    return {
        "schema_version": 1,
        "protocol_id": "SYNTHETIC_SCREENING_FIXTURE",
        "manifest_sha256": "a" * 64,
        "source_vina_campaign_plan_sha256": "b" * 64,
        "result_status": (
            "all_primary_vina_entries_terminal_failures_retained_metrics_not_computed"
        ),
        "execution_policy": {
            "failures_retained_as_unscored_worst_tie": True,
            "metrics_computed": False,
        },
        "campaign_census": {
            "requested": 12,
            "scored": 9,
            "unscored_worst_tie": 3,
        },
        "target_census": target_census,
        "entries": entries,
    }


def test_primary_metrics_are_deterministic_loss_preserving_and_macro_averaged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(metrics, "DEFAULT_BOOTSTRAP_REPLICATES", 20)
    source = _source()

    first = metrics.compute_primary_metrics(source)
    second = metrics.compute_primary_metrics(deepcopy(source))

    assert first == second
    assert first["input_census"] == {
        "requested": 12,
        "scored": 9,
        "unscored_worst_tie": 3,
        "by_target_and_class": [
            {
                "target_id": target_id,
                "active": 2,
                "inactive": 2,
                "unscored_active": 0,
                "unscored_inactive": 1,
            }
            for target_id in ("target-a", "target-b", "target-c")
        ],
        "failure_codes": {"SYNTHETIC_FAILURE": 3},
    }
    assert first["metric_contract"]["failure_policy"] == (
        "unscored parents retained as one worst-ranked tie group"
    )
    assert first["estimate"]["macro_point"]["target_count"] == 3
    assert first["result_status"] == (
        "primary_vina_metrics_complete_sensitivity_not_executed"
    )


def test_primary_metric_manifest_is_create_only_and_recomputes_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source()
    monkeypatch.setattr(metrics, "DEFAULT_BOOTSTRAP_REPLICATES", 20)
    monkeypatch.setattr(
        metrics, "verify_vina_campaign_manifest", lambda *_args, **_kwargs: source
    )
    output = tmp_path / "primary-metrics.json"

    created = metrics.create_primary_metrics_manifest(
        primary_result_path=tmp_path / "primary-results.json",
        primary_plan_path=tmp_path / "primary-plan.json",
        output_path=output,
    )
    original = output.read_bytes()
    repeated = metrics.create_primary_metrics_manifest(
        primary_result_path=tmp_path / "primary-results.json",
        primary_plan_path=tmp_path / "primary-plan.json",
        output_path=output,
    )

    assert created == repeated
    assert output.read_bytes() == original
    assert str(tmp_path) not in output.read_text(encoding="utf-8")


def test_primary_metric_verifier_rejects_rehashed_metric_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source()
    monkeypatch.setattr(metrics, "DEFAULT_BOOTSTRAP_REPLICATES", 20)
    monkeypatch.setattr(
        metrics, "verify_vina_campaign_manifest", lambda *_args, **_kwargs: source
    )
    output = tmp_path / "primary-metrics.json"
    manifest = metrics.compute_primary_metrics(source)
    manifest["estimate"]["macro_point"]["roc_auc"] = 0.123
    unsigned = dict(manifest)
    unsigned.pop("manifest_sha256")
    manifest["manifest_sha256"] = metrics._digest(unsigned)
    output.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(
        metrics.ScreeningBenchmarkPrimaryMetricsError,
        match="do not reproduce",
    ):
        metrics.verify_primary_metrics_manifest(
            output,
            primary_result_path=tmp_path / "primary-results.json",
            primary_plan_path=tmp_path / "primary-plan.json",
        )
