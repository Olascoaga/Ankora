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
from collections.abc import Sequence
from dataclasses import dataclass, replace
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import Any, Literal

from ankora_backend.adapters.chemistry.flex_pose_complex import (
    parse_gnina_flex_pdb_models,
    reinject_gnina_flex_pdb_into_meeko_template,
)
from ankora_backend.adapters.tools.discovery import _read_elf_architecture, discover_tool
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.cancellable_subprocess import (
    CancellableToolExecution,
    run_cancellable_tool,
)
from ankora_backend.execution.subprocess_runner import run_tool
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.gnina import (
    GninaCnnModelIdentity,
    GninaCnnModelSelector,
    GninaDockingParameters,
    GninaLocalRefinementRequest,
)
from ankora_backend.services.gnina_pack import gnina_subprocess_environment

Chem: Any = import_module("rdkit.Chem")
_STAGE = "gnina_docking"
_VERSION_PATTERN = re.compile(r"\bgnina\s+v?(\d+(?:\.\d+)+)\b", re.IGNORECASE)
_SUPPORTED_VERSION = "1.3.3"
VERIFIED_GNINA_1_3_3_SHA256 = (
    "3340c1f49cd3c7c84d8699182a1c6af13c7fa2a22448d1204640446106f72172"
)
_ENSEMBLE_MEMBERS: dict[GninaCnnModelSelector, tuple[str, ...]] = {
    "dense_1_3": ("dense_1_3",),
    "default_1_3_ensemble": (
        "dense_1_3",
        "dense_1_3_PT_KD_3",
        "crossdock_default2018_KD_4",
    ),
    "default1.0": (
        "dense",
        "general_default2018_3",
        "dense_3",
        "crossdock_default2018",
        "redock_default2018_2",
    ),
}
_SDF_PROPERTY = re.compile(rb"^>\s*<([^>]+)>")
_GNINA_FLOAT = r"([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
_SCORE_ONLY_AFFINITY = re.compile(
    rf"^Affinity:\s+{_GNINA_FLOAT}(?:\s+\(?kcal/mol\)?)?", re.MULTILINE
)
_SCORE_ONLY_INTRAMOL = re.compile(
    rf"^Intramolecular energy:\s+{_GNINA_FLOAT}", re.MULTILINE
)
_SCORE_ONLY_CNN_SCORE = re.compile(rf"^CNNscore:\s+{_GNINA_FLOAT}", re.MULTILINE)
_SCORE_ONLY_CNN_AFFINITY = re.compile(rf"^CNNaffinity:\s+{_GNINA_FLOAT}", re.MULTILINE)
_SCORE_ONLY_CNN_VARIANCE = re.compile(rf"^CNNvariance:\s+{_GNINA_FLOAT}", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class ParsedGninaScoreOnlyResult:
    """In-place GNINA 1.3.3 `--score_only` scores parsed from stdout (no pose mutation)."""

    minimized_affinity_kcal_mol: float
    intramolecular_energy_kcal_mol: float | None = None
    cnn_score: float | None = None
    cnn_affinity: float | None = None
    cnn_vs: float | None = None
    cnn_affinity_variance: float | None = None
    used_flex: bool = False


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


@dataclass(frozen=True, slots=True)
class GninaPdbqtPose:
    """One intact GNINA PDBQT pose in the engine's recorded rank order."""

    mode: int
    minimized_affinity_kcal_mol: float
    cnn_score: float
    cnn_affinity: float
    pdbqt: bytes
    cnn_vs: float | None = None
    cnn_affinity_variance: float | None = None


def _error(code: str, message: str, **details: object) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code, stage=_STAGE, message=message, status_code=422, details=details
    )


def _linux_host() -> bool:
    return sys.platform.startswith("linux")


