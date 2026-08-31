"""Deterministically freeze structured validation evidence without recomputation.

The freezer deliberately has no knowledge of docking engines.  A case specification
names exact records, fields, and artifacts; this module verifies those identities and
bytes and renders a stable machine manifest plus a human-readable matrix.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

_WINDOWS_ANKORA_DATA = re.compile(
    r"(?i)\b[A-Z]:[\\/](?:[^\r\n\"']+[\\/])*?\.ankora-data"
)
_WINDOWS_ANKORA_ENV = re.compile(
    r"(?i)\b[A-Z]:[\\/]Users[\\/][^\\/\r\n\"']+[\\/]"
    r"(?:anaconda3|miniconda3)[\\/]envs[\\/]ankora-dev"
)
_WINDOWS_TOOLS_ROOT = re.compile(
    r"(?i)\b[A-Z]:[\\/](?:Users[\\/][^\\/\r\n\"']+[\\/])?tools"
)
_WINDOWS_USER_HOME = re.compile(
    r"(?i)\b[A-Z]:[\\/]Users[\\/][^\\/\r\n\"']+"
)
_WINDOWS_DRIVE_ROOT = re.compile(r"(?i)\b[A-Z]:[\\/]")
_POSIX_USER_HOME = re.compile(r"(?<![A-Za-z0-9])/(?:home|Users)/[^/\s\"']+")


class ValidationEvidenceError(ValueError):
    """The named evidence is missing, inconsistent, or outside the data root."""


class EvidenceFieldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    pointer: str = Field(pattern=r"^/")
    operation: Literal["value", "length"] = "value"


class EvidenceArtifactSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    path: str = Field(min_length=1)
    sha256_pointer: str = Field(pattern=r"^/")
    size_bytes_pointer: str | None = Field(default=None, pattern=r"^/")


class EvidenceRecordSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1)
    label: str = Field(min_length=1)
    path: str = Field(min_length=1)
    identity_pointer: str = Field(pattern=r"^/")
    identity_value: str = Field(min_length=1)
    fields: tuple[EvidenceFieldSpec, ...] = ()
    artifacts: tuple[EvidenceArtifactSpec, ...] = ()


class ValidationCaseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    case_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    frozen_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    scope: str = Field(min_length=1)
    records: tuple[EvidenceRecordSpec, ...] = Field(min_length=1)
    interpretations: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()


def load_validation_case_spec(path: Path) -> ValidationCaseSpec:
    return ValidationCaseSpec.model_validate_json(path.read_text(encoding="utf-8"))


def freeze_validation_evidence(
    spec: ValidationCaseSpec, *, data_root: Path
) -> dict[str, Any]:
    """Read and verify the exact evidence named by ``spec``.

    The output contains no wall-clock timestamp and preserves specification order,
    so repeated runs against unchanged bytes are identical.
    """

    root = data_root.resolve()
    frozen_records: list[dict[str, Any]] = []
    seen_roles: set[str] = set()
    for record_spec in spec.records:
        if record_spec.role in seen_roles:
            raise ValidationEvidenceError(
                f"Duplicate evidence role: {record_spec.role}"
            )
        seen_roles.add(record_spec.role)
        record_path = _resolve_evidence_path(root, record_spec.path)
        record_bytes = _read_required_file(record_path, role=record_spec.role)
        try:
            payload: Any = json.loads(record_bytes)
        except json.JSONDecodeError as error:
            raise ValidationEvidenceError(
                f"Record for {record_spec.role} is not valid JSON: {record_spec.path}"
            ) from error
        if not isinstance(payload, dict):
            raise ValidationEvidenceError(
                f"Record for {record_spec.role} must contain a JSON object"
            )

        identity = _json_pointer(payload, record_spec.identity_pointer)
        if identity != record_spec.identity_value:
            raise ValidationEvidenceError(
                f"Identity mismatch for {record_spec.role}: expected "
                f"{record_spec.identity_value!r}, found {identity!r}"
            )

        fields = {
            field.label: _sanitize_public_value(_field_value(payload, field))
            for field in record_spec.fields
        }
        artifacts = [
            _freeze_artifact(root, payload, record_spec.role, artifact_spec)
            for artifact_spec in record_spec.artifacts
        ]
        frozen_records.append(
            {
                "role": record_spec.role,
                "label": record_spec.label,
                "record_path": record_spec.path.replace("\\", "/"),
                "identity": identity,
                "record_sha256": _sha256(record_bytes),
                "fields": fields,
                "artifacts": artifacts,
            }
        )

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "case_id": spec.case_id,
        "title": spec.title,
        "frozen_on": spec.frozen_on,
        "scope": spec.scope,
        "source": "explicit structured records and their referenced artifacts",
        "path_policy": "absolute filesystem roots replaced with portable placeholders",
        "record_count": len(frozen_records),
        "artifact_count": sum(
            len(record["artifacts"]) for record in frozen_records
        ),
        "records": frozen_records,
        "interpretations": list(spec.interpretations),
        "gaps": list(spec.gaps),
    }
    manifest["evidence_sha256"] = _sha256(_canonical_json(manifest))
    return manifest


def serialize_validation_manifest(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"


def render_validation_matrix(manifest: dict[str, Any]) -> str:
    lines = [
        f"# {manifest['title']}",
        "",
        f"- Case: `{manifest['case_id']}`",
        f"- Frozen on: `{manifest['frozen_on']}`",
        f"- Evidence SHA-256: `{manifest['evidence_sha256']}`",
        f"- Verified records: `{manifest['record_count']}`",
        f"- Verified artifacts: `{manifest['artifact_count']}`",
        f"- Scope: {manifest['scope']}",
        "",
        "This file is generated from the adjacent case specification. It names exact",
        "immutable records and verifies referenced artifact bytes; it does not rerun a",
        "scientific tool or choose a preferred result.",
        "",
        "## Record identities",
        "",
        "| Role | Record | Identity | Record SHA-256 |",
        "|---|---|---|---|",
    ]
    records = _records(manifest)
    for record in records:
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown(record["role"]),
                    _markdown(record["label"]),
                    f"`{_markdown(record['identity'])}`",
                    f"`{_markdown(record['record_sha256'])}`",
                )
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Scientific matrix",
            "",
            "| Role | Field | Recorded value |",
            "|---|---|---|",
        ]
    )
    for record in records:
        fields = record.get("fields")
        if not isinstance(fields, dict):
            continue
        for label, value in fields.items():
            lines.append(
                f"| {_markdown(record['role'])} | {_markdown(label)} | "
                f"{_markdown(_display_value(value))} |"
            )

    lines.extend(
        [
            "",
            "## Verified artifacts",
            "",
            "| Role | Artifact | Bytes | SHA-256 |",
            "|---|---|---:|---|",
        ]
    )
    for record in records:
        artifacts = record.get("artifacts")
        if not isinstance(artifacts, list):
            continue
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            lines.append(
                "| "
                + " | ".join(
                    (
                        _markdown(record["role"]),
                        _markdown(artifact["label"]),
                        _markdown(artifact["size_bytes"]),
                        f"`{_markdown(artifact['sha256'])}`",
                    )
                )
                + " |"
            )

    _append_bullets(lines, "Interpretation", manifest.get("interpretations"))
    _append_bullets(lines, "Known gaps", manifest.get("gaps"))
    return "\n".join(lines) + "\n"


def _freeze_artifact(
    root: Path,
    record: dict[str, Any],
    role: str,
    spec: EvidenceArtifactSpec,
) -> dict[str, Any]:
    path = _resolve_evidence_path(root, spec.path)
    content = _read_required_file(path, role=f"{role}/{spec.label}")
    actual_sha256 = _sha256(content)
    declared_sha256 = _json_pointer(record, spec.sha256_pointer)
    if not isinstance(declared_sha256, str) or actual_sha256 != declared_sha256:
        raise ValidationEvidenceError(
            f"SHA-256 mismatch for {role}/{spec.label}: declared "
            f"{declared_sha256!r}, actual {actual_sha256!r}"
        )
    actual_size = len(content)
    if spec.size_bytes_pointer is not None:
        declared_size = _json_pointer(record, spec.size_bytes_pointer)
        if declared_size != actual_size:
            raise ValidationEvidenceError(
                f"Size mismatch for {role}/{spec.label}: declared "
                f"{declared_size!r}, actual {actual_size}"
            )
    return {
        "label": spec.label,
        "path": spec.path.replace("\\", "/"),
        "size_bytes": actual_size,
        "sha256": actual_sha256,
        "verification": "matched structured record",
    }


def _field_value(document: dict[str, Any], spec: EvidenceFieldSpec) -> Any:
    value = _json_pointer(document, spec.pointer)
    if spec.operation == "length":
        if not isinstance(value, (dict, list, str)):
            raise ValidationEvidenceError(
                f"Cannot take the length of the value at {spec.pointer}"
            )
        return len(value)
    return value


def _sanitize_public_value(value: Any) -> Any:
    """Remove machine-specific absolute roots from publishable evidence fields.

    Record and artifact hashes are still computed from the exact original bytes.
    Only copied display fields are normalized, keeping public manifests portable
    without rewriting the authoritative local evidence.
    """

    if isinstance(value, dict):
        return {key: _sanitize_public_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_public_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_public_value(item) for item in value)
    if not isinstance(value, str):
        return value

    sanitized = _WINDOWS_ANKORA_DATA.sub("<ANKORA_DATA>", value)
    sanitized = _WINDOWS_ANKORA_ENV.sub("<ANKORA_ENV>", sanitized)
    sanitized = _WINDOWS_TOOLS_ROOT.sub("<TOOLS_ROOT>", sanitized)
    sanitized = _WINDOWS_USER_HOME.sub("<USER_HOME>", sanitized)
    sanitized = _WINDOWS_DRIVE_ROOT.sub("<LOCAL_ROOT>/", sanitized)
    return _POSIX_USER_HOME.sub("<USER_HOME>", sanitized)


def _resolve_evidence_path(root: Path, relative_path: str) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ValidationEvidenceError(
            f"Evidence paths must be relative to the data root: {relative_path}"
        )
    resolved = (root / candidate).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValidationEvidenceError(
            f"Evidence path escapes the data root: {relative_path}"
        )
    return resolved


def _read_required_file(path: Path, *, role: str) -> bytes:
    try:
        if not path.is_file():
            raise FileNotFoundError(path)
        return path.read_bytes()
    except OSError as error:
        raise ValidationEvidenceError(
            f"Required evidence for {role} is unavailable: {path.name}"
        ) from error


def _json_pointer(document: Any, pointer: str) -> Any:
    current = document
    for raw_token in pointer.removeprefix("/").split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        try:
            if isinstance(current, list):
                current = current[int(token)]
            elif isinstance(current, dict):
                current = current[token]
            else:
                raise KeyError(token)
        except (KeyError, IndexError, ValueError) as error:
            raise ValidationEvidenceError(f"JSON pointer does not exist: {pointer}") from error
    return current


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _records(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    records = manifest.get("records")
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        raise ValidationEvidenceError("Manifest records are malformed")
    return records


def _display_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(", ", ": "))
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return str(value)


def _markdown(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _append_bullets(lines: list[str], title: str, values: object) -> None:
    if not isinstance(values, list) or not values:
        return
    lines.extend(("", f"## {title}", ""))
    lines.extend(f"- {value}" for value in values)
