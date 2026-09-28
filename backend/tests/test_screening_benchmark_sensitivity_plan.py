"""Recorded contracts for the frozen LIT-PCBA sensitivity plan."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ankora_backend.validation.screening_benchmark_sensitivity_plan import (
    ScreeningBenchmarkSensitivityPlanError,
    build_sensitivity_plan,
    serialize_sensitivity_plan,
    verify_sensitivity_plan,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_ROOT = PROJECT_ROOT / "docs" / "validation" / "reference_cases"
PREFIX = "LIT_PCBA_ANKORA_VS_V1"
PATHS = {
    "spec_path": REFERENCE_ROOT / f"{PREFIX}.spec.json",
    "geometry_manifest_path": REFERENCE_ROOT / f"{PREFIX}.geometry-sentinels.json",
    "final_receptor_manifest_path": REFERENCE_ROOT / f"{PREFIX}.final-receptors.json",
    "primary_plan_path": REFERENCE_ROOT / f"{PREFIX}.vina-primary-plan.json",
    "primary_result_path": REFERENCE_ROOT / f"{PREFIX}.vina-primary-results.json",
    "primary_metrics_path": REFERENCE_ROOT / f"{PREFIX}.vina-primary-metrics.json",
    "microstate_schema_path": (PROJECT_ROOT / "backend/src/ankora_backend/schemas/ligands.py"),
    "microstate_service_path": (
        PROJECT_ROOT / "backend/src/ankora_backend/services/ligand_microstates.py"
    ),
}
RECORDED_PLAN = REFERENCE_ROOT / f"{PREFIX}.vina-sensitivity-plan.json"


def _digest(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def test_sensitivity_plan_is_deterministic_and_loss_preserving() -> None:
    first = build_sensitivity_plan(**PATHS)
    second = build_sensitivity_plan(**PATHS)

    assert first == second
    assert first["cohorts"] == {
        "full_primary_parent_population": {
            "source_parents": 11412,
            "prepared_for_docking": 11302,
            "retained_unscored_worst_tie": 110,
            "by_class": {"active": 176, "inactive": 11236},
        },
        "hash_selected_sentinel_panel": {
            "parents": 96,
            "by_target": {"ESR_antago": 32, "PPARG": 32, "TP53": 32},
            "by_class": {"active": 48, "inactive": 48},
            "all_primary_states_prepared": True,
        },
    }
    assert first["execution_policy"]["maximum_additional_vina_executions"] == 58046
    assert first["execution_policy"]["sensitivity_executed"] is False
    windows_home_prefix = "C:" + "\\Users"
    assert windows_home_prefix not in serialize_sensitivity_plan(first)


def test_sensitivity_plan_rejects_post_freeze_factor_tampering(tmp_path: Path) -> None:
    plan = build_sensitivity_plan(**PATHS)
    plan["variants"][3]["vina_parameters"]["seed"] = 7
    plan.pop("manifest_sha256")
    plan["manifest_sha256"] = _digest(plan)
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(ScreeningBenchmarkSensitivityPlanError):
        verify_sensitivity_plan(path, **PATHS)


def test_recorded_sensitivity_plan_reproduces_exactly() -> None:
    plan = verify_sensitivity_plan(RECORDED_PLAN, **PATHS)

    assert plan["manifest_sha256"] == (
        "63c74c7e7d29a4a763208d815acee9f87537ff9a579dff781cb531868fa2da6d"
    )
    assert [variant["factor"] for variant in plan["variants"]] == [
        "chemical_state",
        "receptor",
        "box",
        "seed",
        "seed",
        "sampling",
    ]
