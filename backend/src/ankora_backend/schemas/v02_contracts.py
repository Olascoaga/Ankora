"""Frozen contracts for Ankora v0.2 Milestone M0."""

import json
from enum import StrEnum
from hashlib import sha256
from types import MappingProxyType
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.receptors import ResidueLocator
from ankora_backend.schemas.screening_benchmark import ScoreDirection

type _Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
type _AtomIndex = Annotated[int, Field(ge=1)]
type _NonBlankString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
type _FlexLocatorKey = tuple[str, str, int, str]
type _Engine = Literal["vina", "autodock4", "autodock_gpu", "gnina"]

DISALLOWED_FLEX_RESIDUE_NAMES = frozenset({"GLY", "ALA", "PRO", "CYX"})
RECOMMENDED_MAX_FLEX_RESIDUES = 4
RECOMMENDED_MAX_FLEX_CHI_TORSIONS = 12


def canonical_contract_sha256(payload: BaseModel | dict[str, object]) -> str:
    """Hash the canonical UTF-8 JSON representation of a contract or JSON object."""
    data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    canonical = json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


class MacrocyclePolicy(StrEnum):
    FLEXIBLE_PSEUDOATOMS = "flexible_pseudoatoms"
    RIGID_INPUT_CONFORMATION = "rigid_input_conformation"


class ReceptorFlexMode(StrEnum):
    RIGID = "rigid"
    SIDECHAIN_FLEX = "sidechain_flex"


class ScoringFamily(StrEnum):
    VINA_VINARDO = "vina_vinardo"
    AUTODOCK4 = "autodock4"
    GNINA_NEURAL = "gnina_neural"


class ScoringFunctionId(StrEnum):
    VINA = "vina"
    VINARDO = "vinardo"
    AUTODOCK4 = "autodock4"
    GNINA_CNN_SCORE = "gnina_cnn_score"
    GNINA_CNN_AFFINITY = "gnina_cnn_affinity"
    GNINA_CNN_VS = "gnina_cnn_vs"
    GNINA_MINIMIZED_AFFINITY = "gnina_minimized_affinity"


class ObservationStatus(StrEnum):
    SCORED = "scored"
    FAILED = "failed"
    NOT_EVALUABLE = "not_evaluable"


class DiagnosticStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"
    NOT_EVALUABLE = "not_evaluable"


class RankingMethod(StrEnum):
    SINGLE_ENGINE = "single_engine"
    PC_Q_CORE_V1 = "pc_q_core_v1"
    PC_Q_NEURAL_V1 = "pc_q_neural_v1"
    PC_ECR_V1 = "pc_ecr_v1"
    PC_L2_V1 = "pc_l2_v1"


_SCORING_FUNCTIONS_BY_FAMILY = MappingProxyType(
    {
        ScoringFamily.VINA_VINARDO: frozenset({ScoringFunctionId.VINA, ScoringFunctionId.VINARDO}),
        ScoringFamily.AUTODOCK4: frozenset({ScoringFunctionId.AUTODOCK4}),
        ScoringFamily.GNINA_NEURAL: frozenset(
            {
                ScoringFunctionId.GNINA_CNN_SCORE,
                ScoringFunctionId.GNINA_CNN_AFFINITY,
                ScoringFunctionId.GNINA_CNN_VS,
                ScoringFunctionId.GNINA_MINIMIZED_AFFINITY,
            }
        ),
    }
)
_SCORING_FUNCTIONS_BY_ENGINE: MappingProxyType[_Engine, frozenset[ScoringFunctionId]] = (
    MappingProxyType(
        {
            "vina": _SCORING_FUNCTIONS_BY_FAMILY[ScoringFamily.VINA_VINARDO]
            | _SCORING_FUNCTIONS_BY_FAMILY[ScoringFamily.AUTODOCK4],
            "autodock4": _SCORING_FUNCTIONS_BY_FAMILY[ScoringFamily.AUTODOCK4],
            "autodock_gpu": _SCORING_FUNCTIONS_BY_FAMILY[ScoringFamily.AUTODOCK4],
            "gnina": _SCORING_FUNCTIONS_BY_FAMILY[ScoringFamily.GNINA_NEURAL],
        }
    )
)


class LigandFlexibilitySpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    macrocycle_policy: MacrocyclePolicy = MacrocyclePolicy.FLEXIBLE_PSEUDOATOMS
    rigidified_smarts: tuple[_NonBlankString, ...] = ()
    rigidified_bond_indices: tuple[tuple[_AtomIndex, _AtomIndex], ...] = ()
    flexible_amides: bool = False
    local_only_refinement: bool = False

    @model_validator(mode="after")
    def validate_rigidified_bonds(self) -> Self:
        pairs = set()
        for first, second in self.rigidified_bond_indices:
            if first == second:
                raise ValueError("A rigidified bond requires two distinct atom indices")
            pair = (min(first, second), max(first, second))
            if pair in pairs:
                raise ValueError("Rigidified bond indices must not contain duplicate pairs")
            pairs.add(pair)
        return self


class _FrozenResidueLocator(ResidueLocator):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _freeze_residue_locator(residue: ResidueLocator) -> ResidueLocator:
    # Snapshot the v0.1 locator so it cannot be edited through either model.
    return _FrozenResidueLocator.model_validate(residue.model_dump())


def _flex_locator_key(residue: ResidueLocator) -> _FlexLocatorKey:
    return (
        residue.chain_id,
        residue.residue_name.upper(),
        residue.sequence_number,
        residue.insertion_code,
    )


class ReceptorFlexSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: ReceptorFlexMode = ReceptorFlexMode.RIGID
    flex_residues: tuple[
        Annotated[ResidueLocator, AfterValidator(_freeze_residue_locator)], ...
    ] = ()
    receptor_rigid_sha256: _Sha256
    receptor_flex_sha256: _Sha256 | None = None
    added_chi_torsion_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_receptor_split(self) -> Self:
        if self.mode == ReceptorFlexMode.RIGID:
            if (
                self.flex_residues
                or self.receptor_flex_sha256 is not None
                or self.added_chi_torsion_count != 0
            ):
                raise ValueError(
                    "Rigid receptors cannot declare flexible residues, a flex hash, or chi torsions"
                )
            return self

        if not self.flex_residues or self.receptor_flex_sha256 is None:
            raise ValueError("Side-chain flexibility requires flex residues and a flex hash")
        positions = set()
        for residue in self.flex_residues:
            if residue.residue_name.upper() in DISALLOWED_FLEX_RESIDUE_NAMES:
                raise ValueError(f"Residue {residue.residue_name} is disallowed for FlexRes")
            position = (residue.chain_id, residue.sequence_number, residue.insertion_code)
            if position in positions:
                raise ValueError("Flexible residue locators must have unique positions")
            positions.add(position)
        return self

    def canonical_flex_locators(self) -> tuple[_FlexLocatorKey, ...]:
        """Return sorted (chain, uppercase residue name, sequence number, insertion code) keys."""
        return tuple(sorted(map(_flex_locator_key, self.flex_residues)))

    @property
    def high_dof_warning_required(self) -> bool:
        return (
            len(self.flex_residues) > RECOMMENDED_MAX_FLEX_RESIDUES
            or self.added_chi_torsion_count > RECOMMENDED_MAX_FLEX_CHI_TORSIONS
        )


