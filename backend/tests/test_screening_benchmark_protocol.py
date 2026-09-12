"""Keep the public point-26 preregistration aligned with executable metrics."""

import hashlib
import json
from pathlib import Path

from ankora_backend.schemas.screening_benchmark import ScoreDirection
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
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "validation"
    / "reference_cases"
    / "LIT_PCBA_ANKORA_VS_V1.spec.json"
)


def test_frozen_protocol_matches_the_metric_implementation() -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))

    assert spec["status"] == (
        "exact_ave_unbiased_source_acquired_before_results_with_amendment_001"
    )
    assert spec["result_status"] == "not_executed"
    assert spec["ranking"] == {
        "unit": "one canonical parent compound",
        "duplicate_key": (
            "RDKit canonical isomeric SMILES of the sanitized source graph without "
            "uncharging, tautomerization, or fragment removal"
        ),
        "primary_state_policy": "exact_imported_state",
        "score_direction": ScoreDirection.LOWER_IS_BETTER,
        "tie_policy": TIE_POLICY,
        "failure_policy": FAILURE_POLICY,
        "cross_engine_pooling": False,
    }
    assert spec["metrics"]["top_fraction"] == DEFAULT_TOP_FRACTION
    assert spec["metrics"]["bedroc_alpha"] == DEFAULT_BEDROC_ALPHA
    assert spec["metrics"]["pr_auc_definition"] == PR_AUC_DEFINITION
    assert spec["metrics"]["bootstrap"] == {
        "method": BOOTSTRAP_METHOD,
        "replicates": DEFAULT_BOOTSTRAP_REPLICATES,
        "confidence_level": DEFAULT_CONFIDENCE_LEVEL,
        "seed": DEFAULT_BOOTSTRAP_SEED,
        "percentile_method": PERCENTILE_METHOD,
    }


def test_frozen_source_and_pre_result_amendment_are_exactly_identified() -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    evidence = spec["primary_evidence"]

    assert evidence["source_archive"] == {
        "filename": "LIT-PCBA_AVE_unbiased.tar.gz",
        "size_bytes": 57399933,
        "sha256": (
            "1f50ef6bf66b8e987f056a2d2528f1d5a9031ad542ddc97f8ee2fbfd651c8de3"
        ),
    }
    assert evidence["source_layout"] == {
        "active_files": ["active_T.smi", "active_V.smi"],
        "inactive_files": ["inactive_T.smi", "inactive_V.smi"],
    }

    [reference] = spec["amendments"]
    amendment_path = SPEC_PATH.parent / reference["path"]
    amendment_bytes = amendment_path.read_bytes()
    amendment = json.loads(amendment_bytes)
    assert hashlib.sha256(amendment_bytes).hexdigest() == reference["sha256"]
    assert amendment["amendment_id"] == reference["amendment_id"] == "001"
    assert amendment["protocol_id"] == spec["protocol_id"]
    assert amendment["invariants"]["scores_seen"] is False
    assert amendment["result_status"] == "pre_result_source_identity_correction"


def test_frozen_cohort_is_multi_target_and_its_source_census_closes() -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))

    targets = spec["primary_evidence"]["targets"]
    assert [target["target_id"] for target in targets] == [
        "ESR_antago",
        "PPARG",
        "TP53",
    ]
    assert [target["source_directory"] for target in targets] == [
        "ESR1_ant",
        "PPARG",
        "TP53",
    ]
    assert len({target["pubchem_aid"] for target in targets}) == 3
    assert sum(target["reported_actives"] for target in targets) == 176
    assert sum(target["reported_inactives"] for target in targets) == 11236
    assert all(
        target["reported_actives"] + target["reported_inactives"] <= 5000
        for target in targets
    )
