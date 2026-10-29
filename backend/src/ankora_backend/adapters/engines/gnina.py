"""GNINA 1.3.3 Linux engine boundary and strict SDF pose parsing.

The SDF fields in this module are anchored to the recorded GNINA 1.3.3 CUDA
engineering run on synthetic ethanol. Values are engine predictions, not
experimentally measured affinities. No scientific executable is run by the UI.
"""

from __future__ import annotations

import io
import math
import os
import re
import sys
import threading
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from rdkit import Chem

from ankora_backend.adapters.tools.discovery import _read_elf_architecture, discover_tool
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.cancellable_subprocess import (
    CancellableToolExecution,
    run_cancellable_tool,
)
from ankora_backend.execution.subprocess_runner import run_tool
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.gnina import GninaDockingParameters

_STAGE = "gnina_docking"
_VERSION_PATTERN = re.compile(r"\bgnina\s+v?(\d+(?:\.\d+)+)\b", re.IGNORECASE)
_SUPPORTED_VERSION = "1.3.3"
_SDF_PROPERTY = re.compile(rb"^>\s*<([^>]+)>")


@dataclass(frozen=True, slots=True)
class GninaInstallation:
    executable: str
    version: str
    sha256: str
    architecture: str


@dataclass(frozen=True, slots=True)
class GninaPose:
    """One actual SDF record, in the order written by GNINA."""

    mode: int
    minimized_affinity_kcal_mol: float
    cnn_score: float
    cnn_affinity: float
    cnn_vs: float | None
    cnn_affinity_variance: float | None
    sdf: bytes


def _error(code: str, message: str, **details: object) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code, stage=_STAGE, message=message, status_code=422, details=details
    )


def _linux_host() -> bool:
    return sys.platform.startswith("linux")


def probe_gnina() -> GninaInstallation:
    """Find and verify a Linux ELF and its reported version; never run on Windows."""
    if not _linux_host():
        raise _error("GNINA_LINUX_ONLY", "GNINA is available only in the Linux edition of Ankora.")
    candidate = discover_tool("gnina", os.getenv("ANKORA_GNINA_PATH"))
    if not candidate.available or candidate.path is None:
        raise _error("SCIENTIFIC_TOOL_UNAVAILABLE", "GNINA is not configured on this Linux system.")
    path = Path(candidate.path).resolve()
    if _read_elf_architecture(path) != "x86_64":
        raise _error(
            "GNINA_EXECUTABLE_INVALID", "GNINA requires a native Linux x86-64 ELF executable."
        )
    digest = sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise _error(
            "GNINA_IDENTITY_UNVERIFIED", "Ankora could not hash the GNINA executable."
        ) from error
    execution = run_tool(
        executable=str(path),
        arguments=["--version"],
        cwd=path.parent,
        stage=_STAGE,
        timeout_seconds=30,
    )
    match = _VERSION_PATTERN.search(f"{execution.stdout}\n{execution.stderr}")
    if execution.exit_code != 0 or match is None:
        raise _error(
            "GNINA_VERSION_UNVERIFIED",
            "Ankora could not verify the GNINA version.",
            command=execution.command,
            exit_code=execution.exit_code,
            stdout=execution.stdout,
            stderr=execution.stderr,
        )
    version = match.group(1)
    if version != _SUPPORTED_VERSION:
        raise _error(
            "GNINA_VERSION_UNSUPPORTED",
            "This GNINA adapter requires the validated 1.3.3 version.",
            detected_version=version,
            required_version=_SUPPORTED_VERSION,
        )
    return GninaInstallation(str(path), version, digest.hexdigest(), "x86_64")


def build_gnina_arguments(
    *,
    receptor_path: Path,
    ligand_path: Path,
    output_path: Path,
    box: BindingBox,
    parameters: GninaDockingParameters,
) -> list[str]:
    """Build an argument array; built-in model and hydrogen defaults are recorded settings."""
    values = (box.center_x, box.center_y, box.center_z, box.size_x, box.size_y, box.size_z)
    if not all(math.isfinite(value) for value in values):
        raise _error("GNINA_INPUT_INVALID", "The GNINA search box must contain finite coordinates.")
    if output_path.suffix.lower() != ".sdf" or output_path.resolve() in {
        receptor_path.resolve(),
        ligand_path.resolve(),
    }:
        raise _error("GNINA_INPUT_INVALID", "GNINA poses require a distinct SDF output path.")
    arguments = [
        "--receptor",
        str(receptor_path),
        "--ligand",
        str(ligand_path),
        "--center_x",
        str(box.center_x),
        "--center_y",
        str(box.center_y),
        "--center_z",
        str(box.center_z),
        "--size_x",
        str(box.size_x),
        "--size_y",
        str(box.size_y),
        "--size_z",
        str(box.size_z),
        "--cpu",
        str(parameters.cpu_threads),
        "--seed",
        str(parameters.seed),
        "--exhaustiveness",
        str(parameters.exhaustiveness),
        "--num_modes",
        str(parameters.num_modes),
        "--min_rmsd_filter",
        str(parameters.min_rmsd_filter_angstrom),
        "--cnn_scoring",
        parameters.cnn_scoring,
        "--out",
        str(output_path),
    ]
    if parameters.compute == "cpu":
        arguments.append("--no_gpu")
    else:
        arguments.extend(("--device", str(parameters.device_index)))
    return arguments


