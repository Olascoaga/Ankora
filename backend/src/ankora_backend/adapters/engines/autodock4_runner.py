"""AutoDock4 CPU discovery, real limit probing, and cancellable execution."""

import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from ankora_backend.adapters.tools.discovery import discover_autodock4
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.cancellable_subprocess import (
    CancellableToolExecution,
    run_cancellable_tool,
)
from ankora_backend.execution.subprocess_runner import run_tool
from ankora_backend.schemas.autodock4 import AutoDock4ToolIdentity
from ankora_backend.schemas.provenance import ToolIdentity

_STAGE = "autodock4_docking"
_VERSION_PATTERN = re.compile(r"AutoDock\s+(\d+(?:\.\d+)+)", re.IGNORECASE)
_TORSIONS_PATTERN = re.compile(r"MAX_TORS\)\s*:\s*(\d+)")
_ATOMS_PATTERN = re.compile(r"MAX_ATOMS\)\s*:\s*(\d+)")
_MAPS_PATTERN = re.compile(r"MAX_MAPS\)\s*:\s*(\d+)")

# Phase 0 validated exactly this build. AutoDock's force field and limits are
# compiled in, so a different build must be reviewed rather than trusted.
SUPPORTED_AUTODOCK4_VERSION = "4.2.6"

DOCKING_PARAMETER_FILENAME = "ligand.dpf"
DOCKING_LOG_FILENAME = "ligand.dlg"
LIGAND_FILENAME = "ligand.pdbqt"


@dataclass(frozen=True, slots=True)
class AutoDock4Installation:
    executable: str
    version: str
    sha256: str
    architecture: str | None
    max_torsions: int
    max_atoms: int
    max_maps: int

    def identity(self) -> AutoDock4ToolIdentity:
        return AutoDock4ToolIdentity(
            tool=ToolIdentity(name="AutoDock", version=self.version),
            executable_path=self.executable,
            sha256=self.sha256,
            architecture=self.architecture,
            max_torsions=self.max_torsions,
            max_atoms=self.max_atoms,
            max_maps=self.max_maps,
        )


def probe_autodock4() -> AutoDock4Installation:
    """Verify AutoDock4 by launching it, reading the limits it reports for itself."""
    discovered = discover_autodock4(os.getenv("ANKORA_AUTODOCK4_PATH"))
    if not discovered.available or discovered.path is None:
        raise AnkoraDomainError(
            code="SCIENTIFIC_TOOL_UNAVAILABLE",
            stage=_STAGE,
            message="AutoDock4 is not configured on this Windows system.",
            status_code=422,
            details={"tool": "AutoDock4", "expected_version": SUPPORTED_AUTODOCK4_VERSION},
        )
    execution = run_tool(
        executable=discovered.path,
        arguments=["-v"],
        cwd=Path(discovered.path).parent,
        stage=_STAGE,
        timeout_seconds=30,
    )
    output = f"{execution.stdout}\n{execution.stderr}"
    version = _VERSION_PATTERN.search(output)
    limits = {
        "max_torsions": _TORSIONS_PATTERN.search(output),
        "max_atoms": _ATOMS_PATTERN.search(output),
        "max_maps": _MAPS_PATTERN.search(output),
    }
    missing = sorted(name for name, match in limits.items() if match is None)
    if execution.exit_code != 0 or version is None or missing:
        raise AnkoraDomainError(
            code="AUTODOCK4_VERSION_UNVERIFIED",
            stage=_STAGE,
            message="Ankora found AutoDock4 but could not verify its version and limits.",
            status_code=422,
            details={
                "command": execution.command,
                "exit_code": execution.exit_code,
                "missing_limits": missing,
                "stdout": execution.stdout,
                "stderr": execution.stderr,
            },
        )
    if version.group(1) != SUPPORTED_AUTODOCK4_VERSION:
        raise AnkoraDomainError(
            code="AUTODOCK4_VERSION_UNSUPPORTED",
            stage=_STAGE,
            message=(
                "This implementation is validated against AutoDock "
                f"{SUPPORTED_AUTODOCK4_VERSION}."
            ),
            status_code=422,
            details={
                "detected_version": version.group(1),
                "required_version": SUPPORTED_AUTODOCK4_VERSION,
            },
        )
    if discovered.sha256 is None:
        raise AnkoraDomainError(
            code="AUTODOCK4_IDENTITY_UNVERIFIED",
            stage=_STAGE,
            message="Ankora could not hash the AutoDock4 executable it would run.",
            status_code=422,
            details={"executable": discovered.path},
        )
    return AutoDock4Installation(
        executable=discovered.path,
        version=version.group(1),
        sha256=discovered.sha256,
        architecture=discovered.architecture,
        max_torsions=int(limits["max_torsions"].group(1)),  # type: ignore[union-attr]
        max_atoms=int(limits["max_atoms"].group(1)),  # type: ignore[union-attr]
        max_maps=int(limits["max_maps"].group(1)),  # type: ignore[union-attr]
    )


def validate_ligand_against_autodock4_limits(
    installation: AutoDock4Installation,
    *,
    atom_count: int,
    torsional_degrees_of_freedom: int,
    map_count: int,
) -> None:
    if atom_count > installation.max_atoms:
        raise _rejected(
            "AUTODOCK4_LIGAND_TOO_LARGE",
            "This ligand has more atoms than the AutoDock4 build supports.",
            {"atom_count": atom_count, "max_atoms": installation.max_atoms},
        )
    if torsional_degrees_of_freedom > installation.max_torsions:
        raise _rejected(
            "AUTODOCK4_LIGAND_TOO_FLEXIBLE",
            "This ligand has more torsions than the AutoDock4 build supports.",
            {
                "torsional_degrees_of_freedom": torsional_degrees_of_freedom,
                "max_torsions": installation.max_torsions,
            },
        )
    if map_count > installation.max_maps:
        raise _rejected(
            "AUTODOCK4_MAP_COUNT_EXCEEDED",
            "This map set has more maps than the AutoDock4 build supports.",
            {"map_count": map_count, "max_maps": installation.max_maps},
        )


def execute_autodock4_cancellable(
    *,
    installation: AutoDock4Installation,
    job_directory: Path,
    timeout_seconds: int,
    cancel_event: threading.Event,
) -> CancellableToolExecution:
    """Run AutoDock4 with relative filenames inside an ASCII-safe job directory."""
    return run_cancellable_tool(
        executable=installation.executable,
        arguments=["-p", DOCKING_PARAMETER_FILENAME, "-l", DOCKING_LOG_FILENAME],
        cwd=job_directory,
        stage=_STAGE,
        cancel_event=cancel_event,
        timeout_seconds=timeout_seconds,
    )


def _rejected(code: str, message: str, details: dict[str, object]) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code, stage=_STAGE, message=message, status_code=422, details=details
    )
