"""AutoDock-GPU discovery, device probing, and cancellable execution.

Everything encoded here was read from the real `AutoDock-GPU.exe` v1.6 on
Windows, not from documentation. Three of its behaviours drive this module and
none of them match the CPU engine:

1. **There is no device-listing flag.** The only way to learn which OpenCL
   device will actually be used is to launch the tool. It does select and print
   the device *before* it validates its inputs, so a probe can name the device
   without a ligand, a map set, or any GPU work.

2. **It exits zero on failure.** A run with a missing `.fld` still returned 0.
   The exit code carries no verdict, so success is read from the phrases the
   tool prints on stdout.

3. **Its `.dlg` has no completion marker.** `autodock4_job.log_reports_success`
   tests for "Successful Completion", which AutoDock-GPU never writes; its log
   ends at `Run time` / `Idle time`. The rest of that parser applies unchanged,
   so only the verdict needs a separate path.

The GPU is a different search, not a faster CPU. It defaults to heuristics,
automatic stopping, and ADADELTA local search where the CPU protocol uses
Solis-Wets, and on identical maps and seeds the two reach different minima.
`DOCKING_POLICY.md` forbids merging engines; the same rule holds between
backends of one engine, so the backend is recorded on every result and GPU
results are never pooled with CPU ones.
"""

import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from ankora_backend.adapters.tools.discovery import discover_autodock_gpu
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.cancellable_subprocess import (
    CancellableToolExecution,
    run_cancellable_tool,
)
from ankora_backend.execution.subprocess_runner import run_tool

_STAGE = "autodock_gpu_docking"

# "AutoDock-GPU version: v1.6|Release|x64"
_VERSION_PATTERN = re.compile(
    r"AutoDock-GPU\s+version:\s*v?(\d+(?:\.\d+)+)\s*\|\s*(\w+)\s*\|\s*(\w+)",
    re.IGNORECASE,
)
# "OpenCL device:                           NVIDIA GeForce RTX 5050 Laptop GPU"
_DEVICE_PATTERN = re.compile(r"^\s*(?:OpenCL|Cuda)\s+device:\s*(.+?)\s*$", re.MULTILINE)

# The tool's own verdicts, captured verbatim from real successful and failed
# runs. Exit codes are useless here, so these are the only signal.
_SUCCESS_SENTINEL = "All jobs ran without errors."
_FAILURE_SENTINEL = "The job was not successful."

# Phase 5 probed exactly this build. The scoring parameters and search defaults
# are compiled in, so a different build must be reviewed rather than trusted.
SUPPORTED_AUTODOCK_GPU_VERSION = "1.6"

LIGAND_FILENAME = "ligand.pdbqt"
MAPS_FIELD_FILENAME = "receptor.maps.fld"
RESULT_BASENAME = "ligand"
DOCKING_LOG_FILENAME = f"{RESULT_BASENAME}.dlg"


@dataclass(frozen=True, slots=True)
class AutoDockGpuInstallation:
    executable: str
    version: str
    sha256: str
    architecture: str | None
    build: str
    """`Release` or `Debug`, as the tool reports it."""
    device_name: str | None
    """The OpenCL device the tool selected, or None when it named none."""

    @property
    def device_available(self) -> bool:
        return self.device_name is not None


def probe_autodock_gpu(*, device_number: int = 1) -> AutoDockGpuInstallation:
    """Verify AutoDock-GPU by launching it, and learn which device it will use.

    Two launches, because the tool splits the information: `--help` reports the
    version and exits zero without touching a device, and a deliberately
    input-less run reports the device it selects. The second launch cannot
    dock - it has no ligand and no maps - and is only ever asked what hardware
    it found.
    """
    discovered = discover_autodock_gpu(os.getenv("ANKORA_AUTODOCK_GPU_PATH"))
    if not discovered.available or discovered.path is None:
        raise AnkoraDomainError(
            code="SCIENTIFIC_TOOL_UNAVAILABLE",
            stage=_STAGE,
            message="AutoDock-GPU is not configured on this Windows system.",
            status_code=422,
            details={
                "tool": "AutoDock-GPU",
                "expected_version": SUPPORTED_AUTODOCK_GPU_VERSION,
            },
        )
    if discovered.sha256 is None:
        raise AnkoraDomainError(
            code="AUTODOCK_GPU_IDENTITY_UNVERIFIED",
            stage=_STAGE,
            message="Ankora could not hash the AutoDock-GPU executable it would run.",
            status_code=422,
            details={"executable": discovered.path},
        )

    working_directory = Path(discovered.path).parent
    help_execution = run_tool(
        executable=discovered.path,
        arguments=["--help"],
        cwd=working_directory,
        stage=_STAGE,
        timeout_seconds=30,
    )
    version_match = _VERSION_PATTERN.search(
        f"{help_execution.stdout}\n{help_execution.stderr}"
    )
    if help_execution.exit_code != 0 or version_match is None:
        raise AnkoraDomainError(
            code="AUTODOCK_GPU_VERSION_UNVERIFIED",
            stage=_STAGE,
            message="Ankora found AutoDock-GPU but could not verify its version.",
            status_code=422,
            details={
                "command": help_execution.command,
                "exit_code": help_execution.exit_code,
                "stdout": help_execution.stdout,
                "stderr": help_execution.stderr,
            },
        )
    version = version_match.group(1)
    if version != SUPPORTED_AUTODOCK_GPU_VERSION:
        raise AnkoraDomainError(
            code="AUTODOCK_GPU_VERSION_UNSUPPORTED",
            stage=_STAGE,
            message=(
                "This implementation is validated against AutoDock-GPU "
                f"{SUPPORTED_AUTODOCK_GPU_VERSION}."
            ),
            status_code=422,
            details={
                "detected_version": version,
                "required_version": SUPPORTED_AUTODOCK_GPU_VERSION,
            },
        )

    return AutoDockGpuInstallation(
        executable=discovered.path,
        version=version,
        sha256=discovered.sha256,
        architecture=discovered.architecture or version_match.group(3),
        build=version_match.group(2),
        device_name=_probe_device(
            executable=discovered.path,
            working_directory=working_directory,
            device_number=device_number,
        ),
    )


