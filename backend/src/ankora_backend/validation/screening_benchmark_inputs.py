"""Inspect exact LIT-PCBA source bytes before any benchmark docking.

The inspector reads an archive without extracting it.  It verifies the frozen
target census, hashes every selected source member, and reconciles exact
canonical-state duplicates and cross-class label conflicts.  It never prepares
a ligand, selects a receptor, or reads a docking score.
"""

from __future__ import annotations

import hashlib
import json
import tarfile
from collections.abc import Iterable
from importlib import import_module
from pathlib import Path, PurePosixPath
from typing import Any

Chem: Any = import_module("rdkit.Chem")


class ScreeningBenchmarkInputError(ValueError):
    """The supplied source cannot satisfy the frozen acquisition contract."""


def inspect_lit_pcba_archive(*, archive: Path, spec_path: Path) -> dict[str, Any]:
    """Return a deterministic, path-free acquisition manifest."""

    spec = _load_object(spec_path)
    protocol_id = _required_string(spec, "protocol_id")
    amendments = _verified_amendments(
        spec,
        spec_path=spec_path,
        protocol_id=protocol_id,
    )
    evidence = _required_object(spec.get("primary_evidence"), "primary_evidence")
    source_layout = _required_object(evidence.get("source_layout"), "source_layout")
    active_filenames = _required_string_list(source_layout, "active_files")
    inactive_filenames = _required_string_list(source_layout, "inactive_files")
    raw_targets = evidence.get("targets")
    if not isinstance(raw_targets, list) or len(raw_targets) < 2:
        raise ScreeningBenchmarkInputError(
            "The frozen protocol must name at least two primary targets."
        )
    archive_size = _file_size(archive)
    if archive_size == 0:
        raise ScreeningBenchmarkInputError("The benchmark source archive is empty.")
    archive_sha256 = _file_sha256(archive)
    _verify_expected_archive(
        archive=archive,
        size_bytes=archive_size,
        sha256=archive_sha256,
        expected=_required_object(evidence.get("source_archive"), "source_archive"),
    )

    try:
        with tarfile.open(archive, mode="r:*") as source:
            members = _safe_regular_members(source)
            targets = [
                _inspect_target(
                    source,
                    members,
                    _required_object(target, "target"),
                    active_filenames=active_filenames,
                    inactive_filenames=inactive_filenames,
                )
                for target in raw_targets
            ]
    except (tarfile.TarError, OSError) as error:
        raise ScreeningBenchmarkInputError(
            "The benchmark source is not a readable tar archive."
        ) from error

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "protocol_id": protocol_id,
        "source": {
            "filename": archive.name,
            "size_bytes": archive_size,
            "sha256": archive_sha256,
            "dataset_page": _required_string(evidence, "dataset_page"),
            "publication_doi": _required_string(evidence, "publication_doi"),
        },
        "amendments": amendments,
        "targets": targets,
        "totals": _totals(targets),
        "result_status": "inputs_inspected_no_docking_executed",
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        _canonical_json(manifest)
    ).hexdigest()
    return manifest


