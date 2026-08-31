"""Typed contracts for reproducible AutoDock Vina execution and poses."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.warnings import StructuredWarning


class DockingEngine(StrEnum):
    AUTODOCK_VINA = "autodock_vina"


class DockingJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELED = "canceled"
    COMPLETED = "completed"
    FAILED = "failed"


class DockingJobPhase(StrEnum):
    QUEUED = "queued"
    VALIDATING = "validating"
    DOCKING = "docking"
    PARSING_POSES = "parsing_poses"
    COMPLETE = "complete"


class VinaDockingParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cpu_threads: int = Field(default=1, ge=1, le=256)
    seed: int = Field(default=20260823, ge=1, le=2_147_483_647)
    exhaustiveness: int = Field(default=8, ge=1, le=128)
    num_modes: int = Field(default=9, ge=1, le=100)
    min_rmsd_angstrom: float = Field(default=1.0, ge=0, le=20)
    energy_range_kcal_mol: float = Field(default=3.0, ge=0, le=100)
    timeout_minutes: int = Field(default=360, ge=1, le=2_880)


class VinaDockingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receptor_id: str = Field(min_length=1)
    binding_site_id: str = Field(min_length=1)
    ligand_id: str = Field(min_length=1)
    ligand_preparation_id: str = Field(min_length=1)
    parameters: VinaDockingParameters = Field(default_factory=VinaDockingParameters)
    acknowledge_inputs_and_scoring: bool = False

    @model_validator(mode="after")
    def require_explicit_acknowledgement(self) -> "VinaDockingRequest":
        if not self.acknowledge_inputs_and_scoring:
            raise ValueError(
                "acknowledge_inputs_and_scoring must be true before docking"
            )
        return self


class VinaBatchDockingParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_cpu_threads: int = Field(default=1, ge=1, le=256)
    parallel_ligands: int = Field(default=1, ge=1, le=64)
    seed: int = Field(default=20260823, ge=1, le=2_147_483_647)
    exhaustiveness: int = Field(default=8, ge=1, le=128)
    num_modes: int = Field(default=9, ge=1, le=100)
    min_rmsd_angstrom: float = Field(default=1.0, ge=0, le=20)
    energy_range_kcal_mol: float = Field(default=3.0, ge=0, le=100)
    timeout_minutes_per_ligand: int = Field(default=360, ge=1, le=2_880)

    @model_validator(mode="after")
    def keep_parallelism_inside_cpu_budget(self) -> "VinaBatchDockingParameters":
        if self.parallel_ligands > self.total_cpu_threads:
            raise ValueError("parallel_ligands cannot exceed total_cpu_threads")
        return self


class VinaBatchDockingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receptor_id: str = Field(min_length=1)
    binding_site_id: str = Field(min_length=1)
    library_id: str = Field(min_length=1)
    filter_run_id: str = Field(min_length=1)
    parameters: VinaBatchDockingParameters = Field(
        default_factory=VinaBatchDockingParameters
    )
    acknowledge_inputs_and_scoring: bool = False

    @model_validator(mode="after")
    def require_explicit_acknowledgement(self) -> "VinaBatchDockingRequest":
        if not self.acknowledge_inputs_and_scoring:
            raise ValueError(
                "acknowledge_inputs_and_scoring must be true before batch docking"
            )
        return self


class DockingPoseArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1)
    mode: int = Field(ge=1)
    filename: str = Field(pattern=r"^pose_\d+\.pdbqt$")
    format: str = Field(pattern="^pdbqt$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)
    content_url: str = Field(min_length=1)


class DockingPoseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: int = Field(ge=1)
    affinity_kcal_mol: float
    rmsd_lower_bound_angstrom: float = Field(ge=0)
    rmsd_upper_bound_angstrom: float = Field(ge=0)
    artifact: DockingPoseArtifact


class DockingExecutionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: list[str] = Field(min_length=1)
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    canceled: bool = False


class DockingFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: dict[str, object] = Field(default_factory=dict)


class VinaDockingJobRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    engine: DockingEngine = DockingEngine.AUTODOCK_VINA
    status: DockingJobStatus
    phase: DockingJobPhase
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    request: VinaDockingRequest
    tool: ToolIdentity
    receptor_output_artifact_id: str = Field(min_length=1)
    receptor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ligand_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    command: list[str] = Field(default_factory=list)
    execution: DockingExecutionEvidence | None = None
    poses: list[DockingPoseResult] = Field(default_factory=list)
    warnings: list[StructuredWarning] = Field(default_factory=list)
    failure: DockingFailure | None = None
    provenance: ProvenanceEvent | None = None


class VinaBatchLigandResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ligand_id: str = Field(min_length=1)
    source_index: int = Field(ge=0)
    name: str = Field(min_length=1)
    canonical_smiles: str | None = None
    molecular_weight_g_mol: float | None = Field(default=None, ge=0)
    preparation_energy_kcal_mol: float | None = None
    ligand_preparation_id: str | None = None
    ligand_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    status: DockingJobStatus
    phase: DockingJobPhase
    started_at: datetime | None = None
    completed_at: datetime | None = None
    command: list[str] = Field(default_factory=list)
    execution: DockingExecutionEvidence | None = None
    poses: list[DockingPoseResult] = Field(default_factory=list)
    failure: DockingFailure | None = None
    provenance: ProvenanceEvent | None = None
    revision: int = Field(default=0, ge=0)


class VinaBatchDockingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str = Field(min_length=1)
    engine: DockingEngine = DockingEngine.AUTODOCK_VINA
    status: DockingJobStatus
    phase: DockingJobPhase
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    request: VinaBatchDockingRequest
    tool: ToolIdentity
    receptor_output_artifact_id: str = Field(min_length=1)
    receptor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_manifest_artifact_id: str = Field(min_length=1)
    selection_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_count: int = Field(ge=1)
    worker_count: int = Field(ge=1)
    threads_per_ligand: int = Field(ge=1)
    completed_count: int = Field(ge=0)
    succeeded_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    canceled_count: int = Field(ge=0)
    entries: list[VinaBatchLigandResult] = Field(min_length=1)
    failure: DockingFailure | None = None
    provenance: ProvenanceEvent | None = None
    revision: int = Field(default=0, ge=0)


class VinaBatchProgress(BaseModel):
    """Small incremental campaign update for frequent UI refreshes."""

    model_config = ConfigDict(extra="forbid")

    batch_id: str = Field(min_length=1)
    status: DockingJobStatus
    phase: DockingJobPhase
    revision: int = Field(ge=0)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    selected_count: int = Field(ge=1)
    worker_count: int = Field(ge=1)
    threads_per_ligand: int = Field(ge=1)
    completed_count: int = Field(ge=0)
    succeeded_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    canceled_count: int = Field(ge=0)
    entries: list[VinaBatchLigandResult] = Field(default_factory=list)
    failure: DockingFailure | None = None
    provenance: ProvenanceEvent | None = None


class DockingCancelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    status: DockingJobStatus


class DockingBatchCancelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str = Field(min_length=1)
    status: DockingJobStatus
