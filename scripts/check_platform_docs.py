"""Verify platform capability matrix, documentation portal, and validation index."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PLATFORM_JSON_PATH = PurePosixPath("docs/product/PLATFORM_STATUS.json")
PLATFORM_MD_PATH = PurePosixPath("docs/product/PLATFORM_STATUS.md")
DOCS_PORTAL_PATH = PurePosixPath("docs/README.md")
VALIDATION_INDEX_PATH = PurePosixPath("docs/validation/INDEX.md")
CORE_LINK_CHECKED_DOCS = (
    PLATFORM_MD_PATH,
    DOCS_PORTAL_PATH,
    PurePosixPath("docs/USER_GUIDE.md"),
    PurePosixPath("docs/product/PRODUCT_DEFINITION.md"),
    PurePosixPath("docs/product/SCOPE.md"),
    PurePosixPath("docs/scientific/REDOCKING_VALIDATION.md"),
    PurePosixPath("docs/architecture/ARCHITECTURE.md"),
    PurePosixPath("docs/DEVELOPMENT_LINUX.md"),
)

ALLOWED_DISTRIBUTION_STATUSES = {
    "private_beta",
    "release_candidate",
    "accepted_release",
    "out_of_scope",
}
REQUIRED_PLATFORM_IDS = ("windows_x86_64", "linux_x86_64", "macos")
REQUIRED_ENGINE_IDS = ("vina", "autodock4_cpu", "autodock_gpu", "gnina")
WINDOWS_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Z]:[\\/]")
POSIX_PERSONAL_PATH = re.compile(r"(?<![A-Za-z0-9])/(?:home|Users)/[^/\s\"']+")


class PlatformDocsError(RuntimeError):
    """Raised when platform status or documentation index invariants fail."""


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check or render platform capability and documentation index files."
    )
    parser.add_argument("--root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Render docs/product/PLATFORM_STATUS.md from PLATFORM_STATUS.json before checking.",
    )
    return parser.parse_args()


def _resolve_repo_path(root: Path, raw_path: str) -> Path:
    if not raw_path or "\\" in raw_path:
        raise PlatformDocsError(f"Repository path must use POSIX separators: {raw_path!r}")
    rel = PurePosixPath(raw_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise PlatformDocsError(f"Path must be repository-relative: {raw_path!r}")
    resolved_root = root.resolve()
    resolved = (resolved_root / Path(*rel.parts)).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise PlatformDocsError(f"Path escapes repository root: {raw_path!r}")
    return resolved


def _require_str(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlatformDocsError(f"{label} must be a non-empty string")
    return value


def _require_str_list(value: object, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise PlatformDocsError(f"{label} must be a {'list' if allow_empty else 'non-empty list'}")
    out: list[str] = []
    for idx, item in enumerate(value):
        out.append(_require_str(item, f"{label}[{idx}]"))
    return out


def _headings(markdown: str) -> set[str]:
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    for raw_heading in re.findall(r"^#{1,6}\s+(.+)$", markdown, re.MULTILINE):
        cleaned = re.sub(r"`([^`]+)`", r"\1", raw_heading.strip())
        cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
        slug = re.sub(r"[^\w\s-]", "", cleaned.lower()).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        anchors.add(f"{slug}-{count}" if count else slug)
        # Also accept literal raw GitHub-style slug when backticks were present
        raw_slug = re.sub(r"[^\w\s-]", "", raw_heading.strip().lower()).replace(" ", "-")
        anchors.add(raw_slug)
    return anchors


def load_and_validate_platform_status(root: Path) -> dict[str, Any]:
    json_path = _resolve_repo_path(root, str(PLATFORM_JSON_PATH))
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PlatformDocsError(f"Missing {PLATFORM_JSON_PATH}") from exc
    except json.JSONDecodeError as exc:
        raise PlatformDocsError(f"Invalid JSON in {PLATFORM_JSON_PATH}: {exc}") from exc

    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise PlatformDocsError("PLATFORM_STATUS.json must be a schema_version=1 object")
    _require_str(data.get("synchronized_on"), "synchronized_on")

    raw_engines = data.get("engines")
    if not isinstance(raw_engines, list):
        raise PlatformDocsError("engines must be a list")
    engines_by_id: dict[str, dict[str, Any]] = {}
    for idx, engine in enumerate(raw_engines):
        if not isinstance(engine, dict):
            raise PlatformDocsError(f"engines[{idx}] must be an object")
        eid = _require_str(engine.get("engine_id"), f"engines[{idx}].engine_id")
        if eid in engines_by_id:
            raise PlatformDocsError(f"Duplicate engine_id: {eid}")
        _require_str(engine.get("label"), f"{eid}.label")
        _require_str(engine.get("version"), f"{eid}.version")
        _require_str_list(engine.get("platforms"), f"{eid}.platforms")
        _require_str_list(engine.get("execution_modes"), f"{eid}.execution_modes")
        _require_str(engine.get("primary_ranking_metric"), f"{eid}.primary_ranking_metric")
        _require_str(engine.get("result_model"), f"{eid}.result_model")
        _require_str(
            engine.get("cross_engine_rank_comparison"), f"{eid}.cross_engine_rank_comparison"
        )
        _require_str(engine.get("scientific_notes"), f"{eid}.scientific_notes")
        engines_by_id[eid] = engine

    if tuple(engines_by_id) != REQUIRED_ENGINE_IDS:
        raise PlatformDocsError(
            f"engines must list {REQUIRED_ENGINE_IDS} in canonical order, got {tuple(engines_by_id)}"
        )

    raw_platforms = data.get("platforms")
    if not isinstance(raw_platforms, list):
        raise PlatformDocsError("platforms must be a list")
    platforms_by_id: dict[str, dict[str, Any]] = {}
    for idx, plat in enumerate(raw_platforms):
        if not isinstance(plat, dict):
            raise PlatformDocsError(f"platforms[{idx}] must be an object")
        pid = _require_str(plat.get("platform_id"), f"platforms[{idx}].platform_id")
        if pid in platforms_by_id:
            raise PlatformDocsError(f"Duplicate platform_id: {pid}")
        _require_str(plat.get("label"), f"{pid}.label")
        status = _require_str(plat.get("distribution_status"), f"{pid}.distribution_status")
        if status not in ALLOWED_DISTRIBUTION_STATUSES:
            raise PlatformDocsError(f"Unsupported distribution_status for {pid}: {status}")
        accepted = plat.get("accepted_release")
        if not isinstance(accepted, bool):
            raise PlatformDocsError(f"{pid}.accepted_release must be a boolean")
        _require_str(plat.get("desktop_shell"), f"{pid}.desktop_shell")
        _require_str(plat.get("ci_lane"), f"{pid}.ci_lane")
        _require_str(plat.get("implemented_workflow"), f"{pid}.implemented_workflow")
        plat_engines = _require_str_list(
            plat.get("engines"), f"{pid}.engines", allow_empty=(status == "out_of_scope")
        )
        for eid in plat_engines:
            if eid not in engines_by_id:
                raise PlatformDocsError(f"{pid} references unknown engine {eid!r}")
        _require_str(plat.get("offline_packaging"), f"{pid}.offline_packaging")
        _require_str(plat.get("engineering_evidence"), f"{pid}.engineering_evidence")
        gates = _require_str_list(
            plat.get("pending_release_gates"), f"{pid}.pending_release_gates", allow_empty=accepted
        )
        if accepted and gates:
            raise PlatformDocsError(
                f"{pid} cannot set accepted_release=true while pending_release_gates remain"
            )
        if status == "accepted_release" and not accepted:
            raise PlatformDocsError(f"{pid} status is accepted_release but accepted_release=false")
        if status != "accepted_release" and accepted:
            raise PlatformDocsError(
                f"{pid} cannot set accepted_release=true while distribution_status={status!r}"
            )
        docs = _require_str_list(
            plat.get("primary_evidence_docs"),
            f"{pid}.primary_evidence_docs",
            allow_empty=(status == "out_of_scope"),
        )
        for doc_rel in docs:
            doc_path = _resolve_repo_path(root, doc_rel)
            if not doc_path.is_file():
                raise PlatformDocsError(f"{pid} primary evidence doc does not exist: {doc_rel}")
        platforms_by_id[pid] = plat

    if tuple(platforms_by_id) != REQUIRED_PLATFORM_IDS:
        raise PlatformDocsError(
            f"platforms must list {REQUIRED_PLATFORM_IDS} in canonical order, "
            f"got {tuple(platforms_by_id)}"
        )

    for eid, engine in engines_by_id.items():
        for pid in engine["platforms"]:
            if pid not in platforms_by_id:
                raise PlatformDocsError(f"Engine {eid} references unknown platform {pid!r}")
            if eid not in platforms_by_id[pid]["engines"]:
                raise PlatformDocsError(
                    f"Platform/engine mismatch: {eid} lists {pid}, "
                    f"but {pid}.engines omits {eid}"
                )

    return data


def render_platform_markdown(data: dict[str, Any]) -> str:
    lines: list[str] = [
        "# Platform and engine capability status",
        "",
        "<!-- Generated from PLATFORM_STATUS.json by scripts/check_platform_docs.py; checked by CI. -->",
        "",
        f"Last synchronized: `{data['synchronized_on']}`",
        "",
        "Ankora separates **implementation**, **offline packaging**, **engineering evidence**, and",
        "**distribution status** so capabilities implemented in source are neither hidden behind",
        "outdated prose nor overstated as bare-metal public releases before their final gates close.",
        "Frozen scientific benchmark boundaries remain governed separately by",
        "[`VALIDATION_STATUS.md`](../validation/VALIDATION_STATUS.md).",
        "",
        "## Platform matrix",
        "",
        "| Platform | Distribution status | Desktop shell & CI | Implemented workflow | Offline packaging | Engineering evidence | Pending release gates |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for plat in data["platforms"]:
        gates_text = "; ".join(plat["pending_release_gates"])
        shell_ci = f"{plat['desktop_shell']} · CI: `{plat['ci_lane']}`"
        lines.append(
            f"| **{plat['label']}** | `{plat['distribution_status']}` | {shell_ci} | "
            f"{plat['implemented_workflow']} | {plat['offline_packaging']} | "
            f"{plat['engineering_evidence']} | {gates_text} |"
        )

    lines.extend(
        [
            "",
            "### Primary platform evidence",
            "",
        ]
    )
    for plat in data["platforms"]:
        if not plat["primary_evidence_docs"]:
            continue
        links = ", ".join(
            f"[`{PurePosixPath(doc).name}`](../../{doc})"
            if not doc.startswith("docs/")
            else f"[`{PurePosixPath(doc).name}`](../{PurePosixPath(doc).relative_to('docs')})"
            for doc in plat["primary_evidence_docs"]
        )
        lines.append(f"- **{plat['label']} (`{plat['distribution_status']}`):** {links}")

    lines.extend(
        [
            "",
            "## Docking engines and scoring boundaries",
            "",
            "| Engine | Platforms | Execution modes | Primary ranking metric | Result model | Cross-engine comparison boundary |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    plat_labels = {p["platform_id"]: p["label"] for p in data["platforms"]}
    for eng in data["engines"]:
        plats = ", ".join(plat_labels[pid] for pid in eng["platforms"])
        modes = "<br>".join(eng["execution_modes"])
        lines.append(
            f"| **{eng['label']} `{eng['version']}`** | {plats} | {modes} | "
            f"{eng['primary_ranking_metric']} | {eng['result_model']} | "
            f"{eng['cross_engine_rank_comparison']} |"
        )

    lines.extend(["", "### Scientific notes per engine", ""])
    for eng in data["engines"]:
        lines.append(f"- **{eng['label']} `{eng['version']}`:** {eng['scientific_notes']}")
    lines.append("")
    return "\n".join(lines)


def check_markdown_links_and_paths(
    root: Path, doc_rel: PurePosixPath, *, require_links: bool = True
) -> set[Path]:
    doc_path = _resolve_repo_path(root, str(doc_rel))
    if not doc_path.is_file():
        raise PlatformDocsError(f"Required documentation file is missing: {doc_rel}")
    content = doc_path.read_text(encoding="utf-8")
    if WINDOWS_ABSOLUTE_PATH.search(content) or POSIX_PERSONAL_PATH.search(content):
        raise PlatformDocsError(f"Personal or Windows absolute path found in {doc_rel}")

    targets = re.findall(r"\]\(([^)\s]+)\)", content)
    targets += re.findall(r'(?:src|href)="([^"]+)"', content)
    if require_links and not targets:
        raise PlatformDocsError(f"{doc_rel} contains no links")

    resolved_targets: set[Path] = set()
    for target in targets:
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc:
            continue
        target_path = (
            (doc_path.parent / unquote(parsed.path)).resolve() if parsed.path else doc_path.resolve()
        )
        if not target_path.is_relative_to(root.resolve()):
            raise PlatformDocsError(f"Link in {doc_rel} escapes repository: {target}")
        if not target_path.exists():
            raise PlatformDocsError(f"Broken relative link in {doc_rel}: {target}")
        resolved_targets.add(target_path)
        if parsed.fragment and target_path.is_file() and target_path.suffix == ".md":
            headings = _headings(target_path.read_text(encoding="utf-8"))
            if parsed.fragment not in headings:
                raise PlatformDocsError(
                    f"Broken heading fragment in {doc_rel}: {target} "
                    f"(available: {sorted(headings)[:8]}...)"
                )
    return resolved_targets


def check_validation_index_completeness(root: Path) -> int:
    validation_dir = _resolve_repo_path(root, "docs/validation")
    index_path = _resolve_repo_path(root, str(VALIDATION_INDEX_PATH))
    linked_paths = check_markdown_links_and_paths(root, VALIDATION_INDEX_PATH)

    expected_md_files = {
        path.resolve()
        for path in list(validation_dir.glob("*.md"))
        + list((validation_dir / "reference_cases").glob("*.md"))
        if path.resolve() != index_path.resolve()
    }
    missing = sorted(
        path.relative_to(root.resolve()).as_posix() for path in (expected_md_files - linked_paths)
    )
    if missing:
        raise PlatformDocsError(
            f"docs/validation/INDEX.md omits {len(missing)} validation record(s): {missing[:10]}"
        )
    return len(expected_md_files)


def verify_all(root: Path, *, write: bool = False) -> tuple[int, int]:
    root = root.resolve()
    data = load_and_validate_platform_status(root)
    expected_md = render_platform_markdown(data)
    md_path = _resolve_repo_path(root, str(PLATFORM_MD_PATH))
    if write:
        md_path.write_text(expected_md, encoding="utf-8")
    else:
        if not md_path.is_file():
            raise PlatformDocsError(f"Missing generated file: {PLATFORM_MD_PATH}")
        actual_md = md_path.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip() + "\n"
        if actual_md != expected_md:
            raise PlatformDocsError(
                f"{PLATFORM_MD_PATH} is out of sync with {PLATFORM_JSON_PATH}; "
                "run `python scripts/check_platform_docs.py --write`."
            )

    for doc_rel in CORE_LINK_CHECKED_DOCS:
        check_markdown_links_and_paths(
            root, doc_rel, require_links=(doc_rel in {PLATFORM_MD_PATH, DOCS_PORTAL_PATH})
        )
    indexed_count = check_validation_index_completeness(root)
    return len(data["platforms"]), indexed_count


def main() -> int:
    args = _arguments()
    try:
        platforms_count, indexed_count = verify_all(args.root, write=args.write)
    except PlatformDocsError as exc:
        print(f"Platform documentation check failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"Platform documentation is synchronized: {platforms_count} platforms verified, "
        f"{indexed_count} validation records indexed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
