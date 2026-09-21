"""Freeze or verify the loss-preserving LIT-PCBA ligand-preparation plan."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "src"))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze every exact source parent and deterministic ETKDG/MMFF/Meeko "
            "preparation decision before any benchmark docking."
        )
    )
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
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
    from ankora_backend.validation.screening_benchmark_ligand_plan import (
        build_ligand_preparation_plan,
        serialize_ligand_preparation_plan,
        verify_ligand_preparation_plan,
    )

    args = _arguments()
    if args.check:
        manifest = verify_ligand_preparation_plan(
            args.manifest,
            archive=args.archive,
            input_manifest_path=args.inputs,
        )
    else:
        manifest = build_ligand_preparation_plan(
            archive=args.archive,
            input_manifest_path=args.inputs,
        )
        _write_create_only(
            args.manifest,
            serialize_ligand_preparation_plan(manifest),
        )
    totals = manifest["totals"]
    print(
        f"{manifest['protocol_id']}: {totals['all_parents']} exact parents frozen "
        f"({totals['active_parents']} active, {totals['inactive_parents']} inactive); "
        f"no preparation or docking executed; manifest SHA-256 "
        f"{manifest['manifest_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
