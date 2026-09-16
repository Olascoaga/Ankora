"""Freeze LIT-PCBA co-crystal boxes and chemical-state sentinels.

This module reads the exact, already hash-bound source archive without
extracting it.  It derives search boxes from the primary holo ligands and
selects a bounded sensitivity panel by SHA-256 only.  It does not prepare a
receptor, ligand, or docking result.
"""

from __future__ import annotations

import hashlib
import json
import math
import tarfile
from importlib import import_module
from pathlib import Path, PurePosixPath
from typing import Any

Chem: Any = import_module("rdkit.Chem")

PRIMARY_BOX_PADDING_ANGSTROM = 5.0
SENSITIVITY_EXTRA_PER_FACE_ANGSTROM = 3.0
SENTINELS_PER_CLASS_PER_TARGET = 16
ACTIVE_SOURCE_FILES = ("active_T.smi", "active_V.smi")
INACTIVE_SOURCE_FILES = ("inactive_T.smi", "inactive_V.smi")
SENTINEL_SELECTION_RULE = (
    "ascending SHA-256 of protocol_id, target_id, class label, and RDKit "
    "canonical isomeric SMILES separated by NUL bytes; source member path, "
    "line number, and source identifier break an exact digest tie"
)


class ScreeningBenchmarkGeometryError(ValueError):
    """Frozen source bytes cannot satisfy the geometry/sentinel contract."""


def build_geometry_manifest(
    *,
    archive: Path,
    input_manifest_path: Path,
    template_manifest_path: Path,
) -> dict[str, Any]:
    """Derive a deterministic, path-free pre-docking manifest."""

    inputs = _load_object(input_manifest_path, "source-population manifest")
    templates = _load_object(template_manifest_path, "template manifest")
    _verify_manifest_identity(inputs, "source-population manifest")
    _verify_manifest_identity(templates, "template manifest")
    protocol_id = _required_string(inputs, "protocol_id")
    if _required_string(templates, "protocol_id") != protocol_id:
        raise ScreeningBenchmarkGeometryError(
            "The source-population and template manifests name different protocols."
        )
    source = _required_object(inputs.get("source"), "source")
    archive_size = _file_size(archive)
    archive_sha256 = _file_sha256(archive)
    if archive_size != _required_nonnegative_int(source, "size_bytes"):
        raise ScreeningBenchmarkGeometryError(
            "The source archive size differs from the frozen input manifest."
        )
    if archive_sha256 != _required_sha256(source, "sha256"):
        raise ScreeningBenchmarkGeometryError(
            "The source archive SHA-256 differs from the frozen input manifest."
        )

    input_targets = _targets_by_id(inputs, "source-population manifest")
    template_targets = _targets_by_id(templates, "template manifest")
    if set(input_targets) != set(template_targets):
        raise ScreeningBenchmarkGeometryError(
            "The source-population and template target sets do not match."
        )

    try:
        with tarfile.open(archive, mode="r:*") as source_archive:
            members = _safe_regular_members(source_archive)
            targets = [
                _build_target(
                    source_archive,
                    members,
                    protocol_id=protocol_id,
                    input_target=input_targets[target_id],
                    template_target=template_targets[target_id],
                )
                for target_id in sorted(input_targets)
            ]
    except (OSError, tarfile.TarError) as error:
        raise ScreeningBenchmarkGeometryError(
            "The benchmark source is not a readable tar archive."
        ) from error

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "protocol_id": protocol_id,
        "dependencies": {
            "source_population_manifest_sha256": _required_sha256(
                inputs, "manifest_sha256"
            ),
            "holo_template_manifest_sha256": _required_sha256(
                templates, "manifest_sha256"
            ),
        },
        "box_policy": {
            "atom_scope": (
                "heavy atoms in the exact source ligand MOL2; explicit modeled "
                "hydrogens are counted but excluded from the bounds"
            ),
            "primary_padding_per_face_angstrom": PRIMARY_BOX_PADDING_ANGSTROM,
            "sensitivity_extra_per_face_angstrom": (
                SENSITIVITY_EXTRA_PER_FACE_ANGSTROM
            ),
            "coordinate_rule": (
                "axis-aligned source-ligand extrema; midpoint center; extent plus "
                "twice the per-face padding"
            ),
        },
        "sentinel_policy": {
            "count_per_class_per_target": SENTINELS_PER_CLASS_PER_TARGET,
            "selection_rule": SENTINEL_SELECTION_RULE,
            "canonicalization": (
                "RDKit canonical isomeric SMILES after ordinary sanitization; "
                "no uncharging, tautomerization, or fragment removal"
            ),
            "execution_boundary": (
                "enumerate all bounded states for every selected parent and report "
                "score/rank ranges; never select the most favorable state"
            ),
        },
        "targets": targets,
        "receptor_preparation_boundary": {
            "status": "not_yet_frozen",
            "reason": (
                "source protein MOL2 files are exact benchmark inputs but are not "
                "silently treated as Ankora docking-ready receptor derivatives"
            ),
            "required_next": (
                "freeze official structure intake, verify official/source coordinate-"
                "frame congruence, then freeze chain/component decisions, repair, "
                "protonation review, and receptor PDBQT identities for every primary "
                "and alternate template before docking"
            ),
        },
        "result_status": "boxes_and_sentinels_frozen_no_docking_executed",
    }
    manifest["manifest_sha256"] = hashlib.sha256(_canonical_json(manifest)).hexdigest()
    return manifest


