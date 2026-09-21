"""Validate the pre-result scientist review of benchmark protonation states."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ankora_backend.schemas.receptors import ProtonationOverride
from ankora_backend.validation.screening_benchmark_protonation_previews import (
    verify_protonation_preview_manifest,
)
from ankora_backend.validation.screening_benchmark_tautomer_verification import (
    verify_tautomer_verification_manifest,
)

SCHEMA_VERSION = 1

_EXPECTED_TP53_OVERRIDES = {
    ("primary", "3zme", "A|HIS|179||HIS 179 A", "HIE"),
    ("primary", "3zme", "A|CYS|238||CYS 238 A", "CYM"),
    ("primary", "3zme", "A|CYS|242||CYS 242 A", "CYM"),
    ("alternate", "5o1i", "A|HIS|179||HIS 179 A", "HIE"),
    ("alternate", "5o1i", "A|CYS|238||CYS 238 A", "CYM"),
    ("alternate", "5o1i", "A|CYS|242||CYS 242 A", "CYM"),
}
_EXPECTED_TP53_DEFAULT_CONFIRMATIONS = {
    ("primary", "3zme", "A|CYS|176||CYS 176 A", "CYM"),
    ("alternate", "5o1i", "A|CYS|176||CYS 176 A", "CYM"),
}
_CONFIRMATION_STATEMENT = (
    "Accept all 443 recorded source defaults plus HIE at HIS A:179 and CYM at "
    "CYS A:238 and CYS A:242 in both TP53 templates."
)


class ScreeningBenchmarkProtonationDecisionError(ValueError):
    """The protonation decision review is incomplete, changed, or unapproved."""


def verify_protonation_decision_review(
    path: Path,
    *,
    preview_manifest_path: Path,
    tautomer_manifest_path: Path,
    require_scientist_confirmation: bool = False,
) -> dict[str, Any]:
    """Verify complete decision coverage without inventing scientist approval."""

    review = _load_object(path, "protonation decision review")
    if review.get("schema_version") != SCHEMA_VERSION:
        raise ScreeningBenchmarkProtonationDecisionError(
            "Unsupported protonation decision review schema."
        )
    recorded = _required_sha256(review, "review_sha256")
    payload = dict(review)
    payload.pop("review_sha256")
    if _digest(payload) != recorded:
        raise ScreeningBenchmarkProtonationDecisionError(
            "The protonation decision review differs from its SHA-256."
        )
    if review.get("scores_seen") is not False:
        raise ScreeningBenchmarkProtonationDecisionError(
            "Protonation decisions must be frozen before docking scores exist."
        )
    _required_string(review, "protocol_id")
    _required_string(review, "review_id")
    if review.get("default_policy") != (
        "accept_source_default_unless_explicit_override"
    ):
        raise ScreeningBenchmarkProtonationDecisionError(
            "The decision review does not define complete default coverage."
        )

    previews = verify_protonation_preview_manifest(preview_manifest_path)
    tautomer = verify_tautomer_verification_manifest(tautomer_manifest_path)
    if review.get("source_protonation_preview_manifest_sha256") != previews.get(
        "manifest_sha256"
    ):
        raise ScreeningBenchmarkProtonationDecisionError(
            "The review names a different protonation-preview manifest."
        )
    if review.get("source_tautomer_verification_manifest_sha256") != tautomer.get(
        "manifest_sha256"
    ):
        raise ScreeningBenchmarkProtonationDecisionError(
            "The review names a different tautomer-verification manifest."
        )

    proposal_index, template_count = _proposal_index(previews)
    tautomer_proofs = _tautomer_proofs(tautomer)
    overrides = _verify_overrides(review, proposal_index, tautomer_proofs)
    _verify_required_defaults(review, proposal_index)
    _verify_census(review, proposal_index, template_count, overrides)
    _verify_confirmation(review, require_scientist_confirmation)
    return review


def protonation_overrides_for_template(
    path: Path,
    *,
    preview_manifest_path: Path,
    tautomer_manifest_path: Path,
    target_id: str,
    role: str,
    pdb_id: str,
) -> list[ProtonationOverride]:
    """Return approved overrides; pending reviews are intentionally unusable."""

    review = verify_protonation_decision_review(
        path,
        preview_manifest_path=preview_manifest_path,
        tautomer_manifest_path=tautomer_manifest_path,
        require_scientist_confirmation=True,
    )
    matches: list[ProtonationOverride] = []
    for raw in _required_list(review, "proposed_overrides"):
        item = _required_object(raw, "proposed override")
        if (
            item.get("target_id"),
            item.get("role"),
            item.get("pdb_id"),
        ) != (target_id, role, pdb_id):
            continue
        matches.append(
            ProtonationOverride.model_validate(
                {
                    "residue": _required_object(item.get("residue"), "residue"),
                    "state": _required_string(item, "selected_state"),
                }
            )
        )
    return matches


def _proposal_index(
    previews: dict[str, Any],
) -> tuple[dict[tuple[str, str, str, str], dict[str, Any]], int]:
    index: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    templates: set[tuple[str, str, str]] = set()
    for raw_preview in _required_list(previews, "previews"):
        preview = _required_object(raw_preview, "preview")
        identity = (
            _required_string(preview, "target_id"),
            _required_string(preview, "role"),
            _required_string(preview, "pdb_id"),
        )
        if identity in templates:
            raise ScreeningBenchmarkProtonationDecisionError(
                "The source preview manifest repeats a template."
            )
        templates.add(identity)
        for raw_proposal in _required_list(preview, "proposals"):
            proposal = _required_object(raw_proposal, "proposal")
            key = (*identity, _required_string(proposal, "proposal_id"))
            if key in index:
                raise ScreeningBenchmarkProtonationDecisionError(
                    "The source preview manifest repeats a proposal."
                )
            index[key] = proposal
    return index, len(templates)


def _tautomer_proofs(manifest: dict[str, Any]) -> set[tuple[str, str]]:
    proofs: set[tuple[str, str]] = set()
    for raw in _required_list(manifest, "previews"):
        item = _required_object(raw, "tautomer preview")
        if (
            item.get("requested_state") == "HIE"
            and item.get("output_state") == "HIE"
            and item.get("ring_hydrogen") == "HE2"
            and item.get("coordinating_atom_left_unprotonated") == "ND1"
        ):
            proofs.add(
                (_required_string(item, "role"), _required_string(item, "pdb_id"))
            )
    return proofs


def _verify_overrides(
    review: dict[str, Any],
    proposals: dict[tuple[str, str, str, str], dict[str, Any]],
    tautomer_proofs: set[tuple[str, str]],
) -> set[tuple[str, str, str, str, str]]:
    observed: set[tuple[str, str, str, str, str]] = set()
    for raw in _required_list(review, "proposed_overrides"):
        item = _required_object(raw, "proposed override")
        target_id = _required_string(item, "target_id")
        role = _required_string(item, "role")
        pdb_id = _required_string(item, "pdb_id")
        proposal_id = _required_string(item, "proposal_id")
        selected_state = _required_string(item, "selected_state")
        proposal = proposals.get((target_id, role, pdb_id, proposal_id))
        if proposal is None:
            raise ScreeningBenchmarkProtonationDecisionError(
                f"Override {proposal_id} does not name a frozen source proposal."
            )
        residue = ProtonationOverride.model_validate(
            {
                "residue": _required_object(item.get("residue"), "residue"),
                "state": selected_state,
            }
        )
        if residue.residue.model_dump() != _required_object(
            proposal.get("residue"), "source residue"
        ):
            raise ScreeningBenchmarkProtonationDecisionError(
                f"Override {proposal_id} names a different residue."
            )
        allowed_states = set(_required_string_list(proposal, "allowed_states"))
        exact_hie_proof = (
            target_id == "TP53"
            and proposal_id == "A|HIS|179||HIS 179 A"
            and selected_state == "HIE"
            and (role, pdb_id) in tautomer_proofs
        )
        if selected_state not in allowed_states and not exact_hie_proof:
            raise ScreeningBenchmarkProtonationDecisionError(
                f"Override {proposal_id} requests an unverified state."
            )
        if selected_state == proposal.get("default_state"):
            raise ScreeningBenchmarkProtonationDecisionError(
                f"Override {proposal_id} redundantly selects the source default."
            )
        if item.get("source_default_state") != proposal.get("default_state"):
            raise ScreeningBenchmarkProtonationDecisionError(
                f"Override {proposal_id} misstates the source default."
            )
        if not _required_string(item, "selection_basis"):
            raise ScreeningBenchmarkProtonationDecisionError(
                f"Override {proposal_id} lacks a selection basis."
            )
        identity = (role, pdb_id, proposal_id, selected_state)
        if (target_id, *identity) in observed:
            raise ScreeningBenchmarkProtonationDecisionError(
                "The decision review repeats an override."
            )
        observed.add((target_id, *identity))
    if observed != {("TP53", *item) for item in _EXPECTED_TP53_OVERRIDES}:
        raise ScreeningBenchmarkProtonationDecisionError(
            "The proposed TP53 zinc-site override set is incomplete or changed."
        )
    return observed


def _verify_required_defaults(
    review: dict[str, Any],
    proposals: dict[tuple[str, str, str, str], dict[str, Any]],
) -> None:
    observed: set[tuple[str, str, str, str]] = set()
    for raw in _required_list(review, "required_default_confirmations"):
        item = _required_object(raw, "required default confirmation")
        if item.get("target_id") != "TP53":
            raise ScreeningBenchmarkProtonationDecisionError(
                "A required zinc-site default names a different target."
            )
        role = _required_string(item, "role")
        pdb_id = _required_string(item, "pdb_id")
        proposal_id = _required_string(item, "proposal_id")
        selected_state = _required_string(item, "selected_state")
        proposal = proposals.get(("TP53", role, pdb_id, proposal_id))
        if proposal is None or proposal.get("default_state") != selected_state:
            raise ScreeningBenchmarkProtonationDecisionError(
                "A required TP53 zinc-site default is missing or changed."
            )
        _required_string(item, "selection_basis")
        observed.add((role, pdb_id, proposal_id, selected_state))
    if observed != _EXPECTED_TP53_DEFAULT_CONFIRMATIONS:
        raise ScreeningBenchmarkProtonationDecisionError(
            "The TP53 CYS A:176 default confirmations are incomplete."
        )


def _verify_census(
    review: dict[str, Any],
    proposals: dict[tuple[str, str, str, str], dict[str, Any]],
    template_count: int,
    overrides: set[tuple[str, str, str, str, str]],
) -> None:
    census = _required_object(review.get("decision_census"), "decision census")
    expected = {
        "templates": template_count,
        "source_proposals": len(proposals),
        "accepted_by_default_policy": len(proposals) - len(overrides),
        "explicit_overrides": len(overrides),
    }
    if census != expected:
        raise ScreeningBenchmarkProtonationDecisionError(
            "The decision census does not cover every frozen proposal exactly once."
        )


def _verify_confirmation(
    review: dict[str, Any], require_scientist_confirmation: bool
) -> None:
    confirmation = _required_object(
        review.get("scientist_confirmation"), "scientist confirmation"
    )
    if confirmation.get("confirmation_statement") != _CONFIRMATION_STATEMENT:
        raise ScreeningBenchmarkProtonationDecisionError(
            "The scientist confirmation statement is incomplete or changed."
        )
    status = confirmation.get("status")
    authorized = review.get("final_creation_authorized")
    if status == "pending":
        if authorized is not False:
            raise ScreeningBenchmarkProtonationDecisionError(
                "A pending review cannot authorize final receptor creation."
            )
        if confirmation.get("confirmed_by") is not None or confirmation.get(
            "confirmed_at"
        ) is not None:
            raise ScreeningBenchmarkProtonationDecisionError(
                "A pending review cannot claim a scientist or confirmation time."
            )
        if require_scientist_confirmation:
            raise ScreeningBenchmarkProtonationDecisionError(
                "Scientist confirmation is still pending."
            )
        return
    if status != "confirmed" or authorized is not True:
        raise ScreeningBenchmarkProtonationDecisionError(
            "Scientist confirmation state is invalid."
        )
    _required_string(confirmation, "confirmed_by")
    _required_string(confirmation, "confirmed_at")


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScreeningBenchmarkProtonationDecisionError(
            f"Could not read {label}: {error}"
        ) from error
    return _required_object(value, label)


def _required_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScreeningBenchmarkProtonationDecisionError(
            f"{label.capitalize()} must be an object."
        )
    return value


def _required_list(value: dict[str, Any], key: str) -> list[Any]:
    result = value.get(key)
    if not isinstance(result, list):
        raise ScreeningBenchmarkProtonationDecisionError(f"{key} must be a list.")
    return result


def _required_string_list(value: dict[str, Any], key: str) -> list[str]:
    result = _required_list(value, key)
    if any(not isinstance(item, str) or not item for item in result):
        raise ScreeningBenchmarkProtonationDecisionError(
            f"{key} must contain non-empty strings."
        )
    return result


def _required_string(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ScreeningBenchmarkProtonationDecisionError(
            f"{key} must be a non-empty string."
        )
    return result


def _required_sha256(value: dict[str, Any], key: str) -> str:
    result = _required_string(value, key)
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        raise ScreeningBenchmarkProtonationDecisionError(
            f"{key} must be a lowercase SHA-256."
        )
    return result


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