def _sha256_executable(path: Path) -> str:
    digest = sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise _error(
            "GNINA_IDENTITY_UNVERIFIED", "Ankora could not hash the GNINA executable."
        ) from error
    return digest.hexdigest()


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
    digest = _sha256_executable(path)
    env = gnina_subprocess_environment(path)
    probe_kwargs: dict[str, Any] = {}
    if env is not None:
        probe_kwargs["environment"] = env
    execution = run_tool(
        executable=str(path),
        arguments=["--version"],
        cwd=path.parent,
        stage=_STAGE,
        timeout_seconds=30,
        **probe_kwargs,
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
    return GninaInstallation(str(path), version, digest, "x86_64")


def resolve_cnn_model_identity(
    selector: GninaCnnModelSelector,
    *,
    binary_sha256: str,
) -> GninaCnnModelIdentity:
    """Resolve explicit built-in CNN model or ensemble members for a GNINA build.

    Built-in ensemble selectors (`default_1_3_ensemble` and `default1.0`) depend
    on the internal `CNNTorchScorer` ensemble table compiled into the verified
    official GNINA 1.3.3 Linux binary (`VERIFIED_GNINA_1_3_3_SHA256`), so an
    unverified binary is refused rather than allowed to claim unverified
    built-in ensemble membership.
    """
    if selector != "dense_1_3" and binary_sha256.lower() != VERIFIED_GNINA_1_3_3_SHA256:
        raise _error(
            "GNINA_CNN_ENSEMBLE_UNVERIFIED_BINARY",
            "Built-in GNINA CNN ensembles require the verified GNINA 1.3.3 executable "
            "SHA-256 so ensemble member provenance is exact.",
            selector=selector,
            binary_sha256=binary_sha256,
            expected_sha256=VERIFIED_GNINA_1_3_3_SHA256,
        )
    members = _ENSEMBLE_MEMBERS[selector]
    cli_arg = None if selector == "default_1_3_ensemble" else selector
    return GninaCnnModelIdentity(
        selector=selector,
        cli_argument=cli_arg,
        member_names=members,
        member_count=len(members),
    )


def build_gnina_arguments(
    *,
    receptor_path: Path,
    ligand_path: Path,
    output_path: Path,
    box: BindingBox,
    parameters: GninaDockingParameters,
    flex_receptor_path: Path | None = None,
    out_flex_path: Path | None = None,
) -> list[str]:
    return _build_arguments(
        receptor_path=receptor_path,
        ligand_path=ligand_path,
        output_path=output_path,
        box=box,
        parameters=parameters,
        flex_receptor_path=flex_receptor_path,
        out_flex_path=out_flex_path,
        search_arguments=[
            "--exhaustiveness", str(parameters.exhaustiveness),
            "--num_modes", str(parameters.num_modes),
            "--min_rmsd_filter", str(parameters.min_rmsd_filter_angstrom),
        ],
    )


def build_gnina_local_only_arguments(
    *,
    receptor_path: Path,
    ligand_path: Path,
    output_path: Path,
    box: BindingBox,
    parameters: GninaLocalRefinementRequest,
    flex_receptor_path: Path | None = None,
    out_flex_path: Path | None = None,
) -> list[str]:
    return _build_arguments(
        receptor_path=receptor_path,
        ligand_path=ligand_path,
        output_path=output_path,
        box=box,
        parameters=parameters,
        flex_receptor_path=flex_receptor_path,
        out_flex_path=out_flex_path,
        search_arguments=["--local_only"],
    )


def _build_arguments(
    *,
    receptor_path: Path,
    ligand_path: Path,
    output_path: Path,
    box: BindingBox,
    parameters: GninaDockingParameters | GninaLocalRefinementRequest,
    flex_receptor_path: Path | None,
    out_flex_path: Path | None,
    search_arguments: list[str],
) -> list[str]:
    values = (box.center_x, box.center_y, box.center_z, box.size_x, box.size_y, box.size_z)
    if not all(math.isfinite(value) for value in values):
        raise _error("GNINA_INPUT_INVALID", "The GNINA search box must contain finite coordinates.")
    if (
        receptor_path.suffix.lower() != ".pdbqt"
        or ligand_path.suffix.lower() != ".pdbqt"
        or output_path.suffix.lower() not in {".sdf", ".pdbqt"}
        or output_path.resolve()
        in {
            receptor_path.resolve(),
            ligand_path.resolve(),
        }
    ):
        raise _error(
            "GNINA_INPUT_INVALID",
            "GNINA requires prepared PDBQT inputs and a distinct SDF or PDBQT output.",
        )
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
        *search_arguments,
        "--cnn_scoring",
        parameters.cnn_scoring,
    ]
    if parameters.cnn_model != "default_1_3_ensemble":
        arguments.extend(("--cnn", parameters.cnn_model))
    arguments.extend(
        (
            "--addH",
            "0",
            "--stripH",
            "0",
            "--out",
            str(output_path),
        )
    )
    if parameters.compute == "cpu":
        arguments.append("--no_gpu")
    else:
        arguments.extend(("--device", str(parameters.device_index)))
    if flex_receptor_path is not None or out_flex_path is not None:
        if (
            flex_receptor_path is None
            or out_flex_path is None
            or flex_receptor_path.suffix.lower() != ".pdbqt"
            or out_flex_path.suffix.lower() != ".pdb"
            or output_path.resolve() == flex_receptor_path.resolve()
            or out_flex_path.resolve() in {
                path.resolve() for path in (
                    receptor_path, ligand_path, flex_receptor_path, output_path
                )
            }
        ):
            raise _error(
                "GNINA_INPUT_INVALID",
                "GNINA FlexRes requires a PDBQT side-chain input and a distinct PDB flex output.",
            )
        arguments.extend(("--flex", str(flex_receptor_path), "--out_flex", str(out_flex_path)))
    return arguments


