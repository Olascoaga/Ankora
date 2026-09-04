"""Typed contracts for explicit M2 receptor inspection and preparation."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ankora_backend.schemas.provenance import ProvenanceEvent
from ankora_backend.schemas.structures import HeterogenKind, StructureFormat
from ankora_backend.schemas.warnings import StructuredWarning


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


class ResidueLocator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chain_id: str
    residue_name: str = Field(min_length=1)
    sequence_number: int
    insertion_code: str = ""


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


class ReceptorInspectionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_artifact_id: str = Field(min_length=1)
    generated_at: datetime
    candidate_chains: list[str]
    components: list[ReceptorComponent]
    water_count: int = Field(ge=0)
    issues: list[ReceptorIssue]
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


class TerminalHeavyAtomAddition(BaseModel):
    """One exact terminal atom the scientist permits PDB2PQR to complete."""

    model_config = ConfigDict(extra="forbid")

    chain_id: str = Field(min_length=1)
    residue_name: str = Field(min_length=1)
    sequence_number: int
    insertion_code: str = ""
    atom_name: Literal["OXT"] = "OXT"


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
    """PROPKA evidence and the exact state Ankora asked PDB2PQR to use."""

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

    @model_validator(mode="after")
    def pdbqt_requires_protonation(self) -> "ReceptorPreparationRequest":
        if self.generate_pdbqt and not self.protonation.enabled:
            raise ValueError("PDBQT generation requires an explicit protonation stage")
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
