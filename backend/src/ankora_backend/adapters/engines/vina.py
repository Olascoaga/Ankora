"""AutoDock Vina 1.2.x command construction, execution, and pose parsing."""

import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from ankora_backend.adapters.tools.discovery import discover_vina
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.cancellable_subprocess import (
    CancellableToolExecution,
    run_cancellable_tool,
)
from ankora_backend.execution.subprocess_runner import run_tool
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.docking import VinaDockingParameters

_VERSION_PATTERN = re.compile(r"AutoDock Vina v(\d+(?:\.\d+)+)", re.IGNORECASE)
_RESULT_PATTERN = re.compile(
    r"^REMARK VINA RESULT:\s+(-?\d+(?:\.\d+)?)\s+"
    r"(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*$"
)


@dataclass(frozen=True, slots=True)
class VinaInstallation:
    executable: str
    version: str


@dataclass(frozen=True, slots=True)
class ParsedVinaPose:
    mode: int
    affinity_kcal_mol: float
    rmsd_lower_bound_angstrom: float
    rmsd_upper_bound_angstrom: float
    content: bytes


def probe_vina() -> VinaInstallation:
    discovered = discover_vina(os.getenv("ANKORA_VINA_PATH"))
    if not discovered.available or discovered.path is None:
        raise AnkoraDomainError(
            code="SCIENTIFIC_TOOL_UNAVAILABLE",
            stage="docking_configuration",
            message="AutoDock Vina is not configured on this Windows system.",
            status_code=422,
            details={"tool": "AutoDock Vina", "expected_version": "1.2.7"},
        )
    execution = run_tool(
        executable=discovered.path,
        arguments=["--version"],
        cwd=Path(discovered.path).parent,
        stage="docking_configuration",
        timeout_seconds=30,
    )
    output = f"{execution.stdout}\n{execution.stderr}"
    match = _VERSION_PATTERN.search(output)
    if execution.exit_code != 0 or match is None:
        raise AnkoraDomainError(
            code="VINA_VERSION_UNVERIFIED",
            stage="docking_configuration",
            message="Ankora found Vina but could not verify its executable version.",
            status_code=422,
            details={
                "command": execution.command,
                "exit_code": execution.exit_code,
                "stdout": execution.stdout,
                "stderr": execution.stderr,
            },
        )
    version = match.group(1)
    if version != "1.2.7":
        raise AnkoraDomainError(
            code="VINA_VERSION_UNSUPPORTED",
            stage="docking_configuration",
            message="This M5 implementation requires AutoDock Vina 1.2.7.",
            status_code=422,
            details={"detected_version": version, "required_version": "1.2.7"},
        )
    return VinaInstallation(executable=discovered.path, version=version)


def build_vina_arguments(
    *,
    receptor_path: Path,
    ligand_path: Path,
    output_path: Path,
    box: BindingBox,
    parameters: VinaDockingParameters,
) -> list[str]:
    return [
        "--receptor",
        str(receptor_path),
        "--ligand",
        str(ligand_path),
        "--center_x",
        _number(box.center_x),
        "--center_y",
        _number(box.center_y),
        "--center_z",
        _number(box.center_z),
        "--size_x",
        _number(box.size_x),
        "--size_y",
        _number(box.size_y),
        "--size_z",
        _number(box.size_z),
        "--cpu",
        str(parameters.cpu_threads),
        "--seed",
        str(parameters.seed),
        "--exhaustiveness",
        str(parameters.exhaustiveness),
        "--num_modes",
        str(parameters.num_modes),
        "--min_rmsd",
        _number(parameters.min_rmsd_angstrom),
        "--energy_range",
        _number(parameters.energy_range_kcal_mol),
        "--verbosity",
        "1",
        "--out",
        str(output_path),
    ]


def execute_vina(
    *,
    installation: VinaInstallation,
    receptor_path: Path,
    ligand_path: Path,
    output_path: Path,
    box: BindingBox,
    parameters: VinaDockingParameters,
    cancel_event: threading.Event,
) -> CancellableToolExecution:
    return run_cancellable_tool(
        executable=installation.executable,
        arguments=build_vina_arguments(
            receptor_path=receptor_path,
            ligand_path=ligand_path,
            output_path=output_path,
            box=box,
            parameters=parameters,
        ),
        cwd=output_path.parent,
        stage="vina_docking",
        cancel_event=cancel_event,
        timeout_seconds=parameters.timeout_minutes * 60,
    )


def parse_vina_poses(content: bytes) -> list[ParsedVinaPose]:
    """Parse each exact MODEL block using Vina's machine-readable RESULT remark."""
    text = content.decode("utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    poses: list[ParsedVinaPose] = []
    block: list[str] = []
    in_model = False
    mode = 0
    for line in lines:
        if line.startswith("MODEL"):
            if in_model:
                raise _invalid_output("nested MODEL records")
            in_model = True
            block = [line]
            try:
                mode = int(line.split()[1])
            except (IndexError, ValueError) as error:
                raise _invalid_output("invalid MODEL identifier") from error
            continue
        if not in_model:
            if line.strip():
                raise _invalid_output("content outside MODEL records")
            continue
        block.append(line)
        if line.startswith("ENDMDL"):
            poses.append(_parse_pose_block(mode, block))
            in_model = False
            block = []
    if in_model:
        raise _invalid_output("unterminated MODEL record")
    if not poses:
        raise _invalid_output("no docking poses")
    if [pose.mode for pose in poses] != list(range(1, len(poses) + 1)):
        raise _invalid_output("non-sequential pose modes")
    return poses


def _parse_pose_block(mode: int, lines: list[str]) -> ParsedVinaPose:
    result_lines = [line.strip() for line in lines if line.startswith("REMARK VINA RESULT:")]
    if len(result_lines) != 1:
        raise _invalid_output(f"mode {mode} has no unique VINA RESULT record")
    match = _RESULT_PATTERN.match(result_lines[0])
    if match is None:
        raise _invalid_output(f"mode {mode} has a malformed VINA RESULT record")
    content = "".join(lines).encode("utf-8")
    return ParsedVinaPose(
        mode=mode,
        affinity_kcal_mol=float(match.group(1)),
        rmsd_lower_bound_angstrom=float(match.group(2)),
        rmsd_upper_bound_angstrom=float(match.group(3)),
        content=content,
    )


def _invalid_output(reason: str) -> AnkoraDomainError:
    return AnkoraDomainError(
        code="VINA_OUTPUT_INVALID",
        stage="vina_pose_parsing",
        message="AutoDock Vina produced an output Ankora could not validate.",
        status_code=500,
        details={"reason": reason},
        recoverable=False,
    )


def _number(value: float) -> str:
    return format(value, ".8g")
