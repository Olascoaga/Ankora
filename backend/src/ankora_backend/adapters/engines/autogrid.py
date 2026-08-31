"""AutoGrid4 discovery, real version/limit probing, and map-set execution."""

import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from ankora_backend.adapters.engines.autodock4 import AutoDockGridPlan
from ankora_backend.adapters.tools.discovery import discover_autogrid4
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.cancellable_subprocess import (
    CancellableToolExecution,
    run_cancellable_tool,
)
from ankora_backend.execution.subprocess_runner import ToolExecution, run_tool
from ankora_backend.schemas.autogrid import AutoGridToolIdentity
from ankora_backend.schemas.provenance import ToolIdentity

_STAGE = "autogrid_map_generation"
_VERSION_PATTERN = re.compile(r"AutoGrid\s+(\d+(?:\.\d+)+)", re.IGNORECASE)
_RECEPTOR_TYPES_PATTERN = re.compile(r"NUM_RECEPTOR_TYPES\)\s*:\s*(\d+)")
_LIGAND_TYPES_PATTERN = re.compile(r"MAX_ATOM_TYPES\)\s*:\s*(\d+)")
_MAPS_PATTERN = re.compile(r"MAX_MAPS\)\s*:\s*(\d+)")
_GRID_POINTS_PATTERN = re.compile(r"MAX_GRID_PTS\)\s*:\s*(\d+)")

# Phase 0 validated exactly this build; a different one must be reviewed rather
# than silently trusted, because AutoGrid's force field and limits are compiled in.
SUPPORTED_AUTOGRID_VERSION = "4.2.6"

GRID_PARAMETER_FILENAME = "receptor.gpf"
GRID_LOG_FILENAME = "receptor.glg"
RECEPTOR_FILENAME = "receptor.pdbqt"
MAP_PREFIX = "receptor"
_SUCCESS_MARKER = "Successful Completion"


@dataclass(frozen=True, slots=True)
class AutoGridInstallation:
    executable: str
    version: str
    sha256: str
    architecture: str | None
    max_receptor_types: int
    max_ligand_types: int
    max_maps: int
    max_grid_points: int

    def identity(self) -> AutoGridToolIdentity:
        return AutoGridToolIdentity(
            tool=ToolIdentity(name="AutoGrid", version=self.version),
            executable_path=self.executable,
            sha256=self.sha256,
            architecture=self.architecture,
            max_receptor_types=self.max_receptor_types,
            max_ligand_types=self.max_ligand_types,
            max_maps=self.max_maps,
            max_grid_points=self.max_grid_points,
        )


def probe_autogrid4() -> AutoGridInstallation:
    """Verify AutoGrid by launching it, reading the limits it reports for itself."""
    discovered = discover_autogrid4(os.getenv("ANKORA_AUTOGRID4_PATH"))
    if not discovered.available or discovered.path is None:
        raise AnkoraDomainError(
            code="SCIENTIFIC_TOOL_UNAVAILABLE",
            stage=_STAGE,
            message="AutoGrid4 is not configured on this Windows system.",
            status_code=422,
            details={"tool": "AutoGrid4", "expected_version": SUPPORTED_AUTOGRID_VERSION},
        )
    execution = run_tool(
        executable=discovered.path,
        arguments=["--version"],
        cwd=Path(discovered.path).parent,
        stage=_STAGE,
        timeout_seconds=30,
    )
    output = f"{execution.stdout}\n{execution.stderr}"
    version = _VERSION_PATTERN.search(output)
    limits = {
        "max_receptor_types": _RECEPTOR_TYPES_PATTERN.search(output),
        "max_ligand_types": _LIGAND_TYPES_PATTERN.search(output),
        "max_maps": _MAPS_PATTERN.search(output),
        "max_grid_points": _GRID_POINTS_PATTERN.search(output),
    }
    missing = sorted(name for name, match in limits.items() if match is None)
    if execution.exit_code != 0 or version is None or missing:
        raise AnkoraDomainError(
            code="AUTOGRID_VERSION_UNVERIFIED",
            stage=_STAGE,
            message="Ankora found AutoGrid4 but could not verify its version and limits.",
            status_code=422,
            details={
                "command": execution.command,
                "exit_code": execution.exit_code,
                "missing_limits": missing,
                "stdout": execution.stdout,
                "stderr": execution.stderr,
            },
        )
    if version.group(1) != SUPPORTED_AUTOGRID_VERSION:
        raise AnkoraDomainError(
            code="AUTOGRID_VERSION_UNSUPPORTED",
            stage=_STAGE,
            message=(
                "This AutoDock4 implementation is validated against AutoGrid "
                f"{SUPPORTED_AUTOGRID_VERSION}."
            ),
            status_code=422,
            details={
                "detected_version": version.group(1),
                "required_version": SUPPORTED_AUTOGRID_VERSION,
            },
        )
    if discovered.sha256 is None:
        raise AnkoraDomainError(
            code="AUTOGRID_IDENTITY_UNVERIFIED",
            stage=_STAGE,
            message="Ankora could not hash the AutoGrid4 executable it would run.",
            status_code=422,
            details={"executable": discovered.path},
        )
    return AutoGridInstallation(
        executable=discovered.path,
        version=version.group(1),
        sha256=discovered.sha256,
        architecture=discovered.architecture,
        max_receptor_types=int(limits["max_receptor_types"].group(1)),  # type: ignore[union-attr]
        max_ligand_types=int(limits["max_ligand_types"].group(1)),  # type: ignore[union-attr]
        max_maps=int(limits["max_maps"].group(1)),  # type: ignore[union-attr]
        max_grid_points=int(limits["max_grid_points"].group(1)),  # type: ignore[union-attr]
    )


