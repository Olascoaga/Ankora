"""Run or verify the six frozen LIT-PCBA receptor protonation previews."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "src"))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Execute six create-only structured PDB2PQR/PROPKA previews or "
            "verify their frozen path-free manifest."
        )
    )
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--structures", type=Path)
    parser.add_argument("--structure-manifest", type=Path)
    parser.add_argument("--receptor-plans", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def _required_path(value: Path | None, option: str) -> Path:
    if value is None:
        raise ValueError(f"{option} is required when executing previews.")
    return value


def main() -> int:
    from ankora_backend.validation.screening_benchmark_protonation_previews import (
        run_screening_benchmark_protonation_previews,
        verify_protonation_preview_manifest,
    )

    args = _arguments()
    try:
        if args.check:
            manifest = verify_protonation_preview_manifest(
                args.manifest,
                evidence_root=args.output,
            )
        else:
            output = args.output
            if output is None:
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                output = (
                    PROJECT_ROOT
                    / ".ankora-data"
                    / "validation"
                    / "LIT_PCBA_ANKORA_VS_V1"
                    / "protonation-previews"
                    / stamp
                )
            manifest = run_screening_benchmark_protonation_previews(
                archive=_required_path(args.archive, "--archive"),
                structure_manifest_path=_required_path(
                    args.structure_manifest, "--structure-manifest"
                ),
                receptor_plan_manifest_path=_required_path(
                    args.receptor_plans, "--receptor-plans"
                ),
                structures_dir=_required_path(args.structures, "--structures"),
                output_root=output,
                public_manifest_path=args.manifest,
                worker_limit=args.workers,
            )
    except (OSError, ValueError) as error:
        print(f"Protonation-preview run failed: {error}", file=sys.stderr)
        return 1
    census = manifest["preview_census"]
    print(
        f"{manifest['protocol_id']}: {census['completed']}/"
        f"{census['requested']} previews completed; "
        f"{census['proposal_count']} proposals; "
        f"{census['review_attention_count']} require focused review; "
        f"manifest SHA-256 {manifest['manifest_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
