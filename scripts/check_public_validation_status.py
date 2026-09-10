"""Fail when public validation summaries diverge from frozen evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = PurePosixPath("docs/validation/VALIDATION_STATUS.json")
STATUS_MARKDOWN_PATH = PurePosixPath("docs/validation/VALIDATION_STATUS.md")
README_PATH = PurePosixPath("README.md")
README_BEGIN = "<!-- BEGIN GENERATED VALIDATION STATUS -->"
README_END = "<!-- END GENERATED VALIDATION STATUS -->"
ALLOWED_CASE_STATUSES = {"completed", "frozen_with_known_gaps"}
REQUIRED_COMPLETED_CASES = {"PIK3CD_6OCO_M5V_RESULTS"}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ValidationStatusError(RuntimeError):
    """Raised when the public validation status is inconsistent."""


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check public validation summaries against frozen manifests."
    )
    parser.add_argument("--root", type=Path, default=REPOSITORY_ROOT)
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValidationStatusError(f"Required public status file is missing: {path}") from error
    except json.JSONDecodeError as error:
        raise ValidationStatusError(f"Invalid JSON in {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValidationStatusError(f"Expected a JSON object in {path}")
    return value


def _resolve_public_path(root: Path, raw_path: object) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise ValidationStatusError("Validation paths must be non-empty strings")
    relative = PurePosixPath(raw_path)
    if relative.is_absolute() or ".." in relative.parts or "\\" in raw_path:
        raise ValidationStatusError(f"Validation path must be repository-relative: {raw_path}")
    resolved_root = root.resolve()
    resolved = (resolved_root / Path(*relative.parts)).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValidationStatusError(f"Validation path escapes the repository: {raw_path}")
    return resolved


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationStatusError(f"{label} must be a non-empty string")
    return value


def _require_positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValidationStatusError(f"{label} must be a positive integer")
    return value


def _validated_cases(root: Path, status: dict[str, Any]) -> list[dict[str, Any]]:
    raw_cases = status.get("reference_cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValidationStatusError("reference_cases must be a non-empty array")
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_case in enumerate(raw_cases):
        if not isinstance(raw_case, dict):
            raise ValidationStatusError(f"reference_cases[{index}] must be an object")
        case_id = _require_string(raw_case.get("case_id"), f"reference_cases[{index}].case_id")
        if case_id in seen:
            raise ValidationStatusError(f"Duplicate reference case: {case_id}")
        seen.add(case_id)
        case_status = _require_string(raw_case.get("status"), f"{case_id}.status")
        if case_status not in ALLOWED_CASE_STATUSES:
            raise ValidationStatusError(f"Unsupported status for {case_id}: {case_status}")
        evidence_sha256 = _require_string(raw_case.get("evidence_sha256"), f"{case_id}.evidence_sha256")
        if not SHA256_PATTERN.fullmatch(evidence_sha256):
            raise ValidationStatusError(f"Invalid evidence SHA-256 for {case_id}")
        record_count = _require_positive_int(raw_case.get("record_count"), f"{case_id}.record_count")
        artifact_count = _require_positive_int(
            raw_case.get("artifact_count"), f"{case_id}.artifact_count"
        )
        _require_string(raw_case.get("label"), f"{case_id}.label")
        _require_string(raw_case.get("conclusion"), f"{case_id}.conclusion")
        manifest_path = _resolve_public_path(root, raw_case.get("manifest"))
        matrix_path = _resolve_public_path(root, raw_case.get("matrix"))
        manifest = _load_json(manifest_path)
        expected_manifest_values = {
            "case_id": case_id,
            "record_count": record_count,
            "artifact_count": artifact_count,
            "evidence_sha256": evidence_sha256,
        }
        for field, expected in expected_manifest_values.items():
            if manifest.get(field) != expected:
                raise ValidationStatusError(
                    f"{case_id} {field} differs between VALIDATION_STATUS.json "
                    f"and {manifest_path.relative_to(root)}"
                )
        try:
            matrix = matrix_path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise ValidationStatusError(f"Validation matrix is missing: {matrix_path}") from error
        matrix_claims = (
            f"- Case: `{case_id}`",
            f"- Evidence SHA-256: `{evidence_sha256}`",
            f"- Verified records: `{record_count}`",
            f"- Verified artifacts: `{artifact_count}`",
        )
        if any(claim not in matrix for claim in matrix_claims):
            raise ValidationStatusError(
                f"{matrix_path.relative_to(root)} does not match its frozen manifest"
            )
        cases.append(raw_case)
    missing = REQUIRED_COMPLETED_CASES - {
        str(case["case_id"]) for case in cases if case["status"] == "completed"
    }
    if missing:
        raise ValidationStatusError(
            "Completed reference evidence is missing from public status: " + ", ".join(sorted(missing))
        )
    return cases


def _render_status_markdown(status: dict[str, Any], cases: list[dict[str, Any]]) -> str:
    workspaces = status["implemented_workspaces"]
    lines = [
        "# Public validation status",
        "",
        "<!-- Generated from VALIDATION_STATUS.json; checked by CI. -->",
        "",
        f"Last synchronized: `{status['synchronized_on']}`",
        "",
        "## Implemented scientific workflow",
        "",
        f"The implemented and accepted workspaces are {workspaces[0]}-{workspaces[-1]}.",
        "Implementation breadth is not evidence of scientific generality; the frozen cases below",
        "define the current validation boundary.",
        "",
        "## Frozen reference cases",
        "",
        "| Reference case | Status | Records | Artifacts | Evidence SHA-256 |",
        "|---|---|---:|---:|---|",
    ]
    for case in cases:
        matrix_path = PurePosixPath(case["matrix"])
        matrix_link = matrix_path.relative_to(PurePosixPath("docs/validation"))
        label = f"[{case['label']}]({matrix_link})"
        lines.append(
            f"| {label} | `{case['status']}` | {case['record_count']} | "
            f"{case['artifact_count']} | `{case['evidence_sha256']}` |"
        )
    lines.extend(["", "## Recorded conclusions", ""])
    for case in cases:
        lines.append(f"- **{case['label']}:** {case['conclusion']}")
    lines.extend(["", "## Claims not established", ""])
    for claim in status["claims_not_established"]:
        lines.append(f"- {claim}")
    lines.extend(
        [
            "",
            "## Next validation boundary",
            "",
            str(status["next_validation_boundary"]),
            "",
        ]
    )
    return "\n".join(lines)


def _render_readme_block(status: dict[str, Any], cases: list[dict[str, Any]]) -> str:
    completed = [case for case in cases if case["status"] == "completed"]
    completed_labels = ", ".join(case["label"] for case in completed)
    summary = (
        f"Ankora implements the {status['implemented_workspaces'][0]}-"
        f"{status['implemented_workspaces'][-1]} workflow. Frozen completed evidence exists for "
        f"{completed_labels}; other cases and known gaps remain visible in the "
        "[public validation status](docs/validation/VALIDATION_STATUS.md). This evidence does "
        "not yet establish virtual-screening enrichment, affinity prediction, biological "
        "activity, or cross-target generality."
    )
    return f"{README_BEGIN}\n## Scientific validation status\n\n{summary}\n{README_END}"


def _check_exact(path: Path, expected: str) -> None:
    try:
        actual = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ValidationStatusError(f"Generated public summary is missing: {path}") from error
    normalized_actual = actual.replace("\r\n", "\n").rstrip() + "\n"
    normalized_expected = expected.rstrip() + "\n"
    if normalized_actual != normalized_expected:
        raise ValidationStatusError(f"Generated public validation summary is stale: {path}")


def _check_readme(path: Path, expected_block: str) -> None:
    try:
        content = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    except FileNotFoundError as error:
        raise ValidationStatusError(f"README is missing: {path}") from error
    if content.count(README_BEGIN) != 1 or content.count(README_END) != 1:
        raise ValidationStatusError("README must contain exactly one generated validation block")
    start = content.index(README_BEGIN)
    end = content.index(README_END, start) + len(README_END)
    if content[start:end] != expected_block:
        raise ValidationStatusError("README public validation block is stale")


def _validate_contract(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    status = _load_json(_resolve_public_path(root, str(STATUS_PATH)))
    if status.get("schema_version") != 1:
        raise ValidationStatusError("Unsupported VALIDATION_STATUS.json schema_version")
    workspaces = status.get("implemented_workspaces")
    if workspaces != [f"M{number}" for number in range(1, 10)]:
        raise ValidationStatusError("implemented_workspaces must explicitly list M1 through M9")
    _require_string(status.get("synchronized_on"), "synchronized_on")
    claims = status.get("claims_not_established")
    if not isinstance(claims, list) or not claims:
        raise ValidationStatusError("claims_not_established must be a non-empty array")
    for index, claim in enumerate(claims):
        _require_string(claim, f"claims_not_established[{index}]")
    _require_string(status.get("next_validation_boundary"), "next_validation_boundary")
    return status, _validated_cases(root, status)


def main() -> int:
    root = _arguments().root.resolve()
    try:
        status, cases = _validate_contract(root)
        _check_exact(
            _resolve_public_path(root, str(STATUS_MARKDOWN_PATH)),
            _render_status_markdown(status, cases),
        )
        _check_readme(
            _resolve_public_path(root, str(README_PATH)),
            _render_readme_block(status, cases),
        )
    except ValidationStatusError as error:
        print(f"Public validation status check failed: {error}", file=sys.stderr)
        return 1
    print(
        f"Public validation status is synchronized: {len(cases)} frozen cases, "
        f"{len(REQUIRED_COMPLETED_CASES)} completed independent case."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
