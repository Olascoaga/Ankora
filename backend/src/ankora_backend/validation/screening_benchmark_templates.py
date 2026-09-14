"""Freeze LIT-PCBA holo-template choices before benchmark docking."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

RCSB_GRAPHQL_ENDPOINT = "https://data.rcsb.org/graphql"
RCSB_TEMPLATE_QUERY = """query($ids:[String!]!){
  entries(entry_ids:$ids){
    rcsb_id
    exptl{method}
    rcsb_entry_info{resolution_combined}
    struct{title}
  }
}"""
SELECTION_RULE = (
    "lowest positive experimental resolution in angstrom, then "
    "lexicographically smallest lowercase PDB ID"
)


class ScreeningBenchmarkTemplateError(ValueError):
    """Template metadata cannot satisfy the pre-result selection contract."""


def build_template_manifest(
    *,
    input_manifest_path: Path,
    rcsb_entries: list[object],
    retrieved_on: str,
) -> dict[str, Any]:
    """Select primary and alternate templates from an exact metadata snapshot."""

    inputs = _load_object(input_manifest_path, "source-population manifest")
    _verify_manifest_identity(inputs, "source-population manifest")
    protocol_id = _required_string(inputs, "protocol_id")
    targets = _required_list(inputs, "targets")
    normalized_entries = _normalize_rcsb_entries(rcsb_entries)

    expected_ids = {
        template_id.lower()
        for raw_target in targets
        for template_id in _required_string_list(
            _required_object(raw_target, "target"), "template_ids"
        )
    }
    observed_ids = {entry["pdb_id"] for entry in normalized_entries}
    if observed_ids != expected_ids:
        missing = sorted(expected_ids - observed_ids)
        unexpected = sorted(observed_ids - expected_ids)
        raise ScreeningBenchmarkTemplateError(
            "RCSB metadata does not close the source-template census: "
            f"missing={missing}, unexpected={unexpected}."
        )
    by_id = {entry["pdb_id"]: entry for entry in normalized_entries}

    planned_targets: list[dict[str, Any]] = []
    for raw_target in targets:
        target = _required_object(raw_target, "target")
        target_id = _required_string(target, "target_id")
        template_ids = [
            value.lower() for value in _required_string_list(target, "template_ids")
        ]
        if len(template_ids) < 2:
            raise ScreeningBenchmarkTemplateError(
                f"Target {target_id} needs at least two holo templates."
            )
        candidates = sorted(
            (
                {
                    **by_id[pdb_id],
                    "source_receptor": _member_identity(target, pdb_id, "protein"),
                    "source_ligand": _member_identity(target, pdb_id, "ligand"),
                }
                for pdb_id in template_ids
            ),
            key=lambda candidate: (candidate["resolution_angstrom"], candidate["pdb_id"]),
        )
        planned_targets.append(
            {
                "target_id": target_id,
                "selection_rule": SELECTION_RULE,
                "primary_template": candidates[0],
                "alternate_template": candidates[1],
                "candidates": candidates,
            }
        )

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "protocol_id": protocol_id,
        "source_population_manifest_sha256": _required_string(
            inputs, "manifest_sha256"
        ),
        "metadata_source": {
            "endpoint": RCSB_GRAPHQL_ENDPOINT,
            "retrieved_on": retrieved_on,
            "query_sha256": hashlib.sha256(
                RCSB_TEMPLATE_QUERY.encode("utf-8")
            ).hexdigest(),
        },
        "selection_boundary": (
            "all candidates are exact paired holo templates from the frozen "
            "LIT-PCBA source; no docking score or enrichment result was inspected"
        ),
        "targets": planned_targets,
        "result_status": "templates_selected_no_docking_executed",
    }
    manifest["manifest_sha256"] = hashlib.sha256(_canonical_json(manifest)).hexdigest()
    return manifest


def verify_template_manifest(
    *, input_manifest_path: Path, template_manifest_path: Path
) -> dict[str, Any]:
    """Rebuild a tracked template manifest from its recorded metadata offline."""

    recorded = _load_object(template_manifest_path, "template manifest")
    _verify_manifest_identity(recorded, "template manifest")
    entries: list[object] = []
    for raw_target in _required_list(recorded, "targets"):
        target = _required_object(raw_target, "target")
        entries.extend(_required_list(target, "candidates"))
    metadata_source = _required_object(
        recorded.get("metadata_source"), "metadata_source"
    )
    rebuilt = build_template_manifest(
        input_manifest_path=input_manifest_path,
        rcsb_entries=entries,
        retrieved_on=_required_string(metadata_source, "retrieved_on"),
    )
    if rebuilt != recorded:
        raise ScreeningBenchmarkTemplateError(
            "The template manifest does not reproduce from its recorded metadata."
        )
    return recorded


def serialize_template_manifest(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def _normalize_rcsb_entries(raw_entries: list[object]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_entry in raw_entries:
        entry = _required_object(raw_entry, "RCSB entry")
        raw_id = entry.get("pdb_id", entry.get("rcsb_id"))
        if not isinstance(raw_id, str) or len(raw_id) != 4 or not raw_id.isalnum():
            raise ScreeningBenchmarkTemplateError("Every RCSB entry needs a valid PDB ID.")
        pdb_id = raw_id.lower()
        if pdb_id in seen:
            raise ScreeningBenchmarkTemplateError(
                f"RCSB metadata repeats template {pdb_id}."
            )
        seen.add(pdb_id)

        raw_methods: object = entry.get("experimental_methods", entry.get("exptl"))
        if isinstance(raw_methods, list) and raw_methods and isinstance(raw_methods[0], dict):
            methods = [item.get("method") for item in raw_methods]
        elif isinstance(raw_methods, list):
            methods = list(raw_methods)
        else:
            methods = []
        if methods != ["X-RAY DIFFRACTION"]:
            raise ScreeningBenchmarkTemplateError(
                f"Template {pdb_id} is not one unambiguous X-ray structure."
            )

        raw_resolution = entry.get("resolution_angstrom")
        if raw_resolution is None:
            info = entry.get("rcsb_entry_info")
            if isinstance(info, dict):
                values = info.get("resolution_combined")
                if isinstance(values, list) and len(values) == 1:
                    raw_resolution = values[0]
        if (
            not isinstance(raw_resolution, (int, float))
            or isinstance(raw_resolution, bool)
            or raw_resolution <= 0
        ):
            raise ScreeningBenchmarkTemplateError(
                f"Template {pdb_id} has no single positive experimental resolution."
            )
        title = entry.get("title")
        if title is None:
            structure = entry.get("struct")
            if isinstance(structure, dict):
                title = structure.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ScreeningBenchmarkTemplateError(f"Template {pdb_id} has no title.")
        normalized.append(
            {
                "pdb_id": pdb_id,
                "experimental_methods": ["X-RAY DIFFRACTION"],
                "resolution_angstrom": float(raw_resolution),
                "title": title.strip(),
            }
        )
    return sorted(normalized, key=lambda entry: entry["pdb_id"])


def _member_identity(target: dict[str, Any], pdb_id: str, kind: str) -> dict[str, Any]:
    suffix = f"/{pdb_id}_{kind}.mol2"
    matches = [
        _required_object(member, "source member")
        for member in _required_list(target, "members")
        if isinstance(member, dict)
        and isinstance(member.get("path"), str)
        and member["path"].lower().endswith(suffix)
    ]
    if len(matches) != 1:
        raise ScreeningBenchmarkTemplateError(
            f"Template {pdb_id} does not have one exact source {kind} member."
        )
    member = matches[0]
    path = _required_string(member, "path")
    if PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
        raise ScreeningBenchmarkTemplateError("Source member path is unsafe.")
    return {
        "path": path,
        "size_bytes": _required_nonnegative_int(member, "size_bytes"),
        "sha256": _required_sha256(member, "sha256"),
    }


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScreeningBenchmarkTemplateError(f"The {label} is unavailable or invalid.") from error
    return _required_object(value, label)


def _verify_manifest_identity(manifest: dict[str, Any], label: str) -> None:
    recorded = _required_sha256(manifest, "manifest_sha256")
    payload = dict(manifest)
    payload.pop("manifest_sha256")
    actual = hashlib.sha256(_canonical_json(payload)).hexdigest()
    if actual != recorded:
        raise ScreeningBenchmarkTemplateError(
            f"The {label} content differs from its manifest SHA-256."
        )


def _required_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScreeningBenchmarkTemplateError(f"{label} must be an object.")
    return value


def _required_list(value: dict[str, Any], key: str) -> list[Any]:
    raw = value.get(key)
    if not isinstance(raw, list):
        raise ScreeningBenchmarkTemplateError(f"{key} must be a list.")
    return raw


def _required_string(value: dict[str, Any], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise ScreeningBenchmarkTemplateError(f"{key} must be a non-empty string.")
    return raw


def _required_string_list(value: dict[str, Any], key: str) -> list[str]:
    raw = _required_list(value, key)
    if not raw or any(not isinstance(item, str) or not item for item in raw):
        raise ScreeningBenchmarkTemplateError(f"{key} must contain strings.")
    return raw


def _required_nonnegative_int(value: dict[str, Any], key: str) -> int:
    raw = value.get(key)
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise ScreeningBenchmarkTemplateError(f"{key} must be a non-negative integer.")
    return raw


def _required_sha256(value: dict[str, Any], key: str) -> str:
    raw = _required_string(value, key).lower()
    if len(raw) != 64 or any(character not in "0123456789abcdef" for character in raw):
        raise ScreeningBenchmarkTemplateError(f"{key} must be a SHA-256 digest.")
    return raw


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
