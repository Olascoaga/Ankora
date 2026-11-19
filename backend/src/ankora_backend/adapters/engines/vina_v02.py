"""AutoDock Vina 1.2.x v0.2 extensions: FlexRes, Vinardo, and `--local_only`.

Kept separate from `ankora_backend.adapters.engines.vina` so the frozen v0.1
`LIT_PCBA_ANKORA_VS_V1` parser source bytes remain cryptographically verified
without weakening historical benchmark manifests.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path

from ankora_backend.adapters.chemistry.flex_pose_complex import split_coupled_pdbqt_model
from ankora_backend.adapters.engines.vina import VinaInstallation, probe_vina
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.cancellable_subprocess import (
    CancellableToolExecution,
    run_cancellable_tool,
)
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.docking import VinaDockingParameters, VinaScoringFunction

__all__ = [
    "ParsedVinaEnergyBreakdown",
    "ParsedVinaLocalOnlyPose",
    "ParsedVinaPose",
    "VinaInstallation",
    "build_vina_arguments",
    "build_vina_local_only_arguments",
    "execute_vina",
    "execute_vina_local_only",
    "parse_vina_local_only_output",
    "parse_vina_poses",
    "parse_vina_stdout_energy",
    "probe_vina",
]

_RESULT_PATTERN = re.compile(
    r"^REMARK VINA RESULT:\s+(-?\d+(?:\.\d+)?)\s+"
    r"(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*$"
)
_STDOUT_BINDING_ENERGY_PATTERN = re.compile(
    r"Estimated Free Energy of Binding\s*:\s*(-?\d+(?:\.\d+)?)\s*\(kcal/mol\)"
)
_STDOUT_INTERMOLECULAR_PATTERN = re.compile(
    r"\(1\)\s+Final Intermolecular Energy\s*:\s*(-?\d+(?:\.\d+)?)\s*\(kcal/mol\)"
)
_STDOUT_INTERNAL_PATTERN = re.compile(
    r"\(2\)\s+Final Total Internal Energy\s*:\s*(-?\d+(?:\.\d+)?)\s*\(kcal/mol\)"
)
_STDOUT_TORSIONAL_PATTERN = re.compile(
    r"\(3\)\s+Torsional Free Energy\s*:\s*(-?\d+(?:\.\d+)?)\s*\(kcal/mol\)"
)
_STDOUT_UNBOUND_PATTERN = re.compile(
    r"\(4\)\s+Unbound System's Energy\s*:\s*(-?\d+(?:\.\d+)?)\s*\(kcal/mol\)"
)


@dataclass(frozen=True, slots=True)
class ParsedVinaPose:
    mode: int
    affinity_kcal_mol: float
    rmsd_lower_bound_angstrom: float
    rmsd_upper_bound_angstrom: float
    content: bytes
    flex_sidechains_content: bytes | None = None
    flex_residue_markers: tuple[str, ...] = ()
    stripped_nul_line_count: int = 0


@dataclass(frozen=True, slots=True)
class ParsedVinaEnergyBreakdown:
    """Authoritative energy breakdown printed on stdout by `--score_only` / `--local_only`."""

    estimated_free_energy_kcal_mol: float
    intermolecular_kcal_mol: float | None = None
    total_internal_kcal_mol: float | None = None
    torsional_free_energy_kcal_mol: float | None = None
    unbound_system_energy_kcal_mol: float | None = None


@dataclass(frozen=True, slots=True)
class ParsedVinaLocalOnlyPose:
    """Authoritative `--local_only` pose + stdout energies (ADR-032 Addendum A4)."""

    energy: ParsedVinaEnergyBreakdown
    ligand_content: bytes
    flex_sidechains_content: bytes | None = None
    flex_residue_markers: tuple[str, ...] = ()
    stripped_nul_line_count: int = 0


def build_vina_arguments(
    *,
    receptor_path: Path,
    ligand_path: Path,
    output_path: Path,
    box: BindingBox,
    parameters: VinaDockingParameters,
    flex_receptor_path: Path | None = None,
) -> list[str]:
    arguments = [
        "--receptor",
        str(receptor_path),
    ]
    if flex_receptor_path is not None:
        arguments.extend(["--flex", str(flex_receptor_path)])
    arguments.extend(
        [
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
        ]
    )
    if parameters.scoring is not VinaScoringFunction.VINA:
        arguments.extend(["--scoring", parameters.scoring.value])
    arguments.extend(
        [
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
    )
    return arguments


def build_vina_local_only_arguments(
    *,
    receptor_path: Path,
    ligand_path: Path,
    output_path: Path,
    box: BindingBox,
    cpu_threads: int = 1,
    seed: int = 20260823,
    scoring: VinaScoringFunction = VinaScoringFunction.VINA,
    flex_receptor_path: Path | None = None,
) -> list[str]:
    """Construct explicit `--local_only` derivative refinement arguments (ADR-032 §1.5)."""
    arguments = [
        "--receptor",
        str(receptor_path),
    ]
    if flex_receptor_path is not None:
        arguments.extend(["--flex", str(flex_receptor_path)])
    arguments.extend(
        [
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
        ]
    )
    if scoring is not VinaScoringFunction.VINA:
        arguments.extend(["--scoring", scoring.value])
    arguments.extend(
        [
            "--cpu",
            str(cpu_threads),
            "--seed",
            str(seed),
            "--local_only",
            "--verbosity",
            "1",
            "--out",
            str(output_path),
        ]
    )
    return arguments


def execute_vina(
    *,
    installation: VinaInstallation,
    receptor_path: Path,
    ligand_path: Path,
    output_path: Path,
    box: BindingBox,
    parameters: VinaDockingParameters,
    cancel_event: threading.Event,
    flex_receptor_path: Path | None = None,
) -> CancellableToolExecution:
    return run_cancellable_tool(
        executable=installation.executable,
        arguments=build_vina_arguments(
            receptor_path=receptor_path,
            ligand_path=ligand_path,
            output_path=output_path,
            box=box,
            parameters=parameters,
            flex_receptor_path=flex_receptor_path,
        ),
        cwd=output_path.parent,
        stage="vina_docking",
        cancel_event=cancel_event,
        timeout_seconds=parameters.timeout_minutes * 60,
    )


def execute_vina_local_only(
    *,
    installation: VinaInstallation,
    receptor_path: Path,
    ligand_path: Path,
    output_path: Path,
    box: BindingBox,
    cpu_threads: int,
    seed: int,
    scoring: VinaScoringFunction,
    timeout_minutes: int,
    cancel_event: threading.Event,
    flex_receptor_path: Path | None = None,
) -> CancellableToolExecution:
    return run_cancellable_tool(
        executable=installation.executable,
        arguments=build_vina_local_only_arguments(
            receptor_path=receptor_path,
            ligand_path=ligand_path,
            output_path=output_path,
            box=box,
            cpu_threads=cpu_threads,
            seed=seed,
            scoring=scoring,
            flex_receptor_path=flex_receptor_path,
        ),
        cwd=output_path.parent,
        stage="vina_local_refinement",
        cancel_event=cancel_event,
        timeout_seconds=timeout_minutes * 60,
    )


def parse_vina_stdout_energy(stdout: str) -> ParsedVinaEnergyBreakdown:
    """Parse authoritative Vina `--local_only`/`--score_only` energies from stdout."""
    binding_match = _STDOUT_BINDING_ENERGY_PATTERN.search(stdout)
    if binding_match is None:
        raise _invalid_output(
            "stdout is missing authoritative Estimated Free Energy of Binding record"
        )
    inter_match = _STDOUT_INTERMOLECULAR_PATTERN.search(stdout)
    internal_match = _STDOUT_INTERNAL_PATTERN.search(stdout)
    torsional_match = _STDOUT_TORSIONAL_PATTERN.search(stdout)
    unbound_match = _STDOUT_UNBOUND_PATTERN.search(stdout)
    return ParsedVinaEnergyBreakdown(
        estimated_free_energy_kcal_mol=float(binding_match.group(1)),
        intermolecular_kcal_mol=float(inter_match.group(1)) if inter_match else None,
        total_internal_kcal_mol=float(internal_match.group(1)) if internal_match else None,
        torsional_free_energy_kcal_mol=(
            float(torsional_match.group(1)) if torsional_match else None
        ),
        unbound_system_energy_kcal_mol=float(unbound_match.group(1)) if unbound_match else None,
    )


def parse_vina_local_only_output(
    *,
    stdout: str,
    output_pdbqt: bytes,
    expect_flex_sidechains: bool = False,
) -> ParsedVinaLocalOnlyPose:
    """Parse Vina `--local_only` flat PDBQT + authoritative stdout energies (ADR-032 A4)."""
    energy = parse_vina_stdout_energy(stdout)
    text = output_pdbqt.decode("utf-8", errors="replace")
    try:
        split = split_coupled_pdbqt_model(text)
    except AnkoraDomainError as error:
        raise _invalid_output(f"invalid local_only PDBQT: {error.message}") from error
    if expect_flex_sidechains and split.flex_sidechains_pdbqt is None:
        raise _invalid_output("local_only output is missing expected BEGIN_RES flex block")
    return ParsedVinaLocalOnlyPose(
        energy=energy,
        ligand_content=split.ligand_pdbqt,
        flex_sidechains_content=split.flex_sidechains_pdbqt,
        flex_residue_markers=split.flex_residue_markers,
        stripped_nul_line_count=split.stripped_nul_line_count,
    )


def parse_vina_poses(
    content: bytes, *, expect_flex_sidechains: bool = False
) -> list[ParsedVinaPose]:
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
            poses.append(
                _parse_pose_block(mode, block, expect_flex_sidechains=expect_flex_sidechains)
            )
            in_model = False
            block = []
    if in_model:
        raise _invalid_output("unterminated MODEL record")
    if not poses:
        raise _invalid_output("no docking poses")
    if [pose.mode for pose in poses] != list(range(1, len(poses) + 1)):
        raise _invalid_output("non-sequential pose modes")
    return poses


def _parse_pose_block(
    mode: int, lines: list[str], *, expect_flex_sidechains: bool = False
) -> ParsedVinaPose:
    result_lines = [line.strip() for line in lines if line.startswith("REMARK VINA RESULT:")]
    if len(result_lines) != 1:
        raise _invalid_output(f"mode {mode} has no unique VINA RESULT record")
    match = _RESULT_PATTERN.match(result_lines[0])
    if match is None:
        raise _invalid_output(f"mode {mode} has a malformed VINA RESULT record")
    raw_block = "".join(lines)
    has_flex = expect_flex_sidechains or any(
        line.lstrip().startswith("BEGIN_RES") for line in lines
    )
    if not has_flex:
        return ParsedVinaPose(
            mode=mode,
            affinity_kcal_mol=float(match.group(1)),
            rmsd_lower_bound_angstrom=float(match.group(2)),
            rmsd_upper_bound_angstrom=float(match.group(3)),
            content=raw_block.encode("utf-8"),
        )
    try:
        split = split_coupled_pdbqt_model(raw_block)
    except AnkoraDomainError as error:
        raise _invalid_output(f"mode {mode} flex split failed: {error.message}") from error
    if expect_flex_sidechains and split.flex_sidechains_pdbqt is None:
        raise _invalid_output(f"mode {mode} is missing expected BEGIN_RES flexible side chains")
    return ParsedVinaPose(
        mode=mode,
        affinity_kcal_mol=float(match.group(1)),
        rmsd_lower_bound_angstrom=float(match.group(2)),
        rmsd_upper_bound_angstrom=float(match.group(3)),
        content=split.ligand_pdbqt,
        flex_sidechains_content=split.flex_sidechains_pdbqt,
        flex_residue_markers=split.flex_residue_markers,
        stripped_nul_line_count=split.stripped_nul_line_count,
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
