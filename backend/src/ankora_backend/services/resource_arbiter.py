"""Process-wide admission control for expensive scientific work.

The engine services used to limit only their own workers.  That prevents two
Vina batches from colliding, but it does not prevent Vina, AutoGrid, ligand
preparation, and AutoDock from collectively asking for more of the same
machine than it has.  This arbiter grants one atomic CPU/GPU/memory/disk claim
before a worker is allowed to leave its queued state.

Memory and disk quantities are deliberately reservations, not measurements of
exact peak use.  They are conservative admission estimates whose policy is
visible in one place; live utilization remains the responsibility of
``system_resources``.
"""

from __future__ import annotations

import os
import shutil
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.system import (
    ResourceAllocation,
    ResourceSchedulerSnapshot,
)

_MIB = 1024 * 1024
_GIB = 1024 * _MIB
_WAIT_POLL_SECONDS = 0.2


@dataclass(frozen=True, slots=True)
class ResourceClaim:
    """One indivisible request for local machine capacity."""

    workload: str
    owner_id: str
    cpu_threads: int
    memory_bytes: int
    disk_bytes: int
    gpu_slots: int = 0

    def __post_init__(self) -> None:
        if not self.workload or not self.owner_id:
            raise ValueError("A resource claim requires workload and owner identity.")
        if self.cpu_threads < 0 or self.memory_bytes < 0 or self.disk_bytes < 0:
            raise ValueError("Resource claim quantities cannot be negative.")
        if self.gpu_slots < 0:
            raise ValueError("GPU slot count cannot be negative.")


class ResourceRequestCanceled(Exception):
    """The owning job was canceled while waiting for admission."""


@dataclass(slots=True)
class _Waiter:
    ticket_id: str
    claim: ResourceClaim
    queued_at: float


class ResourceLease:
    """An idempotently releasable grant returned by :class:`ResourceArbiter`."""

    def __init__(self, arbiter: ResourceArbiter, lease_id: str, claim: ResourceClaim) -> None:
        self._arbiter = arbiter
        self.lease_id = lease_id
        self.claim = claim
        self._released = False
        self._lock = threading.Lock()

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
        self._arbiter.release(self.lease_id)

    def __enter__(self) -> ResourceLease:
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


