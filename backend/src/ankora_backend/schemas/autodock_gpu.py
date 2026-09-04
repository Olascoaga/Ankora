"""AutoDock-GPU docking contracts (ADR-015 item 5).

**Results are shared with the CPU engine; the protocol is not.**

AutoDock-GPU uses AutoDock4's semi-empirical force field and writes the same
`.dlg`, so `AutoDock4ClusterResult`, `AutoDock4RunResult` and
`AutoDock4PoseArtifact` describe its output exactly and are reused rather than
copied. What differs is how the search was conducted, so the parameters, the
tool identity and the execution evidence are this engine's own, and every
record names its backend.

The two backends do not agree. Measured on identical maps, ligand and seeds at
a matched protocol, the best cluster differed by 0.34 kcal/mol with a different
cluster structure. `DOCKING_POLICY.md` forbids merging engines; the same rule
holds between backends of one engine, so GPU results are never pooled with CPU
ones into a single ranking.

**A seed does not make a GPU run reproducible.** AutoDock4 on the CPU is
bit-identical across repeats of one seed; AutoDock-GPU is not. Six repeats of
one seed on one machine produced six different ranking tables, with the best
cluster energy spanning 0.13 kcal/mol (mean −3.30, sd 0.063). The seed is still
recorded, because it is part of the protocol that was requested, but this
contract states plainly that re-running will not reproduce the result exactly.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ankora_backend.schemas.autodock4 import (
    AutoDock4ClusterResult,
    AutoDock4Failure,
    AutoDock4JobPhase,
    AutoDock4JobStatus,
    AutoDock4RunResult,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.warnings import StructuredWarning

# The lifecycle and result shapes are the AutoDock4 ones because the science is
# the AutoDock4 science. Re-exported under backend-neutral names so a reader of
# this module is not misled into thinking a GPU job is a CPU job.
AutoDockJobStatus = AutoDock4JobStatus
AutoDockJobPhase = AutoDock4JobPhase
AutoDockClusterResult = AutoDock4ClusterResult
AutoDockRunResult = AutoDock4RunResult
AutoDockFailure = AutoDock4Failure


class AutoDockBackend(StrEnum):
    """Which executable produced a result. Never inferred, always recorded."""

    CPU = "autodock4_cpu"
    GPU = "autodock_gpu"


class AutoDockGpuLocalSearch(StrEnum):
    """The local-search methods that actually work in AutoDock-GPU 1.6.

    The tool's argument parser names five - `sw`, `sd`, `fire`, `ad`, `adam` -
    but only three of them can be used, established by running each:

    * `adam` is refused at runtime: "LS method adam is not (yet) supported in
      the OpenCL version."
    * `sd` never completed. Two runs of 50,000 evaluations were still going
      after 180 s, where the same work takes about 1 s under the others.

    Offering either would hand a scientist a setting that hangs or errors, so
    neither is exposed. ADADELTA is the tool's default and the reason the GPU
    search differs from the CPU protocol, which uses Solis-Wets.
    """

    ADADELTA = "ad"
    SOLIS_WETS = "sw"
    FIRE = "fire"


class AutoDockGpuDockingParameters(BaseModel):
    """The complete search protocol, stated rather than left to defaults.

    AutoDock-GPU's own defaults enable a ligand-based heuristic and automatic
    stopping, which decide how much searching happens without saying so. Ankora
    defaults instead to a fixed, stated protocol matching the CPU engine's
    evaluation budget, so the two backends are at least asked for comparable
    effort. The adaptive settings remain available and are recorded when used.
    """

    model_config = ConfigDict(extra="forbid")

    # AutoDock-GPU does produce a ranking and a histogram for a single run,
    # unlike the CPU build. The floor of two is Ankora's own and scientific:
    # cluster population is reproducibility evidence, and one run carries none.
    runs: int = Field(default=10, ge=2, le=1_000)
    population_size: int = Field(default=150, ge=2, le=10_000)
    # Ignored by the tool when the heuristic is on, which is why enabling the
    # heuristic and stating a budget are mutually exclusive at the adapter.
    energy_evaluations: int = Field(default=2_500_000, ge=1_000, le=100_000_000)
    heuristics: bool = False
    autostop: bool = False
    local_search_method: AutoDockGpuLocalSearch = AutoDockGpuLocalSearch.ADADELTA
    cluster_rmsd_tolerance_angstrom: float = Field(default=2.0, gt=0, le=20)
    # The tool's own default is "time, process id", which would leave nothing
    # to record at all. Explicit integers narrow the variability even though
    # they cannot remove it - see the module docstring. AutoDock-GPU accepts
    # zero and one, unlike the CPU build, verified against the real binary.
    seed_1: int = Field(default=20260826, ge=0, le=2_147_483_647)
    seed_2: int = Field(default=20260826, ge=0, le=2_147_483_647)
    seed_3: int = Field(default=20260826, ge=0, le=2_147_483_647)
    device_number: int = Field(default=1, ge=1, le=64)
    timeout_minutes: int = Field(default=60, ge=1, le=2_880)

    @property
    def seed(self) -> tuple[int, int, int]:
        return (self.seed_1, self.seed_2, self.seed_3)


class AutoDockGpuDockingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receptor_id: str = Field(min_length=1)
    binding_site_id: str = Field(min_length=1)
    map_set_id: str = Field(min_length=1)
    ligand_id: str = Field(min_length=1)
    ligand_preparation_id: str = Field(min_length=1)
    parameters: AutoDockGpuDockingParameters = Field(
        default_factory=AutoDockGpuDockingParameters
    )
    acknowledge_inputs_and_scoring: bool = False


class AutoDockGpuToolIdentity(BaseModel):
    """The executable and the device it selected.

    AutoDock-GPU reports no compiled-in ligand limits, so unlike the CPU
    identity there are none to record. The device is recorded because the same
    protocol on different hardware is a different execution.
    """

    model_config = ConfigDict(extra="forbid")

    tool: ToolIdentity
    executable_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    architecture: str | None = None
    build: str = Field(min_length=1)
    device_number: int = Field(ge=1)
    device_name: str = Field(min_length=1)


class AutoDockGpuExecutionEvidence(BaseModel):
    """What the run actually did.

    There is no `successful_completion_logged` counterpart to the CPU evidence:
    AutoDock-GPU writes no completion marker into its log and returns zero even
    when it fails, so the verdict comes from the words it printed on stdout.
    """

    model_config = ConfigDict(extra="forbid")

    command: list[str] = Field(min_length=1)
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float = Field(ge=0)
    success_reported_on_stdout: bool
    canceled: bool = False
    timed_out: bool = False


class AutoDockGpuDockingJobRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    backend: AutoDockBackend = AutoDockBackend.GPU
    status: AutoDockJobStatus
    phase: AutoDockJobPhase
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    request: AutoDockGpuDockingRequest
    autodock_gpu: AutoDockGpuToolIdentity
    receptor_id: str = Field(min_length=1)
    binding_site_id: str = Field(min_length=1)
    map_set_id: str = Field(min_length=1)
    map_set_identity_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    ligand_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ligand_atom_types: list[str] = Field(min_length=1)
    ligand_atom_count: int = Field(ge=1)
    torsional_degrees_of_freedom: int = Field(ge=0)
    # Stated on every record rather than left for a reader to infer from the
    # backend: a repeat of this exact job will not reproduce these numbers.
    bitwise_reproducible: bool = False
    command: list[str] = Field(default_factory=list)
    execution: AutoDockGpuExecutionEvidence | None = None
    clusters: list[AutoDockClusterResult] = Field(default_factory=list)
    runs: list[AutoDockRunResult] = Field(default_factory=list)
    warnings: list[StructuredWarning] = Field(default_factory=list)
    failure: AutoDockFailure | None = None
    provenance: ProvenanceEvent | None = None


class AutoDockGpuCancelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    status: AutoDockJobStatus


class AutoDockGpuBatchParameters(AutoDockGpuDockingParameters):
    """Search settings shared by every molecule in a campaign.

    There is deliberately no `parallel_ligands` counterpart to the CPU
    parameters. AutoDock-GPU docks a whole file list inside one process against
    one device, and two concurrent processes measured *slower* than one - 26.9 s
    against 23.1 s over twenty molecules - because they contend for the same
    GPU. A knob whose only settings are "the right one" and "worse" is not a
    decision worth offering.
    """

    model_config = ConfigDict(extra="forbid")


class AutoDockGpuBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receptor_id: str = Field(min_length=1)
    binding_site_id: str = Field(min_length=1)
    map_set_id: str = Field(min_length=1)
    library_id: str = Field(min_length=1)
    filter_run_id: str = Field(min_length=1)
    parameters: AutoDockGpuBatchParameters = Field(
        default_factory=AutoDockGpuBatchParameters
    )
    acknowledge_inputs_and_scoring: bool = False


class AutoDockGpuBatchLigandResult(BaseModel):
    """One molecule's clustering, produced inside the campaign's single pass.

    Unlike the CPU campaign there is no per-molecule execution evidence: the
    whole file list is one invocation, so the command, the exit code and the
    tool's output belong to the campaign rather than to any one molecule.
    """

    model_config = ConfigDict(extra="forbid")

    ligand_id: str = Field(min_length=1)
    parent_compound_id: str | None = None
    chemical_state_id: str | None = None
    chemical_state_formal_charge: int | None = None
    source_index: int = Field(ge=0)
    name: str = Field(min_length=1)
    canonical_smiles: str | None = None
    molecular_weight_g_mol: float | None = Field(default=None, ge=0)
    ligand_preparation_id: str | None = None
    ligand_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    ligand_atom_types: list[str] = Field(default_factory=list)
    status: AutoDockJobStatus
    phase: AutoDockJobPhase
    completed_at: datetime | None = None
    clusters: list[AutoDockClusterResult] = Field(default_factory=list)
    runs: list[AutoDockRunResult] = Field(default_factory=list)
    failure: AutoDockFailure | None = None
    revision: int = Field(default=0, ge=0)


class AutoDockGpuBatchRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str = Field(min_length=1)
    backend: AutoDockBackend = AutoDockBackend.GPU
    status: AutoDockJobStatus
    phase: AutoDockJobPhase
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    request: AutoDockGpuBatchRequest
    autodock_gpu: AutoDockGpuToolIdentity
    receptor_id: str = Field(min_length=1)
    binding_site_id: str = Field(min_length=1)
    map_set_id: str = Field(min_length=1)
    map_set_identity_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_count: int = Field(ge=1)
    # One device, one process. Recorded as a fact of the run, not a setting.
    worker_count: int = Field(default=1, ge=1, le=1)
    bitwise_reproducible: bool = False
    completed_count: int = Field(default=0, ge=0)
    succeeded_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    canceled_count: int = Field(default=0, ge=0)
    command: list[str] = Field(default_factory=list)
    execution: AutoDockGpuExecutionEvidence | None = None
    entries: list[AutoDockGpuBatchLigandResult] = Field(min_length=1)
    warnings: list[StructuredWarning] = Field(default_factory=list)
    failure: AutoDockFailure | None = None
    provenance: ProvenanceEvent | None = None
    revision: int = Field(default=0, ge=0)


class AutoDockGpuBatchProgress(BaseModel):
    """A cheap poll target so a long campaign does not resend every result.

    AutoDock-GPU writes each molecule's log as it finishes rather than at the
    end - measured incrementally across a twenty-molecule pass - so a campaign
    inside one process can still report honest progress.
    """

    model_config = ConfigDict(extra="forbid")

    batch_id: str = Field(min_length=1)
    status: AutoDockJobStatus
    revision: int = Field(ge=0)
    selected_count: int = Field(ge=1)
    completed_count: int = Field(ge=0)
    succeeded_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    canceled_count: int = Field(ge=0)
