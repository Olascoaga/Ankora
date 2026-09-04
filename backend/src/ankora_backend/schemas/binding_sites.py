"""Typed contracts for binding-site definition ahead of docking."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import ResidueLocator
from ankora_backend.schemas.warnings import StructuredWarning


class BindingSiteSource(StrEnum):
    CO_CRYSTALLIZED_LIGAND = "co_crystallized_ligand"
    SELECTED_RESIDUES = "selected_residues"
    MANUAL = "manual"
    FULL_PROTEIN_BLIND = "full_protein_blind"
    POCKET_DETECTED = "pocket_detected"


class BindingBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    center_x: float
    center_y: float
    center_z: float
    size_x: float = Field(ge=0.1, le=200)
    size_y: float = Field(ge=0.1, le=200)
    size_z: float = Field(ge=0.1, le=200)


class LigandDerivedOrigin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heterogen: ResidueLocator
    padding_angstrom: float = Field(default=5.0, ge=0)


class ResidueSelectionOrigin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    residues: list[ResidueLocator] = Field(min_length=1)
    padding_angstrom: float = Field(default=5.0, ge=0)

    @model_validator(mode="after")
    def reject_duplicate_residues(self) -> "ResidueSelectionOrigin":
        locators = {
            (
                residue.chain_id,
                residue.residue_name,
                residue.sequence_number,
                residue.insertion_code,
            )
            for residue in self.residues
        }
        if len(locators) != len(self.residues):
            raise ValueError("selected residues must be unique")
        return self


class PocketCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pocket_id: str = Field(min_length=1)
    rank: int = Field(ge=1)
    druggability_score: float | None = None
    volume_angstrom3: float | None = Field(default=None, gt=0)
    box: BindingBox
    lining_residues: list[ResidueLocator]


class PocketDetectionExecutionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    predictions_csv: str


class PocketDetectionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=1)
    receptor_id: str = Field(min_length=1)
    source_output_artifact_id: str = Field(min_length=1)
    generated_at: datetime
    tool: ToolIdentity
    candidates: list[PocketCandidate]
    warnings: list[StructuredWarning]
    provenance: ProvenanceEvent
    execution: PocketDetectionExecutionEvidence | None = None


class PocketSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=1)
    pocket_id: str = Field(min_length=1)


class BindingSiteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: BindingSiteSource
    ligand_origin: LigandDerivedOrigin | None = None
    residue_selection: ResidueSelectionOrigin | None = None
    manual_box: BindingBox | None = None
    blind_margin_angstrom: float = Field(default=6.0, ge=0)
    acknowledge_exploratory_full_protein: bool = False
    pocket_selection: PocketSelection | None = None
    parent_binding_site_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def require_fields_for_source(self) -> "BindingSiteRequest":
        required: dict[BindingSiteSource, tuple[str, object | None]] = {
            BindingSiteSource.CO_CRYSTALLIZED_LIGAND: ("ligand_origin", self.ligand_origin),
            BindingSiteSource.SELECTED_RESIDUES: ("residue_selection", self.residue_selection),
            BindingSiteSource.MANUAL: ("manual_box", self.manual_box),
            BindingSiteSource.POCKET_DETECTED: ("pocket_selection", self.pocket_selection),
        }
        if self.source in required:
            field_name, value = required[self.source]
            if value is None:
                raise ValueError(f"source '{self.source}' requires '{field_name}'")
        if self.parent_binding_site_id is not None and self.source is not BindingSiteSource.MANUAL:
            raise ValueError("'parent_binding_site_id' is only valid for a manual adjustment")
        return self


class BindingSitePreview(BaseModel):
    """Non-persistent geometry resolved from an explicit source request."""

    model_config = ConfigDict(extra="forbid")

    receptor_id: str = Field(min_length=1)
    source: BindingSiteSource
    box: BindingBox
    warnings: list[StructuredWarning]


class BindingSiteRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binding_site_id: str = Field(min_length=1)
    receptor_id: str = Field(min_length=1)
    source_artifact_id: str = Field(min_length=1)
    created_at: datetime
    decisions: BindingSiteRequest
    box: BindingBox
    stale: bool = False
    warnings: list[StructuredWarning]
    provenance: list[ProvenanceEvent]
