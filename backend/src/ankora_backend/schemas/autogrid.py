"""Immutable AutoGrid4 map-set contracts (ADR-015 Phase 1)."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.warnings import StructuredWarning


class AutoGridLigandSource(StrEnum):
    """Where the ligand affinity-map atom types come from."""

    LIGAND_PREPARATION = "ligand_preparation"
    FILTER_RUN = "filter_run"


class AutoGridMapKind(StrEnum):
    AFFINITY = "affinity"
    ELECTROSTATIC = "electrostatic"
    DESOLVATION = "desolvation"
    FIELD = "field"
    GRID_POINTS = "grid_points"
    RECEPTOR = "receptor"
    GRID_PARAMETER_FILE = "grid_parameter_file"
    GRID_LOG = "grid_log"


class AutoGridParameters(BaseModel):
    """Force-field-affecting settings. Every field participates in map identity."""

    model_config = ConfigDict(extra="forbid")

    spacing_angstrom: float = Field(default=0.375, gt=0, le=1.0)
    smoothing_angstrom: float = Field(default=0.5, ge=0, le=2.0)
    dielectric: float = Field(default=-0.1465, lt=0)
    timeout_minutes: int = Field(default=120, ge=1, le=1_440)


class AutoGridMapSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receptor_id: str = Field(min_length=1)
    binding_site_id: str = Field(min_length=1)
    source: AutoGridLigandSource
    ligand_id: str | None = None
    ligand_preparation_id: str | None = None
    library_id: str | None = None
    filter_run_id: str | None = None
    parameters: AutoGridParameters = Field(default_factory=AutoGridParameters)


class AutoGridGeometry(BaseModel):
    """Discretization of a confirmed box. `npts` counts intervals, not points:
    AutoGrid writes `npts + 1` points per axis, which is why the executable's
    `MAX_GRID_PTS` ceiling of 1025 permits at most 1024 intervals."""

    model_config = ConfigDict(extra="forbid")

    spacing_angstrom: float = Field(gt=0)
    npts: tuple[int, int, int]
    requested_size_angstrom: tuple[float, float, float]
    realized_size_angstrom: tuple[float, float, float]


class AutoGridLigandPreflightRow(BaseModel):
    """One molecule's contribution to the ligand atom-type union.

    An incompatible molecule stays visible here with its reason rather than
    disappearing from the campaign; its atom types are never coerced.
    """

    model_config = ConfigDict(extra="forbid")

    ligand_id: str = Field(min_length=1)
    source_index: int = Field(ge=0)
    name: str = Field(min_length=1)
    compatible: bool
    atom_types: list[str] = Field(default_factory=list)
    reason: str | None = None


class AutoGridPreflight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receptor_atom_types: list[str] = Field(min_length=1)
    ligand_atom_types: list[str] = Field(min_length=1)
    selected_count: int = Field(ge=0)
    prepared_count: int = Field(ge=0)
    compatible_count: int = Field(ge=1)
    incompatible_count: int = Field(ge=0)
    ligands: list[AutoGridLigandPreflightRow] = Field(default_factory=list)


class AutoGridExecutionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: list[str] = Field(min_length=1)
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float = Field(ge=0)
    successful_completion_logged: bool


class AutoGridMapArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1)
    kind: AutoGridMapKind
    atom_type: str | None = None
    filename: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)
    content_url: str = Field(min_length=1)


class AutoGridToolIdentity(BaseModel):
    """AutoGrid's exact identity and the real limits it reports for itself.

    The limits are probed rather than assumed so a differently compiled build
    is validated against its own ceilings instead of this project's defaults.
    """

    model_config = ConfigDict(extra="forbid")

    tool: ToolIdentity
    executable_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    architecture: str | None = None
    max_receptor_types: int = Field(ge=1)
    max_ligand_types: int = Field(ge=1)
    max_maps: int = Field(ge=1)
    max_grid_points: int = Field(ge=2)


class AutoGridMapSetRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    map_set_id: str = Field(min_length=1)
    identity_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    request: AutoGridMapSetRequest
    receptor_id: str = Field(min_length=1)
    receptor_output_artifact_id: str = Field(min_length=1)
    receptor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    binding_site_id: str = Field(min_length=1)
    box: BindingBox
    geometry: AutoGridGeometry
    preflight: AutoGridPreflight
    autogrid: AutoGridToolIdentity
    gpf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    field_artifact_id: str = Field(min_length=1)
    execution: AutoGridExecutionEvidence
    artifacts: list[AutoGridMapArtifact] = Field(min_length=1)
    warnings: list[StructuredWarning] = Field(default_factory=list)
    provenance: ProvenanceEvent


class AutoGridMapSetSummary(BaseModel):
    """Cache-lookup answer: whether an identical immutable map set already exists."""

    model_config = ConfigDict(extra="forbid")

    reused_existing_map_set: bool
    record: AutoGridMapSetRecord


class AutoGridJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELED = "canceled"
    COMPLETED = "completed"
    FAILED = "failed"


class AutoGridJobPhase(StrEnum):
    QUEUED = "queued"
    GENERATING_MAPS = "generating_maps"
    COLLECTING_ARTIFACTS = "collecting_artifacts"
    COMPLETE = "complete"


class AutoGridFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: dict[str, object] = Field(default_factory=dict)


class AutoGridMapJobRecord(BaseModel):
    """Mutable progress for one map-generation run.

    The immutable `AutoGridMapSetRecord` stays separate and is still written
    only once, at the end: the store treats a directory without `record.json`
    as an incomplete run, which is what keeps a canceled or failed job from
    ever being reused as a valid map set.
    """

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    status: AutoGridJobStatus
    phase: AutoGridJobPhase
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    request: AutoGridMapSetRequest
    identity_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    geometry: AutoGridGeometry
    preflight: AutoGridPreflight
    autogrid: AutoGridToolIdentity
    map_set_id: str | None = None
    reused_existing_map_set: bool = False
    evidence_directory: str | None = None
    execution: AutoGridExecutionEvidence | None = None
    failure: AutoGridFailure | None = None


class AutoGridJobCancelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    status: AutoGridJobStatus
