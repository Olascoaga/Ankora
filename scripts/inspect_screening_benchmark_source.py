"""Verify exact LIT-PCBA source bytes against a frozen benchmark protocol."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "src"))

def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect benchmark inputs without extracting or docking them."
    )
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def _write_create_only(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    try:
        with path.open("x", encoding="utf-8", newline="\n") as destination:
            destination.write(temporary.read_text(encoding="utf-8"))
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    from ankora_backend.validation.screening_benchmark_inputs import (
        inspect_lit_pcba_archive,
        serialize_input_manifest,
    )

    args = _arguments()
    manifest = inspect_lit_pcba_archive(archive=args.archive, spec_path=args.spec)
    document = serialize_input_manifest(manifest)
    if args.check:
        if args.manifest.read_text(encoding="utf-8") != document:
            raise RuntimeError(f"Input manifest is stale: {args.manifest}")
    else:
        _write_create_only(args.manifest, document)
    print(
        f"{manifest['protocol_id']}: {manifest['totals']['target_count']} targets, "
        f"source SHA-256 {manifest['source']['sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