class PoseComplexIdentity(BaseModel):
    """E8 identity of the receptor and ligand coordinates for one pose."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: ReceptorFlexMode
    receptor_rigid_sha256: _Sha256
    pose_flex_sidechains_sha256: _Sha256 | None = None
    ligand_pose_sha256: _Sha256

    @model_validator(mode="after")
    def validate_pose_split(self) -> Self:
        if (self.mode == ReceptorFlexMode.SIDECHAIN_FLEX) != (
            self.pose_flex_sidechains_sha256 is not None
        ):
            raise ValueError("A pose flex-sidechains hash is required only in sidechain_flex mode")
        return self

    @property
    def complex_identity_sha256(self) -> str:
        return canonical_contract_sha256(self)


class ProtocolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    engine: _Engine
    scoring_function: ScoringFunctionId
    ligand_flexibility: LigandFlexibilitySpec = Field(default_factory=LigandFlexibilitySpec)
    receptor_flexibility: ReceptorFlexSpec
    binding_box_sha256: _Sha256
    autogrid_map_set_sha256: _Sha256 | None = None
    interaction_rule_set_sha256: _Sha256 | None = None
    random_seed: int | None = None

    @model_validator(mode="after")
    def validate_scoring_protocol(self) -> Self:
        if self.scoring_function not in _SCORING_FUNCTIONS_BY_ENGINE[self.engine]:
            raise ValueError(
                f"Scoring function {self.scoring_function} is invalid for {self.engine}"
            )
        # AutoDock4 and AutoDock-GPU both require AutoDock4 scoring.
        if (
            self.scoring_function == ScoringFunctionId.AUTODOCK4
            and self.autogrid_map_set_sha256 is None
        ):
            raise ValueError("AutoDock4 scoring requires an AutoGrid map-set hash")
        return self

    @property
    def protocol_identity_sha256(self) -> str:
        payload = self.model_dump(
            mode="json", exclude={"receptor_flexibility", "ligand_flexibility"}
        )
        receptor = self.receptor_flexibility
        receptor_payload = receptor.model_dump(mode="json", exclude={"flex_residues"})
        receptor_payload["flex_residues"] = [
            residue.model_dump(mode="json")
            for residue in sorted(receptor.flex_residues, key=_flex_locator_key)
        ]
        payload["receptor_flexibility"] = receptor_payload

        ligand = self.ligand_flexibility
        ligand_payload = ligand.model_dump(mode="json")
        ligand_payload["rigidified_bond_indices"] = sorted(
            (min(first, second), max(first, second))
            for first, second in ligand.rigidified_bond_indices
        )
        ligand_payload["rigidified_smarts"] = sorted(ligand.rigidified_smarts)
        payload["ligand_flexibility"] = ligand_payload
        return canonical_contract_sha256(payload)

    def verify_autogrid_map_binding(
        self,
        *,
        map_receptor_sha256: str,
        map_flex_residues: tuple[ResidueLocator, ...] = (),
    ) -> None:
        """Enforce E7 by matching the receptor hash and exact flex-residue keys."""
        receptor = self.receptor_flexibility
        expected_locators = receptor.canonical_flex_locators()
        map_locators = tuple(sorted(map(_flex_locator_key, map_flex_residues)))
        if (
            map_receptor_sha256 != receptor.receptor_rigid_sha256
            or map_locators != expected_locators
        ):
            raise AnkoraDomainError(
                code="AUTOGRID_FLEXRES_MAP_MISMATCH",
                stage="protocol_contract",
                status_code=422,
                message=(
                    "The AutoGrid map set must match the protocol's rigid receptor and "
                    "flexible residue selection."
                ),
                details={
                    "expected_receptor_sha256": receptor.receptor_rigid_sha256,
                    "map_receptor_sha256": map_receptor_sha256,
                    "expected_flex_locators": expected_locators,
                    "map_flex_locators": map_locators,
                },
            )


class ScoreObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    protocol_identity_sha256: _Sha256
    parent_compound_id: _NonBlankString
    parent_state_id: _NonBlankString
    pose_complex: PoseComplexIdentity | None = None
    scoring_family: ScoringFamily
    scoring_function: ScoringFunctionId
    direction: ScoreDirection
    unit: _NonBlankString
    tool_name: _NonBlankString
    tool_version: _NonBlankString
    status: ObservationStatus
    raw_score: float | None = Field(default=None, allow_inf_nan=False)
    failure_code: str | None = None

    @model_validator(mode="after")
    def validate_score_evidence(self) -> Self:
        if self.scoring_function not in _SCORING_FUNCTIONS_BY_FAMILY[self.scoring_family]:
            raise ValueError("The scoring function must belong to the declared scoring family")
        if self.status == ObservationStatus.SCORED:
            if self.raw_score is None or self.pose_complex is None or self.failure_code is not None:
                raise ValueError(
                    "Scored observations require a raw score and pose, with no failure code"
                )
        elif self.raw_score is not None or not (self.failure_code or "").strip():
            raise ValueError(
                "Failed and not-evaluable observations require a failure code and no raw score"
            )
        return self


class PoseDiagnosticCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    check_id: _NonBlankString
    tool_name: _NonBlankString
    tool_version: _NonBlankString
    status: DiagnosticStatus
    value: float | None = Field(default=None, allow_inf_nan=False)
    threshold: float | None = Field(default=None, allow_inf_nan=False)
    message: str | None = None


class ConformationalStrainDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    force_field: Literal["MMFF94s"] = "MMFF94s"
    parent_state_id: _NonBlankString
    hydrogen_policy: _NonBlankString
    conformer_seed: int
    conformer_budget: int = Field(ge=1)
    pose_restrained_energy_kcal_mol: float = Field(allow_inf_nan=False)
    lowest_free_conformer_energy_kcal_mol: float = Field(allow_inf_nan=False)
    delta_e_ref_kcal_mol: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_energy_difference(self) -> Self:
        difference = (
            self.pose_restrained_energy_kcal_mol - self.lowest_free_conformer_energy_kcal_mol
        )
        if abs(difference - self.delta_e_ref_kcal_mol) > 1e-6:
            raise ValueError("delta_e_ref_kcal_mol must equal restrained minus free energy")
        return self


class PoseAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    pose_complex: PoseComplexIdentity
    overall_status: DiagnosticStatus
    checks: tuple[PoseDiagnosticCheck, ...] = Field(min_length=1)
    strain: ConformationalStrainDiagnostic | None = None
    mutated_original_pose: Literal[False] = False

    @model_validator(mode="after")
    def validate_unique_check_ids(self) -> Self:
        if len({check.check_id for check in self.checks}) != len(self.checks):
            raise ValueError("Pose diagnostic check IDs must be unique")
        return self


class RankingEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    parent_compound_id: _NonBlankString
    parent_state_id: _NonBlankString
    tier: Literal["full_profile", "partial_or_unscored"]
    rank: int | None = Field(default=None, ge=1)
    score_value: float | None = Field(default=None, allow_inf_nan=False)
    percentile: float | None = Field(default=None, ge=0.0, le=100.0, allow_inf_nan=False)
    inter_family_disagreement: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    search_convergence_count: int | None = Field(default=None, ge=0)
    search_engine_count: int | None = Field(default=None, ge=1)
    selected_pose_complex: PoseComplexIdentity | None = None
    failure_or_exclusion_codes: tuple[_NonBlankString, ...] = ()

    @model_validator(mode="after")
    def validate_ranking_entry(self) -> Self:
        if self.tier == "full_profile":
            if self.rank is None or self.score_value is None or self.selected_pose_complex is None:
                raise ValueError("Full-profile entries require a rank, score, and selected pose")
        elif self.rank is not None or not self.failure_or_exclusion_codes:
            raise ValueError("Partial or unscored entries require an exclusion reason and no rank")
        elif (
            self.score_value is not None
            or self.percentile is not None
            or self.inter_family_disagreement is not None
        ):
            raise ValueError("Partial or unscored entries cannot carry consensus metrics")
        if (self.search_convergence_count is None) != (self.search_engine_count is None):
            raise ValueError("Search convergence and engine counts must be provided together")
        if (
            self.search_convergence_count is not None
            and self.search_engine_count is not None
            and self.search_convergence_count > self.search_engine_count
        ):
            raise ValueError("Search convergence count cannot exceed the search engine count")
        return self


class RankingArtifact(BaseModel):
    """E6 two-tier ranking with a denominator that includes unscored parents."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    method: RankingMethod
    reference_panel_sha256: _Sha256 | None = None
    tie_policy: _NonBlankString
    failure_policy: _NonBlankString
    total_parents: int = Field(ge=1)
    full_profile_count: int = Field(ge=0)
    partial_or_unscored_count: int = Field(ge=0)
    entries: tuple[RankingEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_ranking_population(self) -> Self:
        if self.method != RankingMethod.SINGLE_ENGINE and self.reference_panel_sha256 is None:
            raise ValueError("Consensus rankings require a reference panel hash")
        if self.total_parents != len(self.entries) or self.total_parents != (
            self.full_profile_count + self.partial_or_unscored_count
        ):
            raise ValueError("Total parents must equal the entry count and sum of tier counts")
        if len({entry.parent_compound_id for entry in self.entries}) != self.total_parents:
            raise ValueError("Ranking entries must have unique parent compound IDs")

        partial_count = 0
        previous_rank = 0
        for idx, entry in enumerate(self.entries, start=1):
            if entry.tier == "partial_or_unscored":
                partial_count += 1
                continue
            if partial_count:
                raise ValueError("Full-profile entries must precede partial or unscored entries")
            if entry.rank is None or entry.rank < previous_rank:
                raise ValueError("Full-profile ranks must be in non-decreasing order")
            if entry.rank > idx:
                raise ValueError("A full-profile rank cannot exceed its row position")
            previous_rank = entry.rank
        if partial_count != self.partial_or_unscored_count:
            raise ValueError("Ranking tier counts must match the entries")
        return self
