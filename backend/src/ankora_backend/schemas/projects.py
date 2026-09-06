"""Contracts for explicit project identity and dependency state."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    name: str
    registered_at: datetime
    migrated_legacy: bool = False


class ProjectCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_project_id: str
    projects: list[ProjectRecord]


class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Project name cannot be blank.")
        return normalized


class DependencyNodeKind(StrEnum):
    STRUCTURE = "structure"
    RECEPTOR = "receptor"
    LIGAND = "ligand"
    LIGAND_LIBRARY = "ligand_library"
    LIGAND_FILTER = "ligand_filter"
    CHEMICAL_STATE = "chemical_state"
    CONFORMER = "conformer"
    LIGAND_PREPARATION = "ligand_preparation"
    BINDING_SITE = "binding_site"
    POCKET_DETECTION = "pocket_detection"
    AUTOGRID_MAP_SET = "autogrid_map_set"
    DOCKING_CAMPAIGN = "docking_campaign"
    VALIDATION = "validation"
    POSE_ANALYSIS = "pose_analysis"
    EXPORT = "export"
    UNKNOWN = "unknown"


class DependencyNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    kind: DependencyNodeKind
    label: str
    relative_path: str
    parent_ids: list[str] = Field(default_factory=list)
    unresolved_parent_ids: list[str] = Field(default_factory=list)
    stale: bool = False
    stale_reasons: list[str] = Field(default_factory=list)


class DependencyEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_id: str
    child_id: str


class ProjectDependencyGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    generated_at: datetime
    nodes: list[DependencyNode]
    edges: list[DependencyEdge]
    total_nodes: int
    offset: int
    limit: int
    stale_count: int
    unresolved_reference_count: int


class MarkArtifactStaleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=240)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("A stale-state reason is required.")
        return normalized


class MarkArtifactStaleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marked_node_id: str
    affected_node_ids: list[str]
