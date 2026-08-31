"""AutoDock4 CPU docking contracts (ADR-015 Phase 2).

Results are cluster-native. AutoDock performs independent Lamarckian-GA runs and
then groups them by RMSD; cluster population is scientifically meaningful, so it
is preserved rather than flattened into a Vina-shaped ranked pose list.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.warnings import StructuredWarning


class AutoDock4JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELED = "canceled"
    COMPLETED = "completed"
    FAILED = "failed"


class AutoDock4JobPhase(StrEnum):
    QUEUED = "queued"
    DOCKING = "docking"
    PARSING_RESULTS = "parsing_results"
    COMPLETE = "complete"


class AutoDock4DockingParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # AutoDock4 4.2.6 emits no CLUSTERING HISTOGRAM, RMSD TABLE or RANKING
    # records for a single run - there is nothing to cluster against - so a
    # cluster-native result cannot be built from one. Verified against the real
    # binary rather than assumed.
    ga_runs: int = Field(default=10, ge=2, le=256)
    ga_population_size: int = Field(default=150, ge=2, le=10_000)
    ga_energy_evaluations: int = Field(default=2_500_000, ge=1_000, le=100_000_000)
    ga_generations: int = Field(default=27_000, ge=1, le=1_000_000)
    cluster_rmsd_tolerance_angstrom: float = Field(default=2.0, gt=0, le=20)
    # AutoDock's own default is `pid time`, which would make a run
    # unreproducible; Ankora always passes and records explicit integers.
    # AutoDock4 refuses a seed of zero or one outright: "Random number seed
    # cannot be zero or one, or negative". Accepting 1 and letting the tool
    # fatal mid-campaign is not validation, so the floor is the tool's own.
    seed_1: int = Field(default=20260824, ge=2, le=2_147_483_647)
    seed_2: int = Field(default=20260824, ge=2, le=2_147_483_647)
    timeout_minutes: int = Field(default=360, ge=1, le=2_880)


class AutoDock4DockingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receptor_id: str = Field(min_length=1)
    binding_site_id: str = Field(min_length=1)
    map_set_id: str = Field(min_length=1)
    ligand_id: str = Field(min_length=1)
    ligand_preparation_id: str = Field(min_length=1)
    parameters: AutoDock4DockingParameters = Field(
        default_factory=AutoDock4DockingParameters
    )
    acknowledge_inputs_and_scoring: bool = False


class AutoDock4ToolIdentity(BaseModel):
    """AutoDock4's exact identity and the limits it reports for itself."""

    model_config = ConfigDict(extra="forbid")

    tool: ToolIdentity
    executable_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    architecture: str | None = None
    max_torsions: int = Field(ge=1)
    max_atoms: int = Field(ge=1)
    max_maps: int = Field(ge=1)