def build_gnina_score_only_arguments(
    *,
    receptor_path: Path,
    ligand_path: Path,
    compute: Literal["cpu", "cuda"] = "cpu",
    device_index: int = 0,
    cpu_threads: int = 1,
    cnn_scoring: Literal["none", "rescore", "all"] = "rescore",
    cnn_model: GninaCnnModelSelector = "dense_1_3",
    flex_receptor_path: Path | None = None,
) -> list[str]:
    """Build explicit `--score_only` arguments (evaluates fixed coordinates in place)."""
    if cpu_threads < 1:
        raise _error("GNINA_INPUT_INVALID", "GNINA --score_only requires cpu_threads >= 1.")
    if receptor_path.suffix.lower() != ".pdbqt" or ligand_path.suffix.lower() != ".pdbqt":
        raise _error(
            "GNINA_INPUT_INVALID",
            "GNINA --score_only requires prepared PDBQT receptor and ligand inputs.",
        )
    if flex_receptor_path is not None and flex_receptor_path.suffix.lower() != ".pdbqt":
        raise _error(
            "GNINA_INPUT_INVALID",
            "GNINA --score_only --flex requires a prepared Meeko-template PDBQT file.",
        )
    arguments = [
        "--receptor",
        str(receptor_path),
        "--ligand",
        str(ligand_path),
        "--cpu",
        str(cpu_threads),
        "--score_only",
        "--cnn_scoring",
        cnn_scoring,
    ]
    if cnn_scoring != "none" and cnn_model != "default_1_3_ensemble":
        arguments.extend(("--cnn", cnn_model))
    arguments.extend(("--addH", "0", "--stripH", "0"))
    if compute == "cpu":
        arguments.append("--no_gpu")
    else:
        arguments.extend(("--device", str(device_index)))
    if flex_receptor_path is not None:
        arguments.extend(("--flex", str(flex_receptor_path)))
    return arguments


def execute_gnina_score_only(
    *,
    installation: GninaInstallation,
    receptor_path: Path,
    ligand_path: Path,
    working_dir: Path,
    compute: Literal["cpu", "cuda"] = "cpu",
    device_index: int = 0,
    cpu_threads: int = 1,
    cnn_scoring: Literal["none", "rescore", "all"] = "rescore",
    cnn_model: GninaCnnModelSelector = "dense_1_3",
    flex_receptor_path: Path | None = None,
    timeout_minutes: int = 10,
    cancel_event: threading.Event,
) -> CancellableToolExecution:
    """Execute GNINA 1.3.3 `--score_only` in place without mutating pose bytes."""
    if not _linux_host():
        raise _error("GNINA_LINUX_ONLY", "GNINA is available only in the Linux edition of Ankora.")
    exe_path = Path(installation.executable)
    if _sha256_executable(exe_path) != installation.sha256:
        raise _error(
            "GNINA_IDENTITY_CHANGED", "The GNINA executable changed after it was inspected."
        )
    arguments = build_gnina_score_only_arguments(
        receptor_path=receptor_path,
        ligand_path=ligand_path,
        compute=compute,
        device_index=device_index,
        cpu_threads=cpu_threads,
        cnn_scoring=cnn_scoring,
        cnn_model=cnn_model,
        flex_receptor_path=flex_receptor_path,
    )
    env = gnina_subprocess_environment(exe_path)
    exec_kwargs: dict[str, Any] = {}
    if env is not None:
        exec_kwargs["environment"] = env
    return run_cancellable_tool(
        executable=installation.executable,
        arguments=arguments,
        cwd=working_dir,
        stage="gnina_score_only",
        cancel_event=cancel_event,
        timeout_seconds=timeout_minutes * 60,
        **exec_kwargs,
    )