class ResourceArbiter:
    """Fair, atomic admission control shared by all scientific executors."""

    def __init__(
        self,
        *,
        cpu_threads: int,
        gpu_slots: int,
        memory_total_bytes: int,
        memory_reserve_bytes: int,
        disk_path: Path,
        disk_total_bytes: int,
        disk_reserve_bytes: int,
        memory_available: Callable[[], int],
        disk_free: Callable[[], int],
    ) -> None:
        if cpu_threads < 1:
            raise ValueError("The CPU capacity must contain at least one thread.")
        if gpu_slots < 0:
            raise ValueError("The GPU capacity cannot be negative.")
        self.cpu_threads = cpu_threads
        self.gpu_slots = gpu_slots
        self.memory_total_bytes = memory_total_bytes
        self.memory_reserve_bytes = memory_reserve_bytes
        self.disk_path = disk_path.resolve()
        self.disk_total_bytes = disk_total_bytes
        self.disk_reserve_bytes = disk_reserve_bytes
        self._memory_available = memory_available
        self._disk_free = disk_free
        self._condition = threading.Condition(threading.RLock())
        self._waiters: deque[_Waiter] = deque()
        self._active: dict[str, ResourceClaim] = {}

    @classmethod
    def from_environment(cls) -> ResourceArbiter:
        psutil: Any = import_module("psutil")
        logical = int(os.cpu_count() or 1)
        default_cpu = logical - 1 if logical > 1 else 1
        cpu_threads = _positive_environment_int("ANKORA_RESOURCE_CPU_THREADS", default_cpu)
        gpu_slots = _nonnegative_environment_int("ANKORA_RESOURCE_GPU_SLOTS", 1)
        memory = psutil.virtual_memory()
        memory_reserve = _nonnegative_environment_int(
            "ANKORA_RESOURCE_MEMORY_RESERVE_BYTES",
            max(2 * _GIB, int(memory.total * 0.15)),
        )
        configured_root = os.getenv("ANKORA_DATA_DIR")
        disk_path = (
            Path(configured_root) if configured_root else Path.cwd() / ".ankora-data"
        ).resolve()
        probe_path = _nearest_existing_parent(disk_path)
        disk = shutil.disk_usage(probe_path)
        disk_reserve = _nonnegative_environment_int(
            "ANKORA_RESOURCE_DISK_RESERVE_BYTES",
            max(2 * _GIB, int(disk.total * 0.05)),
        )
        return cls(
            cpu_threads=cpu_threads,
            gpu_slots=gpu_slots,
            memory_total_bytes=int(memory.total),
            memory_reserve_bytes=memory_reserve,
            disk_path=disk_path,
            disk_total_bytes=int(disk.total),
            disk_reserve_bytes=disk_reserve,
            memory_available=lambda: int(psutil.virtual_memory().available),
            disk_free=lambda: int(shutil.disk_usage(probe_path).free),
        )

    def validate(self, claim: ResourceClaim) -> None:
        """Reject a request that can never fit, instead of queueing forever."""
        impossible: dict[str, dict[str, int]] = {}
        if claim.cpu_threads > self.cpu_threads:
            impossible["cpu_threads"] = {
                "requested": claim.cpu_threads,
                "capacity": self.cpu_threads,
            }
        if claim.gpu_slots > self.gpu_slots:
            impossible["gpu_slots"] = {
                "requested": claim.gpu_slots,
                "capacity": self.gpu_slots,
            }
        memory_capacity = max(0, self.memory_total_bytes - self.memory_reserve_bytes)
        if claim.memory_bytes > memory_capacity:
            impossible["memory_bytes"] = {
                "requested": claim.memory_bytes,
                "capacity": memory_capacity,
            }
        disk_capacity = max(0, self.disk_total_bytes - self.disk_reserve_bytes)
        if claim.disk_bytes > disk_capacity:
            impossible["disk_bytes"] = {
                "requested": claim.disk_bytes,
                "capacity": disk_capacity,
            }
        if impossible:
            raise AnkoraDomainError(
                code="RESOURCE_REQUEST_EXCEEDS_CAPACITY",
                stage="resource_scheduling",
                message=(
                    "This job requests more local machine capacity than Ankora can "
                    "ever grant under the configured safety reserves."
                ),
                status_code=422,
                details={
                    "workload": claim.workload,
                    "owner_id": claim.owner_id,
                    "resources": impossible,
                },
            )

    def acquire(
        self,
        claim: ResourceClaim,
        *,
        cancel_event: threading.Event | None = None,
    ) -> ResourceLease:
        """Wait in FIFO order until the complete claim can be granted."""
        self.validate(claim)
        waiter = _Waiter(ticket_id=str(uuid4()), claim=claim, queued_at=monotonic())
        with self._condition:
            self._waiters.append(waiter)
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    self._remove_waiter(waiter.ticket_id)
                    self._condition.notify_all()
                    raise ResourceRequestCanceled()
                if self._waiters[0] is waiter and self._fits(claim):
                    self._waiters.popleft()
                    lease_id = str(uuid4())
                    self._active[lease_id] = claim
                    self._condition.notify_all()
                    return ResourceLease(self, lease_id, claim)
                self._condition.wait(timeout=_WAIT_POLL_SECONDS)

    def release(self, lease_id: str) -> None:
        with self._condition:
            self._active.pop(lease_id, None)
            self._condition.notify_all()

    def snapshot(self) -> ResourceSchedulerSnapshot:
        with self._condition:
            allocations = [
                ResourceAllocation(
                    workload=claim.workload,
                    owner_id=claim.owner_id,
                    cpu_threads=claim.cpu_threads,
                    memory_bytes=claim.memory_bytes,
                    disk_bytes=claim.disk_bytes,
                    gpu_slots=claim.gpu_slots,
                )
                for claim in self._active.values()
            ]
            cpu_allocated, memory_reserved, disk_reserved, gpu_allocated = self._allocated()
            return ResourceSchedulerSnapshot(
                cpu_threads_capacity=self.cpu_threads,
                cpu_threads_allocated=cpu_allocated,
                gpu_slots_capacity=self.gpu_slots,
                gpu_slots_allocated=gpu_allocated,
                memory_reserve_bytes=self.memory_reserve_bytes,
                memory_bytes_reserved=memory_reserved,
                disk_path=str(self.disk_path),
                disk_reserve_bytes=self.disk_reserve_bytes,
                disk_bytes_reserved=disk_reserved,
                queued_requests=len(self._waiters),
                active_allocations=allocations,
            )

    def _fits(self, claim: ResourceClaim) -> bool:
        cpu, memory, disk, gpu = self._allocated()
        usable_memory = max(0, self._memory_available() - self.memory_reserve_bytes)
        usable_disk = max(0, self._disk_free() - self.disk_reserve_bytes)
        return (
            cpu + claim.cpu_threads <= self.cpu_threads
            and gpu + claim.gpu_slots <= self.gpu_slots
            and memory + claim.memory_bytes <= usable_memory
            and disk + claim.disk_bytes <= usable_disk
        )

    def _allocated(self) -> tuple[int, int, int, int]:
        return (
            sum(claim.cpu_threads for claim in self._active.values()),
            sum(claim.memory_bytes for claim in self._active.values()),
            sum(claim.disk_bytes for claim in self._active.values()),
            sum(claim.gpu_slots for claim in self._active.values()),
        )

    def _remove_waiter(self, ticket_id: str) -> None:
        self._waiters = deque(waiter for waiter in self._waiters if waiter.ticket_id != ticket_id)