class AutoDock4PoseArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1)
    run: int = Field(ge=1)
    filename: str = Field(pattern=r"^run_\d+\.pdbqt$")
    format: str = Field(pattern="^pdbqt$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)
    content_url: str = Field(min_length=1)


class AutoDock4RunResult(BaseModel):
    """One independent LGA run and where AutoDock ranked it."""

    model_config = ConfigDict(extra="forbid")

    run: int = Field(ge=1)
    cluster_rank: int = Field(ge=1)
    sub_rank: int = Field(ge=1)
    binding_energy_kcal_mol: float
    cluster_rmsd_angstrom: float = Field(ge=0)
    reference_rmsd_angstrom: float = Field(ge=0)
    artifact: AutoDock4PoseArtifact


class AutoDock4ClusterResult(BaseModel):
    """A group of runs that converged on the same pose.

    `run_count` is evidence of reproducibility, not a score: a large tight
    cluster means the search kept finding the same solution.
    """

    model_config = ConfigDict(extra="forbid")

    cluster_rank: int = Field(ge=1)
    lowest_binding_energy_kcal_mol: float
    mean_binding_energy_kcal_mol: float
    run_count: int = Field(ge=1)
    representative_run: int = Field(ge=1)
    runs: list[int] = Field(min_length=1)


class AutoDock4ExecutionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: list[str] = Field(min_length=1)
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float = Field(ge=0)
    successful_completion_logged: bool
    canceled: bool = False
    timed_out: bool = False


class AutoDock4Failure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: dict[str, object] = Field(default_factory=dict)


class AutoDock4DockingJobRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    status: AutoDock4JobStatus
    phase: AutoDock4JobPhase
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    request: AutoDock4DockingRequest
    autodock4: AutoDock4ToolIdentity
    receptor_id: str = Field(min_length=1)
    binding_site_id: str = Field(min_length=1)
    map_set_id: str = Field(min_length=1)
    map_set_identity_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    ligand_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ligand_atom_types: list[str] = Field(min_length=1)
    ligand_atom_count: int = Field(ge=1)
    torsional_degrees_of_freedom: int = Field(ge=0)
    dpf_sha256: str | None = None
    command: list[str] = Field(default_factory=list)
    execution: AutoDock4ExecutionEvidence | None = None
    clusters: list[AutoDock4ClusterResult] = Field(default_factory=list)
    runs: list[AutoDock4RunResult] = Field(default_factory=list)
    warnings: list[StructuredWarning] = Field(default_factory=list)
    failure: AutoDock4Failure | None = None
    provenance: ProvenanceEvent | None = None


class AutoDock4CancelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    status: AutoDock4JobStatus


class AutoDock4BatchParameters(AutoDock4DockingParameters):
    """Search settings shared by every molecule, plus how many run at once.

    AutoDock4 4.2.6 reports `OpenMP multiprocessor support (_OPENMP): no`, so a
    single process uses exactly one core. That makes this pool the whole CPU
    budget - there is no inner thread count to coordinate with, and therefore no
    nested oversubscription to avoid (ADR-013).
    """

    model_config = ConfigDict(extra="forbid")

    parallel_ligands: int = Field(default=1, ge=1, le=64)


class AutoDock4BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receptor_id: str = Field(min_length=1)
    binding_site_id: str = Field(min_length=1)
    map_set_id: str = Field(min_length=1)
    library_id: str = Field(min_length=1)
    filter_run_id: str = Field(min_length=1)
    parameters: AutoDock4BatchParameters = Field(
        default_factory=AutoDock4BatchParameters
    )
    acknowledge_inputs_and_scoring: bool = False


class AutoDock4BatchLigandResult(BaseModel):
    """One molecule's own AutoDock4 job, with its own clustering.

    Every molecule runs a complete AutoDock4 process, so its clusters are the
    ones AutoDock itself produced rather than anything Ankora recomputed.
    """

    model_config = ConfigDict(extra="forbid")

    ligand_id: str = Field(min_length=1)
    source_index: int = Field(ge=0)
    name: str = Field(min_length=1)
    canonical_smiles: str | None = None
    molecular_weight_g_mol: float | None = Field(default=None, ge=0)
    ligand_preparation_id: str | None = None
    ligand_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    ligand_atom_types: list[str] = Field(default_factory=list)
    status: AutoDock4JobStatus
    phase: AutoDock4JobPhase
    started_at: datetime | None = None
    completed_at: datetime | None = None
    command: list[str] = Field(default_factory=list)
    dpf_sha256: str | None = None
    execution: AutoDock4ExecutionEvidence | None = None
    clusters: list[AutoDock4ClusterResult] = Field(default_factory=list)
    runs: list[AutoDock4RunResult] = Field(default_factory=list)
    failure: AutoDock4Failure | None = None
    provenance: ProvenanceEvent | None = None
    revision: int = Field(default=0, ge=0)


class AutoDock4BatchRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str = Field(min_length=1)
    status: AutoDock4JobStatus
    phase: AutoDock4JobPhase
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    request: AutoDock4BatchRequest
    autodock4: AutoDock4ToolIdentity
    receptor_id: str = Field(min_length=1)
    binding_site_id: str = Field(min_length=1)
    map_set_id: str = Field(min_length=1)
    map_set_identity_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_count: int = Field(ge=1)
    worker_count: int = Field(ge=1)
    completed_count: int = Field(default=0, ge=0)
    succeeded_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    canceled_count: int = Field(default=0, ge=0)
    entries: list[AutoDock4BatchLigandResult] = Field(min_length=1)
    warnings: list[StructuredWarning] = Field(default_factory=list)
    failure: AutoDock4Failure | None = None
    provenance: ProvenanceEvent | None = None
    revision: int = Field(default=0, ge=0)


class AutoDock4BatchProgress(BaseModel):
    """A cheap poll target so a long campaign does not resend every result."""

    model_config = ConfigDict(extra="forbid")

    batch_id: str = Field(min_length=1)
    status: AutoDock4JobStatus
    revision: int = Field(ge=0)
    selected_count: int = Field(ge=1)
    completed_count: int = Field(ge=0)
    succeeded_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    canceled_count: int = Field(ge=0)
    running_ligand_ids: list[str] = Field(default_factory=list)