def serialize_input_manifest(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def _inspect_target(
    source: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    target: dict[str, Any],
    *,
    active_filenames: list[str],
    inactive_filenames: list[str],
) -> dict[str, Any]:
    target_id = _required_string(target, "target_id")
    source_directory = _required_string(target, "source_directory")
    active_members = [
        _one_member(members, source_directory, filename)
        for filename in active_filenames
    ]
    inactive_members = [
        _one_member(members, source_directory, filename)
        for filename in inactive_filenames
    ]
    receptor_members = _matching_members(members, source_directory, "_protein.mol2")
    ligand_members = _matching_members(members, source_directory, "_ligand.mol2")
    if not receptor_members or not ligand_members:
        raise ScreeningBenchmarkInputError(
            f"Target {target_id} must contain crystallographic receptor and ligand files."
        )
    receptor_stems = {_structure_stem(member, "_protein.mol2") for member in receptor_members}
    ligand_stems = {_structure_stem(member, "_ligand.mol2") for member in ligand_members}
    if receptor_stems != ligand_stems:
        raise ScreeningBenchmarkInputError(
            f"Target {target_id} receptor/ligand template identities do not pair exactly."
        )
    expected_templates = _required_nonnegative_int(target, "reported_templates")
    if len(receptor_stems) != expected_templates:
        raise ScreeningBenchmarkInputError(
            f"Target {target_id} template census differs from the frozen source report: "
            f"expected {expected_templates}, found {len(receptor_stems)}."
        )

    active_rows = _parse_member_rows(
        source, active_members, target_id=target_id, label="active"
    )
    inactive_rows = _parse_member_rows(
        source, inactive_members, target_id=target_id, label="inactive"
    )
    expected_active = _required_nonnegative_int(target, "reported_actives")
    expected_inactive = _required_nonnegative_int(target, "reported_inactives")
    if len(active_rows) != expected_active or len(inactive_rows) != expected_inactive:
        raise ScreeningBenchmarkInputError(
            f"Target {target_id} census differs from the frozen source report: "
            f"expected {expected_active}/{expected_inactive} active/inactive rows, "
            f"found {len(active_rows)}/{len(inactive_rows)}."
        )

    active_keys, active_unparsed = _canonical_keys(active_rows)
    inactive_keys, inactive_unparsed = _canonical_keys(inactive_rows)
    conflicts = sorted(set(active_keys) & set(inactive_keys))
    active_unique = set(active_keys) - set(conflicts)
    inactive_unique = set(inactive_keys) - set(conflicts)
    active_conflict_rows = sum(key in conflicts for key in active_keys)
    inactive_conflict_rows = sum(key in conflicts for key in inactive_keys)

    return {
        "target_id": target_id,
        "source_directory": source_directory,
        "pubchem_aid": _required_nonnegative_int(target, "pubchem_aid"),
        "source_census": {
            "active_rows": len(active_rows),
            "inactive_rows": len(inactive_rows),
        },
        "canonicalization": {
            "method": (
                "RDKit canonical isomeric SMILES after ordinary sanitization; "
                "no uncharging, tautomerization, or fragment removal"
            ),
            "active_unique_keys": len(active_unique),
            "inactive_unique_keys": len(inactive_unique),
            "active_duplicate_rows": len(active_keys) - len(set(active_keys)),
            "inactive_duplicate_rows": len(inactive_keys) - len(set(inactive_keys)),
            "active_unparsed_rows": active_unparsed,
            "inactive_unparsed_rows": inactive_unparsed,
            "cross_class_conflict_keys": conflicts,
            "cross_class_conflict_active_rows": active_conflict_rows,
            "cross_class_conflict_inactive_rows": inactive_conflict_rows,
            "evaluation_active_units": len(active_unique) + active_unparsed,
            "evaluation_inactive_units": len(inactive_unique) + inactive_unparsed,
        },
        "members": [
            _member_identity(source, member)
            for member in [
                *active_members,
                *inactive_members,
                *receptor_members,
                *ligand_members,
            ]
        ],
        "template_ids": sorted(receptor_stems),
        "template_count": len(receptor_stems),
    }


def _safe_regular_members(source: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    members: dict[str, tarfile.TarInfo] = {}
    for member in source.getmembers():
        path = PurePosixPath(member.name.replace("\\", "/"))
        has_windows_drive = bool(path.parts) and path.parts[0].endswith(":")
        if path.is_absolute() or has_windows_drive or ".." in path.parts:
            raise ScreeningBenchmarkInputError(
                f"Archive member escapes its source root: {member.name}"
            )
        if not member.isfile():
            continue
        normalized = path.as_posix()
        if normalized in members:
            raise ScreeningBenchmarkInputError(
                f"Archive contains an ambiguous duplicate member: {normalized}"
            )
        members[normalized] = member
    return members


def _one_member(
    members: dict[str, tarfile.TarInfo], source_directory: str, filename: str
) -> tarfile.TarInfo:
    matches = [
        member
        for name, member in members.items()
        if _belongs_to_target(name, source_directory)
        and PurePosixPath(name).name == filename
    ]
    if len(matches) != 1:
        raise ScreeningBenchmarkInputError(
            f"Source target {source_directory} requires exactly one {filename}; "
            f"found {len(matches)}."
        )
    return matches[0]


def _matching_members(
    members: dict[str, tarfile.TarInfo], target_id: str, suffix: str
) -> list[tarfile.TarInfo]:
    return sorted(
        (
            member
            for name, member in members.items()
            if _belongs_to_target(name, target_id)
            and PurePosixPath(name).name.endswith(suffix)
        ),
        key=lambda member: member.name,
    )


def _belongs_to_target(name: str, target_id: str) -> bool:
    parts = PurePosixPath(name).parts
    return target_id in parts


def _structure_stem(member: tarfile.TarInfo, suffix: str) -> str:
    return PurePosixPath(member.name).name[: -len(suffix)]


def _member_bytes(source: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    extracted = source.extractfile(member)
    if extracted is None:
        raise ScreeningBenchmarkInputError(f"Archive member is unreadable: {member.name}")
    return extracted.read()


def _member_identity(source: tarfile.TarFile, member: tarfile.TarInfo) -> dict[str, Any]:
    content = _member_bytes(source, member)
    return {
        "path": PurePosixPath(member.name.replace("\\", "/")).as_posix(),
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _parse_member_rows(
    source: tarfile.TarFile,
    members: list[tarfile.TarInfo],
    *,
    target_id: str,
    label: str,
) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for member in members:
        rows.extend(
            _parse_smiles_rows(
                _member_bytes(source, member),
                target_id=target_id,
                label=f"{label} source {PurePosixPath(member.name).name}",
            )
        )
    return rows


def _parse_smiles_rows(
    content: bytes, *, target_id: str, label: str
) -> list[tuple[str, str]]:
    try:
        document = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ScreeningBenchmarkInputError(
            f"Target {target_id} {label} is not UTF-8 text."
        ) from error
    rows: list[tuple[str, str]] = []
    for line_number, line in enumerate(document.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        fields = stripped.split()
        if len(fields) < 2:
            raise ScreeningBenchmarkInputError(
                f"Target {target_id} {label} line {line_number} lacks an identifier."
            )
        rows.append((fields[0], fields[1]))
    return rows


def _canonical_keys(rows: Iterable[tuple[str, str]]) -> tuple[list[str], int]:
    keys: list[str] = []
    unparsed = 0
    for smiles, _source_id in rows:
        molecule = Chem.MolFromSmiles(smiles)
        if molecule is None:
            unparsed += 1
            continue
        keys.append(Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True))
    return keys, unparsed


def _totals(targets: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "target_count": len(targets),
        "active_rows": sum(target["source_census"]["active_rows"] for target in targets),
        "inactive_rows": sum(
            target["source_census"]["inactive_rows"] for target in targets
        ),
        "evaluation_active_units": sum(
            target["canonicalization"]["evaluation_active_units"] for target in targets
        ),
        "evaluation_inactive_units": sum(
            target["canonicalization"]["evaluation_inactive_units"] for target in targets
        ),
    }


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScreeningBenchmarkInputError(
            "The frozen benchmark specification is unavailable or invalid."
        ) from error
    if not isinstance(value, dict):
        raise ScreeningBenchmarkInputError("The frozen specification must be an object.")
    return value


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError as error:
        raise ScreeningBenchmarkInputError(
            "The benchmark source archive is unavailable."
        ) from error


def _file_sha256(path: Path, *, label: str = "benchmark source archive") -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        raise ScreeningBenchmarkInputError(
            f"The {label} cannot be read."
        ) from error
    return digest.hexdigest()


def _required_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScreeningBenchmarkInputError(f"{label} must be an object.")
    return value


def _required_string(value: dict[str, Any], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise ScreeningBenchmarkInputError(f"{key} must be a non-empty string.")
    return raw


def _required_nonnegative_int(value: dict[str, Any], key: str) -> int:
    raw = value.get(key)
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise ScreeningBenchmarkInputError(f"{key} must be a non-negative integer.")
    return raw


def _required_string_list(value: dict[str, Any], key: str) -> list[str]:
    raw = value.get(key)
    if (
        not isinstance(raw, list)
        or not raw
        or any(not isinstance(item, str) or not item for item in raw)
        or len(set(raw)) != len(raw)
    ):
        raise ScreeningBenchmarkInputError(
            f"{key} must be a non-empty list of unique filenames."
        )
    if any(PurePosixPath(item).name != item for item in raw):
        raise ScreeningBenchmarkInputError(f"{key} entries must be plain filenames.")
    return raw


def _required_sha256(value: dict[str, Any], key: str) -> str:
    raw = _required_string(value, key).lower()
    if len(raw) != 64 or any(character not in "0123456789abcdef" for character in raw):
        raise ScreeningBenchmarkInputError(
            f"{key} must be a lowercase or uppercase SHA-256 hexadecimal digest."
        )
    return raw


def _verified_amendments(
    spec: dict[str, Any], *, spec_path: Path, protocol_id: str
) -> list[dict[str, str]]:
    raw_amendments = spec.get("amendments", [])
    if not isinstance(raw_amendments, list):
        raise ScreeningBenchmarkInputError("amendments must be a list.")

    verified: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for raw_reference in raw_amendments:
        reference = _required_object(raw_reference, "amendment reference")
        amendment_id = _required_string(reference, "amendment_id")
        relative_path = _required_string(reference, "path")
        expected_sha256 = _required_sha256(reference, "sha256")
        if amendment_id in seen_ids:
            raise ScreeningBenchmarkInputError(
                f"Amendment {amendment_id} is referenced more than once."
            )
        seen_ids.add(amendment_id)

        portable_path = PurePosixPath(relative_path)
        if portable_path.name != relative_path or portable_path.is_absolute():
            raise ScreeningBenchmarkInputError(
                "Amendment paths must be filenames adjacent to the frozen specification."
            )
        amendment_path = spec_path.parent / relative_path
        actual_sha256 = _file_sha256(amendment_path, label=f"amendment {amendment_id}")
        if actual_sha256 != expected_sha256:
            raise ScreeningBenchmarkInputError(
                f"Amendment {amendment_id} differs from its frozen SHA-256: "
                f"expected {expected_sha256}, found {actual_sha256}."
            )

        amendment = _load_object(amendment_path)
        if _required_string(amendment, "amendment_id") != amendment_id:
            raise ScreeningBenchmarkInputError(
                f"Amendment {amendment_id} does not match its reference identity."
            )
        if _required_string(amendment, "protocol_id") != protocol_id:
            raise ScreeningBenchmarkInputError(
                f"Amendment {amendment_id} belongs to a different protocol."
            )
        invariants = _required_object(amendment.get("invariants"), "invariants")
        if invariants.get("scores_seen") is not False:
            raise ScreeningBenchmarkInputError(
                f"Amendment {amendment_id} must record scores_seen as false."
            )
        verified.append(
            {
                "amendment_id": amendment_id,
                "path": relative_path,
                "sha256": expected_sha256,
            }
        )
    return verified


def _verify_expected_archive(
    *, archive: Path, size_bytes: int, sha256: str, expected: dict[str, Any]
) -> None:
    expected_filename = _required_string(expected, "filename")
    expected_size = _required_nonnegative_int(expected, "size_bytes")
    expected_sha256 = _required_sha256(expected, "sha256")
    if (
        archive.name != expected_filename
        or size_bytes != expected_size
        or sha256 != expected_sha256
    ):
        raise ScreeningBenchmarkInputError(
            "The supplied archive identity differs from the frozen source: "
            f"expected {expected_filename} / {expected_size} bytes / SHA-256 "
            f"{expected_sha256}; found {archive.name} / {size_bytes} bytes / SHA-256 "
            f"{sha256}."
        )


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
