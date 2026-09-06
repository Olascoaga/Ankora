"""What this machine is doing right now, for the status bar.

A docking campaign is the most expensive thing Ankora does, and until now the
only way to see what it cost the machine was to open Task Manager. This
samples CPU, memory and the GPU on request.

The rule is the one the rest of the project follows: report what was measured
and say why when something could not be. A machine with no NVIDIA driver
reports no GPU and the reason, never a reassuring 0%.
"""

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from threading import Lock
from typing import Any

from ankora_backend.schemas.system import (
    GpuUsage,
    ResourceSchedulerSnapshot,
    ResourceUsage,
)

# `cpu_percent(interval=None)` reports the load since the previous call, so the
# very first one in a process has nothing to compare against and returns 0.0.
# Priming here means the first request a user ever makes is already a real
# measurement rather than a zero that looks like an idle machine.
_psutil: Any = import_module("psutil")
_psutil.cpu_percent(interval=None)

# `nvidia-smi` costs about 47 ms, measured, because it starts a process. The
# status bar polls, so one reading is shared across anything asking within the
# same couple of seconds rather than paying that per request.
_GPU_CACHE_SECONDS = 2.0
_GPU_TIMEOUT_SECONDS = 4.0

GpuReading = tuple[GpuUsage | None, str | None]


@dataclass(frozen=True, slots=True)
class _CachedGpuReading:
    captured_at: float
    usage: GpuUsage | None
    unavailable_reason: str | None


class _GpuTelemetryCache:
    """A short-lived, single-flight cache around the NVIDIA driver probe.

    FastAPI may execute several synchronous resource requests on different
    worker threads.  Cache inspection, refresh, and publication therefore form
    one critical section: at most one request starts ``nvidia-smi`` and every
    waiter receives that complete reading rather than racing a second process
    or observing partially updated state.
    """

    def __init__(self, *, lifetime_seconds: float) -> None:
        self._lifetime_seconds = lifetime_seconds
        self._lock = Lock()
        self._reading: _CachedGpuReading | None = None

    def read(self, loader: Callable[[], GpuReading]) -> GpuReading:
        with self._lock:
            now = time.monotonic()
            if (
                self._reading is not None
                and now - self._reading.captured_at < self._lifetime_seconds
            ):
                return self._reading.usage, self._reading.unavailable_reason

            usage, reason = loader()
            self._reading = _CachedGpuReading(
                captured_at=time.monotonic(),
                usage=usage,
                unavailable_reason=reason,
            )
            return usage, reason

    def clear(self) -> None:
        """Discard one reading through the same serialized boundary as reads."""
        with self._lock:
            self._reading = None


_gpu_cache = _GpuTelemetryCache(lifetime_seconds=_GPU_CACHE_SECONDS)


def collect_resource_usage(*, scheduler: ResourceSchedulerSnapshot | None = None) -> ResourceUsage:
    memory = _psutil.virtual_memory()
    gpu, reason = _gpu_usage()
    return ResourceUsage(
        cpu_percent=float(_psutil.cpu_percent(interval=None)),
        logical_cores=int(_psutil.cpu_count(logical=True) or 0),
        memory_used_bytes=int(memory.total - memory.available),
        memory_total_bytes=int(memory.total),
        memory_percent=float(memory.percent),
        gpu=gpu,
        gpu_unavailable_reason=reason,
        scheduler=scheduler,
    )


def _gpu_usage() -> GpuReading:
    return _gpu_cache.read(_query_nvidia_smi)


def _query_nvidia_smi() -> GpuReading:
    """The driver's own tool, asked for exactly four numbers.

    An argument array with `shell=False`, like every other process Ankora
    starts, and a timeout so a wedged driver cannot hold the status bar.
    """
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=_GPU_TIMEOUT_SECONDS,
            shell=False,
        )
    except FileNotFoundError:
        return None, "No NVIDIA driver tools are installed on this machine."
    except subprocess.TimeoutExpired:
        return None, "The NVIDIA driver did not answer."
    except OSError as error:
        return None, f"The NVIDIA driver could not be queried: {error}."

    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        return None, detail[0] if detail else "nvidia-smi reported an error."

    line = (completed.stdout or "").strip().splitlines()
    if not line:
        return None, "No NVIDIA GPU was reported."
    fields = [part.strip() for part in line[0].split(",")]
    if len(fields) != 4:
        return None, "The NVIDIA driver reported an unexpected format."
    try:
        return GpuUsage(
            name=fields[0],
            utilization_percent=float(fields[1]),
            # nvidia-smi reports mebibytes under `nounits`.
            memory_used_bytes=int(float(fields[2]) * 1024 * 1024),
            memory_total_bytes=int(float(fields[3]) * 1024 * 1024),
        ), None
    except ValueError:
        return None, "The NVIDIA driver reported values Ankora could not read."
