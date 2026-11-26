"""Pure deterministic evaluation of declarative ProLIF pharmacophoric rules & Tanimoto IFP (M4).

Zero new dependencies: operates strictly over structured `InteractionContact`
evidence emitted by `ProLIF 2.2.1` on the exact coupled `PoseComplex` (`ADR-032 E8`).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.interaction_rules import (
    ClauseEvaluationResult,
    IfpBit,
    IfpCountEntry,
    IfpSourceKind,
    IfpTanimotoResult,
    InteractionFingerprint,
    InteractionRuleClause,
    InteractionRuleKind,
    InteractionRuleSetRecord,
    InteractionTarget,
    TargetEvaluationResult,
    compute_ifp_sha256,
    format_residue_label,
    residue_locator_sort_key,
)
from ankora_backend.schemas.pose_interactions import InteractionContact, InteractionProfile
from ankora_backend.schemas.receptors import ResidueLocator
from ankora_backend.schemas.v02_contracts import (
    DiagnosticStatus,
    ObservationStatus,
    ScoreObservation,
)
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode

_STAGE = "interaction_rule_evaluation"

#: Failure codes assigned when a sealed InteractionRuleSet gates protocol calibration.
INTERACTION_RULE_FAILED_CODE = "INTERACTION_RULE_SET_FAILED"
INTERACTION_RULE_NOT_EVALUABLE_CODE = "INTERACTION_RULE_NOT_EVALUABLE"


@dataclass(frozen=True)
class RuleEvaluationOutcome:
    """Structured outcome returned before persistence wraps it in a provenance record."""

    overall_status: DiagnosticStatus
    pose_ifp: InteractionFingerprint
    clause_results: tuple[ClauseEvaluationResult, ...]
    passed_clause_count: int
    failed_clause_count: int
    tanimoto: IfpTanimotoResult | None
    warnings: tuple[StructuredWarning, ...]


def extract_receptor_residues_from_pdb(pdb_path: Path) -> set[tuple[str, int, str, str]]:
    """Extract canonical `(chain_id, sequence_number, insertion_code, residue_name)` tuples."""
    residues: set[tuple[str, int, str, str]] = set()
    for line in pdb_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not (line.startswith("ATOM  ") or line.startswith("HETATM")):
            continue
        if len(line) < 27:
            continue
        residue_name = line[17:20].strip().upper()
        chain_id = line[21:22].strip()
        seq_raw = line[22:26].strip()
        insertion_code = line[26:27].strip()
        if not residue_name or not seq_raw:
            continue
        try:
            sequence_number = int(seq_raw)
        except ValueError:
            continue
        residues.add((chain_id, sequence_number, insertion_code, residue_name))
    return residues


def validate_residues_against_receptor(
    *,
    receptor_residues: set[tuple[str, int, str, str]],
    locators: Sequence[ResidueLocator],
) -> None:
    """Fail closed (422) if any rule or reference bit names a residue absent from the receptor."""
    missing: list[dict[str, object]] = []
    for locator in locators:
        key = residue_locator_sort_key(locator)
        if key not in receptor_residues:
            missing.append(
                {
                    "label": format_residue_label(locator),
                    "chain_id": locator.chain_id,
                    "residue_name": locator.residue_name,
                    "sequence_number": locator.sequence_number,
                    "insertion_code": locator.insertion_code,
                }
            )
    if missing:
        labels = ", ".join(str(item["label"]) for item in missing)
        raise AnkoraDomainError(
            code="INTERACTION_RULE_RESIDUE_NOT_FOUND",
            stage=_STAGE,
            status_code=422,
            message=(
                f"Residue(s) {labels} were not found in the prepared receptor's protonated PDB."
            ),
            details={"missing_residues": missing},
        )


def fingerprint_from_contacts(
    contacts: Sequence[InteractionContact],
    *,
    profile: InteractionProfile,
    source_kind: IfpSourceKind = IfpSourceKind.POSE_ANALYSIS,
    source_analysis_id: str | None = None,
    source_catalog_id: str | None = None,
    source_ligand_id: str | None = None,
    source_pose_artifact_id: str | None = None,
    source_pose_complex_sha256: str | None = None,
) -> InteractionFingerprint:
    """Project ProLIF contacts into a canonical sorted binary + counted IFP."""
    enabled = set(profile.interactions)
    bit_by_key: dict[tuple[str, int, str, str, str], IfpBit] = {}
    counts: Counter[tuple[str, int, str, str, str]] = Counter()
    for contact in contacts:
        if contact.detector_type not in enabled:
            continue
        bit = IfpBit(
            residue=ResidueLocator(
                chain_id=contact.residue.chain_id.strip(),
                residue_name=contact.residue.residue_name.strip().upper(),
                sequence_number=contact.residue.sequence_number,
                insertion_code=contact.residue.insertion_code.strip(),
            ),
            interaction_type=contact.detector_type,
        )
        key = bit.sort_key()
        bit_by_key.setdefault(key, bit)
        counts[key] += 1

    ordered_keys = sorted(bit_by_key)
    ordered_bits = tuple(bit_by_key[key] for key in ordered_keys)
    ordered_counts = tuple(
        IfpCountEntry(bit=bit_by_key[key], count=counts[key]) for key in ordered_keys
    )
    return InteractionFingerprint(
        profile=profile,
        bits=ordered_bits,
        counts=ordered_counts,
        source_kind=source_kind,
        source_analysis_id=source_analysis_id,
        source_catalog_id=source_catalog_id,
        source_ligand_id=source_ligand_id,
        source_pose_artifact_id=source_pose_artifact_id,
        source_pose_complex_sha256=source_pose_complex_sha256,
        fingerprint_sha256=compute_ifp_sha256(profile=profile, bits=ordered_bits),
    )


def fingerprint_from_explicit_bits(
    bits: Sequence[IfpBit],
    *,
    profile: InteractionProfile,
) -> InteractionFingerprint:
    """Canonicalize an explicitly supplied reference IFP bit set."""
    unique: dict[tuple[str, int, str, str, str], IfpBit] = {}
    for raw in bits:
        normalized = IfpBit(
            residue=ResidueLocator(
                chain_id=raw.residue.chain_id.strip(),
                residue_name=raw.residue.residue_name.strip().upper(),
                sequence_number=raw.residue.sequence_number,
                insertion_code=raw.residue.insertion_code.strip(),
            ),
            interaction_type=raw.interaction_type,
        )
        unique.setdefault(normalized.sort_key(), normalized)
    ordered_bits = tuple(unique[key] for key in sorted(unique))
    ordered_counts = tuple(IfpCountEntry(bit=bit, count=1) for bit in ordered_bits)
    return InteractionFingerprint(
        profile=profile,
        bits=ordered_bits,
        counts=ordered_counts,
        source_kind=IfpSourceKind.EXPLICIT_BITS,
        fingerprint_sha256=compute_ifp_sha256(profile=profile, bits=ordered_bits),
    )


def compute_ifp_tanimoto(
    *,
    pose_ifp: InteractionFingerprint,
    reference_ifp: InteractionFingerprint,
    min_threshold: float | None = None,
) -> IfpTanimotoResult:
    """Compute exact binary Tanimoto similarity |A ∩ B| / |A ∪ B| over residue x type bits."""
    pose_interactions = set(pose_ifp.profile.interactions)
    ref_interactions = set(reference_ifp.profile.interactions)
    if pose_interactions != ref_interactions or not math.isclose(
        pose_ifp.profile.vicinity_cutoff_angstrom,
        reference_ifp.profile.vicinity_cutoff_angstrom,
        abs_tol=1e-9,
    ):
        raise AnkoraDomainError(
            code="INTERACTION_IFP_PROFILE_MISMATCH",
            stage=_STAGE,
            status_code=422,
            message=(
                "Cannot compute IFP Tanimoto similarity between fingerprints built under "
                "incompatible interaction profiles."
            ),
            details={
                "pose_interactions": sorted(pose_interactions),
                "reference_interactions": sorted(ref_interactions),
                "pose_vicinity_cutoff_angstrom": pose_ifp.profile.vicinity_cutoff_angstrom,
                "reference_vicinity_cutoff_angstrom": (
                    reference_ifp.profile.vicinity_cutoff_angstrom
                ),
            },
        )
    pose_map = {bit.sort_key(): bit for bit in pose_ifp.bits}
    ref_map = {bit.sort_key(): bit for bit in reference_ifp.bits}
    pose_keys = set(pose_map)
    ref_keys = set(ref_map)

    shared_keys = sorted(pose_keys & ref_keys)
    pose_only_keys = sorted(pose_keys - ref_keys)
    ref_only_keys = sorted(ref_keys - pose_keys)
    union_count = len(pose_keys | ref_keys)
    intersection_count = len(shared_keys)

    if union_count == 0:
        return IfpTanimotoResult(
            reference_fingerprint_sha256=reference_ifp.fingerprint_sha256,
            pose_fingerprint_sha256=pose_ifp.fingerprint_sha256,
            status=DiagnosticStatus.NOT_EVALUABLE,
            similarity=None,
            min_threshold=min_threshold,
            intersection_count=0,
            union_count=0,
            shared_bits=(),
            pose_only_bits=(),
            reference_only_bits=(),
        )

    similarity = intersection_count / union_count
    if min_threshold is None or similarity + 1e-12 >= min_threshold:
        status = DiagnosticStatus.PASS
    else:
        status = DiagnosticStatus.FAIL

    return IfpTanimotoResult(
        reference_fingerprint_sha256=reference_ifp.fingerprint_sha256,
        pose_fingerprint_sha256=pose_ifp.fingerprint_sha256,
        status=status,
        similarity=similarity,
        min_threshold=min_threshold,
        intersection_count=intersection_count,
        union_count=union_count,
        shared_bits=tuple(pose_map[key] for key in shared_keys),
        pose_only_bits=tuple(pose_map[key] for key in pose_only_keys),
        reference_only_bits=tuple(ref_map[key] for key in ref_only_keys),
    )


def _match_target(
    target: InteractionTarget, contacts: Sequence[InteractionContact]
) -> TargetEvaluationResult:
    target_residue_key = residue_locator_sort_key(target.residue)
    allowed_types = set(target.interaction_types)
    matched_ids: list[str] = []
    distances: list[float] = []

    for contact in contacts:
        if residue_locator_sort_key(contact.residue) != target_residue_key:
            continue
        if contact.detector_type not in allowed_types:
            continue
        if target.max_distance_angstrom is not None:
            if contact.distance_angstrom is None:
                continue
            if contact.distance_angstrom > target.max_distance_angstrom:
                continue
        matched_ids.append(contact.contact_id)
        if contact.distance_angstrom is not None:
            distances.append(float(contact.distance_angstrom))

    return TargetEvaluationResult(
        target=target,
        matched=bool(matched_ids),
        matched_contact_ids=tuple(matched_ids),
        shortest_distance_angstrom=min(distances) if distances else None,
    )


def _evaluate_clause(
    clause: InteractionRuleClause, contacts: Sequence[InteractionContact]
) -> ClauseEvaluationResult:
    target_results = tuple(_match_target(target, contacts) for target in clause.targets)
    satisfied = sum(1 for item in target_results if item.matched)
    all_matched_contact_ids = tuple(
        dict.fromkeys(
            cid for item in target_results for cid in item.matched_contact_ids
        )
    )

    if clause.kind is InteractionRuleKind.REQUIRED:
        required = len(clause.targets)
        passed = satisfied == required
        status = DiagnosticStatus.PASS if passed else DiagnosticStatus.FAIL
        explanation = (
            f"All {required} required target(s) matched "
            f"({len(all_matched_contact_ids)} contact(s))."
            if passed
            else f"Matched {satisfied} of {required} required target(s)."
        )
    elif clause.kind is InteractionRuleKind.ALTERNATIVE_OR:
        required = clause.effective_min_satisfied
        passed = satisfied >= required
        status = DiagnosticStatus.PASS if passed else DiagnosticStatus.FAIL
        explanation = (
            f"Matched {satisfied} of {len(clause.targets)} alternative target(s) "
            f"(minimum required: {required})."
            if passed
            else f"Only {satisfied} of {len(clause.targets)} alternative target(s) matched "
            f"(minimum required: {required})."
        )
    else:
        required = 0
        passed = satisfied == 0
        status = DiagnosticStatus.PASS if passed else DiagnosticStatus.FAIL
        explanation = (
            "No forbidden contacts detected."
            if passed
            else f"Detected {satisfied} forbidden target(s) across "
            f"{len(all_matched_contact_ids)} contact(s)."
        )

    return ClauseEvaluationResult(
        clause_id=clause.clause_id,
        label=clause.label,
        kind=clause.kind,
        status=status,
        satisfied_target_count=satisfied,
        required_target_count=required,
        matched_contact_ids=all_matched_contact_ids,
        target_results=target_results,
        explanation=explanation,
    )


def evaluate_rule_set_against_contacts(
    *,
    rule_set: InteractionRuleSetRecord,
    contacts: Sequence[InteractionContact],
    source_analysis_id: str | None = None,
    source_catalog_id: str | None = None,
    source_ligand_id: str | None = None,
    source_pose_artifact_id: str | None = None,
    source_pose_complex_sha256: str | None = None,
) -> RuleEvaluationOutcome:
    """Evaluate all clauses and optional reference Tanimoto IFP on one pose's contacts."""
    pose_ifp = fingerprint_from_contacts(
        contacts,
        profile=rule_set.profile,
        source_kind=IfpSourceKind.POSE_ANALYSIS,
        source_analysis_id=source_analysis_id,
        source_catalog_id=source_catalog_id,
        source_ligand_id=source_ligand_id,
        source_pose_artifact_id=source_pose_artifact_id,
        source_pose_complex_sha256=source_pose_complex_sha256,
    )
    clause_results = tuple(_evaluate_clause(clause, contacts) for clause in rule_set.clauses)
    passed_clause_count = sum(
        1 for item in clause_results if item.status is DiagnosticStatus.PASS
    )
    failed_clauses = [item for item in clause_results if item.status is DiagnosticStatus.FAIL]
    forbidden_failures = [
        item for item in failed_clauses if item.kind is InteractionRuleKind.FORBIDDEN
    ]

    warnings: list[StructuredWarning] = []
    if failed_clauses:
        warnings.append(
            StructuredWarning(
                code=WarningCode.INTERACTION_RULE_CLAUSES_FAILED,
                stage=_STAGE,
                message=(
                    f"{len(failed_clauses)} pharmacophoric clause(s) did not pass for this pose "
                    "complex. The pose remains preserved in the campaign census."
                ),
                details={"failed_clause_ids": [item.clause_id for item in failed_clauses]},
            )
        )
    if forbidden_failures:
        warnings.append(
            StructuredWarning(
                code=WarningCode.INTERACTION_RULE_FORBIDDEN_CONTACT,
                stage=_STAGE,
                message=(
                    f"{len(forbidden_failures)} FORBIDDEN interaction clause(s) triggered on "
                    "this pose complex."
                ),
                details={
                    "forbidden_clause_ids": [item.clause_id for item in forbidden_failures],
                    "contact_ids": [
                        cid for item in forbidden_failures for cid in item.matched_contact_ids
                    ],
                },
            )
        )

    tanimoto: IfpTanimotoResult | None = None
    if rule_set.reference_ifp is not None:
        tanimoto = compute_ifp_tanimoto(
            pose_ifp=pose_ifp,
            reference_ifp=rule_set.reference_ifp,
            min_threshold=rule_set.min_tanimoto_similarity,
        )
        if tanimoto.status is DiagnosticStatus.NOT_EVALUABLE:
            warnings.append(
                StructuredWarning(
                    code=WarningCode.INTERACTION_IFP_EMPTY_UNION,
                    stage=_STAGE,
                    message=(
                        "Both pose and reference IFPs contain zero contacts (0/0 union); "
                        "Tanimoto similarity is reported honestly as not_evaluable."
                    ),
                )
            )
        elif tanimoto.status is DiagnosticStatus.FAIL and tanimoto.similarity is not None:
            warnings.append(
                StructuredWarning(
                    code=WarningCode.INTERACTION_IFP_TANIMOTO_BELOW_THRESHOLD,
                    stage=_STAGE,
                    message=(
                        f"Pose IFP Tanimoto similarity ({tanimoto.similarity:.3f}) is below the "
                        f"required threshold ({rule_set.min_tanimoto_similarity:.3f})."
                    ),
                    details={
                        "similarity": tanimoto.similarity,
                        "min_threshold": rule_set.min_tanimoto_similarity,
                    },
                )
            )

    tanimoto_required = rule_set.min_tanimoto_similarity is not None
    if failed_clauses or (
        tanimoto is not None and tanimoto.status is DiagnosticStatus.FAIL
    ):
        overall_status = DiagnosticStatus.FAIL
    elif (
        tanimoto is not None
        and tanimoto.status is DiagnosticStatus.NOT_EVALUABLE
        and (tanimoto_required or not clause_results)
    ):
        overall_status = DiagnosticStatus.NOT_EVALUABLE
    else:
        overall_status = DiagnosticStatus.PASS

    return RuleEvaluationOutcome(
        overall_status=overall_status,
        pose_ifp=pose_ifp,
        clause_results=clause_results,
        passed_clause_count=passed_clause_count,
        failed_clause_count=len(failed_clauses),
        tanimoto=tanimoto,
        warnings=tuple(warnings),
    )


