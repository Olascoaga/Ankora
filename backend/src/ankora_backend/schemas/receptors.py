"""Typed contracts for explicit M2 receptor inspection and preparation."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from ankora_backend.schemas.provenance import ProvenanceEvent
from ankora_backend.schemas.structures import HeterogenKind, StructureFormat
from ankora_backend.schemas.warnings import StructuredWarning

DISALLOWED_FLEX_RESIDUE_NAMES = frozenset({"GLY", "ALA", "PRO", "CYX"})
RECOMMENDED_MAX_FLEX_RESIDUES = 4
RECOMMENDED_MAX_FLEX_CHI_TORSIONS = 12


class ReceptorIssueKind(StrEnum):
    MISSING_RESIDUE = "missing_residue"
    MISSING_ATOMS = "missing_atoms"
    ALTERNATE_LOCATION = "alternate_location"
    NONSTANDARD_RESIDUE = "nonstandard_residue"


class ReceptorIssueSeverity(StrEnum):
    UNASSESSED = "unassessed"
    NEAR_REFERENCE = "near_reference"
    REMOTE = "remote"


class ReceptorDecisionAction(StrEnum):
    LEAVE = "leave"
    REPAIR = "repair"
    REMOVE = "remove"
    MANUAL_REVIEW = "manual_review"


class ComponentAction(StrEnum):
    KEEP = "keep"
    REMOVE = "remove"


class ReceptorPreparationStatus(StrEnum):
    SELECTED = "selected"
    PROTONATED = "protonated"
    DOCKING_READY = "docking_ready"


class ReceptorOutputStage(StrEnum):
    SELECTED = "selected"
    REPAIRED = "repaired"
    RELAXED = "relaxed"
    PROTONATED_PDB = "protonated_pdb"
    PROTONATED_PQR = "protonated_pqr"
    MEEKO_INPUT_PQR = "meeko_input_pqr"
    PDBQT = "pdbqt"
    PDBQT_RIGID = "pdbqt_rigid"
    PDBQT_FLEX = "pdbqt_flex"


class ResidueLocator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chain_id: str
    residue_name: str = Field(min_length=1)
    sequence_number: int
    insertion_code: str = ""


class ReceptorFlexMode(StrEnum):
    RIGID = "rigid"
    SIDECHAIN_FLEX = "sidechain_flex"


def _validate_flex_selection(residues: list[ResidueLocator] | tuple[ResidueLocator, ...]) -> None:
    positions = set()
    for residue in residues:
        if residue.residue_name.upper() in DISALLOWED_FLEX_RESIDUE_NAMES:
            raise ValueError(f"Residue {residue.residue_name} is disallowed for FlexRes")
        position = (residue.chain_id, residue.sequence_number, residue.insertion_code)
        if position in positions:
            raise ValueError("Flexible residue locators must have unique positions")
        positions.add(position)


class ReceptorFlexRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: ReceptorFlexMode = ReceptorFlexMode.RIGID
    flex_residues: list[ResidueLocator] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_flex_selection(self) -> Self:
        if self.mode is ReceptorFlexMode.RIGID:
            if self.flex_residues:
                raise ValueError("Rigid receptors cannot declare flexible residues")
        else:
            if not self.flex_residues:
                raise ValueError("Side-chain flexibility requires at least one flexible residue")
            _validate_flex_selection(self.flex_residues)
        return self


type _Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class _FrozenResidueLocator(ResidueLocator):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _freeze_residue_locator(residue: ResidueLocator) -> ResidueLocator:
    # Snapshot the v0.1 locator so it cannot be edited through either model.
    return _FrozenResidueLocator.model_validate(residue.model_dump())


def flex_residue_locator_key(residue: ResidueLocator) -> tuple[str, str, int, str]:
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
        _validate_flex_selection(self.flex_residues)
        return self

    def canonical_flex_locators(self) -> tuple[tuple[str, str, int, str], ...]:
        """Return sorted (chain, uppercase residue name, sequence number, insertion code) keys."""
        return tuple(sorted(map(flex_residue_locator_key, self.flex_residues)))

    @property
    def high_dof_warning_required(self) -> bool:
        return (
            len(self.flex_residues) > RECOMMENDED_MAX_FLEX_RESIDUES
            or self.added_chi_torsion_count > RECOMMENDED_MAX_FLEX_CHI_TORSIONS
        )


class ReceptorIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: str = Field(min_length=1)
    kind: ReceptorIssueKind
    residue: ResidueLocator
    missing_atoms: list[str] = Field(default_factory=list)
    alternate_locations: list[str] = Field(default_factory=list)
    distance_to_reference_angstrom: float | None = Field(default=None, ge=0)
    severity: ReceptorIssueSeverity
    allowed_actions: list[ReceptorDecisionAction]
    message: str = Field(min_length=1)


class ReceptorComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    chain_id: str
    sequence_number: int | None
    insertion_code: str = ""
    atom_count: int = Field(ge=1)
    kind: HeterogenKind


class TerminalHeavyAtomAddition(BaseModel):
    """One exact terminal atom the scientist permits PDB2PQR to complete."""

    model_config = ConfigDict(extra="forbid")

    chain_id: str = Field(min_length=1)
    residue_name: str = Field(min_length=1)
    sequence_number: int
    insertion_code: str = ""
    atom_name: Literal["OXT"] = "OXT"


class ReceptorInspectionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_artifact_id: str = Field(min_length=1)
    generated_at: datetime
    candidate_chains: list[str]
    components: list[ReceptorComponent]
    water_count: int = Field(ge=0)
    issues: list[ReceptorIssue]
    terminal_oxygen_candidates: list[TerminalHeavyAtomAddition] = Field(default_factory=list)
    reference_component_id: str | None = None
    near_reference_cutoff_angstrom: float = Field(gt=0)
    warnings: list[StructuredWarning]
    provenance: ProvenanceEvent


class ComponentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: str = Field(min_length=1)
    action: ComponentAction


class IssueDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: str = Field(min_length=1)
    action: ReceptorDecisionAction
    selected_altloc: str | None = None

    @model_validator(mode="after")
    def require_selected_altloc_for_repair(self) -> "IssueDecision":
        if self.selected_altloc is not None and len(self.selected_altloc) != 1:
            raise ValueError("selected_altloc must contain exactly one alternate-location label")
        return self


class ProtonationDecisionSource(StrEnum):
    PROPKA_PREDICTION = "propka_prediction"
    SCIENTIST_OVERRIDE = "scientist_override"


class ProtonationOverride(BaseModel):
    """One explicit residue-state decision that differs from PROPKA's default."""

    model_config = ConfigDict(extra="forbid")

    residue: ResidueLocator
    state: str = Field(min_length=2, max_length=32, pattern=r"^[A-Z0-9_+-]+$")