def parse_gnina_score_only_stdout(
    stdout: str,
    *,
    used_flex: bool = False,
    require_cnn: bool = True,
) -> ParsedGninaScoreOnlyResult:
    """Strictly parse GNINA 1.3.3 `--score_only` stdout records."""
    aff_match = _SCORE_ONLY_AFFINITY.search(stdout)
    if aff_match is None:
        raise _error(
            "GNINA_OUTPUT_INVALID",
            "GNINA --score_only stdout is missing Affinity record.",
        )
    affinity = float(aff_match.group(1))
    if not math.isfinite(affinity):
        raise _error("GNINA_OUTPUT_INVALID", "GNINA --score_only Affinity is not finite.")

    intramol_match = _SCORE_ONLY_INTRAMOL.search(stdout)
    intramol = float(intramol_match.group(1)) if intramol_match else None
    score_match = _SCORE_ONLY_CNN_SCORE.search(stdout)
    cnn_aff_match = _SCORE_ONLY_CNN_AFFINITY.search(stdout)
    var_match = _SCORE_ONLY_CNN_VARIANCE.search(stdout)

    cnn_score = float(score_match.group(1)) if score_match else None
    cnn_affinity = float(cnn_aff_match.group(1)) if cnn_aff_match else None
    cnn_variance = float(var_match.group(1)) if var_match else None

    if require_cnn and (cnn_score is None or cnn_affinity is None):
        raise _error(
            "GNINA_OUTPUT_INVALID",
            "GNINA --score_only stdout is missing CNNscore or CNNaffinity.",
        )
    for label, value in (
        ("Intramolecular energy", intramol),
        ("CNNscore", cnn_score),
        ("CNNaffinity", cnn_affinity),
        ("CNNvariance", cnn_variance),
    ):
        if value is not None and not math.isfinite(value):
            raise _error("GNINA_OUTPUT_INVALID", f"GNINA --score_only {label} is not finite.")
    if cnn_variance is not None and cnn_variance < 0.0:
        raise _error("GNINA_OUTPUT_INVALID", "GNINA --score_only CNNvariance cannot be negative.")
    cnn_vs = (
        cnn_score * cnn_affinity
        if cnn_score is not None and cnn_affinity is not None
        else None
    )
    return ParsedGninaScoreOnlyResult(
        minimized_affinity_kcal_mol=affinity,
        intramolecular_energy_kcal_mol=intramol,
        cnn_score=cnn_score,
        cnn_affinity=cnn_affinity,
        cnn_vs=cnn_vs,
        cnn_affinity_variance=cnn_variance,
        used_flex=used_flex,
    )


def execute_gnina(
    *,
    installation: GninaInstallation,
    receptor_path: Path,
    ligand_path: Path,
    output_path: Path,
    box: BindingBox,
    parameters: GninaDockingParameters,
    cancel_event: threading.Event,
    flex_receptor_path: Path | None = None,
    out_flex_path: Path | None = None,
) -> CancellableToolExecution:
    return _execute(
        installation=installation,
        arguments=build_gnina_arguments(
            receptor_path=receptor_path,
            ligand_path=ligand_path,
            output_path=output_path,
            box=box,
            parameters=parameters,
            flex_receptor_path=flex_receptor_path,
            out_flex_path=out_flex_path,
        ),
        output_path=output_path,
        out_flex_path=out_flex_path,
        cancel_event=cancel_event,
        timeout_minutes=parameters.timeout_minutes,
    )


def execute_gnina_local_only(
    *,
    installation: GninaInstallation,
    receptor_path: Path,
    ligand_path: Path,
    output_path: Path,
    box: BindingBox,
    parameters: GninaLocalRefinementRequest,
    cancel_event: threading.Event,
    flex_receptor_path: Path | None = None,
    out_flex_path: Path | None = None,
) -> CancellableToolExecution:
    return _execute(
        installation=installation,
        arguments=build_gnina_local_only_arguments(
            receptor_path=receptor_path,
            ligand_path=ligand_path,
            output_path=output_path,
            box=box,
            parameters=parameters,
            flex_receptor_path=flex_receptor_path,
            out_flex_path=out_flex_path,
        ),
        output_path=output_path,
        out_flex_path=out_flex_path,
        cancel_event=cancel_event,
        timeout_minutes=parameters.timeout_minutes,
    )


