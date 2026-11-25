"""M0 contract checks using synthetic identities, scores, and records."""

import json
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.autogrid import AutoGridMapSetRecord
from ankora_backend.schemas.receptors import ReceptorPreparationRequest, ResidueLocator
from ankora_backend.schemas.screening_benchmark import ScoreDirection, ScreeningBenchmarkObservation
from ankora_backend.schemas.v02_contracts import (
    ConformationalStrainDiagnostic,
    DiagnosticStatus,
    LigandFlexibilitySpec,
    MacrocyclePolicy,
    ObservationStatus,
    PoseAssessment,
    PoseComplexIdentity,
    PoseDiagnosticCheck,
    ProtocolSpec,
    RankingArtifact,
    RankingEntry,
    RankingMethod,
    ReceptorFlexMode,
    ReceptorFlexSpec,
    ScoreObservation,
    ScoringFamily,
    ScoringFunctionId,
    canonical_contract_sha256,
)
from ankora_backend.services.project_dependencies import ProjectDependencyService

RIGID_HASH = "a" * 64
FLEX_HASH = "b" * 64
LIGAND_HASH = "c" * 64
MAP_HASH = "d" * 64
BOX_HASH = "e" * 64
PANEL_HASH = "f" * 64


def _updated[Model: BaseModel](model: Model, **changes: object) -> Model:
    return type(model).model_validate({**model.model_dump(), **changes})


def _lys(sequence: int, insertion_code: str = "") -> ResidueLocator:
    return ResidueLocator(
        chain_id="A", residue_name="LYS", sequence_number=sequence, insertion_code=insertion_code
    )


def _contract(request: pytest.FixtureRequest, name: str) -> BaseModel:
    model = request.getfixturevalue(name)
    assert isinstance(model, BaseModel)
    return model


@pytest.fixture
def ligand_flex() -> LigandFlexibilitySpec:
    return LigandFlexibilitySpec()


@pytest.fixture
def receptor_flex() -> ReceptorFlexSpec:
    return ReceptorFlexSpec(
        mode=ReceptorFlexMode.SIDECHAIN_FLEX,
        flex_residues=(_lys(12, "B"), _lys(9), _lys(12)),
        receptor_rigid_sha256=RIGID_HASH,
        receptor_flex_sha256=FLEX_HASH,
    )


@pytest.fixture
def protocol(receptor_flex: ReceptorFlexSpec) -> ProtocolSpec:
    return ProtocolSpec(
        engine="vina",
        scoring_function=ScoringFunctionId.AUTODOCK4,
        receptor_flexibility=receptor_flex,
        binding_box_sha256=BOX_HASH,
        autogrid_map_set_sha256=MAP_HASH,
    )


@pytest.fixture
def pose() -> PoseComplexIdentity:
    return PoseComplexIdentity(
        mode=ReceptorFlexMode.SIDECHAIN_FLEX,
        receptor_rigid_sha256=RIGID_HASH,
        pose_flex_sidechains_sha256=FLEX_HASH,
        ligand_pose_sha256=LIGAND_HASH,
    )


@pytest.fixture
def observation(protocol: ProtocolSpec, pose: PoseComplexIdentity) -> ScoreObservation:
    return ScoreObservation(
        protocol_identity_sha256=protocol.protocol_identity_sha256,
        parent_compound_id="synthetic-parent",
        parent_state_id="synthetic-state",
        pose_complex=pose,
        scoring_family=ScoringFamily.AUTODOCK4,
        scoring_function=ScoringFunctionId.AUTODOCK4,
        direction=ScoreDirection.LOWER_IS_BETTER,
        unit="kcal/mol",
        tool_name="synthetic tool",
        tool_version="1",
        status=ObservationStatus.SCORED,
        raw_score=-4.0,
    )


@pytest.fixture
def check() -> PoseDiagnosticCheck:
    return PoseDiagnosticCheck(
        check_id="synthetic-distance",
        tool_name="synthetic tool",
        tool_version="1",
        status=DiagnosticStatus.PASS,
        value=0.5,
        threshold=1.0,
    )


@pytest.fixture
def strain() -> ConformationalStrainDiagnostic:
    return ConformationalStrainDiagnostic(
        parent_state_id="synthetic-state",
        hydrogen_policy="synthetic policy",
        conformer_seed=42,
        conformer_budget=1,
        pose_restrained_energy_kcal_mol=2.0,
        lowest_free_conformer_energy_kcal_mol=3.0,
        delta_e_ref_kcal_mol=-1.0,
    )


@pytest.fixture
def assessment(
    pose: PoseComplexIdentity, check: PoseDiagnosticCheck, strain: ConformationalStrainDiagnostic
) -> PoseAssessment:
    return PoseAssessment(
        pose_complex=pose, overall_status=DiagnosticStatus.PASS, checks=(check,), strain=strain
    )