def apply_interaction_rule_gate_to_observations(
    observations: Sequence[ScoreObservation],
    *,
    gated_protocol_identity_sha256: str,
    rule_statuses_by_parent: Mapping[str, DiagnosticStatus],
) -> tuple[ScoreObservation, ...]:
    """Apply a sealed InteractionRuleSet gate while preserving an invariant denominator.

    Parents whose docked pose fails the sealed rule set are NEVER dropped from
    `M2` Protocol Calibration: they remain in the split denominator as
    `ObservationStatus.FAILED` (`INTERACTION_RULE_SET_FAILED`, worst-ranked tie)
    so selective filtration can never silently inflate BEDROC20 or EF1%.
    """
    gated: list[ScoreObservation] = []
    for obs in observations:
        if obs.status is not ObservationStatus.SCORED:
            gated.append(
                obs.model_copy(
                    update={"protocol_identity_sha256": gated_protocol_identity_sha256}
                )
            )
            continue

        rule_status = rule_statuses_by_parent.get(obs.parent_compound_id)
        if rule_status is DiagnosticStatus.PASS:
            gated.append(
                obs.model_copy(
                    update={"protocol_identity_sha256": gated_protocol_identity_sha256}
                )
            )
        elif rule_status is DiagnosticStatus.FAIL:
            gated.append(
                ScoreObservation(
                    protocol_identity_sha256=gated_protocol_identity_sha256,
                    parent_compound_id=obs.parent_compound_id,
                    parent_state_id=obs.parent_state_id,
                    pose_complex=obs.pose_complex,
                    scoring_family=obs.scoring_family,
                    scoring_function=obs.scoring_function,
                    direction=obs.direction,
                    unit=obs.unit,
                    tool_name=obs.tool_name,
                    tool_version=obs.tool_version,
                    status=ObservationStatus.FAILED,
                    raw_score=None,
                    failure_code=INTERACTION_RULE_FAILED_CODE,
                )
            )
        else:
            gated.append(
                ScoreObservation(
                    protocol_identity_sha256=gated_protocol_identity_sha256,
                    parent_compound_id=obs.parent_compound_id,
                    parent_state_id=obs.parent_state_id,
                    pose_complex=obs.pose_complex,
                    scoring_family=obs.scoring_family,
                    scoring_function=obs.scoring_function,
                    direction=obs.direction,
                    unit=obs.unit,
                    tool_name=obs.tool_name,
                    tool_version=obs.tool_version,
                    status=ObservationStatus.NOT_EVALUABLE,
                    raw_score=None,
                    failure_code=INTERACTION_RULE_NOT_EVALUABLE_CODE,
                )
            )
    return tuple(gated)
