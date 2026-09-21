"""Freeze the loss-preserving LIT-PCBA primary ligand-preparation plan.

The public plan binds every source parent to one exact imported chemical state
and one deterministic conformer seed without copying molecular strings into
Git.  It performs no 3D generation, minimization, PDBQT conversion, docking, or
metric calculation.
"""

from __future__ import annotations

import hashlib
import json
import tarfile
from importlib import import_module
from pathlib import Path, PurePosixPath
from typing import Any

Chem: Any = import_module("rdkit.Chem")
rdBase: Any = import_module("rdkit.rdBase")

SCHEMA_VERSION = 1
CONFORMER_POOL_SIZE = 20
MAX_MMFF_ITERATIONS = 500
SEED_RULE = (
    "first 31 bits of SHA-256 over protocol_id, target_id, class label, "
    "canonical isomeric SMILES, source member path, physical line number, "
    "source identifier, and ETKDGv3 separated by NUL bytes; zero maps to one"
)
SOURCE_FILENAMES = {
    "active": ("active_T.smi", "active_V.smi"),
    "inactive": ("inactive_T.smi", "inactive_V.smi"),
}


class ScreeningBenchmarkLigandPlanError(ValueError):
    """The source population cannot satisfy the frozen preparation contract."""


def build_ligand_preparation_plan(
    *, archive: Path, input_manifest_path: Path
) -> dict[str, Any]:
    """Build a deterministic path-free plan from the exact inspected source."""

    inputs = _load_object(input_manifest_path, "source-population manifest")
    _verify_manifest_identity(inputs, "source-population manifest")
    protocol_id = _required_string(inputs, "protocol_id")
    source_identity = _required_object(inputs.get("source"), "source identity")
    if archive.name != _required_string(source_identity, "filename"):
        raise ScreeningBenchmarkLigandPlanError(
            "The source archive filename differs from the inspected input manifest."
        )
    if archive.stat().st_size != _required_nonnegative_int(source_identity, "size_bytes"):
        raise ScreeningBenchmarkLigandPlanError(
            "The source archive size differs from the inspected input manifest."
        )
    if _file_sha256(archive) != _required_sha256(source_identity, "sha256"):
        raise ScreeningBenchmarkLigandPlanError(
            "The source archive SHA-256 differs from the inspected input manifest."
        )

    try:
        with tarfile.open(archive, mode="r:*") as source:
            members = _safe_regular_members(source)
            targets, next_sequence = _build_targets(
                source,
                members,
                protocol_id=protocol_id,
                inputs=inputs,
            )
    except (OSError, tarfile.TarError) as error:
        raise ScreeningBenchmarkLigandPlanError(
            "The benchmark source is not a readable tar archive."
        ) from error

    totals = _required_object(inputs.get("totals"), "input totals")
    active_count = sum(int(target["active_count"]) for target in targets)
    inactive_count = sum(int(target["inactive_count"]) for target in targets)
    if active_count != _required_nonnegative_int(totals, "evaluation_active_units"):
        raise ScreeningBenchmarkLigandPlanError(
            "The active preparation census differs from the inspected population."
        )
    if inactive_count != _required_nonnegative_int(totals, "evaluation_inactive_units"):
        raise ScreeningBenchmarkLigandPlanError(
            "The inactive preparation census differs from the inspected population."
        )
    if next_sequence - 1 != active_count + inactive_count:
        raise ScreeningBenchmarkLigandPlanError(
            "The global preparation sequence does not cover every source parent."
        )

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": protocol_id,
        "dependencies": {
            "source_population_manifest_sha256": _required_sha256(
                inputs, "manifest_sha256"
            ),
            "source_archive": {
                "filename": archive.name,
                "size_bytes": archive.stat().st_size,
                "sha256": _file_sha256(archive),
            },
        },
        "chemical_state_policy": {
            "primary_state": "exact_imported_state",
            "canonicalization": (
                "RDKit canonical isomeric SMILES after ordinary sanitization; "
                "no uncharging, tautomerization, fragment removal, or other rewriting"
            ),
            "undefined_stereochemistry": "retain parent and record preparation failure",
            "multiple_components": "retain parent and record preparation failure",
            "filters": (
                "Lipinski, Veber, Ghose, Muegge, QED, PAINS, and Brenk are "
                "descriptive only and cannot remove a benchmark parent"
            ),
        },
        "conformer_policy": {
            "embedding_method": "ETKDGv3",
            "pool_size": CONFORMER_POOL_SIZE,
            "enforce_chirality": True,
            "seed_derivation": SEED_RULE,
            "force_field": "MMFF94s",
            "max_iterations": MAX_MMFF_ITERATIONS,
            "selection": "lowest_energy_converged",
            "nonconverged_fallback": (
                "retain the lowest-energy nonconverged conformer as evidence and "
                "do not send it to Meeko"
            ),
        },
        "pdbqt_policy": {
            "tool": "Meeko ligand preparation",
            "charge_model": "gasteiger",
            "requires_converged_conformer": True,
        },
        "execution_policy": {
            "all_source_parents_retained": True,
            "failures_retained_as_unscored_worst_tie": True,
            "parallelism": "logical processors minus one, capped by task count",
            "restartable_create_only_entry_attempts": True,
            "docking_executed": False,
            "scores_or_metrics_computed": False,
        },
        "tool_contract": {
            "rdkit_version": rdBase.rdkitVersion,
            "meeko_version_required": "0.7.1",
        },
        "targets": targets,
        "totals": {
            "target_count": len(targets),
            "active_parents": active_count,
            "inactive_parents": inactive_count,
            "all_parents": active_count + inactive_count,
        },
        "result_status": (
            "ligand_preparation_plan_frozen_no_ligand_preparation_docking_"
            "score_or_metric_executed"
        ),
    }
    manifest["manifest_sha256"] = _digest(manifest)
    return manifest