@pytest.fixture
def ranked(pose: PoseComplexIdentity) -> RankingEntry:
    return RankingEntry(
        parent_compound_id="synthetic-ranked-parent",
        parent_state_id="synthetic-ranked-state",
        tier="full_profile",
        rank=1,
        score_value=0.7,
        percentile=100.0,
        inter_family_disagreement=0.2,
        search_convergence_count=2,
        search_engine_count=2,
        selected_pose_complex=pose,
    )


@pytest.fixture
def unranked() -> RankingEntry:
    return RankingEntry(
        parent_compound_id="synthetic-unranked-parent",
        parent_state_id="synthetic-unranked-state",
        tier="partial_or_unscored",
        failure_or_exclusion_codes=("SYNTHETIC_TOOL_FAILURE",),
    )


@pytest.fixture
def ranking(ranked: RankingEntry, unranked: RankingEntry) -> RankingArtifact:
    return RankingArtifact(
        method=RankingMethod.SINGLE_ENGINE,
        tie_policy="shared rank",
        failure_policy="retain unranked parents",
        total_parents=2,
        full_profile_count=1,
        partial_or_unscored_count=1,
        entries=(ranked, unranked),
    )


@pytest.mark.parametrize(
    "fixture_name",
    (
        "ligand_flex",
        "receptor_flex",
        "protocol",
        "pose",
        "observation",
        "check",
        "strain",
        "assessment",
        "ranked",
        "unranked",
        "ranking",
    ),
)
def test_contracts_round_trip_and_reject_mutation_and_extra_fields(
    request: pytest.FixtureRequest, fixture_name: str
) -> None:
    model = _contract(request, fixture_name)
    assert type(model).model_validate_json(model.model_dump_json()) == model
    with pytest.raises(ValidationError, match="extra_forbidden"):
        _updated(model, unexpected_field=True)
    field = next(iter(type(model).model_fields))
    with pytest.raises(ValidationError, match="frozen_instance"):
        setattr(model, field, getattr(model, field))


@pytest.mark.parametrize("fixture_name", ("protocol", "observation", "assessment", "ranking"))
def test_versioned_contracts_reject_unknown_versions(
    request: pytest.FixtureRequest, fixture_name: str
) -> None:
    model = _contract(request, fixture_name)
    assert model.model_dump()["schema_version"] == 1
    with pytest.raises(ValidationError, match="schema_version"):
        _updated(model, schema_version=2)


@pytest.mark.parametrize(
    ("fixture_name", "field"),
    (
        ("receptor_flex", "receptor_rigid_sha256"),
        ("receptor_flex", "receptor_flex_sha256"),
        ("pose", "receptor_rigid_sha256"),
        ("pose", "pose_flex_sidechains_sha256"),
        ("pose", "ligand_pose_sha256"),
        ("protocol", "binding_box_sha256"),
        ("protocol", "autogrid_map_set_sha256"),
        ("protocol", "interaction_rule_set_sha256"),
        ("observation", "protocol_identity_sha256"),
        ("ranking", "reference_panel_sha256"),
    ),
)
@pytest.mark.parametrize(
    "invalid_hash", ("a" * 63, "a" * 65, "A" * 64, "g" * 64, RIGID_HASH + "\n")
)
def test_all_hash_fields_require_exact_lowercase_hex(
    request: pytest.FixtureRequest, fixture_name: str, field: str, invalid_hash: str
) -> None:
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        _updated(_contract(request, fixture_name), **{field: invalid_hash})


@pytest.mark.parametrize(
    ("fixture_name", "field"),
    (
        ("check", "check_id"),
        ("check", "tool_name"),
        ("check", "tool_version"),
        ("strain", "parent_state_id"),
        ("strain", "hydrogen_policy"),
        ("ranked", "parent_compound_id"),
        ("ranked", "parent_state_id"),
        ("ranking", "tie_policy"),
        ("ranking", "failure_policy"),
        ("observation", "parent_compound_id"),
        ("observation", "parent_state_id"),
        ("observation", "unit"),
        ("observation", "tool_name"),
        ("observation", "tool_version"),
    ),
)
def test_provenance_strings_are_trimmed_and_non_blank(
    request: pytest.FixtureRequest, fixture_name: str, field: str
) -> None:
    model = _contract(request, fixture_name)
    for blank in ("", " \t\n "):
        with pytest.raises(ValidationError, match=field):
            _updated(model, **{field: blank})
    value = model.model_dump()[field]
    assert _updated(model, **{field: f" \t{value}\n "}) == model


def test_ranking_exclusion_code_items_are_trimmed_and_non_blank(unranked: RankingEntry) -> None:
    code = unranked.failure_or_exclusion_codes[0]
    for blank in ("", " \t\n "):
        with pytest.raises(ValidationError, match=r"failure_or_exclusion_codes\.1"):
            _updated(unranked, failure_or_exclusion_codes=(code, blank))
    assert _updated(unranked, failure_or_exclusion_codes=(f" \t{code}\n ",)) == unranked