def ligand_filter_claim(owner_id: str, cpu_threads: int) -> ResourceClaim:
    return ResourceClaim(
        workload="ligand_filtering",
        owner_id=owner_id,
        cpu_threads=cpu_threads,
        memory_bytes=256 * _MIB * cpu_threads,
        disk_bytes=16 * _MIB,
    )


def ligand_conformer_claim(owner_id: str) -> ResourceClaim:
    return ResourceClaim(
        workload="ligand_conformer_preparation",
        owner_id=owner_id,
        cpu_threads=1,
        memory_bytes=512 * _MIB,
        disk_bytes=32 * _MIB,
    )


def ligand_pdbqt_claim(owner_id: str) -> ResourceClaim:
    return ResourceClaim(
        workload="ligand_pdbqt_preparation",
        owner_id=owner_id,
        cpu_threads=1,
        memory_bytes=256 * _MIB,
        disk_bytes=32 * _MIB,
    )


def vina_claim(
    owner_id: str, *, cpu_threads: int, concurrent_processes: int, ligand_count: int
) -> ResourceClaim:
    return ResourceClaim(
        workload="vina_docking",
        owner_id=owner_id,
        cpu_threads=cpu_threads,
        memory_bytes=384 * _MIB * concurrent_processes,
        disk_bytes=max(8 * _MIB, 8 * _MIB * ligand_count),
    )


def autogrid_claim(owner_id: str, *, npts: tuple[int, int, int], map_count: int) -> ResourceClaim:
    point_count = (npts[0] + 1) * (npts[1] + 1) * (npts[2] + 1)
    map_bytes = point_count * max(1, map_count) * 4
    return ResourceClaim(
        workload="autogrid_map_generation",
        owner_id=owner_id,
        cpu_threads=1,
        memory_bytes=max(512 * _MIB, map_bytes * 4),
        disk_bytes=max(64 * _MIB, map_bytes * 2),
    )


def autodock4_claim(
    owner_id: str, *, concurrent_processes: int, ligand_count: int
) -> ResourceClaim:
    return ResourceClaim(
        workload="autodock4_cpu",
        owner_id=owner_id,
        cpu_threads=concurrent_processes,
        memory_bytes=256 * _MIB * concurrent_processes,
        disk_bytes=max(8 * _MIB, 8 * _MIB * ligand_count),
    )


def autodock_gpu_claim(owner_id: str, *, ligand_count: int) -> ResourceClaim:
    return ResourceClaim(
        workload="autodock_gpu",
        owner_id=owner_id,
        cpu_threads=1,
        memory_bytes=1024 * _MIB,
        disk_bytes=max(8 * _MIB, 8 * _MIB * ligand_count),
        gpu_slots=1,
    )


def _nearest_existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    return candidate


def _positive_environment_int(name: str, default: int) -> int:
    value = _nonnegative_environment_int(name, default)
    if value < 1:
        raise RuntimeError(f"{name} must be at least 1.")
    return value


def _nonnegative_environment_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer.") from error
    if value < 0:
        raise RuntimeError(f"{name} cannot be negative.")
    return value