def execute_gnina(
    *,
    installation: GninaInstallation,
    receptor_path: Path,
    ligand_path: Path,
    output_path: Path,
    box: BindingBox,
    parameters: GninaDockingParameters,
    cancel_event: threading.Event,
) -> CancellableToolExecution:
    """Run GNINA in a caller-owned isolated directory, preserving raw tool output.

    This boundary does not itself verify GPU execution or publish results; the
    future service must do both and use an exclusive, create-only directory.
    """
    if output_path.exists():
        raise _error(
            "GNINA_OUTPUT_EXISTS", "The GNINA output already exists; it cannot be overwritten."
        )
    return run_cancellable_tool(
        executable=installation.executable,
        arguments=build_gnina_arguments(
            receptor_path=receptor_path,
            ligand_path=ligand_path,
            output_path=output_path,
            box=box,
            parameters=parameters,
        ),
        cwd=output_path.parent,
        stage=_STAGE,
        cancel_event=cancel_event,
        timeout_seconds=parameters.timeout_minutes * 60,
    )


def _value(mol: Chem.Mol, name: str, *, optional: bool = False) -> float | None:
    if not mol.HasProp(name):
        if optional:
            return None
        raise _error(
            "GNINA_OUTPUT_INVALID", "A GNINA pose is missing a required score.", field=name
        )
    raw = mol.GetProp(name).strip()
    try:
        result = float(raw)
    except ValueError as error:
        raise _error(
            "GNINA_OUTPUT_INVALID", "A GNINA pose has an invalid score.", field=name
        ) from error
    if not math.isfinite(result):
        raise _error("GNINA_OUTPUT_INVALID", "A GNINA pose has a non-finite score.", field=name)
    return result


def parse_gnina_sdf(content: bytes) -> list[GninaPose]:
    """Read all GNINA records without sorting or rewriting their source bytes."""
    records: list[bytes] = []
    block: list[bytes] = []
    for line in content.splitlines(keepends=True):
        block.append(line)
        if line.rstrip(b"\r\n") == b"$$$$":
            records.append(b"".join(block))
            block = []
    if b"".join(block).strip() or not records:
        raise _error("GNINA_OUTPUT_INVALID", "The GNINA SDF is empty or has an incomplete record.")
    poses: list[GninaPose] = []
    score_fields = {
        b"minimizedAffinity",
        b"CNNscore",
        b"CNNaffinity",
        b"CNN_VS",
        b"CNNaffinity_variance",
    }
    for mode, record in enumerate(records, start=1):
        fields: set[bytes] = set()
        for line in record.splitlines():
            match = _SDF_PROPERTY.match(line)
            if match and match.group(1) in score_fields:
                if match.group(1) in fields:
                    raise _error(
                        "GNINA_OUTPUT_INVALID", "A GNINA pose repeats a score field.", mode=mode
                    )
                fields.add(match.group(1))
        supplier = Chem.ForwardSDMolSupplier(io.BytesIO(record), sanitize=True, removeHs=False)
        mol = next(supplier, None)
        if mol is None or not mol.GetNumAtoms() or not mol.GetNumConformers():
            raise _error(
                "GNINA_OUTPUT_INVALID", "A GNINA pose has invalid molecular geometry.", mode=mode
            )
        conformer = mol.GetConformer()
        for atom in range(mol.GetNumAtoms()):
            position = conformer.GetAtomPosition(atom)
            if not all(math.isfinite(value) for value in (position.x, position.y, position.z)):
                raise _error(
                    "GNINA_OUTPUT_INVALID", "A GNINA pose has non-finite coordinates.", mode=mode
                )
        affinity = _value(mol, "minimizedAffinity")
        score = _value(mol, "CNNscore")
        cnn_affinity = _value(mol, "CNNaffinity")
        assert affinity is not None and score is not None and cnn_affinity is not None
        poses.append(
            GninaPose(
                mode,
                affinity,
                score,
                cnn_affinity,
                _value(mol, "CNN_VS", optional=True),
                _value(mol, "CNNaffinity_variance", optional=True),
                record,
            )
        )
    return poses