@pytest.mark.parametrize(
    ("fixture_name", "field"),
    (
        ("observation", "raw_score"),
        ("check", "value"),
        ("check", "threshold"),
        ("strain", "pose_restrained_energy_kcal_mol"),
        ("strain", "lowest_free_conformer_energy_kcal_mol"),
        ("strain", "delta_e_ref_kcal_mol"),
        ("ranked", "score_value"),
        ("ranked", "percentile"),
        ("ranked", "inter_family_disagreement"),
    ),
)
@pytest.mark.parametrize("value", (float("nan"), float("inf"), float("-inf")))
def test_numeric_evidence_rejects_non_finite_values(
    request: pytest.FixtureRequest, fixture_name: str, field: str, value: float
) -> None:
    with pytest.raises(ValidationError, match="finite_number"):
        _updated(_contract(request, fixture_name), **{field: value})


def test_canonical_contract_sha256_sorts_keys_and_encodes_utf8(check: PoseDiagnosticCheck) -> None:
    first: dict[str, object] = {"z": [{"b": False, "a": "é"}], "a": 2}
    second: dict[str, object] = {"a": 2, "z": [{"a": "é", "b": False}]}
    expected = sha256(b'{"a":2,"z":[{"a":"\xc3\xa9","b":false}]}').hexdigest()
    assert canonical_contract_sha256(first) == canonical_contract_sha256(second) == expected
    assert canonical_contract_sha256(check) == canonical_contract_sha256(
        check.model_dump(mode="json")
    )
    with pytest.raises(ValueError, match="Out of range float"):
        canonical_contract_sha256({"score": float("nan")})


def test_ligand_bonds_are_independent_of_smarts(ligand_flex: LigandFlexibilitySpec) -> None:
    assert ligand_flex.macrocycle_policy is MacrocyclePolicy.FLEXIBLE_PSEUDOATOMS
    explicit = _updated(ligand_flex, rigidified_bond_indices=((1, 4),))
    assert explicit.rigidified_smarts == ()
    combined = _updated(explicit, rigidified_smarts=("  [#6]-[#7]  ",))
    assert combined.rigidified_smarts == ("[#6]-[#7]",)
    assert combined.rigidified_bond_indices == explicit.rigidified_bond_indices == ((1, 4),)


@pytest.mark.parametrize("smarts", ("", " \t "))
def test_ligand_smarts_cannot_be_blank(smarts: str) -> None:
    with pytest.raises(ValidationError, match="rigidified_smarts"):
        LigandFlexibilitySpec(rigidified_smarts=(smarts,))


@pytest.mark.parametrize("pairs", (((0, 1),), ((1, -2),), ((2, 2),), ((1, 2), (2, 1))))
def test_ligand_bond_pairs_must_be_positive_distinct_and_unique(
    pairs: tuple[tuple[int, int], ...],
) -> None:
    with pytest.raises(ValidationError):
        LigandFlexibilitySpec(rigidified_bond_indices=pairs)


@pytest.mark.parametrize(
    "field", ("flex_residues", "receptor_flex_sha256", "added_chi_torsion_count")
)
def test_rigid_receptor_rejects_each_flex_field(field: str) -> None:
    additions: dict[str, object] = {
        "flex_residues": (_lys(9),),
        "receptor_flex_sha256": FLEX_HASH,
        "added_chi_torsion_count": 1,
    }
    rigid = ReceptorFlexSpec(receptor_rigid_sha256=RIGID_HASH)
    assert rigid.canonical_flex_locators() == ()
    with pytest.raises(ValidationError, match="Rigid receptors"):
        _updated(rigid, **{field: additions[field]})


@pytest.mark.parametrize("changes", ({"flex_residues": ()}, {"receptor_flex_sha256": None}))
def test_flexible_receptor_requires_residues_and_flex_hash(
    receptor_flex: ReceptorFlexSpec, changes: dict[str, object]
) -> None:
    with pytest.raises(ValidationError, match="requires flex residues and a flex hash"):
        _updated(receptor_flex, **changes)


@pytest.mark.parametrize("name", ("GLY", "ALA", "PRO", "CYX", "gLy"))
def test_disallowed_flexible_residue_names_are_case_insensitive(
    receptor_flex: ReceptorFlexSpec, name: str
) -> None:
    residue = ResidueLocator(chain_id="A", sequence_number=1, residue_name=name)
    with pytest.raises(ValidationError, match="disallowed"):
        _updated(receptor_flex, flex_residues=(residue,))