def validate_against_autogrid_limits(
    installation: AutoGridInstallation,
    *,
    plan: AutoDockGridPlan,
    receptor_atom_types: tuple[str, ...],
    ligand_atom_types: tuple[str, ...],
) -> None:
    """Check the planned job against the ceilings this exact build reports.

    `MAX_GRID_PTS` counts grid points while the GPF's `npts` counts intervals,
    and AutoGrid writes `npts + 1` points per axis, so the usable interval
    ceiling is one below the reported maximum.
    """
    max_intervals = installation.max_grid_points - 1
    oversized = {
        axis: count
        for axis, count in zip("xyz", plan.npts, strict=True)
        if count > max_intervals
    }
    if oversized:
        raise AnkoraDomainError(
            code="AUTOGRID_BOX_EXCEEDS_GRID_LIMIT",
            stage=_STAGE,
            message=(
                "This binding site is too large for AutoGrid at the requested "
                "spacing. Reduce the box or increase the grid spacing."
            ),
            status_code=422,
            details={
                "npts": list(plan.npts),
                "max_intervals_per_axis": max_intervals,
                "oversized_axes": oversized,
                "spacing_angstrom": plan.spacing_angstrom,
            },
        )
    if len(receptor_atom_types) > installation.max_receptor_types:
        raise AnkoraDomainError(
            code="AUTOGRID_RECEPTOR_TYPES_EXCEEDED",
            stage=_STAGE,
            message="The receptor uses more atom types than this AutoGrid build supports.",
            status_code=422,
            details={
                "receptor_atom_types": list(receptor_atom_types),
                "max_receptor_types": installation.max_receptor_types,
            },
        )
    if len(ligand_atom_types) > installation.max_ligand_types:
        raise AnkoraDomainError(
            code="AUTOGRID_LIGAND_TYPES_EXCEEDED",
            stage=_STAGE,
            message="The selection uses more ligand atom types than AutoGrid supports.",
            status_code=422,
            details={
                "ligand_atom_types": list(ligand_atom_types),
                "max_ligand_types": installation.max_ligand_types,
            },
        )
    # Affinity maps plus the electrostatic and desolvation maps share MAX_MAPS.
    required_maps = len(ligand_atom_types) + 2
    if required_maps > installation.max_maps:
        raise AnkoraDomainError(
            code="AUTOGRID_MAP_COUNT_EXCEEDED",
            stage=_STAGE,
            message="This selection requires more grid maps than AutoGrid supports.",
            status_code=422,
            details={
                "required_maps": required_maps,
                "max_maps": installation.max_maps,
            },
        )


def execute_autogrid(
    *,
    installation: AutoGridInstallation,
    job_directory: Path,
    timeout_seconds: int,
) -> ToolExecution:
    """Run AutoGrid with relative filenames inside an ASCII-safe job directory."""
    return run_tool(
        executable=installation.executable,
        arguments=["-p", GRID_PARAMETER_FILENAME, "-l", GRID_LOG_FILENAME],
        cwd=job_directory,
        stage=_STAGE,
        timeout_seconds=timeout_seconds,
    )


def execute_autogrid_cancellable(
    *,
    installation: AutoGridInstallation,
    job_directory: Path,
    timeout_seconds: int,
    cancel_event: threading.Event,
) -> CancellableToolExecution:
    """Same run, but interruptible.

    A full-protein grid takes minutes, so the scientist must be able to stop it
    without waiting for the timeout. Cancellation kills the whole process tree.
    """
    return run_cancellable_tool(
        executable=installation.executable,
        arguments=["-p", GRID_PARAMETER_FILENAME, "-l", GRID_LOG_FILENAME],
        cwd=job_directory,
        stage=_STAGE,
        cancel_event=cancel_event,
        timeout_seconds=timeout_seconds,
    )


def grid_log_reports_success(job_directory: Path) -> bool:
    """AutoGrid can exit zero on a partial run, so the log is the real verdict."""
    log_path = job_directory / GRID_LOG_FILENAME
    if not log_path.is_file():
        return False
    return _SUCCESS_MARKER in log_path.read_text(encoding="utf-8", errors="replace")