def _execute(
    *,
    installation: GninaInstallation,
    arguments: list[str],
    output_path: Path,
    out_flex_path: Path | None,
    cancel_event: threading.Event,
    timeout_minutes: int,
) -> CancellableToolExecution:
    """Run in an isolated directory and leave raw scientific outputs in place."""
    if not _linux_host():
        raise _error("GNINA_LINUX_ONLY", "GNINA is available only in the Linux edition of Ankora.")
    exe_path = Path(installation.executable)
    if _sha256_executable(exe_path) != installation.sha256:
        raise _error(
            "GNINA_IDENTITY_CHANGED", "The GNINA executable changed after it was inspected."
        )
    if any(path.exists() or path.is_symlink() for path in (output_path, out_flex_path)
           if path is not None):
        raise _error(
            "GNINA_OUTPUT_EXISTS", "The GNINA output already exists; it cannot be overwritten."
        )
    env = gnina_subprocess_environment(exe_path)
    exec_kwargs: dict[str, Any] = {}
    if env is not None:
        exec_kwargs["environment"] = env
    return run_cancellable_tool(
        executable=installation.executable,
        arguments=arguments,
        cwd=output_path.parent,
        stage=_STAGE,
        cancel_event=cancel_event,
        timeout_seconds=timeout_minutes * 60,
        **exec_kwargs,
    )


def _value(mol: Any, name: str, *, optional: bool = False) -> float | None:
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
        cnn_variance = _value(mol, "CNNaffinity_variance", optional=True)
        if cnn_variance is not None and cnn_variance < 0:
            raise _error(
                "GNINA_OUTPUT_INVALID",
                "A GNINA pose has a negative CNNaffinity_variance.",
                field="CNNaffinity_variance",
            )
        assert affinity is not None and score is not None and cnn_affinity is not None
        poses.append(
            GninaPose(
                mode,
                affinity,
                score,
                cnn_affinity,
                _value(mol, "CNN_VS", optional=True),
                cnn_variance,
                record,
            )
        )
    return poses


_REQUIRED_PDBQT_SCORES = frozenset({"minimizedAffinity", "CNNscore", "CNNaffinity"})
_RECOGNIZED_PDBQT_SCORES = frozenset(
    {
        b"minimizedAffinity",
        b"CNNscore",
        b"CNNaffinity",
        b"CNN_VS",
        b"CNNaffinity_variance",
    }
)


def parse_gnina_pdbqt(content: bytes) -> list[GninaPdbqtPose]:
    """Parse actual GNINA pose records without reordering or rewriting them."""
    poses: list[GninaPdbqtPose] = []
    block: list[bytes] | None = None
    mode = 0
    scores: dict[str, float] = {}
    atom_count = 0
    for line in content.splitlines(keepends=True):
        words = line.strip().split()
        if words and words[0] == b"MODEL":
            if block is not None or len(words) != 2:
                raise _error("GNINA_OUTPUT_INVALID", "GNINA has an invalid MODEL record.")
            try:
                mode = int(words[1])
            except ValueError as error:
                raise _error("GNINA_OUTPUT_INVALID", "GNINA has an invalid pose number.") from error
            if mode != len(poses) + 1:
                raise _error("GNINA_OUTPUT_INVALID", "GNINA pose numbers are not sequential.")
            block = [line]
            scores = {}
            atom_count = 0
            continue
        if block is None:
            if words:
                raise _error("GNINA_OUTPUT_INVALID", "GNINA has content outside a pose.")
            continue
        block.append(line)
        if words and words[0] in {b"ATOM", b"HETATM"}:
            atom_count += 1
        if len(words) >= 2 and words[0] == b"REMARK" and words[1] in _RECOGNIZED_PDBQT_SCORES:
            name = words[1].decode("ascii")
            if name in scores or len(words) != 3:
                raise _error(
                    "GNINA_OUTPUT_INVALID", "GNINA has a repeated or invalid score.", field=name
                )
            try:
                value = float(words[2])
            except ValueError as error:
                raise _error(
                    "GNINA_OUTPUT_INVALID", "GNINA has an invalid score.", field=name
                ) from error
            if not math.isfinite(value):
                raise _error("GNINA_OUTPUT_INVALID", "GNINA has a non-finite score.", field=name)
            if name == "CNNaffinity_variance" and value < 0:
                raise _error(
                    "GNINA_OUTPUT_INVALID",
                    "GNINA has a negative CNNaffinity_variance.",
                    field=name,
                )
            scores[name] = value
        if words and words[0] == b"ENDMDL":
            if (
                len(words) != 1
                or atom_count == 0
                or not _REQUIRED_PDBQT_SCORES.issubset(scores)
            ):
                raise _error(
                    "GNINA_OUTPUT_INVALID", "GNINA pose has missing scores or atoms.", mode=mode
                )
            poses.append(
                GninaPdbqtPose(
                    mode=mode,
                    minimized_affinity_kcal_mol=scores["minimizedAffinity"],
                    cnn_score=scores["CNNscore"],
                    cnn_affinity=scores["CNNaffinity"],
                    pdbqt=b"".join(block),
                    cnn_vs=scores.get("CNN_VS"),
                    cnn_affinity_variance=scores.get("CNNaffinity_variance"),
                )
            )
            block = None
    if block is not None or not poses:
        raise _error("GNINA_OUTPUT_INVALID", "GNINA output is empty or has an incomplete pose.")
    return poses