def test_flexible_residue_positions_must_be_unique_even_with_different_names(
    receptor_flex: ReceptorFlexSpec,
) -> None:
    lys = _lys(12, "B")
    arg = _updated(lys, residue_name="ARG")
    with pytest.raises(ValidationError, match="unique positions"):
        _updated(receptor_flex, flex_residues=(lys, arg))


def test_flexible_residue_locators_are_frozen_snapshots(receptor_flex: ReceptorFlexSpec) -> None:
    legacy = _lys(9)
    receptor = _updated(receptor_flex, flex_residues=(legacy,))
    legacy.sequence_number = 19
    assert receptor.canonical_flex_locators() == (("A", "LYS", 9, ""),)
    with pytest.raises(ValidationError, match="frozen_instance"):
        receptor.flex_residues[0].sequence_number = 19


@pytest.mark.parametrize(
    ("residues", "torsions", "warn"), ((4, 12, False), (5, 12, True), (4, 13, True))
)
def test_high_dof_is_advisory_above_either_threshold(
    receptor_flex: ReceptorFlexSpec, residues: int, torsions: int, warn: bool
) -> None:
    model = _updated(
        receptor_flex,
        flex_residues=tuple(_lys(i) for i in range(1, residues + 1)),
        added_chi_torsion_count=torsions,
    )
    assert model.high_dof_warning_required is warn


@pytest.mark.parametrize(
    ("engine", "valid_functions"),
    (
        ("vina", {"vina", "vinardo", "autodock4"}),
        ("autodock4", {"autodock4"}),
        ("autodock_gpu", {"autodock4"}),
        (
            "gnina",
            {"gnina_cnn_score", "gnina_cnn_affinity", "gnina_cnn_vs", "gnina_minimized_affinity"},
        ),
    ),
)
@pytest.mark.parametrize("function", tuple(ScoringFunctionId))
def test_engine_scoring_pairings(
    protocol: ProtocolSpec, engine: str, valid_functions: set[str], function: ScoringFunctionId
) -> None:
    if function in valid_functions:
        assert (
            _updated(protocol, engine=engine, scoring_function=function).scoring_function
            is function
        )
    else:
        with pytest.raises(ValidationError, match="Scoring function"):
            _updated(protocol, engine=engine, scoring_function=function)


@pytest.mark.parametrize("engine", ("vina", "autodock4", "autodock_gpu"))
def test_autodock4_scoring_requires_maps_for_every_engine(
    protocol: ProtocolSpec, engine: str
) -> None:
    with pytest.raises(ValidationError, match="requires an AutoGrid map-set hash"):
        _updated(protocol, engine=engine, autogrid_map_set_sha256=None)


def test_protocol_identity_ignores_residue_selection_order(protocol: ProtocolSpec) -> None:
    receptor = protocol.receptor_flexibility
    reordered = _updated(receptor, flex_residues=tuple(reversed(receptor.flex_residues)))
    assert (
        reordered.canonical_flex_locators()
        == receptor.canonical_flex_locators()
        == (("A", "LYS", 9, ""), ("A", "LYS", 12, ""), ("A", "LYS", 12, "B"))
    )
    equivalent = _updated(protocol, receptor_flexibility=reordered)
    assert equivalent.protocol_identity_sha256 == protocol.protocol_identity_sha256
    canonical_receptor = _updated(receptor, flex_residues=(_lys(9), _lys(12), _lys(12, "B")))
    canonical = _updated(protocol, receptor_flexibility=canonical_receptor)
    assert canonical_contract_sha256(canonical) == protocol.protocol_identity_sha256
    changed = _updated(protocol, receptor_flexibility=_updated(receptor, flex_residues=(_lys(9),)))
    assert changed.protocol_identity_sha256 != protocol.protocol_identity_sha256
    assert (
        _updated(protocol, random_seed=1).protocol_identity_sha256
        != protocol.protocol_identity_sha256
    )


@pytest.mark.parametrize(
    "changes",
    (
        {"rigidified_bond_indices": ((3, 5), (1, 4))},
        {"rigidified_bond_indices": ((4, 1), (5, 3))},
        {"rigidified_smarts": ("[#6]-[#8]", "[#6]-[#7]")},
    ),
)
def test_protocol_identity_ignores_ligand_selection_order(
    protocol: ProtocolSpec, changes: dict[str, object]
) -> None:
    ligand = LigandFlexibilitySpec(
        rigidified_bond_indices=((1, 4), (3, 5)),
        rigidified_smarts=("[#6]-[#7]", "[#6]-[#8]"),
    )
    canonical = _updated(protocol, ligand_flexibility=ligand)
    reordered = _updated(canonical, ligand_flexibility=_updated(ligand, **changes))
    assert reordered.protocol_identity_sha256 == canonical.protocol_identity_sha256
    assert canonical.protocol_identity_sha256 != protocol.protocol_identity_sha256


