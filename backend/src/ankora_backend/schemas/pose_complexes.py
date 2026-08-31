"""A ligand-receptor PDB written from one exact preserved docking pose."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PoseComplexExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Used only to make the file recognizable in a scientist-owned folder.
    # The URL identifiers, not this presentation label, select its contents.
    molecule_name: str = Field(min_length=1)
    destination: str | None = Field(default=None, min_length=1)


class PoseComplexFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)


class PoseComplexExport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    export_id: str = Field(min_length=1)
    exported_at: datetime
    catalog_id: str = Field(min_length=1)
    ligand_id: str = Field(min_length=1)
    molecule_name: str = Field(min_length=1)
    pose_artifact_id: str = Field(min_length=1)
    pose_label: str = Field(min_length=1)
    directory: str = Field(min_length=1)
    outside_project: bool = False
    record_directory: str = Field(min_length=1)
    file: PoseComplexFile


class PoseComplexManifest(BaseModel):
    """Project-retained evidence for an exported coordinate file."""

    model_config = ConfigDict(extra="forbid")

    export_id: str = Field(min_length=1)
    exported_at: datetime
    catalog_id: str = Field(min_length=1)
    ligand_id: str = Field(min_length=1)
    molecule_name: str = Field(min_length=1)
    pose_artifact_id: str = Field(min_length=1)
    pose_label: str = Field(min_length=1)
    written_to: str = Field(min_length=1)
    recorded_in: str = Field(min_length=1)
    file: PoseComplexFile
    notes: list[str] = Field(default_factory=list)