def parse_gnina_local_only_pdbqt(content: bytes) -> GninaPdbqtPose:
    """Accept one wrapped or flat local pose and retain its exact pose bytes."""
    wrapped = any(
        line.strip().split(maxsplit=1)[0:1] == [b"MODEL"] for line in content.splitlines()
    )
    parsed = parse_gnina_pdbqt(content if wrapped else b"MODEL 1\n" + content + b"\nENDMDL\n")
    if len(parsed) != 1:
        raise _error("GNINA_OUTPUT_INVALID", "GNINA local refinement must output exactly one pose.")
    return parsed[0] if wrapped else replace(parsed[0], pdbqt=content)


def pair_gnina_flex_models(
    poses: Sequence[GninaPdbqtPose],
    *,
    gnina_flex_pdb_text: str,
    meeko_flex_template_pdbqt: str,
) -> tuple[bytes, ...]:
    """Pair GNINA outputs by ordinal and preserve Meeko's side-chain topology."""
    models = parse_gnina_flex_pdb_models(gnina_flex_pdb_text)
    if len(models) != len(poses):
        raise _error(
            "GNINA_OUTPUT_INVALID",
            "GNINA wrote different numbers of ligand and flexible side-chain models.",
            ligand_models=len(poses),
            flex_models=len(models),
        )
    return tuple(
        reinject_gnina_flex_pdb_into_meeko_template(
            meeko_flex_pdbqt_text=meeko_flex_template_pdbqt,
            gnina_flex_pdb_model_text=model.pdb_text,
        )
        for model in models
    )


def require_matching_topology(pose: GninaPdbqtPose, conformer_sdf: bytes) -> None:
    """Apply the same isomeric topology guard used by the interaction adapter."""
    from meeko import PDBQTMolecule, RDKitMolCreate

    try:
        pdbqt = PDBQTMolecule(pose.pdbqt.decode("utf-8"), skip_typing=True)
        ligands = [mol for mol in RDKitMolCreate.from_pdbqt_mol(pdbqt) if mol is not None]
        supplier = Chem.ForwardSDMolSupplier(
            io.BytesIO(conformer_sdf), sanitize=True, removeHs=False
        )
        template = next(supplier, None)
        if template is None or next(supplier, None) is not None or len(ligands) != 1:
            raise ValueError("Expected one reconstructable ligand and one prepared conformer.")
        if not ligands[0].GetNumConformers():
            raise ValueError("The reconstructed ligand has no pose coordinates.")
        coordinates = ligands[0].GetConformer()
        for atom in range(ligands[0].GetNumAtoms()):
            position = coordinates.GetAtomPosition(atom)
            if not all(math.isfinite(value) for value in (position.x, position.y, position.z)):
                raise ValueError("The reconstructed ligand has non-finite coordinates.")
        ligand_check = Chem.Mol(ligands[0])
        template_check = Chem.Mol(template)
        Chem.AssignStereochemistryFrom3D(ligand_check)
        if template_check.GetNumConformers():
            Chem.AssignStereochemistryFrom3D(template_check)
        ligand_smiles = Chem.MolToSmiles(Chem.RemoveHs(ligand_check), isomericSmiles=True)
        expected_smiles = Chem.MolToSmiles(Chem.RemoveHs(template_check), isomericSmiles=True)
    except Exception as error:  # noqa: BLE001 - normalize third-party parsing failures
        raise _error(
            "GNINA_POSE_TOPOLOGY_UNVERIFIED",
            "GNINA pose topology could not be reconstructed.",
            mode=pose.mode,
            reason=type(error).__name__,
        ) from error
    if ligand_smiles != expected_smiles:
        raise _error(
            "GNINA_POSE_TOPOLOGY_MISMATCH",
            "GNINA pose does not match its prepared conformer.",
            mode=pose.mode,
            pose_smiles=ligand_smiles,
            conformer_smiles=expected_smiles,
        )