def test_e7_flex_locator_keys_and_map_binding_ignore_residue_name_case(
    protocol: ProtocolSpec,
) -> None:
    lys = _lys(9)
    arg = _updated(_lys(12, "B"), residue_name="ARG")
    lowercase_arg = _updated(arg, residue_name="arg")
    receptor = _updated(protocol.receptor_flexibility, flex_residues=(lys, arg))
    lowercase_receptor = _updated(receptor, flex_residues=(lowercase_arg, lys))
    assert (
        lowercase_receptor.canonical_flex_locators()
        == receptor.canonical_flex_locators()
        == (("A", "ARG", 12, "B"), ("A", "LYS", 9, ""))
    )
    _updated(protocol, receptor_flexibility=lowercase_receptor).verify_autogrid_map_binding(
        map_receptor_sha256=RIGID_HASH, map_flex_residues=(lys, arg)
    )


def test_e7_accepts_matching_map_binding(protocol: ProtocolSpec) -> None:
    protocol.verify_autogrid_map_binding(
        map_receptor_sha256=RIGID_HASH, map_flex_residues=(_lys(9), _lys(12), _lys(12, "B"))
    )
    rigid = _updated(
        protocol, receptor_flexibility=ReceptorFlexSpec(receptor_rigid_sha256=RIGID_HASH)
    )
    rigid.verify_autogrid_map_binding(map_receptor_sha256=RIGID_HASH)
    with pytest.raises(AnkoraDomainError, match="must match"):
        rigid.verify_autogrid_map_binding(
            map_receptor_sha256=RIGID_HASH, map_flex_residues=(_lys(9),)
        )


@pytest.mark.parametrize("case", ("full_receptor", "missing", "different", "duplicate"))
def test_e7_rejects_reused_full_receptor_maps_and_wrong_flex_residues(
    protocol: ProtocolSpec, case: str
) -> None:
    matching = protocol.receptor_flexibility.flex_residues
    cases = {
        "full_receptor": ("0" * 64, matching),
        "missing": (RIGID_HASH, ()),
        "different": (RIGID_HASH, (_lys(9), _lys(12), _lys(12, "C"))),
        "duplicate": (RIGID_HASH, (*matching, matching[0])),
    }
    receptor_hash, residues = cases[case]
    with pytest.raises(AnkoraDomainError) as caught:
        protocol.verify_autogrid_map_binding(
            map_receptor_sha256=receptor_hash, map_flex_residues=residues
        )
    assert caught.value.code == "AUTOGRID_FLEXRES_MAP_MISMATCH"
    assert caught.value.stage == "protocol_contract"
    assert caught.value.status_code == 422


def test_e8_pose_identity_changes_when_sidechains_move(pose: PoseComplexIdentity) -> None:
    rigid = _updated(pose, mode=ReceptorFlexMode.RIGID, pose_flex_sidechains_sha256=None)
    moved = _updated(pose, pose_flex_sidechains_sha256="0" * 64)
    assert rigid.ligand_pose_sha256 == pose.ligand_pose_sha256 == moved.ligand_pose_sha256
    assert len({item.complex_identity_sha256 for item in (rigid, pose, moved)}) == 3
    assert pose.complex_identity_sha256 == canonical_contract_sha256(pose)
    with pytest.raises(ValidationError, match="pose flex-sidechains hash"):
        _updated(pose, mode=ReceptorFlexMode.RIGID)
    with pytest.raises(ValidationError, match="pose flex-sidechains hash"):
        _updated(pose, pose_flex_sidechains_sha256=None)


@pytest.mark.parametrize(
    ("family", "valid_functions"),
    (
        (ScoringFamily.VINA_VINARDO, {"vina", "vinardo"}),
        (ScoringFamily.AUTODOCK4, {"autodock4"}),
        (
            ScoringFamily.GNINA_NEURAL,
            {"gnina_cnn_score", "gnina_cnn_affinity", "gnina_cnn_vs", "gnina_minimized_affinity"},
        ),
    ),
)
@pytest.mark.parametrize("function", tuple(ScoringFunctionId))
def test_observation_scoring_families(
    observation: ScoreObservation,
    family: ScoringFamily,
    valid_functions: set[str],
    function: ScoringFunctionId,
) -> None:
    if function in valid_functions:
        assert (
            _updated(observation, scoring_family=family, scoring_function=function).scoring_family
            is family
        )
    else:
        with pytest.raises(ValidationError, match="scoring family"):
            _updated(observation, scoring_family=family, scoring_function=function)


@pytest.mark.parametrize(
    "changes", ({"raw_score": None}, {"pose_complex": None}, {"failure_code": ""})
)
def test_scored_observations_require_score_and_pose_and_forbid_failure(
    observation: ScoreObservation, changes: dict[str, object]
) -> None:
    assert _updated(observation, raw_score=0.0).raw_score == 0.0
    with pytest.raises(ValidationError, match="Scored observations"):
        _updated(observation, **changes)


