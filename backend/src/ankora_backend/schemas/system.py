"""Bootstrap endpoint contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(ContractModel):
    status: Literal["ok"]
    backend_version: str


class SystemResponse(ContractModel):
    platform: str
    architecture: str
    python_version: str
    python_environment: str
    app_mode: str


class GpuUsage(ContractModel):
    """What the driver reports, or nothing at all.

    A machine with no NVIDIA GPU, no driver, or a driver that did not answer
    reports `None` and a reason. Showing 0% would be a measurement Ankora
    never made.
    """

    name: str
    utilization_percent: float
    memory_used_bytes: int
    memory_total_bytes: int


class ResourceAllocation(ContractModel):
    """Capacity held by one admitted scientific workload."""

    workload: str
    owner_id: str
    cpu_threads: int
    memory_bytes: int
    disk_bytes: int
    gpu_slots: int


class ResourceSchedulerSnapshot(ContractModel):
    """Observable state of the process-wide scientific-work arbiter."""

    cpu_threads_capacity: int
    cpu_threads_allocated: int
    gpu_slots_capacity: int
    gpu_slots_allocated: int
    memory_reserve_bytes: int
    memory_bytes_reserved: int
    disk_path: str
    disk_reserve_bytes: int
    disk_bytes_reserved: int
    queued_requests: int
    active_allocations: list[ResourceAllocation]


class ResourceUsage(ContractModel):
    """A snapshot of what this machine is doing right now.

    Sampled per request rather than accumulated: the status bar asks
    periodically, and a docking campaign's cost is visible in the answer.
    """

    cpu_percent: float
    logical_cores: int
    memory_used_bytes: int
    memory_total_bytes: int
    memory_percent: float
    gpu: GpuUsage | None = None
    gpu_unavailable_reason: str | None = None
    scheduler: ResourceSchedulerSnapshot | None = None


class ToolStatus(ContractModel):
    available: bool
    path: str | None
    version: str | None
    architecture: str | None = None
    sha256: str | None = None


class ToolsResponse(ContractModel):
    vina: ToolStatus
    gnina: ToolStatus
    autogrid4: ToolStatus
    autodock4: ToolStatus
    autodock_gpu: ToolStatus
    pdbfixer: ToolStatus
    pdb2pqr: ToolStatus
    propka: ToolStatus
    meeko: ToolStatus
    meeko_ligand: ToolStatus
    p2rank: ToolStatus
