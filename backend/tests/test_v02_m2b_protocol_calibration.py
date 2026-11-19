"""M2b out-of-sample protocol calibration checks.

Everything molecular in this module is a **labelled synthetic fixture**: the
SMILES are generic alkyl-substituted ring systems chosen only because their
Bemis-Murcko scaffolds are distinct and their RDKit descriptors are easy to
match or deliberately shift, and every docking score is an invented number
constructed to place a chosen number of actives at the favorable end of a
ranking.  No value here is, or is derived from, a recorded docking result, and
none of it may be read as evidence about any receptor, ligand, or engine.  The
scenarios exercise the decision logic of `ADR-031` §3 — grouped splitting, the
paired parent bootstrap, the `1-SE` parsimony rule, and the single-use locked
Confirmation split — not the scientific performance of any protocol.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.calibration_store import CalibrationArtifactStore
from ankora_backend.schemas.calibration import (
    ACYCLIC_SCAFFOLD_PREFIX,
    INSUFFICIENT_EVIDENCE_TEXT,
    CalibrationCandidateProtocol,
    CalibrationCompoundInput,
    CalibrationRunRecord,
    CalibrationSplitPolicy,
    ConfirmationVerdict,
    SplitGroupingStrategy,
    interpolated_quantile,
)
from ankora_backend.schemas.receptors import (
    ReceptorFlexMode,
    ReceptorFlexSpec,
    ResidueLocator,
)
from ankora_backend.schemas.screening_benchmark import ScoreDirection
from ankora_backend.schemas.v02_contracts import (
    ObservationStatus,
    PoseComplexIdentity,
    ProtocolSpec,
    ScoreObservation,
    ScoringFamily,
    ScoringFunctionId,
)
from ankora_backend.schemas.warnings import WarningCode
from ankora_backend.services.protocol_calibration import (
    MISSING_OBSERVATION_FAILURE_CODE,
    ProtocolCalibrationService,
    audit_physicochemical_bias,
    extract_compound_properties,
    observations_for_split,
)
from ankora_backend.services.screening_benchmark import _quantile

# Synthetic receptor, flexible side-chain, and box identities.
SYNTHETIC_RIGID_HASH = "a" * 64
SYNTHETIC_FLEX_HASH = "b" * 64
SYNTHETIC_BOX_HASH = "e" * 64

BASELINE_ID = "vina_rigid_base"
FLEX_ID = "vina_flex_2res"

#: Eight synthetic ring systems with eight distinct Bemis-Murcko scaffolds.
SYNTHETIC_CORES: tuple[str, ...] = (
    "c1ccccc1",
    "c1ccc2ccccc2c1",
    "c1ccncc1",
    "C1CCCCC1",
    "c1ccsc1",
    "C1CCNCC1",
    "c1ccc(-c2ccccc2)cc1",
    "c1cnc2ccccc2c1",
)

#: Synthetic acyclic compounds; RDKit returns an empty Murcko scaffold for each.
SYNTHETIC_ACYCLIC_SMILES: tuple[str, ...] = (
    "CCCCCCO",
    "CCCCCCCO",
    "CCCCCCCCO",
    "CCC(=O)NCCC",
    "CCCCC(=O)NCC",
    "CCCCCCC(=O)N",
)

def MATCHED_LABELS(family: int, member: int) -> bool:
    """Property-matched labelling: the active label cycles through chain lengths."""
    return member % 3 == 0


def SHIFTED_LABELS(family: int, member: int) -> bool:
    """Shifted labelling: every active is small, every decoy heavy and greasy."""
    return member < 3


def SINGLE_SCAFFOLD_ACTIVES(family: int, member: int) -> bool:
    """Every active inside one scaffold group, so no leakage-free split exists."""
    return family == 0

#: Fewer replicates than the product default keeps the suite fast while staying
#: above the contract floor; the seed is fixed so every interval is exact.
TEST_POLICY = CalibrationSplitPolicy(bootstrap_replicates=200)


def synthetic_library(
    labeller: Callable[[int, int], bool],
    *,
    families: int = 8,
    members: int = 10,
) -> list[CalibrationCompoundInput]:
    """Build a synthetic parent set of alkyl-substituted ring systems."""
    compounds: list[CalibrationCompoundInput] = []
    for family in range(families):
        core = SYNTHETIC_CORES[family]
        for member in range(members):
            compounds.append(
                CalibrationCompoundInput(
                    parent_id=f"PAR-{family}-{member:02d}",
                    canonical_smiles="C" * (member + 1) + core,
                    is_active=labeller(family, member),
                    state_ids=(f"PAR-{family}-{member:02d}-S1",),
                )
            )
    return compounds


def synthetic_acyclic_library() -> list[CalibrationCompoundInput]:
    return [
        CalibrationCompoundInput(
            parent_id=f"ACY-{index:02d}",
            canonical_smiles=smiles,
            is_active=index % 3 == 0,
        )
        for index, smiles in enumerate(SYNTHETIC_ACYCLIC_SMILES)
    ]


def rigid_candidate() -> CalibrationCandidateProtocol:
    return CalibrationCandidateProtocol(
        protocol_id=BASELINE_ID,
        label="Synthetic Vina rigid receptor",
        protocol_spec=ProtocolSpec(
            engine="vina",
            scoring_function=ScoringFunctionId.VINA,
            receptor_flexibility=ReceptorFlexSpec(
                receptor_rigid_sha256=SYNTHETIC_RIGID_HASH
            ),
            binding_box_sha256=SYNTHETIC_BOX_HASH,
            random_seed=7,
        ),
    )


def flex_candidate(
    *, protocol_id: str = FLEX_ID, residues: int = 2, torsions: int = 6
) -> CalibrationCandidateProtocol:
    locators = (
        ResidueLocator(chain_id="A", residue_name="LYS", sequence_number=101),
        ResidueLocator(chain_id="A", residue_name="ARG", sequence_number=271),
        ResidueLocator(chain_id="A", residue_name="THR", sequence_number=333),
    )[:residues]
    return CalibrationCandidateProtocol(
        protocol_id=protocol_id,
        label=f"Synthetic Vina {residues}-residue FlexRes",
        protocol_spec=ProtocolSpec(
            engine="vina",
            scoring_function=ScoringFunctionId.VINA,
            receptor_flexibility=ReceptorFlexSpec(
                mode=ReceptorFlexMode.SIDECHAIN_FLEX,
                flex_residues=locators,
                receptor_rigid_sha256=SYNTHETIC_RIGID_HASH,
                receptor_flex_sha256=SYNTHETIC_FLEX_HASH,
                added_chi_torsion_count=torsions,
            ),
            binding_box_sha256=SYNTHETIC_BOX_HASH,
            random_seed=7,
        ),
        added_chi_torsion_count=torsions,
    )


def synthetic_scores(
    parent_ids: Sequence[str],
    active_parent_ids: frozenset[str],
    *,
    top_actives: int,
    tag: str,
) -> dict[str, float]:
    """Invent `kcal/mol`-shaped scores that promote `top_actives` actives.

    The promoted actives are taken in `parent_id` order, so two protocols that
    promote overlapping counts differ only by the extra actives one of them
    lifted.  Everything else is ordered by a tag-seeded digest, which is a
    deterministic stand-in for an uninformative ranking.
    """
    actives = sorted(parent for parent in parent_ids if parent in active_parent_ids)
    others = sorted(parent for parent in parent_ids if parent not in active_parent_ids)
    promoted = actives[:top_actives]
    remainder = sorted(
        actives[top_actives:] + others,
        key=lambda parent: sha256(f"{tag}:{parent}".encode()).hexdigest(),
    )
    scores = {parent: -14.0 + 0.01 * index for index, parent in enumerate(promoted)}
    scores.update({parent: -10.0 + 0.01 * index for index, parent in enumerate(remainder)})
    return scores


def synthetic_observations(
    candidate: CalibrationCandidateProtocol, scores: Mapping[str, float]
) -> list[ScoreObservation]:
    mode = candidate.protocol_spec.receptor_flexibility.mode
    return [
        ScoreObservation(
            protocol_identity_sha256=candidate.protocol_spec.protocol_identity_sha256,
            parent_compound_id=parent,
            parent_state_id=f"{parent}-S1",
            pose_complex=PoseComplexIdentity(
                mode=mode,
                receptor_rigid_sha256=SYNTHETIC_RIGID_HASH,
                pose_flex_sidechains_sha256=(
                    SYNTHETIC_FLEX_HASH if mode is ReceptorFlexMode.SIDECHAIN_FLEX else None
                ),
                ligand_pose_sha256=sha256(parent.encode()).hexdigest(),
            ),
            scoring_family=ScoringFamily.VINA_VINARDO,
            scoring_function=ScoringFunctionId.VINA,
            direction=ScoreDirection.LOWER_IS_BETTER,
            unit="kcal/mol",
            tool_name="vina",
            tool_version="synthetic-fixture",
            status=ObservationStatus.SCORED,
            raw_score=score,
        )
        for parent, score in sorted(scores.items())
    ]


def unscored_observation(
    candidate: CalibrationCandidateProtocol, parent: str, failure_code: str
) -> ScoreObservation:
    return ScoreObservation(
        protocol_identity_sha256=candidate.protocol_spec.protocol_identity_sha256,
        parent_compound_id=parent,
        parent_state_id=f"{parent}-S1",
        scoring_family=ScoringFamily.VINA_VINARDO,
        scoring_function=ScoringFunctionId.VINA,
        direction=ScoreDirection.LOWER_IS_BETTER,
        unit="kcal/mol",
        tool_name="vina",
        tool_version="synthetic-fixture",
        status=ObservationStatus.FAILED,
        failure_code=failure_code,
    )


@pytest.fixture
def store(tmp_path: Path) -> CalibrationArtifactStore:
    return CalibrationArtifactStore.for_project_root(tmp_path / "project")


@pytest.fixture
def service(store: CalibrationArtifactStore) -> ProtocolCalibrationService:
    return ProtocolCalibrationService(store)


def locked_split(
    service: ProtocolCalibrationService,
    *,
    labeller: Callable[[int, int], bool] = MATCHED_LABELS,
    policy: CalibrationSplitPolicy = TEST_POLICY,
    compounds: Sequence[CalibrationCompoundInput] | None = None,
) -> CalibrationRunRecord:
    return service.create_split(
        project_id="synthetic-project",
        receptor_id="synthetic-receptor",
        binding_site_id="synthetic-site",
        compounds=list(compounds) if compounds is not None else synthetic_library(labeller),
        policy=policy,
        created_at=datetime(2026, 11, 19, 12, 0, tzinfo=UTC),
    )


# -- 1. Parent and Bemis-Murcko scaffold grouping -------------------------


def test_split_groups_parents_and_scaffolds_without_leakage(
    service: ProtocolCalibrationService,
) -> None:
    split = locked_split(service).split

    assert split.policy.grouping_strategy is SplitGroupingStrategy.PARENT_AND_MURCKO_SCAFFOLD
    assert not set(split.calibration_parent_ids) & set(split.confirmation_parent_ids)
    assert not set(split.calibration_scaffolds) & set(split.confirmation_scaffolds)
    assert len(split.calibration_parent_ids) + len(split.confirmation_parent_ids) == 80
    assert split.calibration_active_count >= 1
    assert split.calibration_inactive_count >= 1
    assert split.confirmation_active_count >= 1
    assert split.confirmation_inactive_count >= 1

    # Every parent of a scaffold group travels with its group.
    side_by_scaffold = {scaffold: "calibration" for scaffold in split.calibration_scaffolds}
    side_by_scaffold.update(
        {scaffold: "confirmation" for scaffold in split.confirmation_scaffolds}
    )
    calibration = set(split.calibration_parent_ids)
    for profile in split.compounds:
        expected = "calibration" if profile.parent_id in calibration else "confirmation"
        assert side_by_scaffold[profile.murcko_scaffold] == expected

    # The calibration side lands near the declared fraction on both axes.
    total_actives = split.calibration_active_count + split.confirmation_active_count
    assert abs(len(split.calibration_parent_ids) / 80 - 0.6) <= 0.15
    assert abs(split.calibration_active_count / total_actives - 0.6) <= 0.15


def test_split_is_invariant_under_input_permutation(
    service: ProtocolCalibrationService, store: CalibrationArtifactStore
) -> None:
    compounds = synthetic_library(MATCHED_LABELS)
    first = locked_split(service, compounds=compounds).split
    reversed_order = locked_split(
        service,
        compounds=sorted(
            compounds,
            key=lambda compound: sha256(compound.parent_id.encode()).hexdigest(),
        ),
    ).split

    assert first.split_identity_sha256 == reversed_order.split_identity_sha256
    assert first.calibration_parent_ids == reversed_order.calibration_parent_ids
    assert first.confirmation_parent_ids == reversed_order.confirmation_parent_ids
    assert first.compounds == reversed_order.compounds
    assert len(store.list_runs()) == 2


def test_acyclic_compounds_keep_their_own_scaffold_group(
    service: ProtocolCalibrationService,
) -> None:
    compounds = synthetic_acyclic_library()
    profiles = extract_compound_properties(compounds)

    assert all(profile.is_acyclic for profile in profiles)
    assert {profile.murcko_scaffold for profile in profiles} == {
        f"{ACYCLIC_SCAFFOLD_PREFIX}{compound.parent_id}" for compound in compounds
    }

    split = locked_split(service, compounds=compounds).split
    assert len(split.calibration_scaffolds) + len(split.confirmation_scaffolds) == len(compounds)
    assert not set(split.calibration_scaffolds) & set(split.confirmation_scaffolds)


def test_split_fails_closed_when_every_active_shares_one_scaffold(
    service: ProtocolCalibrationService,
) -> None:
    with pytest.raises(AnkoraDomainError) as error:
        locked_split(service, labeller=SINGLE_SCAFFOLD_ACTIVES)

    assert error.value.code == "CALIBRATION_SPLIT_INFEASIBLE"
    assert error.value.details["active_scaffold_group_count"] == 1


def test_invalid_smiles_fails_closed() -> None:
    with pytest.raises(AnkoraDomainError) as error:
        extract_compound_properties(
            [
                CalibrationCompoundInput(
                    parent_id="PAR-OK", canonical_smiles="c1ccccc1", is_active=True
                ),
                CalibrationCompoundInput(
                    parent_id="PAR-BAD", canonical_smiles="not-a-smiles", is_active=False
                ),
            ]
        )

    assert error.value.code == "CALIBRATION_INVALID_SMILES"
    assert error.value.details["parent_id"] == "PAR-BAD"


def test_duplicate_parent_identifier_fails_closed() -> None:
    compound = CalibrationCompoundInput(
        parent_id="PAR-DUP", canonical_smiles="c1ccccc1", is_active=True
    )
    with pytest.raises(AnkoraDomainError) as error:
        extract_compound_properties([compound, compound])

    assert error.value.code == "CALIBRATION_DUPLICATE_PARENT_ID"


# -- 2. Physicochemical decoy bias audit ----------------------------------


def test_property_matched_decoys_are_not_flagged(service: ProtocolCalibrationService) -> None:
    record = locked_split(service, labeller=MATCHED_LABELS)
    audit = record.split.bias_audit

    assert audit.any_bias_flagged is False
    assert audit.flagged_properties == ()
    assert {metric.property_name for metric in audit.metrics} == {
        "molecular_weight",
        "clogp",
        "hbd",
        "hba",
        "rotatable_bonds",
        "formal_charge",
    }
    assert all(abs(metric.standardized_mean_difference) < 0.5 for metric in audit.metrics)
    assert not any(
        warning.code is WarningCode.CALIBRATION_DECOY_PROPERTY_BIAS
        for warning in record.warnings
    )


def test_shifted_decoys_are_flagged_and_warned(service: ProtocolCalibrationService) -> None:
    record = locked_split(service, labeller=SHIFTED_LABELS)
    audit = record.split.bias_audit

    assert audit.any_bias_flagged is True
    assert "molecular_weight" in audit.flagged_properties
    assert "clogp" in audit.flagged_properties
    warning = next(
        item for item in record.warnings
        if item.code is WarningCode.CALIBRATION_DECOY_PROPERTY_BIAS
    )
    assert warning.details["flagged_properties"] == list(audit.flagged_properties)

    # The audit is symmetric in sign only: heavy decoys push the active-minus-
    # inactive difference negative on both size and lipophilicity.
    by_name = {metric.property_name: metric for metric in audit.metrics}
    assert by_name["molecular_weight"].standardized_mean_difference < -0.5
    assert by_name["clogp"].standardized_mean_difference < -0.5
    assert by_name["formal_charge"].flagged_bias is False


def test_bias_audit_needs_both_classes() -> None:
    profiles = extract_compound_properties(
        [
            CalibrationCompoundInput(
                parent_id="PAR-A", canonical_smiles="c1ccccc1", is_active=True
            ),
            CalibrationCompoundInput(
                parent_id="PAR-B", canonical_smiles="Cc1ccccc1", is_active=False
            ),
            CalibrationCompoundInput(
                parent_id="PAR-C", canonical_smiles="CCc1ccccc1", is_active=False
            ),
        ]
    )
    with pytest.raises(AnkoraDomainError) as error:
        audit_physicochemical_bias(profiles)

    assert error.value.code == "CALIBRATION_BIAS_AUDIT_INFEASIBLE"


def test_underpowered_confirmation_is_warned(service: ProtocolCalibrationService) -> None:
    record = locked_split(
        service, compounds=synthetic_library(MATCHED_LABELS, families=4, members=4)
    )

    assert record.split.confirmation_active_count < record.split.policy.min_confirmation_actives
    assert record.split.confirmation_underpowered is True
    warning = next(
        item for item in record.warnings
        if item.code is WarningCode.CALIBRATION_CONFIRMATION_UNDERPOWERED
    )
    assert warning.details["min_confirmation_actives"] == 10


# -- 3. Denominator invariance and the active/inactive failure census -----


def test_failed_and_missing_observations_stay_in_the_denominator(
    service: ProtocolCalibrationService,
) -> None:
    split = locked_split(service).split
    candidate = rigid_candidate()
    parents = split.calibration_parent_ids
    actives = sorted(parent for parent in parents if parent in split.active_parent_ids)
    inactives = sorted(parent for parent in parents if parent not in split.active_parent_ids)

    # Two actives fail, two actives go missing entirely, three decoys fail.
    scored = {
        parent: -9.0 - 0.01 * index
        for index, parent in enumerate(parents)
        if parent not in actives[:4] + inactives[:3]
    }
    observations = synthetic_observations(candidate, scored)
    observations.extend(
        unscored_observation(candidate, parent, "MEEKO_CONNECTIVITY_FAILURE")
        for parent in actives[:2]
    )
    observations.extend(
        unscored_observation(candidate, parent, "LIG_3D_COORDINATES_MISSING")
        for parent in inactives[:3]
    )

    rows, census = observations_for_split(
        candidate=candidate,
        observations=observations,
        split_parent_ids=parents,
        active_parent_ids=split.active_parent_ids,
    )

    assert len(rows) == len(parents)
    assert tuple(row.parent_id for row in rows) == tuple(sorted(parents))
    assert census.total_parents == len(parents)
    assert census.failed_active_count == 4
    assert census.failed_inactive_count == 3
    assert census.scored_active_count == split.calibration_active_count - 4
    assert census.scored_inactive_count == split.calibration_inactive_count - 3
    assert census.failure_codes_active == {
        "MEEKO_CONNECTIVITY_FAILURE": 2,
        MISSING_OBSERVATION_FAILURE_CODE: 2,
    }
    assert census.failure_codes_inactive == {"LIG_3D_COORDINATES_MISSING": 3}
    # Every unscored parent forms one worst-ranked tie group, never a dropped row.
    assert all(row.score is None for row in rows if row.parent_id in actives[:4])


def test_confirmation_parents_never_reach_a_calibration_evaluation(
    service: ProtocolCalibrationService,
) -> None:
    split = locked_split(service).split
    candidate = rigid_candidate()
    leaked = synthetic_scores(
        split.confirmation_parent_ids, split.active_parent_ids, top_actives=12, tag="leak"
    )

    rows, census = observations_for_split(
        candidate=candidate,
        observations=synthetic_observations(candidate, leaked),
        split_parent_ids=split.calibration_parent_ids,
        active_parent_ids=split.active_parent_ids,
    )

    assert len(rows) == len(split.calibration_parent_ids)
    assert census.scored_count == 0
    assert census.failed_count == len(split.calibration_parent_ids)


def test_duplicate_parent_observation_fails_closed(
    service: ProtocolCalibrationService,
) -> None:
    split = locked_split(service).split
    candidate = rigid_candidate()
    scores = synthetic_scores(
        split.calibration_parent_ids, split.active_parent_ids, top_actives=8, tag="dup"
    )
    observations = synthetic_observations(candidate, scores)
    # A second microstate of one parent would otherwise become an unrecorded
    # best-of-K selection.
    observations.append(observations[0].model_copy(update={"raw_score": -20.0}))

    with pytest.raises(AnkoraDomainError) as error:
        observations_for_split(
            candidate=candidate,
            observations=observations,
            split_parent_ids=split.calibration_parent_ids,
            active_parent_ids=split.active_parent_ids,
        )

    assert error.value.code == "CALIBRATION_DUPLICATE_PARENT_OBSERVATION"


def test_mismatched_protocol_identity_fails_closed(
    service: ProtocolCalibrationService,
) -> None:
    split = locked_split(service).split
    rigid = rigid_candidate()
    flex = flex_candidate()
    scores = synthetic_scores(
        split.calibration_parent_ids, split.active_parent_ids, top_actives=8, tag="mismatch"
    )

    with pytest.raises(AnkoraDomainError) as error:
        observations_for_split(
            candidate=rigid,
            observations=synthetic_observations(flex, scores),
            split_parent_ids=split.calibration_parent_ids,
            active_parent_ids=split.active_parent_ids,
        )

    assert error.value.code == "CALIBRATION_PROTOCOL_IDENTITY_MISMATCH"
    assert (
        error.value.details["expected_protocol_identity_sha256"]
        == rigid.protocol_spec.protocol_identity_sha256
    )


# -- 4. Null hypothesis / Type I error sanity check -----------------------


def test_tied_protocols_record_the_exact_null_verdict(
    service: ProtocolCalibrationService,
) -> None:
    record = locked_split(service)
    rigid, flex = rigid_candidate(), flex_candidate()
    split = record.split

    calibration = synthetic_scores(
        split.calibration_parent_ids, split.active_parent_ids, top_actives=9, tag="null"
    )
    selected = service.select_protocol_on_calibration(
        calibration_id=record.calibration_id,
        baseline_protocol_id=BASELINE_ID,
        candidates=[rigid, flex],
        observations_by_protocol={
            BASELINE_ID: synthetic_observations(rigid, calibration),
            FLEX_ID: synthetic_observations(flex, calibration),
        },
    )
    selection = selected.calibration_selection
    assert selection is not None
    # Exactly tied protocols are separated only by parsimony, so the rigid
    # receptor wins and nothing was "preferred".
    assert selection.best_point_protocol_id == BASELINE_ID
    assert selection.selected_protocol_id == BASELINE_ID
    assert selection.selected_by_one_se_parsimony is False

    confirmation_scores = synthetic_scores(
        split.confirmation_parent_ids, split.active_parent_ids, top_actives=5, tag="null"
    )
    completed = service.evaluate_locked_confirmation(
        calibration_id=record.calibration_id,
        observations_by_protocol={
            BASELINE_ID: synthetic_observations(rigid, confirmation_scores),
            FLEX_ID: synthetic_observations(flex, confirmation_scores),
        },
    )
    evaluation = completed.confirmation_evaluation
    assert evaluation is not None
    assert evaluation.verdict is ConfirmationVerdict.INSUFFICIENT_EVIDENCE
    assert evaluation.verdict_text == "Insufficient evidence to prefer over baseline"
    delta = evaluation.paired_delta_vs_baseline
    assert delta.ci_lower <= 0.0 <= delta.ci_upper
    assert delta.excludes_zero_positively is False


def test_equal_quality_random_rankings_do_not_separate_from_zero(
    service: ProtocolCalibrationService,
) -> None:
    record = locked_split(service)
    rigid, flex = rigid_candidate(), flex_candidate()
    split = record.split

    selected = service.select_protocol_on_calibration(
        calibration_id=record.calibration_id,
        baseline_protocol_id=BASELINE_ID,
        candidates=[rigid, flex],
        observations_by_protocol={
            BASELINE_ID: synthetic_observations(
                rigid,
                synthetic_scores(
                    split.calibration_parent_ids,
                    split.active_parent_ids,
                    top_actives=6,
                    tag="rigid-noise",
                ),
            ),
            FLEX_ID: synthetic_observations(
                flex,
                synthetic_scores(
                    split.calibration_parent_ids,
                    split.active_parent_ids,
                    top_actives=6,
                    tag="flex-noise",
                ),
            ),
        },
    )
    selection = selected.calibration_selection
    assert selection is not None
    flex_vs_baseline = next(
        delta
        for delta in selection.deltas_vs_baseline
        if delta.candidate_protocol_id == FLEX_ID
    )
    assert flex_vs_baseline.bootstrap_se > 0.0
    assert flex_vs_baseline.ci_lower <= 0.0 <= flex_vs_baseline.ci_upper
    assert flex_vs_baseline.excludes_zero_positively is False
    # Two equally informative rankings cannot justify the costlier protocol.
    assert selection.selected_protocol_id == BASELINE_ID


# -- 5. Rigid versus FlexRes: three synthetic scenarios -------------------


def _run_scenario(
    service: ProtocolCalibrationService,
    *,
    calibration_rigid_top: int,
    calibration_flex_top: int,
    confirmation_rigid_top: int,
    confirmation_flex_top: int,
    policy: CalibrationSplitPolicy = TEST_POLICY,
) -> CalibrationRunRecord:
    record = locked_split(service, policy=policy)
    rigid, flex = rigid_candidate(), flex_candidate()
    split = record.split

    service.select_protocol_on_calibration(
        calibration_id=record.calibration_id,
        baseline_protocol_id=BASELINE_ID,
        candidates=[rigid, flex],
        observations_by_protocol={
            BASELINE_ID: synthetic_observations(
                rigid,
                synthetic_scores(
                    split.calibration_parent_ids,
                    split.active_parent_ids,
                    top_actives=calibration_rigid_top,
                    tag="calibration",
                ),
            ),
            FLEX_ID: synthetic_observations(
                flex,
                synthetic_scores(
                    split.calibration_parent_ids,
                    split.active_parent_ids,
                    top_actives=calibration_flex_top,
                    tag="calibration",
                ),
            ),
        },
    )
    return service.evaluate_locked_confirmation(
        calibration_id=record.calibration_id,
        observations_by_protocol={
            BASELINE_ID: synthetic_observations(
                rigid,
                synthetic_scores(
                    split.confirmation_parent_ids,
                    split.active_parent_ids,
                    top_actives=confirmation_rigid_top,
                    tag="confirmation",
                ),
            ),
            FLEX_ID: synthetic_observations(
                flex,
                synthetic_scores(
                    split.confirmation_parent_ids,
                    split.active_parent_ids,
                    top_actives=confirmation_flex_top,
                    tag="confirmation",
                ),
            ),
        },
    )


def test_scenario_a_noisy_flexres_inside_one_se_retains_the_rigid_baseline(
    service: ProtocolCalibrationService,
) -> None:
    """FlexRes scores marginally higher, but not beyond the paired noise."""
    completed = _run_scenario(
        service,
        calibration_rigid_top=3,
        calibration_flex_top=4,
        confirmation_rigid_top=3,
        confirmation_flex_top=4,
    )
    selection = completed.calibration_selection
    evaluation = completed.confirmation_evaluation
    assert selection is not None
    assert evaluation is not None

    by_id = {item.protocol_id: item for item in selection.evaluations}
    assert by_id[FLEX_ID].metrics.bedroc > by_id[BASELINE_ID].metrics.bedroc
    assert selection.best_point_protocol_id == FLEX_ID

    baseline_delta = next(
        delta for delta in selection.deltas_vs_best if delta.candidate_protocol_id == BASELINE_ID
    )
    assert baseline_delta.reference_protocol_id == FLEX_ID
    assert baseline_delta.within_one_se_of_reference is True
    assert -baseline_delta.point_delta <= baseline_delta.bootstrap_se

    assert selection.selected_protocol_id == BASELINE_ID
    assert selection.selected_by_one_se_parsimony is True
    assert evaluation.verdict is ConfirmationVerdict.BASELINE_RETAINED_BY_ONE_SE
    assert evaluation.verdict_text.startswith("Baseline protocol retained by 1-SE parsimony")


def test_scenario_b_calibration_overfit_fails_on_locked_confirmation(
    service: ProtocolCalibrationService,
) -> None:
    """FlexRes earns selection on Calibration and then does not replicate."""
    completed = _run_scenario(
        service,
        calibration_rigid_top=2,
        calibration_flex_top=10,
        confirmation_rigid_top=8,
        confirmation_flex_top=1,
    )
    selection = completed.calibration_selection
    evaluation = completed.confirmation_evaluation
    assert selection is not None
    assert evaluation is not None

    baseline_delta = next(
        delta for delta in selection.deltas_vs_best if delta.candidate_protocol_id == BASELINE_ID
    )
    assert baseline_delta.within_one_se_of_reference is False
    assert selection.selected_protocol_id == FLEX_ID
    assert selection.selected_by_one_se_parsimony is False

    delta = evaluation.paired_delta_vs_baseline
    assert delta.candidate_protocol_id == FLEX_ID
    assert delta.reference_protocol_id == BASELINE_ID
    assert delta.point_delta < 0.0
    assert delta.excludes_zero_positively is False
    assert evaluation.verdict is ConfirmationVerdict.INSUFFICIENT_EVIDENCE
    assert evaluation.verdict_text == "Insufficient evidence to prefer over baseline"
    # The negative evidence is retained, not discarded.
    assert evaluation.selected_evaluation.metrics.bedroc < (
        evaluation.baseline_evaluation.metrics.bedroc
    )
    assert completed.status == "confirmation_completed"

    # A top-1% cut over 50 and then 30 parents retains a single parent, so the
    # enrichment factor is explicitly flagged rather than quietly reported.
    assert evaluation.selected_evaluation.metrics.top_count == 1
    assert evaluation.selected_evaluation.ef_small_sample_caution is True
    caution_splits = {
        warning.details["split_name"]
        for warning in completed.warnings
        if warning.code is WarningCode.CALIBRATION_SMALL_SAMPLE_EF_CAUTION
    }
    assert caution_splits == {"calibration", "confirmation"}


def test_scenario_c_genuine_induced_fit_gain_is_preferred(
    service: ProtocolCalibrationService,
) -> None:
    """FlexRes wins beyond one SE on Calibration and replicates on Confirmation."""
    completed = _run_scenario(
        service,
        calibration_rigid_top=2,
        calibration_flex_top=10,
        confirmation_rigid_top=1,
        confirmation_flex_top=8,
    )
    selection = completed.calibration_selection
    evaluation = completed.confirmation_evaluation
    assert selection is not None
    assert evaluation is not None

    assert selection.selected_protocol_id == FLEX_ID
    delta = evaluation.paired_delta_vs_baseline
    assert delta.point_delta > 0.0
    assert delta.ci_lower > 0.0
    assert delta.excludes_zero_positively is True
    assert completed.split.confirmation_underpowered is False
    assert evaluation.verdict is ConfirmationVerdict.PREFERRED_OVER_BASELINE
    assert FLEX_ID in evaluation.verdict_text


def test_underpowered_confirmation_cannot_prefer_a_protocol(
    service: ProtocolCalibrationService,
) -> None:
    """An underpowered Confirmation split can only return the null verdict.

    The scores are Scenario C's, so the paired interval does exclude zero
    positively; the verdict is still the ADR-031 null phrase because the
    declared minimum number of confirmation actives was not met.
    """
    completed = _run_scenario(
        service,
        calibration_rigid_top=2,
        calibration_flex_top=10,
        confirmation_rigid_top=1,
        confirmation_flex_top=8,
        policy=CalibrationSplitPolicy(
            bootstrap_replicates=200, min_confirmation_actives=20
        ),
    )
    selection = completed.calibration_selection
    evaluation = completed.confirmation_evaluation
    assert selection is not None
    assert evaluation is not None

    assert completed.split.confirmation_underpowered is True
    assert selection.selected_protocol_id == FLEX_ID
    assert evaluation.paired_delta_vs_baseline.excludes_zero_positively is True
    assert evaluation.verdict is ConfirmationVerdict.INSUFFICIENT_EVIDENCE
    assert evaluation.verdict_text == INSUFFICIENT_EVIDENCE_TEXT


# -- 6. Fail-closed stage guards ------------------------------------------


def test_confirmation_before_selection_fails_closed(
    service: ProtocolCalibrationService,
) -> None:
    record = locked_split(service)
    with pytest.raises(AnkoraDomainError) as error:
        service.evaluate_locked_confirmation(
            calibration_id=record.calibration_id, observations_by_protocol={}
        )

    assert error.value.code == "CALIBRATION_SELECTION_REQUIRED"
    assert error.value.status_code == 409


def test_selection_cannot_be_resealed(service: ProtocolCalibrationService) -> None:
    record = locked_split(service)
    rigid = rigid_candidate()
    split = record.split
    observations = {
        BASELINE_ID: synthetic_observations(
            rigid,
            synthetic_scores(
                split.calibration_parent_ids,
                split.active_parent_ids,
                top_actives=5,
                tag="seal",
            ),
        )
    }
    service.select_protocol_on_calibration(
        calibration_id=record.calibration_id,
        baseline_protocol_id=BASELINE_ID,
        candidates=[rigid],
        observations_by_protocol=observations,
    )
    with pytest.raises(AnkoraDomainError) as error:
        service.select_protocol_on_calibration(
            calibration_id=record.calibration_id,
            baseline_protocol_id=BASELINE_ID,
            candidates=[rigid],
            observations_by_protocol=observations,
        )

    assert error.value.code == "CALIBRATION_SELECTION_ALREADY_SEALED"
    assert error.value.status_code == 409


def test_confirmation_cannot_be_consumed_twice(service: ProtocolCalibrationService) -> None:
    completed = _run_scenario(
        service,
        calibration_rigid_top=2,
        calibration_flex_top=10,
        confirmation_rigid_top=1,
        confirmation_flex_top=8,
    )
    rigid, flex = rigid_candidate(), flex_candidate()
    split = completed.split
    with pytest.raises(AnkoraDomainError) as error:
        service.evaluate_locked_confirmation(
            calibration_id=completed.calibration_id,
            observations_by_protocol={
                BASELINE_ID: synthetic_observations(
                    rigid,
                    synthetic_scores(
                        split.confirmation_parent_ids,
                        split.active_parent_ids,
                        top_actives=0,
                        tag="retry",
                    ),
                ),
                FLEX_ID: synthetic_observations(
                    flex,
                    synthetic_scores(
                        split.confirmation_parent_ids,
                        split.active_parent_ids,
                        top_actives=12,
                        tag="retry",
                    ),
                ),
            },
        )

    assert error.value.code == "CALIBRATION_CONFIRMATION_ALREADY_CONSUMED"
    assert error.value.status_code == 409


def test_baseline_must_be_a_candidate(service: ProtocolCalibrationService) -> None:
    record = locked_split(service)
    flex = flex_candidate()
    with pytest.raises(AnkoraDomainError) as error:
        service.select_protocol_on_calibration(
            calibration_id=record.calibration_id,
            baseline_protocol_id=BASELINE_ID,
            candidates=[flex],
            observations_by_protocol={FLEX_ID: []},
        )

    assert error.value.code == "CALIBRATION_BASELINE_NOT_A_CANDIDATE"


def test_unknown_calibration_id_is_not_found(store: CalibrationArtifactStore) -> None:
    with pytest.raises(AnkoraDomainError) as error:
        store.get_run("00000000-0000-4000-8000-000000000000")

    assert error.value.code == "CALIBRATION_NOT_FOUND"
    assert error.value.status_code == 404


def test_path_traversal_identifier_is_rejected(store: CalibrationArtifactStore) -> None:
    with pytest.raises(AnkoraDomainError) as error:
        store.get_run("../../escape")

    assert error.value.code == "CALIBRATION_NOT_FOUND"


# -- 7. Persistence round-trip and the ADR-031 dependency budget ----------


def test_persistence_round_trip(
    service: ProtocolCalibrationService, store: CalibrationArtifactStore
) -> None:
    completed = _run_scenario(
        service,
        calibration_rigid_top=2,
        calibration_flex_top=10,
        confirmation_rigid_top=1,
        confirmation_flex_top=8,
    )
    reloaded = store.get_run(completed.calibration_id)

    assert reloaded == completed
    assert reloaded.confirmation_locked is False
    assert reloaded.confirmation_consumed is True
    assert reloaded.split.split_identity_sha256 == completed.split.split_identity_sha256

    directory = store.root / completed.calibration_id
    assert sorted(path.name for path in directory.iterdir()) == [
        "confirmation.json",
        "record.json",
        "selection.json",
        "split.json",
    ]

    listed = store.list_runs()
    assert [item.calibration_id for item in listed] == [completed.calibration_id]

    # A second run is listed newest first.
    later = service.create_split(
        project_id="synthetic-project",
        receptor_id="synthetic-receptor",
        binding_site_id="synthetic-site",
        compounds=synthetic_library(MATCHED_LABELS),
        policy=TEST_POLICY,
        created_at=datetime(2026, 11, 20, 12, 0, tzinfo=UTC),
    )
    assert [item.calibration_id for item in store.list_runs()] == [
        later.calibration_id,
        completed.calibration_id,
    ]


def test_create_run_refuses_to_overwrite(
    service: ProtocolCalibrationService, store: CalibrationArtifactStore
) -> None:
    record = locked_split(service)
    with pytest.raises(AnkoraDomainError) as error:
        store.create_run(record)

    assert error.value.code == "CALIBRATION_ALREADY_EXISTS"
    assert error.value.status_code == 409


M2B_SOURCE_FILES: tuple[str, ...] = (
    "backend/src/ankora_backend/schemas/calibration.py",
    "backend/src/ankora_backend/persistence/calibration_store.py",
    "backend/src/ankora_backend/services/protocol_calibration.py",
)

#: `ADR-031` budgets `0` bytes for M2, so the only third-party roots these
#: modules may reach are distributions already pinned in both platform locks.
ALLOWED_THIRD_PARTY_ROOTS = frozenset({"pydantic", "rdkit", "scipy", "numpy"})


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "import_module"
        ):
            roots.update(
                argument.value.split(".")[0]
                for argument in node.args
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
            )
    return roots


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_m2b_modules_introduce_no_new_dependency() -> None:
    repository = _repository_root()
    for relative in M2B_SOURCE_FILES:
        roots = _imported_roots(repository / relative)
        third_party = roots - set(sys.stdlib_module_names) - {"ankora_backend"}
        assert third_party <= ALLOWED_THIRD_PARTY_ROOTS, (relative, sorted(third_party))


def test_scientific_toolkits_are_only_reached_lazily() -> None:
    repository = _repository_root()
    for relative in M2B_SOURCE_FILES:
        tree = ast.parse((repository / relative).read_text(encoding="utf-8"))
        statically_imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                statically_imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                statically_imported.add(node.module.split(".")[0])
        assert not statically_imported & {"rdkit", "scipy", "numpy"}, relative


def test_percentile_convention_matches_the_v01_benchmark() -> None:
    samples = [0.1, 0.4, 0.25, 0.9, 0.55, 0.05, 0.7]
    for probability in (0.0, 0.025, 0.25, 0.5, 0.975, 1.0):
        assert interpolated_quantile(samples, probability) == _quantile(
            sorted(samples), probability
        )


def test_parsimony_rank_key_orders_simpler_protocols_first() -> None:
    rigid = rigid_candidate()
    flex_one = flex_candidate(protocol_id="flex_1res", residues=1, torsions=3)
    flex_two = flex_candidate(protocol_id="flex_2res", residues=2, torsions=6)
    flex_two_fitted = CalibrationCandidateProtocol.model_validate(
        {**flex_two.model_dump(), "protocol_id": "flex_2res_fitted", "fitted_parameter_count": 4}
    )
    flex_two_consensus = CalibrationCandidateProtocol.model_validate(
        {
            **flex_two_fitted.model_dump(),
            "protocol_id": "flex_2res_consensus",
            "engine_count": 3,
        }
    )
    flex_two_neural = CalibrationCandidateProtocol.model_validate(
        {
            **flex_two_consensus.model_dump(),
            "protocol_id": "flex_2res_neural",
            "is_neural_scoring": True,
        }
    )

    ordered = sorted(
        [flex_two_neural, flex_two, rigid, flex_two_consensus, flex_one, flex_two_fitted],
        key=lambda candidate: candidate.parsimony_rank_key,
    )
    assert [candidate.protocol_id for candidate in ordered] == [
        BASELINE_ID,
        "flex_1res",
        "flex_2res",
        "flex_2res_fitted",
        "flex_2res_consensus",
        "flex_2res_neural",
    ]
    assert rigid.is_sidechain_flex is False
    assert flex_two.is_sidechain_flex is True
    assert flex_two.flex_residue_count == 2
