"""Contracts for the recorded pre-result protonation decision review."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import ankora_backend.validation.screening_benchmark_protonation_decisions as decisions
from ankora_backend.validation.screening_benchmark_protonation_decisions import (
    ScreeningBenchmarkProtonationDecisionError,
    protonation_overrides_for_template,
    verify_protonation_decision_review,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_ROOT = PROJECT_ROOT / "docs" / "validation" / "reference_cases"
REVIEW_PATH = REFERENCE_ROOT / (
    "LIT_PCBA_ANKORA_VS_V1.protonation-decision-review.json"
)
PREVIEW_PATH = REFERENCE_ROOT / "LIT_PCBA_ANKORA_VS_V1.protonation-previews.json"
TAUTOMER_PATH = REFERENCE_ROOT / (
    "LIT_PCBA_ANKORA_VS_V1.tp53-tautomer-verification.json"
)


def test_recorded_review_covers_every_proposal_and_releases_exact_overrides() -> None:
    review = verify_protonation_decision_review(
        REVIEW_PATH,
        preview_manifest_path=PREVIEW_PATH,
        tautomer_manifest_path=TAUTOMER_PATH,
    )

    assert review["scores_seen"] is False
    assert review["decision_census"] == {
        "templates": 6,
        "source_proposals": 449,
        "accepted_by_default_policy": 443,
        "explicit_overrides": 6,
    }
    assert review["scientist_confirmation"]["status"] == "confirmed"
    assert review["scientist_confirmation"]["confirmed_by"] == "Samael Olascoaga"
    assert review["final_creation_authorized"] is True

    overrides = protonation_overrides_for_template(
        REVIEW_PATH,
        preview_manifest_path=PREVIEW_PATH,
        tautomer_manifest_path=TAUTOMER_PATH,
        target_id="TP53",
        role="primary",
        pdb_id="3zme",
    )
    assert [item.state for item in overrides] == ["HIE", "CYM", "CYM"]
    assert [item.residue.sequence_number for item in overrides] == [179, 238, 242]


def test_pending_review_cannot_release_candidate_overrides(
    tmp_path: Path,
) -> None:
    value = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
    value["scientist_confirmation"] = {
        **value["scientist_confirmation"],
        "status": "pending",
        "confirmed_by": None,
        "confirmed_at": None,
    }
    value["final_creation_authorized"] = False
    payload = dict(value)
    payload.pop("review_sha256")
    value["review_sha256"] = decisions._digest(payload)
    path = tmp_path / "pending-review.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(
        ScreeningBenchmarkProtonationDecisionError,
        match="Scientist confirmation is still pending",
    ):
        protonation_overrides_for_template(
            path,
            preview_manifest_path=PREVIEW_PATH,
            tautomer_manifest_path=TAUTOMER_PATH,
            target_id="TP53",
            role="primary",
            pdb_id="3zme",
        )


def test_review_rejects_hash_valid_but_incomplete_override_set(tmp_path: Path) -> None:
    value = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
    value["proposed_overrides"].pop()
    value["decision_census"]["explicit_overrides"] = 5
    value["decision_census"]["accepted_by_default_policy"] = 444
    payload = dict(value)
    payload.pop("review_sha256")
    value["review_sha256"] = decisions._digest(payload)
    path = tmp_path / "incomplete-review.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(
        ScreeningBenchmarkProtonationDecisionError,
        match="override set is incomplete",
    ):
        verify_protonation_decision_review(
            path,
            preview_manifest_path=PREVIEW_PATH,
            tautomer_manifest_path=TAUTOMER_PATH,
        )