def verify_geometry_manifest(
    *,
    archive: Path,
    input_manifest_path: Path,
    template_manifest_path: Path,
    geometry_manifest_path: Path,
) -> dict[str, Any]:
    """Rebuild and compare an existing geometry/sentinel manifest."""

    recorded = _load_object(geometry_manifest_path, "geometry/sentinel manifest")
    _verify_manifest_identity(recorded, "geometry/sentinel manifest")
    rebuilt = build_geometry_manifest(
        archive=archive,
        input_manifest_path=input_manifest_path,
        template_manifest_path=template_manifest_path,
    )
    if rebuilt != recorded:
        raise ScreeningBenchmarkGeometryError(
            "The geometry/sentinel manifest does not reproduce from source bytes."
        )
    return recorded


def serialize_geometry_manifest(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def _build_target(
    source: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    *,
    protocol_id: str,
    input_target: dict[str, Any],
    template_target: dict[str, Any],
) -> dict[str, Any]:
    target_id = _required_string(input_target, "target_id")
    if _required_string(template_target, "target_id") != target_id:
        raise ScreeningBenchmarkGeometryError("Target identities do not join exactly.")
    primary = _required_object(
        template_target.get("primary_template"), "primary_template"
    )
    alternate = _required_object(
        template_target.get("alternate_template"), "alternate_template"
    )
    source_ligand = _required_object(primary.get("source_ligand"), "source_ligand")
    ligand_content = _verified_member_bytes(source, members, source_ligand)
    atoms = _parse_mol2_atoms(ligand_content, target_id=target_id)
    heavy_atoms = [
        atom for atom in atoms if atom[0].split(".", 1)[0].upper() != "H"
    ]
    if not heavy_atoms:
        raise ScreeningBenchmarkGeometryError(
            f"Target {target_id} primary ligand has no heavy atoms."
        )
    coordinates = [atom[1] for atom in heavy_atoms]
    coordinate_bounds = _coordinate_bounds(coordinates)
    primary_box = _box_from_bounds(
        coordinate_bounds, padding=PRIMARY_BOX_PADDING_ANGSTROM
    )
    sensitivity_box = {
        **{key: primary_box[key] for key in ("center_x", "center_y", "center_z")},
        "size_x": _rounded(
            primary_box["size_x"] + 2 * SENSITIVITY_EXTRA_PER_FACE_ANGSTROM
        ),
        "size_y": _rounded(
            primary_box["size_y"] + 2 * SENSITIVITY_EXTRA_PER_FACE_ANGSTROM
        ),
        "size_z": _rounded(
            primary_box["size_z"] + 2 * SENSITIVITY_EXTRA_PER_FACE_ANGSTROM
        ),
    }
    source_directory = _required_string(input_target, "source_directory")
    active_rows = _source_rows(
        source,
        members,
        source_directory=source_directory,
        filenames=ACTIVE_SOURCE_FILES,
        target_id=target_id,
        label="active",
    )
    inactive_rows = _source_rows(
        source,
        members,
        source_directory=source_directory,
        filenames=INACTIVE_SOURCE_FILES,
        target_id=target_id,
        label="inactive",
    )
    expected_census = _required_object(input_target.get("source_census"), "source_census")
    if len(active_rows) != _required_nonnegative_int(expected_census, "active_rows"):
        raise ScreeningBenchmarkGeometryError(
            f"Target {target_id} active census changed after source inspection."
        )
    if len(inactive_rows) != _required_nonnegative_int(expected_census, "inactive_rows"):
        raise ScreeningBenchmarkGeometryError(
            f"Target {target_id} inactive census changed after source inspection."
        )
    active_sentinels = _select_sentinels(
        active_rows,
        protocol_id=protocol_id,
        target_id=target_id,
        label="active",
    )
    inactive_sentinels = _select_sentinels(
        inactive_rows,
        protocol_id=protocol_id,
        target_id=target_id,
        label="inactive",
    )
    return {
        "target_id": target_id,
        "primary_template_id": _required_string(primary, "pdb_id"),
        "alternate_template_id": _required_string(alternate, "pdb_id"),
        "co_crystal_box": {
            "source_ligand": {
                "path": _required_string(source_ligand, "path"),
                "size_bytes": _required_nonnegative_int(source_ligand, "size_bytes"),
                "sha256": _required_sha256(source_ligand, "sha256"),
            },
            "atom_count": len(atoms),
            "heavy_atom_count": len(heavy_atoms),
            "explicit_hydrogen_count": sum(
                atom_type.split(".", 1)[0].upper() == "H" for atom_type, _ in atoms
            ),
            "coordinate_bounds_angstrom": coordinate_bounds,
            "primary_box_angstrom": primary_box,
            "expanded_sensitivity_box_angstrom": sensitivity_box,
        },
        "chemical_state_sentinels": {
            "active": active_sentinels,
            "inactive": inactive_sentinels,
            "total": len(active_sentinels) + len(inactive_sentinels),
        },
    }


def _parse_mol2_atoms(
    content: bytes, *, target_id: str
) -> list[tuple[str, tuple[float, float, float]]]:
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ScreeningBenchmarkGeometryError(
            f"Target {target_id} primary ligand MOL2 is not UTF-8."
        ) from error
    atom_headers = [
        index for index, line in enumerate(lines) if line.strip() == "@<TRIPOS>ATOM"
    ]
    if len(atom_headers) != 1:
        raise ScreeningBenchmarkGeometryError(
            f"Target {target_id} primary ligand must contain one MOL2 atom section."
        )
    atoms: list[tuple[str, tuple[float, float, float]]] = []
    for line in lines[atom_headers[0] + 1 :]:
        stripped = line.strip()
        if stripped.startswith("@<TRIPOS>"):
            break
        if not stripped:
            continue
        fields = stripped.split()
        if len(fields) < 6:
            raise ScreeningBenchmarkGeometryError(
                f"Target {target_id} primary ligand has a malformed MOL2 atom row."
            )
        try:
            position = (float(fields[2]), float(fields[3]), float(fields[4]))
        except ValueError as error:
            raise ScreeningBenchmarkGeometryError(
                f"Target {target_id} primary ligand has a non-numeric coordinate."
            ) from error
        if not all(math.isfinite(value) for value in position):
            raise ScreeningBenchmarkGeometryError(
                f"Target {target_id} primary ligand has a non-finite coordinate."
            )
        atoms.append((fields[5], position))
    if not atoms:
        raise ScreeningBenchmarkGeometryError(
            f"Target {target_id} primary ligand has no atoms."
        )
    return atoms


def _coordinate_bounds(
    coordinates: list[tuple[float, float, float]],
) -> dict[str, float]:
    return {
        "min_x": _rounded(min(position[0] for position in coordinates)),
        "max_x": _rounded(max(position[0] for position in coordinates)),
        "min_y": _rounded(min(position[1] for position in coordinates)),
        "max_y": _rounded(max(position[1] for position in coordinates)),
        "min_z": _rounded(min(position[2] for position in coordinates)),
        "max_z": _rounded(max(position[2] for position in coordinates)),
    }


def _box_from_bounds(bounds: dict[str, float], *, padding: float) -> dict[str, float]:
    return {
        "center_x": _rounded((bounds["min_x"] + bounds["max_x"]) / 2),
        "center_y": _rounded((bounds["min_y"] + bounds["max_y"]) / 2),
        "center_z": _rounded((bounds["min_z"] + bounds["max_z"]) / 2),
        "size_x": _rounded(bounds["max_x"] - bounds["min_x"] + 2 * padding),
        "size_y": _rounded(bounds["max_y"] - bounds["min_y"] + 2 * padding),
        "size_z": _rounded(bounds["max_z"] - bounds["min_z"] + 2 * padding),
    }


def _source_rows(
    source: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    *,
    source_directory: str,
    filenames: tuple[str, ...],
    target_id: str,
    label: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for filename in filenames:
        matching = [
            (path, member)
            for path, member in members.items()
            if source_directory in PurePosixPath(path).parts
            and PurePosixPath(path).name == filename
        ]
        if len(matching) != 1:
            raise ScreeningBenchmarkGeometryError(
                f"Target {target_id} requires exactly one {filename}."
            )
        member_path, member = matching[0]
        content = _member_bytes(source, member)
        try:
            document = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ScreeningBenchmarkGeometryError(
                f"Target {target_id} {filename} is not UTF-8."
            ) from error
        for line_number, line in enumerate(document.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            fields = stripped.split()
            if len(fields) < 2:
                raise ScreeningBenchmarkGeometryError(
                    f"Target {target_id} {filename} line {line_number} lacks an identifier."
                )
            molecule = Chem.MolFromSmiles(fields[0])
            if molecule is None:
                raise ScreeningBenchmarkGeometryError(
                    f"Target {target_id} {label} row cannot be canonicalized."
                )
            rows.append(
                {
                    "source_member_path": member_path,
                    "source_line_number": line_number,
                    "source_id": fields[1],
                    "source_smiles": fields[0],
                    "canonical_isomeric_smiles": Chem.MolToSmiles(
                        molecule, canonical=True, isomericSmiles=True
                    ),
                }
            )
    return rows


def _select_sentinels(
    rows: list[dict[str, Any]],
    *,
    protocol_id: str,
    target_id: str,
    label: str,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    candidates: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        canonical = _required_string(row, "canonical_isomeric_smiles")
        if canonical in seen:
            raise ScreeningBenchmarkGeometryError(
                f"Target {target_id} {label} rows contain a canonical duplicate."
            )
        seen.add(canonical)
        digest = hashlib.sha256(
            "\0".join((protocol_id, target_id, label, canonical)).encode("utf-8")
        ).hexdigest()
        candidates.append((digest, row))
    if len(candidates) < SENTINELS_PER_CLASS_PER_TARGET:
        raise ScreeningBenchmarkGeometryError(
            f"Target {target_id} has too few {label} parents for the sentinel panel."
        )
    candidates.sort(
        key=lambda item: (
            item[0],
            item[1]["source_member_path"],
            item[1]["source_line_number"],
            item[1]["source_id"],
        )
    )
    selected: list[dict[str, Any]] = []
    for rank, (selection_sha256, row) in enumerate(
        candidates[:SENTINELS_PER_CLASS_PER_TARGET], start=1
    ):
        canonical = _required_string(row, "canonical_isomeric_smiles")
        source_smiles = _required_string(row, "source_smiles")
        selected.append(
            {
                "selection_rank": rank,
                "selection_sha256": selection_sha256,
                "source_member_path": _required_string(row, "source_member_path"),
                "source_line_number": _required_positive_int(
                    row, "source_line_number"
                ),
                "source_id": _required_string(row, "source_id"),
                "source_smiles_sha256": hashlib.sha256(
                    source_smiles.encode("utf-8")
                ).hexdigest(),
                "canonical_isomeric_smiles_sha256": hashlib.sha256(
                    canonical.encode("utf-8")
                ).hexdigest(),
            }
        )
    return selected


def _targets_by_id(manifest: dict[str, Any], label: str) -> dict[str, dict[str, Any]]:
    raw_targets = manifest.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise ScreeningBenchmarkGeometryError(f"The {label} has no targets.")
    targets: dict[str, dict[str, Any]] = {}
    for raw_target in raw_targets:
        target = _required_object(raw_target, "target")
        target_id = _required_string(target, "target_id")
        if target_id in targets:
            raise ScreeningBenchmarkGeometryError(
                f"The {label} repeats target {target_id}."
            )
        targets[target_id] = target
    return targets


def _safe_regular_members(source: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    members: dict[str, tarfile.TarInfo] = {}
    for member in source.getmembers():
        path = PurePosixPath(member.name.replace("\\", "/"))
        has_windows_drive = bool(path.parts) and path.parts[0].endswith(":")
        if path.is_absolute() or has_windows_drive or ".." in path.parts:
            raise ScreeningBenchmarkGeometryError(
                f"Archive member escapes its source root: {member.name}"
            )
        if not member.isfile():
            continue
        normalized = path.as_posix()
        if normalized in members:
            raise ScreeningBenchmarkGeometryError(
                f"Archive contains an ambiguous duplicate member: {normalized}"
            )
        members[normalized] = member
    return members


def _verified_member_bytes(
    source: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    identity: dict[str, Any],
) -> bytes:
    path = _required_string(identity, "path")
    member = members.get(path)
    if member is None:
        raise ScreeningBenchmarkGeometryError(f"Source member is missing: {path}")
    content = _member_bytes(source, member)
    if len(content) != _required_nonnegative_int(identity, "size_bytes"):
        raise ScreeningBenchmarkGeometryError(f"Source member size changed: {path}")
    if hashlib.sha256(content).hexdigest() != _required_sha256(identity, "sha256"):
        raise ScreeningBenchmarkGeometryError(f"Source member SHA-256 changed: {path}")
    return content


def _member_bytes(source: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    extracted = source.extractfile(member)
    if extracted is None:
        raise ScreeningBenchmarkGeometryError(
            f"Archive member is unreadable: {member.name}"
        )
    return extracted.read()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScreeningBenchmarkGeometryError(
            f"The {label} is unavailable or invalid."
        ) from error
    return _required_object(value, label)


def _verify_manifest_identity(manifest: dict[str, Any], label: str) -> None:
    recorded = _required_sha256(manifest, "manifest_sha256")
    payload = dict(manifest)
    payload.pop("manifest_sha256")
    if hashlib.sha256(_canonical_json(payload)).hexdigest() != recorded:
        raise ScreeningBenchmarkGeometryError(
            f"The {label} content differs from its manifest SHA-256."
        )


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError as error:
        raise ScreeningBenchmarkGeometryError(
            "The benchmark source archive is unavailable."
        ) from error


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        raise ScreeningBenchmarkGeometryError(
            "The benchmark source archive cannot be read."
        ) from error
    return digest.hexdigest()


def _required_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScreeningBenchmarkGeometryError(f"{label} must be an object.")
    return value


def _required_string(value: dict[str, Any], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise ScreeningBenchmarkGeometryError(f"{key} must be a non-empty string.")
    return raw


def _required_nonnegative_int(value: dict[str, Any], key: str) -> int:
    raw = value.get(key)
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise ScreeningBenchmarkGeometryError(
            f"{key} must be a non-negative integer."
        )
    return raw


def _required_positive_int(value: dict[str, Any], key: str) -> int:
    raw = _required_nonnegative_int(value, key)
    if raw == 0:
        raise ScreeningBenchmarkGeometryError(f"{key} must be positive.")
    return raw


def _required_sha256(value: dict[str, Any], key: str) -> str:
    raw = _required_string(value, key).lower()
    if len(raw) != 64 or any(character not in "0123456789abcdef" for character in raw):
        raise ScreeningBenchmarkGeometryError(f"{key} must be a SHA-256 digest.")
    return raw


def _rounded(value: float) -> float:
    return round(value, 6)


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