@pytest.mark.parametrize("status", (ObservationStatus.FAILED, ObservationStatus.NOT_EVALUABLE))
def test_unscored_observations_retain_a_failure_code(
    observation: ScoreObservation, status: ObservationStatus
) -> None:
    unscored = _updated(
        observation,
        status=status,
        pose_complex=None,
        raw_score=None,
        failure_code="SYNTHETIC_TOOL_FAILURE",
    )
    assert unscored.status is status
    for changes in (
        {"raw_score": 0.0},
        {"failure_code": None},
        {"failure_code": ""},
        {"failure_code": " "},
    ):
        with pytest.raises(ValidationError, match="require a failure code and no raw score"):
            _updated(unscored, **changes)


def test_strain_accepts_negative_delta_and_requires_consistent_finite_arithmetic(
    strain: ConformationalStrainDiagnostic,
) -> None:
    assert strain.delta_e_ref_kcal_mol == -1.0
    assert _updated(strain, delta_e_ref_kcal_mol=-1.0000005).delta_e_ref_kcal_mol < 0
    with pytest.raises(ValidationError, match="must equal restrained minus free energy"):
        _updated(strain, delta_e_ref_kcal_mol=-0.999998)
    with pytest.raises(ValidationError, match="must equal restrained minus free energy"):
        _updated(
            strain,
            pose_restrained_energy_kcal_mol=1.7e308,
            lowest_free_conformer_energy_kcal_mol=-1.7e308,
        )
    with pytest.raises(ValidationError, match="conformer_budget"):
        _updated(strain, conformer_budget=0)


def test_assessment_requires_unique_checks_and_preserved_pose(assessment: PoseAssessment) -> None:
    assert assessment.mutated_original_pose is False
    with pytest.raises(ValidationError, match="must be unique"):
        _updated(assessment, checks=assessment.checks * 2)
    with pytest.raises(ValidationError, match="at least 1"):
        _updated(assessment, checks=())
    with pytest.raises(ValidationError, match="mutated_original_pose"):
        _updated(assessment, mutated_original_pose=True)


@pytest.mark.parametrize("field", ("rank", "score_value", "selected_pose_complex"))
def test_full_profile_entry_requires_rank_score_and_pose(ranked: RankingEntry, field: str) -> None:
    with pytest.raises(ValidationError, match="Full-profile entries require"):
        _updated(ranked, **{field: None})


def test_partial_entry_requires_exclusion_code_and_must_be_unranked(unranked: RankingEntry) -> None:
    for changes in ({"rank": 1}, {"failure_or_exclusion_codes": ()}):
        with pytest.raises(ValidationError, match="require an exclusion reason and no rank"):
            _updated(unranked, **changes)


@pytest.mark.parametrize("field", ("score_value", "percentile", "inter_family_disagreement"))
def test_e6_partial_entry_rejects_consensus_metrics(unranked: RankingEntry, field: str) -> None:
    with pytest.raises(ValidationError, match="cannot carry consensus metrics"):
        _updated(unranked, **{field: 0.0})


@pytest.mark.parametrize("fixture_name", ("ranked", "unranked"))
@pytest.mark.parametrize("missing_field", ("search_convergence_count", "search_engine_count"))
def test_e6_search_convergence_and_engine_counts_must_be_paired(
    request: pytest.FixtureRequest, fixture_name: str, missing_field: str
) -> None:
    with_counts = _updated(
        _contract(request, fixture_name), search_convergence_count=0, search_engine_count=2
    )
    with pytest.raises(ValidationError, match="must be provided together"):
        _updated(with_counts, **{missing_field: None})


