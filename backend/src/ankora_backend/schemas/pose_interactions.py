"""Typed, immutable interaction evidence for one exact docking pose (M9)."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.receptors import ResidueLocator
from ankora_backend.schemas.warnings import StructuredWarning


class PoseKind(StrEnum):
    VINA_MODE = "vina_mode"
    AUTODOCK_RUN = "autodock_run"


class PoseReference(BaseModel):
    """One engine-native pose. No Vina mode is relabelled as an AD4 run."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1)
    kind: PoseKind
    ordinal: int = Field(ge=1)
    label: str = Field(min_length=1)
    result_kcal_mol: float
    value_label: str = Field(min_length=1)
    cluster_rank: int | None = Field(default=None, ge=1)
    sub_rank: int | None = Field(default=None, ge=1)
    rmsd_lower_bound_angstrom: float | None = Field(default=None, ge=0)
    rmsd_upper_bound_angstrom: float | None = Field(default=None, ge=0)
    cluster_rmsd_angstrom: float | None = Field(default=None, ge=0)
    reference_rmsd_angstrom: float | None = Field(default=None, ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_url: str = Field(min_length=1)


class PoseInventory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_id: str = Field(min_length=1)
    ligand_id: str = Field(min_length=1)
    engine_label: str = Field(min_length=1)
    receptor_artifact_id: str | None = None
    receptor_content_url: str | None = None
    poses: list[PoseReference] = Field(default_factory=list)


class InteractionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(default="ankora-default-v1", min_length=1)
    vicinity_cutoff_angstrom: float = Field(default=6.0, gt=0, le=20)
    interactions: list[str] = Field(
        default_factory=lambda: [
            "Hydrophobic",
            "HBDonor",
            "HBAcceptor",
            "FaceToFace",
            "EdgeToFace",
            "CationPi",
            "PiCation",
            "Anionic",
            "Cationic",
            "XBAcceptor",
            "XBDonor",
            "MetalAcceptor",
            "MetalDonor",
        ]
    )


class InteractionAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: InteractionProfile = Field(default_factory=InteractionProfile)


class LigandDiagramAtom(BaseModel):
    model_config = ConfigDict(extra="forbid")

    atom_index: int = Field(ge=0)
    element: str = Field(min_length=1)
    label: str = Field(min_length=1)
    x: float
    y: float


class LigandDiagramBond(BaseModel):
    model_config = ConfigDict(extra="forbid")

    begin_atom_index: int = Field(ge=0)
    end_atom_index: int = Field(ge=0)
    order: float = Field(gt=0)


class LigandDiagram(BaseModel):
    model_config = ConfigDict(extra="forbid")

    atoms: list[LigandDiagramAtom] = Field(min_length=1)
    bonds: list[LigandDiagramBond] = Field(default_factory=list)


class Point3D(BaseModel):
    """A position in the docking coordinate frame, in ångströms.

    The frame is the one both the prepared receptor and the pose are already
    in, so a point recorded here lands on the same atom in any viewer that
    opens those two files.
    """

    model_config = ConfigDict(extra="forbid")

    x: float
    y: float
    z: float


class InteractionContact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_id: str = Field(min_length=1)
    detector_type: str = Field(min_length=1)
    display_type: str = Field(min_length=1)
    residue: ResidueLocator
    ligand_atom_indices: list[int] = Field(default_factory=list)
    protein_atom_indices: list[int] = Field(default_factory=list)
    ligand_atom_labels: list[str] = Field(default_factory=list)
    protein_atom_labels: list[str] = Field(default_factory=list)
    distance_angstrom: float | None = Field(default=None, ge=0)
    geometry: dict[str, float] = Field(default_factory=dict)
    # Where this contact actually is, taken from the very atoms the detector
    # used. Optional because analyses recorded before Ankora drew contacts in
    # 3D have no endpoints, and a record is never rewritten to invent them.
    ligand_point: Point3D | None = None
    protein_point: Point3D | None = None


class InteractionAnalysisRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_id: str = Field(min_length=1)
    created_at: datetime
    catalog_id: str = Field(min_length=1)
    engine_key: str = Field(min_length=1)
    record_id: str = Field(min_length=1)
    engine_label: str = Field(min_length=1)
    ligand_id: str = Field(min_length=1)
    ligand_preparation_id: str = Field(min_length=1)
    conformer_id: str = Field(min_length=1)
    conformer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pose: PoseReference
    receptor_id: str = Field(min_length=1)
    docking_receptor_artifact_id: str = Field(min_length=1)
    docking_receptor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    analysis_receptor_artifact_id: str = Field(min_length=1)
    analysis_receptor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    analysis_receptor_content_url: str = Field(min_length=1)
    detector: ToolIdentity
    profile: InteractionProfile
    contacts: list[InteractionContact] = Field(default_factory=list)
    ligand_diagram: LigandDiagram
    warnings: list[StructuredWarning] = Field(default_factory=list)
    provenance: ProvenanceEvent
