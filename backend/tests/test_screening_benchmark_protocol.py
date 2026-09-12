"""Keep the public point-26 preregistration aligned with executable metrics."""

import json
from pathlib import Path

from ankora_backend.schemas.screening_benchmark import ScoreDirection
from ankora_backend.services.screening_benchmark import (
    DEFAULT_BEDROC_ALPHA,
    DEFAULT_TOP_FRACTION,
    FAILURE_POLICY,
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

    assert spec["status"].endswith("before_acquisition_or_results")
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


def test_frozen_cohort_is_multi_target_and_its_source_census_closes() -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))

    targets = spec["primary_evidence"]["targets"]
    assert [target["target_id"] for target in targets] == [
        "ESR_antago",
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
