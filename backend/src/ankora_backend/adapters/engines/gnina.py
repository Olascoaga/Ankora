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
from importlib import import_module
from pathlib import Path
from typing import Any

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
) -> list[str]:
    """Build an argument array for explicitly recorded model and hydrogen handling."""
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
        "--exhaustiveness",
        str(parameters.exhaustiveness),
        "--num_modes",
        str(parameters.num_modes),
        "--min_rmsd_filter",
        str(parameters.min_rmsd_filter_angstrom),
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
    if not _linux_host():
        raise _error("GNINA_LINUX_ONLY", "GNINA is available only in the Linux edition of Ankora.")
    exe_path = Path(installation.executable)
    if _sha256_executable(exe_path) != installation.sha256:
        raise _error(
            "GNINA_IDENTITY_CHANGED", "The GNINA executable changed after it was inspected."
        )
    if output_path.exists():
        raise _error(
            "GNINA_OUTPUT_EXISTS", "The GNINA output already exists; it cannot be overwritten."
        )
    env = gnina_subprocess_environment(exe_path)
    exec_kwargs: dict[str, Any] = {}
    if env is not None:
        exec_kwargs["environment"] = env
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
        ligand_smiles = Chem.MolToSmiles(Chem.RemoveHs(ligands[0]), isomericSmiles=True)
        expected_smiles = Chem.MolToSmiles(Chem.RemoveHs(template), isomericSmiles=True)
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