def _probe_device(
    *, executable: str, working_directory: Path, device_number: int
) -> str | None:
    """Ask the tool which device it selects, without giving it work to do.

    It initialises OpenCL and prints the device before it reads its inputs, so
    pointing it at a file that does not exist yields the hardware answer and
    nothing else. A machine with no usable device names none; that is reported
    rather than raised, because discovery is not the moment to refuse.
    """
    execution = run_tool(
        executable=executable,
        arguments=[
            "--ffile", "ankora-device-probe.fld",
            "--lfile", "ankora-device-probe.pdbqt",
            "--devnum", str(device_number),
            "--nrun", "1",
        ],
        cwd=working_directory,
        stage=_STAGE,
        timeout_seconds=120,
    )
    match = _DEVICE_PATTERN.search(f"{execution.stdout}\n{execution.stderr}")
    return match.group(1) if match else None


def require_device(installation: AutoDockGpuInstallation) -> str:
    """The device name, or an explicit refusal to dock without one."""
    if installation.device_name is None:
        raise AnkoraDomainError(
            code="AUTODOCK_GPU_NO_DEVICE",
            stage=_STAGE,
            message=(
                "AutoDock-GPU is installed but selected no OpenCL device, so it "
                "cannot dock on this machine."
            ),
            status_code=422,
            details={"executable": installation.executable},
        )
    return installation.device_name


def build_arguments(
    *,
    field_filename: str = MAPS_FIELD_FILENAME,
    device_number: int,
    runs: int,
    seed: tuple[int, int, int],
    heuristics: bool,
    autostop: bool,
    energy_evaluations: int | None,
    population_size: int,
    local_search_method: str,
    cluster_rmsd_tolerance_angstrom: float,
) -> list[str]:
    """The exact command line, with every search setting stated explicitly.

    Nothing is left to the tool's defaults. AutoDock-GPU's own defaults enable
    heuristics and automatic stopping, which silently decide how much searching
    happens; a recorded protocol has to say what was asked for, so every flag
    that governs the search is written out even when it matches the default.
    `--nev` is omitted only when heuristics are on, because the heuristic is
    then what sets the evaluation count.
    """
    arguments = [
        "--ffile", field_filename,
        "--lfile", LIGAND_FILENAME,
        "--resnam", RESULT_BASENAME,
        "--devnum", str(device_number),
        "--nrun", str(runs),
        "--seed", ",".join(str(value) for value in seed),
        "--heuristics", "1" if heuristics else "0",
        "--autostop", "1" if autostop else "0",
        "--psize", str(population_size),
        "--lsmet", local_search_method,
        "--rmstol", _format_number(cluster_rmsd_tolerance_angstrom),
        "--dlgoutput", "1",
        "--xmloutput", "0",
    ]
    if not heuristics:
        if energy_evaluations is None:
            raise AnkoraDomainError(
                code="AUTODOCK_GPU_EVALUATIONS_REQUIRED",
                stage=_STAGE,
                message=(
                    "With the heuristic disabled, the number of score "
                    "evaluations per run must be stated explicitly."
                ),
                status_code=422,
                details={},
            )
        arguments += ["--nev", str(energy_evaluations)]
    return arguments


def execute_autodock_gpu_cancellable(
    *,
    installation: AutoDockGpuInstallation,
    job_directory: Path,
    arguments: list[str],
    timeout_seconds: int,
    cancel_event: threading.Event,
) -> CancellableToolExecution:
    """Run AutoDock-GPU with relative filenames inside an ASCII-safe directory."""
    return run_cancellable_tool(
        executable=installation.executable,
        arguments=arguments,
        cwd=job_directory,
        stage=_STAGE,
        cancel_event=cancel_event,
        timeout_seconds=timeout_seconds,
    )


def run_reports_success(stdout: str) -> bool:
    """Whether AutoDock-GPU says the run worked.

    Its exit code does not: a run whose map file did not exist still returned
    zero. The tool states the verdict in words instead, and a run that says
    neither is not assumed to have worked.
    """
    if _FAILURE_SENTINEL in stdout:
        return False
    return _SUCCESS_SENTINEL in stdout


def _format_number(value: float) -> str:
    return f"{value:g}"
