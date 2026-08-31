"""Freeze one explicit validation case into deterministic JSON and Markdown."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "src"))

from ankora_backend.services.validation_evidence import (
    freeze_validation_evidence,
    load_validation_case_spec,
    render_validation_matrix,
    serialize_validation_manifest,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify exact structured evidence without running scientific tools."
    )
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if committed outputs differ; do not write files.",
    )
    return parser.parse_args()


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _check(path: Path, expected: str) -> None:
    try:
        actual = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise RuntimeError(f"Frozen output is missing: {path}") from error
    if actual != expected:
        raise RuntimeError(f"Frozen output is stale: {path}")


def main() -> int:
    args = _arguments()
    spec = load_validation_case_spec(args.spec)
    manifest = freeze_validation_evidence(spec, data_root=args.data_root)
    manifest_document = serialize_validation_manifest(manifest)
    markdown_document = render_validation_matrix(manifest)
    if args.check:
        _check(args.manifest, manifest_document)
        _check(args.markdown, markdown_document)
    else:
        _write_atomic(args.manifest, manifest_document)
        _write_atomic(args.markdown, markdown_document)
    print(
        f"{spec.case_id}: {len(spec.records)} records verified; "
        f"evidence SHA-256 {manifest['evidence_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