def verify_ligand_preparation_plan(
    path: Path,
    *,
    archive: Path | None = None,
    input_manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Verify plan identity and optionally reproduce it from exact source bytes."""

    manifest = _load_object(path, "ligand-preparation plan")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ScreeningBenchmarkLigandPlanError(
            "Unsupported ligand-preparation plan schema."
        )
    recorded = _required_sha256(manifest, "manifest_sha256")
    payload = dict(manifest)
    payload.pop("manifest_sha256")
    if _digest(payload) != recorded:
        raise ScreeningBenchmarkLigandPlanError(
            "The ligand-preparation plan differs from its SHA-256."
        )
    _verify_plan_contract(manifest)
    if (archive is None) != (input_manifest_path is None):
        raise ScreeningBenchmarkLigandPlanError(
            "Archive and input manifest must be supplied together for reproduction."
        )
    if archive is not None and input_manifest_path is not None:
        rebuilt = build_ligand_preparation_plan(
            archive=archive,
            input_manifest_path=input_manifest_path,
        )
        if rebuilt != manifest:
            raise ScreeningBenchmarkLigandPlanError(
                "The ligand-preparation plan does not reproduce from source bytes."
            )
    return manifest


def serialize_ligand_preparation_plan(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def _build_targets(
    source: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    *,
    protocol_id: str,
    inputs: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    targets: list[dict[str, Any]] = []
    sequence = 1
    raw_targets = _required_list(inputs, "targets")
    for raw_target in raw_targets:
        input_target = _required_object(raw_target, "input target")
        target_id = _required_string(input_target, "target_id")
        source_directory = _required_string(input_target, "source_directory")
        member_index = _input_members_by_path(input_target)
        target_parents: list[dict[str, Any]] = []
        seen_canonical: set[str] = set()
        class_counts: dict[str, int] = {}
        target_sequence = 1
        for class_label in ("active", "inactive"):
            class_index = 1
            for filename in SOURCE_FILENAMES[class_label]:
                member_path = _one_member_path(
                    members,
                    source_directory=source_directory,
                    filename=filename,
                )
                member = members[member_path]
                expected = member_index.get(member_path)
                if expected is None:
                    raise ScreeningBenchmarkLigandPlanError(
                        f"Source member {member_path} is absent from the input manifest."
                    )
                content = _member_bytes(source, member)
                if len(content) != _required_nonnegative_int(expected, "size_bytes"):
                    raise ScreeningBenchmarkLigandPlanError(
                        f"Source member size changed: {member_path}."
                    )
                if hashlib.sha256(content).hexdigest() != _required_sha256(
                    expected, "sha256"
                ):
                    raise ScreeningBenchmarkLigandPlanError(
                        f"Source member SHA-256 changed: {member_path}."
                    )
                for line_number, source_smiles, source_identifier in _source_rows(
                    content,
                    target_id=target_id,
                    member_path=member_path,
                ):
                    molecule = Chem.MolFromSmiles(source_smiles, sanitize=True)
                    if molecule is None or molecule.GetNumHeavyAtoms() == 0:
                        raise ScreeningBenchmarkLigandPlanError(
                            f"Source parent cannot be sanitized: {member_path}:{line_number}."
                        )
                    canonical = Chem.MolToSmiles(
                        molecule, canonical=True, isomericSmiles=True
                    )
                    if canonical in seen_canonical:
                        raise ScreeningBenchmarkLigandPlanError(
                            "A canonical source parent appears more than once in the "
                            "preparation population."
                        )
                    seen_canonical.add(canonical)
                    target_parents.append(
                        {
                            "sequence": sequence,
                            "target_sequence": target_sequence,
                            "class_label": class_label,
                            "class_index": class_index,
                            "source_member_path": member_path,
                            "source_line_number": line_number,
                            "source_identifier": source_identifier,
                            "source_smiles_sha256": hashlib.sha256(
                                source_smiles.encode("utf-8")
                            ).hexdigest(),
                            "canonical_isomeric_smiles_sha256": hashlib.sha256(
                                canonical.encode("utf-8")
                            ).hexdigest(),
                            "conformer_seed": _conformer_seed(
                                protocol_id=protocol_id,
                                target_id=target_id,
                                class_label=class_label,
                                canonical_smiles=canonical,
                                member_path=member_path,
                                line_number=line_number,
                                source_identifier=source_identifier,
                            ),
                        }
                    )
                    sequence += 1
                    target_sequence += 1
                    class_index += 1
            class_counts[class_label] = class_index - 1
        source_census = _required_object(
            input_target.get("source_census"), "source census"
        )
        if class_counts["active"] != _required_nonnegative_int(
            source_census, "active_rows"
        ):
            raise ScreeningBenchmarkLigandPlanError(
                f"Target {target_id} active census changed."
            )
        if class_counts["inactive"] != _required_nonnegative_int(
            source_census, "inactive_rows"
        ):
            raise ScreeningBenchmarkLigandPlanError(
                f"Target {target_id} inactive census changed."
            )
        targets.append(
            {
                "target_id": target_id,
                "source_directory": source_directory,
                "active_count": class_counts["active"],
                "inactive_count": class_counts["inactive"],
                "parents": target_parents,
            }
        )
    return targets, sequence


def _verify_plan_contract(manifest: dict[str, Any]) -> None:
    state_policy = _required_object(
        manifest.get("chemical_state_policy"), "chemical-state policy"
    )
    conformer_policy = _required_object(
        manifest.get("conformer_policy"), "conformer policy"
    )
    execution = _required_object(manifest.get("execution_policy"), "execution policy")
    if state_policy.get("primary_state") != "exact_imported_state":
        raise ScreeningBenchmarkLigandPlanError(
            "The primary benchmark must preserve the exact imported state."
        )
    if (
        conformer_policy.get("embedding_method") != "ETKDGv3"
        or conformer_policy.get("pool_size") != CONFORMER_POOL_SIZE
        or conformer_policy.get("force_field") != "MMFF94s"
        or conformer_policy.get("max_iterations") != MAX_MMFF_ITERATIONS
        or conformer_policy.get("seed_derivation") != SEED_RULE
    ):
        raise ScreeningBenchmarkLigandPlanError(
            "The frozen conformer/MMFF contract is incomplete or changed."
        )
    if (
        execution.get("all_source_parents_retained") is not True
        or execution.get("failures_retained_as_unscored_worst_tie") is not True
        or execution.get("docking_executed") is not False
        or execution.get("scores_or_metrics_computed") is not False
    ):
        raise ScreeningBenchmarkLigandPlanError(
            "The loss-preserving pre-result execution boundary is incomplete."
        )
    targets = _required_list(manifest, "targets")
    totals = _required_object(manifest.get("totals"), "plan totals")
    sequences: list[int] = []
    active_count = 0
    inactive_count = 0
    for raw_target in targets:
        target = _required_object(raw_target, "target plan")
        parents = _required_list(target, "parents")
        canonical_hashes: set[str] = set()
        observed_active = 0
        observed_inactive = 0
        for raw_parent in parents:
            parent = _required_object(raw_parent, "planned parent")
            sequence = _required_positive_int(parent, "sequence")
            sequences.append(sequence)
            label = _required_string(parent, "class_label")
            if label == "active":
                observed_active += 1
            elif label == "inactive":
                observed_inactive += 1
            else:
                raise ScreeningBenchmarkLigandPlanError(
                    "A planned parent has an unsupported class label."
                )
            canonical_hash = _required_sha256(
                parent, "canonical_isomeric_smiles_sha256"
            )
            if canonical_hash in canonical_hashes:
                raise ScreeningBenchmarkLigandPlanError(
                    "A canonical parent hash appears more than once in the plan."
                )
            canonical_hashes.add(canonical_hash)
            _required_sha256(parent, "source_smiles_sha256")
            _required_positive_int(parent, "conformer_seed")
            _safe_member_path(_required_string(parent, "source_member_path"))
        if observed_active != _required_nonnegative_int(target, "active_count"):
            raise ScreeningBenchmarkLigandPlanError(
                "A target active count differs from its parent rows."
            )
        if observed_inactive != _required_nonnegative_int(target, "inactive_count"):
            raise ScreeningBenchmarkLigandPlanError(
                "A target inactive count differs from its parent rows."
            )
        active_count += observed_active
        inactive_count += observed_inactive
    if sequences != list(range(1, len(sequences) + 1)):
        raise ScreeningBenchmarkLigandPlanError(
            "Planned parent sequences must be complete and source ordered."
        )
    expected = (
        len(targets),
        active_count,
        inactive_count,
        active_count + inactive_count,
    )
    observed = (
        _required_nonnegative_int(totals, "target_count"),
        _required_nonnegative_int(totals, "active_parents"),
        _required_nonnegative_int(totals, "inactive_parents"),
        _required_nonnegative_int(totals, "all_parents"),
    )
    if observed != expected:
        raise ScreeningBenchmarkLigandPlanError(
            "The ligand-preparation plan totals do not close."
        )


def _conformer_seed(
    *,
    protocol_id: str,
    target_id: str,
    class_label: str,
    canonical_smiles: str,
    member_path: str,
    line_number: int,
    source_identifier: str,
) -> int:
    payload = "\0".join(
        (
            protocol_id,
            target_id,
            class_label,
            canonical_smiles,
            member_path,
            str(line_number),
            source_identifier,
            "ETKDGv3",
        )
    ).encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(payload).digest()[:4], "big") & 0x7FFF_FFFF
    return seed or 1


def _source_rows(
    content: bytes, *, target_id: str, member_path: str
) -> list[tuple[int, str, str]]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ScreeningBenchmarkLigandPlanError(
            f"Target {target_id} source member is not UTF-8: {member_path}."
        ) from error
    rows: list[tuple[int, str, str]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        fields = stripped.split()
        if len(fields) < 2:
            raise ScreeningBenchmarkLigandPlanError(
                f"Target {target_id} source row lacks an identifier: "
                f"{member_path}:{line_number}."
            )
        rows.append((line_number, fields[0], fields[1]))
    return rows


def _input_members_by_path(target: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for raw in _required_list(target, "members"):
        member = _required_object(raw, "input member")
        path = _required_string(member, "path")
        if path in index:
            raise ScreeningBenchmarkLigandPlanError(
                "The input manifest repeats a source member path."
            )
        index[path] = member
    return index


def _safe_regular_members(source: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    members: dict[str, tarfile.TarInfo] = {}
    for member in source.getmembers():
        normalized = _safe_member_path(member.name)
        if not member.isfile():
            continue
        if normalized in members:
            raise ScreeningBenchmarkLigandPlanError(
                f"Archive contains an ambiguous duplicate member: {normalized}."
            )
        members[normalized] = member
    return members


def _safe_member_path(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    has_windows_drive = bool(path.parts) and path.parts[0].endswith(":")
    if path.is_absolute() or has_windows_drive or ".." in path.parts:
        raise ScreeningBenchmarkLigandPlanError(
            f"Archive member escapes its source root: {value}."
        )
    return path.as_posix()


def _one_member_path(
    members: dict[str, tarfile.TarInfo], *, source_directory: str, filename: str
) -> str:
    matches = [
        path
        for path in members
        if source_directory in PurePosixPath(path).parts
        and PurePosixPath(path).name == filename
    ]
    if len(matches) != 1:
        raise ScreeningBenchmarkLigandPlanError(
            f"Source target {source_directory} requires exactly one {filename}; "
            f"found {len(matches)}."
        )
    return matches[0]


def _member_bytes(source: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    extracted = source.extractfile(member)
    if extracted is None:
        raise ScreeningBenchmarkLigandPlanError(
            f"Archive member is unreadable: {member.name}."
        )
    return extracted.read()


def _verify_manifest_identity(manifest: dict[str, Any], label: str) -> None:
    recorded = _required_sha256(manifest, "manifest_sha256")
    payload = dict(manifest)
    payload.pop("manifest_sha256")
    if _digest(payload) != recorded:
        raise ScreeningBenchmarkLigandPlanError(
            f"The {label} differs from its recorded SHA-256."
        )


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScreeningBenchmarkLigandPlanError(
            f"The {label} is unavailable or invalid."
        ) from error
    return _required_object(value, label)


def _required_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScreeningBenchmarkLigandPlanError(f"{label} must be an object.")
    return value


def _required_list(value: dict[str, Any], key: str) -> list[Any]:
    raw = value.get(key)
    if not isinstance(raw, list):
        raise ScreeningBenchmarkLigandPlanError(f"{key} must be a list.")
    return raw


def _required_string(value: dict[str, Any], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise ScreeningBenchmarkLigandPlanError(f"{key} must be a non-empty string.")
    return raw


def _required_nonnegative_int(value: dict[str, Any], key: str) -> int:
    raw = value.get(key)
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise ScreeningBenchmarkLigandPlanError(
            f"{key} must be a non-negative integer."
        )
    return raw


def _required_positive_int(value: dict[str, Any], key: str) -> int:
    raw = _required_nonnegative_int(value, key)
    if raw == 0:
        raise ScreeningBenchmarkLigandPlanError(f"{key} must be positive.")
    return raw


def _required_sha256(value: dict[str, Any], key: str) -> str:
    raw = _required_string(value, key).lower()
    if len(raw) != 64 or any(character not in "0123456789abcdef" for character in raw):
        raise ScreeningBenchmarkLigandPlanError(f"{key} must be a SHA-256.")
    return raw


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