@pytest.mark.parametrize(
    "changes",
    (
        {"rank": 0},
        {"percentile": -0.1},
        {"percentile": 100.1},
        {"inter_family_disagreement": -0.1},
        {"search_engine_count": 0},
        {"search_convergence_count": -1},
        {"search_convergence_count": 3},
    ),
)
def test_ranking_entry_enforces_metric_bounds(
    ranked: RankingEntry, changes: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        _updated(ranked, **changes)


@pytest.mark.parametrize(
    "method", tuple(method for method in RankingMethod if method is not RankingMethod.SINGLE_ENGINE)
)
def test_consensus_ranking_requires_reference_panel(
    ranking: RankingArtifact, method: RankingMethod
) -> None:
    with pytest.raises(ValidationError, match="require a reference panel hash"):
        _updated(ranking, method=method)
    assert (
        _updated(ranking, method=method, reference_panel_sha256=PANEL_HASH).reference_panel_sha256
        == PANEL_HASH
    )


def test_e6_rejects_wrong_tier_and_rank_order(
    ranking: RankingArtifact, ranked: RankingEntry, unranked: RankingEntry
) -> None:
    with pytest.raises(ValidationError, match="must precede"):
        _updated(ranking, entries=(unranked, ranked))
    second = _updated(ranked, parent_compound_id="synthetic-second-ranked-parent", rank=2)
    third = _updated(ranked, parent_compound_id="synthetic-third-ranked-parent")
    with pytest.raises(ValidationError, match="non-decreasing"):
        _updated(
            ranking,
            total_parents=4,
            full_profile_count=3,
            entries=(ranked, second, third, unranked),
        )
    tie = _updated(second, rank=ranked.rank)
    for next_entry in (second, tie):
        assert (
            _updated(
                ranking,
                total_parents=3,
                full_profile_count=2,
                entries=(ranked, next_entry, unranked),
            ).total_parents
            == 3
        )


@pytest.mark.parametrize("ranks", ((2, 2, 3), (1, 3, 3), (1, 1, 4)))
def test_e6_full_profile_rank_cannot_exceed_row_position(
    ranking: RankingArtifact, ranked: RankingEntry, unranked: RankingEntry, ranks: tuple[int, ...]
) -> None:
    full_profile = tuple(
        _updated(ranked, parent_compound_id=f"synthetic-ranked-parent-{idx}", rank=rank)
        for idx, rank in enumerate(ranks, start=1)
    )
    with pytest.raises(ValidationError, match="cannot exceed its row position"):
        _updated(ranking, total_parents=4, full_profile_count=3, entries=(*full_profile, unranked))


def test_e6_keeps_unique_parents_and_all_entries_in_denominator(
    ranking: RankingArtifact,
    ranked: RankingEntry,
    unranked: RankingEntry,
) -> None:
    with pytest.raises(ValidationError, match="unique parent compound IDs"):
        _updated(
            ranking,
            entries=(ranked, _updated(unranked, parent_compound_id=ranked.parent_compound_id)),
        )
    with pytest.raises(ValidationError, match="Total parents"):
        _updated(ranking, entries=(ranked,))
    with pytest.raises(ValidationError, match="Total parents"):
        _updated(ranking, total_parents=3)
    with pytest.raises(ValidationError, match="Total parents"):
        _updated(ranking, partial_or_unscored_count=0)
    with pytest.raises(ValidationError, match="tier counts must match"):
        _updated(ranking, full_profile_count=2, partial_or_unscored_count=0)
    assert (
        _updated(
            ranking, total_parents=1, full_profile_count=0, entries=(unranked,)
        ).partial_or_unscored_count
        == 1
    )


def test_v01_receptor_request_and_screening_observation_deserialize() -> None:
    receptor = ReceptorPreparationRequest.model_validate_json("""{
        "selected_chains": ["A"], "water_action": "remove", "component_decisions": [],
        "issue_decisions": [{"issue_id": "synthetic-issue", "action": "leave"}]
    }""")
    assert receptor.selected_chains == ["A"]
    assert receptor.repair_method == "legacy"
    assert receptor.inspection_method == "reported_only"
    assert {"repair_method", "repair_seed", "inspection_method"}.isdisjoint(receptor.model_dump())
    assert ReceptorPreparationRequest.model_validate_json(receptor.model_dump_json()) == receptor

    for result in (
        {"score": -1.0, "failure_code": None},
        {"score": None, "failure_code": "SYNTHETIC_FAILURE"},
    ):
        legacy = {
            "parent_id": "synthetic-parent",
            "state_id": "synthetic-state",
            "is_active": True,
            **result,
        }
        assert (
            ScreeningBenchmarkObservation.model_validate_json(json.dumps(legacy)).model_dump()
            == legacy
        )


def test_v01_map_set_record_deserializes_without_flex_metadata() -> None:
    timestamp = "2026-01-01T00:00:00Z"
    tool = {"name": "synthetic AutoGrid", "version": "1"}
    legacy: dict[str, object] = {
        "map_set_id": "synthetic-map-set",
        "identity_key": MAP_HASH,
        "created_at": timestamp,
        "request": {
            "receptor_id": "synthetic-receptor",
            "binding_site_id": "synthetic-site",
            "source": "ligand_preparation",
            "ligand_preparation_id": "synthetic-preparation",
        },
        "receptor_id": "synthetic-receptor",
        "receptor_output_artifact_id": "synthetic-receptor-pdbqt",
        "receptor_sha256": RIGID_HASH,
        "binding_site_id": "synthetic-site",
        "box": {
            "center_x": 0,
            "center_y": 0,
            "center_z": 0,
            "size_x": 12,
            "size_y": 12,
            "size_z": 12,
        },
        "geometry": {
            "spacing_angstrom": 0.375,
            "npts": [32, 32, 32],
            "requested_size_angstrom": [12, 12, 12],
            "realized_size_angstrom": [12, 12, 12],
        },
        "preflight": {
            "receptor_atom_types": ["C"],
            "ligand_atom_types": ["C"],
            "selected_count": 1,
            "prepared_count": 1,
            "compatible_count": 1,
            "incompatible_count": 0,
        },
        "autogrid": {
            "tool": tool,
            "executable_path": "synthetic/autogrid4.exe",
            "sha256": "0" * 64,
            "max_receptor_types": 32,
            "max_ligand_types": 32,
            "max_maps": 32,
            "max_grid_points": 1025,
        },
        "gpf_sha256": "1" * 64,
        "field_artifact_id": "synthetic-field",
        "execution": {
            "command": ["autogrid4.exe", "-p", "synthetic.gpf"],
            "exit_code": 0,
            "stdout": "synthetic stdout",
            "stderr": "",
            "duration_seconds": 0,
            "successful_completion_logged": True,
        },
        "artifacts": [
            {
                "artifact_id": "synthetic-field",
                "kind": "field",
                "filename": "synthetic.maps.fld",
                "sha256": "2" * 64,
                "size_bytes": 1,
                "content_url": "/synthetic/map-field",
            }
        ],
        "provenance": {
            "event_id": "synthetic-event",
            "event_type": "synthetic map generation",
            "timestamp": timestamp,
            "tool": tool,
        },
    }
    record = AutoGridMapSetRecord.model_validate_json(json.dumps(legacy))
    assert record.receptor_sha256 == RIGID_HASH
    assert record.geometry.npts == (32, 32, 32)
    assert record.execution.stdout == "synthetic stdout"
    assert AutoGridMapSetRecord.model_validate_json(record.model_dump_json()) == record


@pytest.mark.parametrize("root_directory", ("analysis", "derived"))
@pytest.mark.parametrize("stale_parent", ("synthetic-receptor", "synthetic-maps"))
def test_stale_propagation_to_immutable_v02_record(
    tmp_path: Path, protocol: ProtocolSpec, root_directory: str, stale_parent: str
) -> None:
    project = tmp_path / "projects" / "default"
    receptor_id = "synthetic-receptor"
    map_set_id = "synthetic-maps"
    record_id = "synthetic-protocol"
    records = {
        project / f"derived/receptors/{receptor_id}/record.json": {"receptor_id": receptor_id},
        project / f"derived/autogrid_maps/{map_set_id}/record.json": {
            "map_set_id": map_set_id,
            "receptor_id": receptor_id,
        },
        project / f"{root_directory}/v02_protocols/{record_id}/record.json": {
            "dependencies": {"receptor_id": receptor_id, "map_set_id": map_set_id},
            "protocol": protocol.model_dump(mode="json"),
        },
    }
    for path, payload in records.items():
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    before = {path: path.read_bytes() for path in records}

    service = ProjectDependencyService(root=tmp_path, project_id="default")
    initial = service.graph()
    assert initial.unresolved_reference_count == 0
    node = next(node for node in initial.nodes if node.node_id == record_id)
    assert set(node.parent_ids) == {receptor_id, map_set_id}
    assert node.stale is False

    result = service.mark_stale(stale_parent, "Synthetic upstream invalidation")
    affected = {map_set_id, record_id}
    if stale_parent == receptor_id:
        affected.add(receptor_id)
    assert set(result.affected_node_ids) == affected
    reloaded = ProjectDependencyService(root=tmp_path, project_id="default")
    assert {node.node_id for node in reloaded.graph().nodes if node.stale} == affected
    with pytest.raises(AnkoraDomainError) as caught:
        reloaded.require_current([record_id])
    assert caught.value.code == "PROJECT_INPUT_STALE"
    assert {path: path.read_bytes() for path in records} == before
def test_adr031_installer_size_budget_manifest_matches_frozen_baseline() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    budget = json.loads(
        (repo_root / "environment" / "v02-installer-size-budget.json").read_text(encoding="utf-8")
    )
    assert budget["schema_version"] == 1
    assert budget["adr"] == "ADR-031"
    assert budget["baseline_tag"] == "v0.1.0-beta.2"
    assert budget["baseline_commit"] == "36f1c0e9b11adb579920437d23298472ac948bcf"
    assert budget["milestone_budgets_bytes"]["M0"]["max_delta_bytes"] == 0
    assert budget["milestone_budgets_bytes"]["M0"]["new_dependencies"] == []
    assert budget["milestone_budgets_bytes"]["M1"]["max_delta_bytes"] == 0
    assert budget["milestone_budgets_bytes"]["M2"]["max_delta_bytes"] == 0
    assert budget["milestone_budgets_bytes"]["M3"]["max_delta_bytes"] == 1048576
    for artifact in budget["published_release_baselines"].values():
        assert artifact["size_bytes"] > 0
        assert len(artifact["sha256"]) == 64