class ProtonationMetalContact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    chain_id: str
    sequence_number: int | None
    insertion_code: str = ""
    distance_angstrom: float = Field(ge=0)


class ReceptorProtonationProposal(BaseModel):
    """PROPKA evidence plus requested and verified written states."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=1)
    residue: ResidueLocator
    group_label: str = Field(min_length=1)
    group_type: str | None = None
    predicted_pka: float
    model_pka: float | None = None
    buried_fraction: float | None = Field(default=None, ge=0)
    coupled_group: str | None = None
    predicted_state: str = Field(min_length=1)
    default_state: str = Field(min_length=1)
    selected_state: str = Field(min_length=1)
    output_state: str | None = Field(default=None, min_length=1)
    allowed_states: list[str] = Field(min_length=1)
    decision_source: ProtonationDecisionSource
    distance_to_reference_angstrom: float | None = Field(default=None, ge=0)
    near_reference: bool = False
    nearby_metals: list[ProtonationMetalContact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ReceptorProtonationAnalysis(BaseModel):
    """Structured, immutable interpretation of one exact PROPKA execution."""

    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_ph: float = Field(ge=0, le=14)
    force_field: str = Field(min_length=1)
    tool_version: str = Field(min_length=1)
    proposals: list[ReceptorProtonationProposal]
    reference_component_id: str | None = None
    near_reference_cutoff_angstrom: float = Field(gt=0)
    metal_warning_cutoff_angstrom: float = Field(gt=0)


class ProtonationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    ph: float = Field(default=7.4, ge=0, le=14)
    force_field: str = Field(default="AMBER", pattern=r"^[A-Z0-9_-]+$")
    authorized_terminal_heavy_atom_additions: list[TerminalHeavyAtomAddition] = Field(
        default_factory=list
    )
    overrides: list[ProtonationOverride] = Field(default_factory=list)

    @model_validator(mode="after")
    def terminal_additions_require_protonation(self) -> "ProtonationSettings":
        if self.authorized_terminal_heavy_atom_additions and not self.enabled:
            raise ValueError("Terminal heavy-atom additions require protonation")
        identities = {
            (
                item.chain_id,
                item.residue_name,
                item.sequence_number,
                item.insertion_code,
                item.atom_name,
            )
            for item in self.authorized_terminal_heavy_atom_additions
        }
        if len(identities) != len(self.authorized_terminal_heavy_atom_additions):
            raise ValueError("Terminal heavy-atom additions must not contain duplicates")
        override_identities = {
            (
                item.residue.chain_id,
                item.residue.residue_name,
                item.residue.sequence_number,
                item.residue.insertion_code,
            )
            for item in self.overrides
        }
        if len(override_identities) != len(self.overrides):
            raise ValueError("Protonation overrides must not contain duplicate residues")
        if self.overrides and not self.enabled:
            raise ValueError("Protonation overrides require protonation")
        return self


class RelaxationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    restraint_force_constant_kcal_mol_a2: float = Field(default=50.0, gt=0)
    max_iterations: int = Field(default=200, ge=1, le=5000)


ReceptorInspectionMethod = Literal["reported_only", "templates_v1"]


class ReceptorPreparationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_chains: list[str] = Field(min_length=1)
    water_action: ComponentAction
    component_decisions: list[ComponentDecision]
    issue_decisions: list[IssueDecision]
    reference_component_id: str | None = None
    relaxation: RelaxationSettings = Field(default_factory=RelaxationSettings)
    protonation: ProtonationSettings = Field(default_factory=ProtonationSettings)
    generate_pdbqt: bool = False
    repair_method: Literal["legacy", "topology_guard_v3"] = "legacy"
    repair_seed: int = Field(default=20261014, ge=1, le=2147483647)
    inspection_method: ReceptorInspectionMethod = "reported_only"
    flexibility: ReceptorFlexRequest | None = None

    @model_serializer(mode="wrap")
    def preserve_legacy_request_shape(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, object]:
        result: dict[str, object] = handler(self)
        if self.flexibility is None:
            result.pop("flexibility", None)
        if self.inspection_method == "reported_only":
            result.pop("inspection_method", None)
        if self.repair_method == "legacy":
            result.pop("repair_method", None)
            result.pop("repair_seed", None)
        return result

    @model_validator(mode="after")
    def pdbqt_requires_protonation(self) -> "ReceptorPreparationRequest":
        if self.generate_pdbqt and not self.protonation.enabled:
            raise ValueError("PDBQT generation requires an explicit protonation stage")
        return self

    @model_validator(mode="after")
    def flexible_receptor_requires_protonated_pdbqt(self) -> Self:
        if self.flexibility is None or self.flexibility.mode is ReceptorFlexMode.RIGID:
            return self
        if not self.generate_pdbqt or not self.protonation.enabled:
            raise ValueError("Side-chain flexibility requires protonation and PDBQT generation")
        if {item.chain_id for item in self.flexibility.flex_residues} - set(self.selected_chains):
            raise ValueError("Flexible residues must belong to selected chains")
        return self

    @model_validator(mode="after")
    def relaxation_requires_a_repair(self) -> "ReceptorPreparationRequest":
        if self.relaxation.enabled and not any(
            decision.action is ReceptorDecisionAction.REPAIR
            for decision in self.issue_decisions
        ):
            raise ValueError("Relaxation requires at least one issue decision set to repair")
        return self

    @model_validator(mode="after")
    def terminal_additions_require_selected_chains(self) -> "ReceptorPreparationRequest":
        unknown_chains = {
            item.chain_id
            for item in self.protonation.authorized_terminal_heavy_atom_additions
        } - set(self.selected_chains)
        if unknown_chains:
            raise ValueError(
                "Terminal heavy-atom additions must belong to selected chains"
            )
        return self


class ReceptorOutputArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1)
    stage: ReceptorOutputStage
    filename: str = Field(min_length=1)
    format: StructureFormat | str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)
    created_at: datetime
    content_url: str = Field(min_length=1)


class ReceptorPreparationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receptor_id: str = Field(min_length=1)
    source_artifact_id: str = Field(min_length=1)
    created_at: datetime
    status: ReceptorPreparationStatus
    decisions: ReceptorPreparationRequest
    outputs: list[ReceptorOutputArtifact]
    warnings: list[StructuredWarning]
    provenance: list[ProvenanceEvent]
    display_output_artifact_id: str = Field(min_length=1)
    protonation_analysis: ReceptorProtonationAnalysis | None = None
    flex_spec: ReceptorFlexSpec | None = None
    flex_atom_types: list[str] = Field(default_factory=list)
