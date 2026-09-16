"""Freeze or verify pre-docking LIT-PCBA boxes and sentinels."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "src"))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Freeze co-crystal boxes and hash-selected sensitivity sentinels."
    )
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--templates", type=Path, required=True)
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
    from ankora_backend.validation.screening_benchmark_geometry import (
        build_geometry_manifest,
        serialize_geometry_manifest,
        verify_geometry_manifest,
    )

    args = _arguments()
    if args.check:
        manifest = verify_geometry_manifest(
            archive=args.archive,
            input_manifest_path=args.inputs,
            template_manifest_path=args.templates,
            geometry_manifest_path=args.manifest,
        )
    else:
        manifest = build_geometry_manifest(
            archive=args.archive,
            input_manifest_path=args.inputs,
            template_manifest_path=args.templates,
        )
        _write_create_only(args.manifest, serialize_geometry_manifest(manifest))
    boxes = ", ".join(
        f"{target['target_id']}={target['primary_template_id']}"
        for target in manifest["targets"]
    )
    print(
        f"{manifest['protocol_id']}: {boxes}; "
        f"manifest SHA-256 {manifest['manifest_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
