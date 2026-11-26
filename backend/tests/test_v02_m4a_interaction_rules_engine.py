"""Unit & M2-calibration integration tests for M4a declarative ProLIF rules & Tanimoto IFP.

All contacts, molecules, and docking scores in this module are explicitly labelled
synthetic fixtures chosen to exercise declarative rule semantics, order-invariant
identity hashing, Tanimoto math (including 0/0 empty union), and denominator-invariant
gating inside `ProtocolCalibrationService`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from ankora_backend.adapters.interactions.pharmacophore_rules import (
    INTERACTION_RULE_FAILED_CODE,
    INTERACTION_RULE_NOT_EVALUABLE_CODE,
    apply_interaction_rule_gate_to_observations,
    compute_ifp_tanimoto,
    evaluate_rule_set_against_contacts,
    extract_receptor_residues_from_pdb,
    fingerprint_from_contacts,
    fingerprint_from_explicit_bits,
    validate_residues_against_receptor,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.calibration_store import CalibrationArtifactStore
from ankora_backend.schemas.calibration import (
    CalibrationCandidateProtocol,
    CalibrationCompoundInput,
    CalibrationSplitPolicy,
)
from ankora_backend.schemas.interaction_rules import (
    CreateInteractionRuleSetRequest,
    IfpBit,
    IfpSourceKind,
    InteractionFingerprint,
    InteractionRuleClause,
    InteractionRuleKind,
    InteractionRuleSetRecord,
    InteractionTarget,
    compute_ifp_sha256,
    compute_rule_set_identity_sha256,
)
from ankora_backend.schemas.pose_interactions import InteractionContact, InteractionProfile
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import ReceptorFlexMode, ReceptorFlexSpec, ResidueLocator
from ankora_backend.schemas.screening_benchmark import ScoreDirection
from ankora_backend.schemas.v02_contracts import (
    DiagnosticStatus,
    ObservationStatus,
    PoseComplexIdentity,
    ProtocolSpec,
    ScoreObservation,
    ScoringFamily,
    ScoringFunctionId,
)
from ankora_backend.schemas.warnings import WarningCode
from ankora_backend.services.protocol_calibration import ProtocolCalibrationService

_NOW = datetime(2026, 11, 19, 14, 0, tzinfo=UTC)
_REC_SHA = "a" * 64
_BOX_SHA = "b" * 64

_RES_SER = ResidueLocator(chain_id="A", residue_name="SER", sequence_number=5)
_RES_TYR = ResidueLocator(chain_id="A", residue_name="TYR", sequence_number=12)
_RES_ASP = ResidueLocator(chain_id="A", residue_name="ASP", sequence_number=20)
_RES_LEU = ResidueLocator(chain_id="A", residue_name="LEU", sequence_number=30)


def _contact(
    contact_id: str,
    residue: ResidueLocator,
    detector_type: str,
    distance: float | None = 2.8,
) -> InteractionContact:
    return InteractionContact(
        contact_id=contact_id,
        detector_type=detector_type,
        display_type=detector_type,
        residue=residue,
        distance_angstrom=distance,
    )


def _rule_set(
    *,
    clauses: tuple[InteractionRuleClause, ...] = (),
    reference_ifp: InteractionFingerprint | None = None,
    min_tanimoto: float | None = None,
    profile: InteractionProfile | None = None,
) -> InteractionRuleSetRecord:
    prof = profile or InteractionProfile()
    identity = compute_rule_set_identity_sha256(
        receptor_protonated_sha256=_REC_SHA,
        profile=prof,
        clauses=clauses,
        reference_fingerprint_sha256=(
            reference_ifp.fingerprint_sha256 if reference_ifp is not None else None
        ),
        min_tanimoto_similarity=min_tanimoto,
    )
    return InteractionRuleSetRecord(
        rule_set_id="00000000-0000-0000-0000-000000000401",
        created_at=_NOW,
        name="Synthetic pharmacophore hypothesis",
        receptor_id="00000000-0000-0000-0000-000000000001",
        receptor_protonated_artifact_id="art-prot-pdb",
        receptor_protonated_sha256=_REC_SHA,
        profile=prof,
        clauses=clauses,
        reference_ifp=reference_ifp,
        min_tanimoto_similarity=min_tanimoto,
        rule_set_identity_sha256=identity,
        provenance=ProvenanceEvent(
            event_id="evt-rs-1",
            event_type="interaction_rule_set_created",
            timestamp=_NOW,
            input_artifacts=["art-prot-pdb"],
            output_artifacts=["00000000-0000-0000-0000-000000000401"],
            tool=ToolIdentity(name="ProLIF", version="2.2.1"),
            parameters={},
        ),
    )


def test_rule_set_identity_hash_is_order_invariant() -> None:
    prof = InteractionProfile()
    c1 = InteractionRuleClause(
        clause_id="c-req",
        label="Required hinge H-bond",
        kind=InteractionRuleKind.REQUIRED,
        targets=(
            InteractionTarget(residue=_RES_SER, interaction_types=("HBDonor", "HBAcceptor")),
        ),
    )
    c2 = InteractionRuleClause(
        clause_id="c-or",
        label="Hydrophobic or pi contact",
        kind=InteractionRuleKind.ALTERNATIVE_OR,
        targets=(
            InteractionTarget(residue=_RES_TYR, interaction_types=("FaceToFace", "EdgeToFace")),
            InteractionTarget(residue=_RES_LEU, interaction_types=("Hydrophobic",)),
        ),
        min_satisfied=1,
    )
    c2_swapped = InteractionRuleClause(
        clause_id="c-or",
        label="Hydrophobic or pi contact (reordered)",
        kind=InteractionRuleKind.ALTERNATIVE_OR,
        targets=(
            InteractionTarget(residue=_RES_LEU, interaction_types=("Hydrophobic",)),
            InteractionTarget(residue=_RES_TYR, interaction_types=("EdgeToFace", "FaceToFace")),
        ),
        min_satisfied=1,
    )
    h1 = compute_rule_set_identity_sha256(
        receptor_protonated_sha256=_REC_SHA,
        profile=prof,
        clauses=(c1, c2),
        reference_fingerprint_sha256=None,
        min_tanimoto_similarity=None,
    )
    h2 = compute_rule_set_identity_sha256(
        receptor_protonated_sha256=_REC_SHA,
        profile=prof,
        clauses=(c2_swapped, c1),
        reference_fingerprint_sha256=None,
        min_tanimoto_similarity=None,
    )
    assert h1 == h2


def test_clause_and_request_validation_rejects_ambiguous_definitions() -> None:
    with pytest.raises(ValidationError, match="at least two"):
        InteractionRuleClause(
            clause_id="bad-or",
            label="Single-target OR",
            kind=InteractionRuleKind.ALTERNATIVE_OR,
            targets=(InteractionTarget(residue=_RES_SER, interaction_types=("HBDonor",)),),
        )
    with pytest.raises(ValidationError, match="may only be set on ALTERNATIVE_OR"):
        InteractionRuleClause(
            clause_id="bad-req",
            label="Required with min_satisfied",
            kind=InteractionRuleKind.REQUIRED,
            targets=(InteractionTarget(residue=_RES_SER, interaction_types=("HBDonor",)),),
            min_satisfied=1,
        )
    with pytest.raises(ValidationError, match="Unsupported ProLIF"):
        InteractionTarget(residue=_RES_SER, interaction_types=("NotARealProlifType",))
    with pytest.raises(ValidationError, match="not enabled in the rule set profile"):
        CreateInteractionRuleSetRequest(
            name="Profile mismatch",
            receptor_id="rec-1",
            profile=InteractionProfile(interactions=["HBDonor"]),
            clauses=(
                InteractionRuleClause(
                    clause_id="c1",
                    label="Hydrophobic missing from profile",
                    kind=InteractionRuleKind.REQUIRED,
                    targets=(
                        InteractionTarget(residue=_RES_LEU, interaction_types=("Hydrophobic",)),
                    ),
                ),
            ),
        )
    with pytest.raises(ValidationError, match="requires a reference_pose or reference_bits"):
        CreateInteractionRuleSetRequest(
            name="Dangling threshold",
            receptor_id="rec-1",
            clauses=(
                InteractionRuleClause(
                    clause_id="c1",
                    label="SER H-bond",
                    kind=InteractionRuleKind.REQUIRED,
                    targets=(InteractionTarget(residue=_RES_SER, interaction_types=("HBDonor",)),),
                ),
            ),
            min_tanimoto_similarity=0.5,
        )


def test_required_alternative_or_forbidden_and_distance_cap_evaluation() -> None:
    clauses = (
        InteractionRuleClause(
            clause_id="req-ser",
            label="SER A:5 H-bond within 3.2 A",
            kind=InteractionRuleKind.REQUIRED,
            targets=(
                InteractionTarget(
                    residue=_RES_SER,
                    interaction_types=("HBDonor", "HBAcceptor"),
                    max_distance_angstrom=3.2,
                ),
            ),
        ),
        InteractionRuleClause(
            clause_id="or-pocket",
            label="TYR stacking OR LEU hydrophobic",
            kind=InteractionRuleKind.ALTERNATIVE_OR,
            targets=(
                InteractionTarget(residue=_RES_TYR, interaction_types=("FaceToFace", "EdgeToFace")),
                InteractionTarget(residue=_RES_LEU, interaction_types=("Hydrophobic",)),
            ),
            min_satisfied=1,
        ),
        InteractionRuleClause(
            clause_id="forbid-asp",
            label="No ASP A:20 cationic salt bridge",
            kind=InteractionRuleKind.FORBIDDEN,
            targets=(InteractionTarget(residue=_RES_ASP, interaction_types=("Cationic",)),),
        ),
    )
    rs = _rule_set(clauses=clauses)

    # Case 1: PASS (SER H-bond at 2.75 A + LEU hydrophobic, no ASP cationic)
    outcome_pass = evaluate_rule_set_against_contacts(
        rule_set=rs,
        contacts=[
            _contact("contact-1", _RES_SER, "HBDonor", 2.75),
            _contact("contact-2", _RES_LEU, "Hydrophobic", 3.90),
        ],
    )
    assert outcome_pass.overall_status is DiagnosticStatus.PASS
    assert outcome_pass.passed_clause_count == 3
    assert outcome_pass.failed_clause_count == 0
    assert outcome_pass.clause_results[0].matched_contact_ids == ("contact-1",)
    assert outcome_pass.clause_results[1].matched_contact_ids == ("contact-2",)
    assert outcome_pass.warnings == ()

    # Case 2: FAIL on distance cap (> 3.2 A) AND FORBIDDEN contact triggered
    outcome_fail = evaluate_rule_set_against_contacts(
        rule_set=rs,
        contacts=[
            _contact("contact-1", _RES_SER, "HBDonor", 3.45),
            _contact("contact-2", _RES_LEU, "Hydrophobic", 3.90),
            _contact("contact-3", _RES_ASP, "Cationic", 3.10),
        ],
    )
    assert outcome_fail.overall_status is DiagnosticStatus.FAIL
    assert outcome_fail.passed_clause_count == 1
    assert outcome_fail.failed_clause_count == 2
    assert outcome_fail.clause_results[0].status is DiagnosticStatus.FAIL
    assert outcome_fail.clause_results[2].status is DiagnosticStatus.FAIL
    assert outcome_fail.clause_results[2].matched_contact_ids == ("contact-3",)
    warning_codes = {w.code for w in outcome_fail.warnings}
    assert WarningCode.INTERACTION_RULE_CLAUSES_FAILED in warning_codes
    assert WarningCode.INTERACTION_RULE_FORBIDDEN_CONTACT in warning_codes


def test_tanimoto_ifp_exact_math_and_honest_empty_union() -> None:
    prof = InteractionProfile()
    bit_ser = IfpBit(residue=_RES_SER, interaction_type="HBDonor")
    bit_tyr = IfpBit(residue=_RES_TYR, interaction_type="FaceToFace")
    bit_leu = IfpBit(residue=_RES_LEU, interaction_type="Hydrophobic")

    ref_ifp = fingerprint_from_explicit_bits([bit_ser, bit_tyr], profile=prof)
    pose_ifp_half = fingerprint_from_contacts(
        [
            _contact("c1", _RES_SER, "HBDonor", 2.8),
            _contact("c2", _RES_SER, "HBDonor", 2.9),  # duplicate bit increments count, not union
            _contact("c3", _RES_LEU, "Hydrophobic", 3.8),
        ],
        profile=prof,
    )
    assert len(pose_ifp_half.bits) == 2
    assert dict((e.bit.sort_key(), e.count) for e in pose_ifp_half.counts)[bit_ser.sort_key()] == 2

    # |{SER}| / |{SER, TYR, LEU}| = 1/3
    tanimoto = compute_ifp_tanimoto(
        pose_ifp=pose_ifp_half, reference_ifp=ref_ifp, min_threshold=0.5
    )
    assert tanimoto.intersection_count == 1
    assert tanimoto.union_count == 3
    assert tanimoto.similarity == pytest.approx(1.0 / 3.0)
    assert tanimoto.status is DiagnosticStatus.FAIL
    assert tanimoto.shared_bits == (bit_ser,)
    assert tanimoto.pose_only_bits == (bit_leu,)
    assert tanimoto.reference_only_bits == (bit_tyr,)

    # Empty union 0 / 0 must report similarity=None and NOT_EVALUABLE (never 1.0 or 0.0)
    empty_ifp = InteractionFingerprint(
        profile=prof,
        bits=(),
        counts=(),
        source_kind=IfpSourceKind.EXPLICIT_BITS,
        fingerprint_sha256=compute_ifp_sha256(profile=prof, bits=()),
    )
    rs_empty_ref = _rule_set(reference_ifp=empty_ifp, min_tanimoto=0.5)
    outcome_empty = evaluate_rule_set_against_contacts(rule_set=rs_empty_ref, contacts=[])
    assert outcome_empty.tanimoto is not None
    assert outcome_empty.tanimoto.union_count == 0
    assert outcome_empty.tanimoto.similarity is None
    assert outcome_empty.tanimoto.status is DiagnosticStatus.NOT_EVALUABLE
    assert outcome_empty.overall_status is DiagnosticStatus.NOT_EVALUABLE
    assert any(w.code is WarningCode.INTERACTION_IFP_EMPTY_UNION for w in outcome_empty.warnings)


def test_pdb_residue_validation_fails_closed_on_missing_or_mismatched_residue(
    tmp_path: Path,
) -> None:
    pdb = tmp_path / "synthetic_receptor.pdb"
    pdb.write_text(
        "ATOM      1  CA  SER A   5       0.000   0.000   0.000  1.00  0.00           C  \n"
        "ATOM      2  CA  TYR A  12       4.000   0.000   0.000  1.00  0.00           C  \n"
        "END\n",
        encoding="utf-8",
    )
    residues = extract_receptor_residues_from_pdb(pdb)
    validate_residues_against_receptor(receptor_residues=residues, locators=[_RES_SER, _RES_TYR])

    with pytest.raises(AnkoraDomainError) as exc_info:
        validate_residues_against_receptor(
            receptor_residues=residues,
            locators=[ResidueLocator(chain_id="A", residue_name="ASP", sequence_number=5)],
        )
    assert exc_info.value.code == "INTERACTION_RULE_RESIDUE_NOT_FOUND"
    assert exc_info.value.status_code == 422


def test_sealed_rule_set_integrates_with_m2_calibration_with_invariant_denominator(
    tmp_path: Path,
) -> None:
    """Proves M4 anti-leakage + invariant denominator inside M2 ProtocolCalibrationService.

    1. Sealing a ProtocolSpec with `interaction_rule_set_sha256` pins that exact
       rule set during Calibration.
    2. Parents failing the sealed pharmacophore rule are retained in the denominator
       with `INTERACTION_RULE_SET_FAILED` (never dropped).
    3. Attempting to supply observations tagged with a different rule-set hash when
       unlocking Confirmation fails closed (`422` protocol identity mismatch).
    """
    cores = (
        "c1ccccc1",
        "c1ccc2ccccc2c1",
        "c1ccncc1",
        "C1CCCCC1",
        "c1ccsc1",
        "C1CCNCC1",
        "c1ccc(-c2ccccc2)cc1",
        "c1cnc2ccccc2c1",
    )
    compounds: list[CalibrationCompoundInput] = []
    for fam_idx, core in enumerate(cores):
        for member in range(6):
            tail = "C" * (member + 1)
            compounds.append(
                CalibrationCompoundInput(
                    parent_id=f"synth_f{fam_idx}_m{member}",
                    canonical_smiles=f"{core}{tail}",
                    is_active=(member % 3 == 0),
                )
            )

    service = ProtocolCalibrationService(store=CalibrationArtifactStore(root=tmp_path))
    run = service.create_split(
        project_id="default",
        receptor_id="rec-synth",
        binding_site_id="site-synth",
        compounds=compounds,
        policy=CalibrationSplitPolicy(bootstrap_replicates=150, min_confirmation_actives=4),
    )

    rs = _rule_set(
        clauses=(
            InteractionRuleClause(
                clause_id="req-hinge",
                label="SER A:5 H-bond",
                kind=InteractionRuleKind.REQUIRED,
                targets=(InteractionTarget(residue=_RES_SER, interaction_types=("HBDonor",)),),
            ),
        )
    )
    receptor_spec = ReceptorFlexSpec(
        mode=ReceptorFlexMode.RIGID,
        receptor_rigid_sha256=_REC_SHA,
    )
    base_spec = ProtocolSpec(
        engine="vina",
        scoring_function=ScoringFunctionId.VINA,
        receptor_flexibility=receptor_spec,
        binding_box_sha256=_BOX_SHA,
    )
    gated_spec = ProtocolSpec(
        engine="vina",
        scoring_function=ScoringFunctionId.VINA,
        receptor_flexibility=receptor_spec,
        binding_box_sha256=_BOX_SHA,
        interaction_rule_set_sha256=rs.rule_set_identity_sha256,
    )
    assert base_spec.protocol_identity_sha256 != gated_spec.protocol_identity_sha256

    def _raw_observations(
        parent_ids: tuple[str, ...], spec: ProtocolSpec
    ) -> list[ScoreObservation]:
        active_set = {p.parent_id for p in run.split.compounds if p.is_active}
        out: list[ScoreObservation] = []
        for idx, pid in enumerate(parent_ids):
            score = -8.5 if pid in active_set else -8.6 + (idx * 0.01)
            pose_sha = sha256(f"{pid}-pose".encode()).hexdigest()
            out.append(
                ScoreObservation(
                    protocol_identity_sha256=spec.protocol_identity_sha256,
                    parent_compound_id=pid,
                    parent_state_id=f"{pid}-state-1",
                    pose_complex=PoseComplexIdentity(
                        mode=ReceptorFlexMode.RIGID,
                        receptor_rigid_sha256=_REC_SHA,
                        ligand_pose_sha256=pose_sha,
                    ),
                    scoring_family=ScoringFamily.VINA_VINARDO,
                    scoring_function=ScoringFunctionId.VINA,
                    direction=ScoreDirection.LOWER_IS_BETTER,
                    unit="kcal/mol",
                    tool_name="AutoDock Vina",
                    tool_version="1.2.7",
                    status=ObservationStatus.SCORED,
                    raw_score=score,
                )
            )
        return out

    active_set = {p.parent_id for p in run.split.compounds if p.is_active}
    # Synthetic rule gate passes all actives, fails half the inactives, marks 1 inactive N/E
    cal_ids = run.split.calibration_parent_ids
    conf_ids = run.split.confirmation_parent_ids
    all_ids = cal_ids + conf_ids
    rule_statuses: dict[str, DiagnosticStatus] = {}
    inactive_counter = 0
    for pid in all_ids:
        if pid in active_set:
            rule_statuses[pid] = DiagnosticStatus.PASS
        else:
            inactive_counter += 1
            if inactive_counter == 1:
                rule_statuses[pid] = DiagnosticStatus.NOT_EVALUABLE
            elif inactive_counter % 2 == 0:
                rule_statuses[pid] = DiagnosticStatus.FAIL
            else:
                rule_statuses[pid] = DiagnosticStatus.PASS

    cal_base_obs = _raw_observations(cal_ids, base_spec)
    cal_gated_obs = apply_interaction_rule_gate_to_observations(
        cal_base_obs,
        gated_protocol_identity_sha256=gated_spec.protocol_identity_sha256,
        rule_statuses_by_parent=rule_statuses,
    )
    # Invariant denominator: every parent stays present!
    assert len(cal_gated_obs) == len(cal_base_obs)
    assert any(
        o.status is ObservationStatus.FAILED and o.failure_code == INTERACTION_RULE_FAILED_CODE
        for o in cal_gated_obs
    )
    assert any(
        o.status is ObservationStatus.NOT_EVALUABLE
        and o.failure_code == INTERACTION_RULE_NOT_EVALUABLE_CODE
        for o in cal_gated_obs
    )

    selected = service.select_protocol_on_calibration(
        calibration_id=run.calibration_id,
        baseline_protocol_id="vina_base",
        candidates=(
            CalibrationCandidateProtocol(
                protocol_id="vina_base",
                label="Vina rigid baseline",
                protocol_spec=base_spec,
            ),
            CalibrationCandidateProtocol(
                protocol_id="vina_pic_gated",
                label="Vina + sealed SER A:5 pharmacophore rule",
                protocol_spec=gated_spec,
            ),
        ),
        observations_by_protocol={
            "vina_base": cal_base_obs,
            "vina_pic_gated": list(cal_gated_obs),
        },
    )
    assert selected.calibration_selection is not None
    gated_eval = next(
        ev
        for ev in selected.calibration_selection.evaluations
        if ev.protocol_id == "vina_pic_gated"
    )
    assert gated_eval.failure_census.total_parents == len(cal_ids)
    assert gated_eval.failure_census.failed_inactive_count > 0

    # Leakage guard: mutating interaction_rule_set_sha256 after Calibration fails closed!
    tampered_spec = gated_spec.model_copy(update={"interaction_rule_set_sha256": "f" * 64})
    conf_base_obs = _raw_observations(conf_ids, base_spec)
    tampered_conf_obs = apply_interaction_rule_gate_to_observations(
        conf_base_obs,
        gated_protocol_identity_sha256=tampered_spec.protocol_identity_sha256,
        rule_statuses_by_parent=rule_statuses,
    )
    with pytest.raises(AnkoraDomainError):
        service.evaluate_locked_confirmation(
            calibration_id=run.calibration_id,
            observations_by_protocol={
                "vina_base": conf_base_obs,
                "vina_pic_gated": list(tampered_conf_obs),
            },
        )


def test_pharmacophore_rules_profile_mismatch_duplicate_targets_and_boundary_oracles() -> None:
    """D2-015 + mutation oracles: profile guard, unique targets, exact threshold/distance bounds."""
    prof_hb = InteractionProfile(interactions=["HBDonor"])
    prof_hyd = InteractionProfile(interactions=["Hydrophobic"])
    prof_far = InteractionProfile(interactions=["HBDonor"], vicinity_cutoff_angstrom=8.0)

    ifp_hb = fingerprint_from_explicit_bits(
        [IfpBit(residue=_RES_SER, interaction_type="HBDonor")], profile=prof_hb
    )
    ifp_hyd = fingerprint_from_explicit_bits(
        [IfpBit(residue=_RES_SER, interaction_type="Hydrophobic")], profile=prof_hyd
    )
    ifp_far = fingerprint_from_explicit_bits(
        [IfpBit(residue=_RES_SER, interaction_type="HBDonor")], profile=prof_far
    )

    # 1. Cross-profile IFP Tanimoto comparison must fail closed
    with pytest.raises(AnkoraDomainError) as exc_type:
        compute_ifp_tanimoto(pose_ifp=ifp_hb, reference_ifp=ifp_hyd)
    assert exc_type.value.code == "INTERACTION_IFP_PROFILE_MISMATCH"
    with pytest.raises(AnkoraDomainError) as exc_cut:
        compute_ifp_tanimoto(pose_ifp=ifp_hb, reference_ifp=ifp_far)
    assert exc_cut.value.code == "INTERACTION_IFP_PROFILE_MISMATCH"

    # 2. Duplicate canonical targets in ALTERNATIVE_OR must fail validation
    dup_target = InteractionTarget(residue=_RES_SER, interaction_types=("HBDonor",))
    with pytest.raises(ValidationError, match="targets must be unique"):
        InteractionRuleClause(
            clause_id="dup-or",
            label="Duplicate alternative targets",
            kind=InteractionRuleKind.ALTERNATIVE_OR,
            targets=(dup_target, dup_target),
            min_satisfied=2,
        )

    # 3. Exact Tanimoto threshold boundaries (kills M06, M07, M08, M09)
    prof = InteractionProfile()
    ref_two = fingerprint_from_explicit_bits(
        [
            IfpBit(residue=_RES_SER, interaction_type="HBDonor"),
            IfpBit(residue=_RES_TYR, interaction_type="FaceToFace"),
        ],
        profile=prof,
    )
    pose_one = fingerprint_from_explicit_bits(
        [IfpBit(residue=_RES_SER, interaction_type="HBDonor")],
        profile=prof,
    )
    # similarity == 0.5 exactly
    assert compute_ifp_tanimoto(
        pose_ifp=pose_one, reference_ifp=ref_two, min_threshold=None
    ).status is DiagnosticStatus.PASS
    assert compute_ifp_tanimoto(
        pose_ifp=pose_one, reference_ifp=ref_two, min_threshold=0.5
    ).status is DiagnosticStatus.PASS
    assert compute_ifp_tanimoto(
        pose_ifp=pose_one, reference_ifp=ref_two, min_threshold=0.5 + 1e-13
    ).status is DiagnosticStatus.PASS
    assert compute_ifp_tanimoto(
        pose_ifp=pose_one, reference_ifp=ref_two, min_threshold=0.505
    ).status is DiagnosticStatus.FAIL

    # 4. Exact max_distance_angstrom equality must match (kills M11)
    exact_clause = InteractionRuleClause(
        clause_id="exact-dist",
        label="Exact distance threshold",
        kind=InteractionRuleKind.REQUIRED,
        targets=(
            InteractionTarget(
                residue=_RES_SER, interaction_types=("HBDonor",), max_distance_angstrom=3.0
            ),
        ),
    )
    c_exact = _contact("c-exact", _RES_SER, "HBDonor", 3.0)
    rs_exact = _rule_set(clauses=(exact_clause,), reference_ifp=pose_one, min_tanimoto=0.5)
    out_exact = evaluate_rule_set_against_contacts(rule_set=rs_exact, contacts=[c_exact])
    assert out_exact.overall_status is DiagnosticStatus.PASS
    # Passing Tanimoto must NOT emit INTERACTION_IFP_TANIMOTO_BELOW_THRESHOLD (kills M16)
    assert not any(
        w.code is WarningCode.INTERACTION_IFP_TANIMOTO_BELOW_THRESHOLD for w in out_exact.warnings
    )

    # 5. Empty 0/0 union with passing/failing clauses & optional vs required Tanimoto (kills M20)
    empty_ifp = fingerprint_from_explicit_bits([], profile=prof)
    rs_empty_opt_only_ref = _rule_set(clauses=(), reference_ifp=empty_ifp, min_tanimoto=None)
    out_only_ref = evaluate_rule_set_against_contacts(
        rule_set=rs_empty_opt_only_ref, contacts=[]
    )
    assert out_only_ref.overall_status is DiagnosticStatus.NOT_EVALUABLE

    # Optional empty Tanimoto + non-empty passing FORBIDDEN clause => overall PASS
    forbid_clause = InteractionRuleClause(
        clause_id="forbid-tyr",
        label="No TYR contact",
        kind=InteractionRuleKind.FORBIDDEN,
        targets=(InteractionTarget(residue=_RES_TYR, interaction_types=("FaceToFace",)),),
    )
    rs_empty_opt_with_clause = _rule_set(
        clauses=(forbid_clause,), reference_ifp=empty_ifp, min_tanimoto=None
    )
    out_with_clause = evaluate_rule_set_against_contacts(
        rule_set=rs_empty_opt_with_clause, contacts=[]
    )
    assert out_with_clause.overall_status is DiagnosticStatus.PASS

    # Required empty Tanimoto + passing FORBIDDEN clause => overall NOT_EVALUABLE
    rs_empty_req_with_clause = _rule_set(
        clauses=(forbid_clause,), reference_ifp=empty_ifp, min_tanimoto=0.5
    )
    out_req_with_clause = evaluate_rule_set_against_contacts(
        rule_set=rs_empty_req_with_clause, contacts=[]
    )
    assert out_req_with_clause.overall_status is DiagnosticStatus.NOT_EVALUABLE
