"""Freeze or verify explicit receptor plans for all benchmark templates."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "src"))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze explicit chain, component, repair, protonation-review, and "
            "PDBQT receptor plans before any benchmark docking result exists."
        )
    )
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--structures", type=Path, required=True)
    parser.add_argument("--structure-manifest", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--frozen-on",
        default=datetime.now(UTC).date().isoformat(),
    )
    return parser.parse_args()


def _write_create_only(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(content)
    try:
        with path.open("xb") as destination:
            destination.write(temporary.read_bytes())
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    from ankora_backend.validation.screening_benchmark_receptor_plans import (
        build_receptor_plan_manifest,
        serialize_receptor_plan_manifest,
        verify_receptor_plan_manifest,
    )

    args = _arguments()
    if args.check:
        manifest = verify_receptor_plan_manifest(
            archive=args.archive,
            structure_manifest_path=args.structure_manifest,
            structures_dir=args.structures,
            receptor_plan_manifest_path=args.manifest,
        )
    else:
        manifest = build_receptor_plan_manifest(
            archive=args.archive,
            structure_manifest_path=args.structure_manifest,
            structures_dir=args.structures,
            frozen_on=args.frozen_on,
        )
        _write_create_only(
            args.manifest,
            serialize_receptor_plan_manifest(manifest).encode("utf-8"),
        )
    plans = manifest["plan_census"]["template_plan_count"]
    print(
        f"{manifest['protocol_id']}: {plans} explicit receptor plans; "
        f"manifest SHA-256 {manifest['manifest_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
