"""Run or verify exact TP53 histidine-tautomer preview evidence."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "src"))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--structures", type=Path)
    parser.add_argument("--structure-manifest", type=Path)
    parser.add_argument("--receptor-plans", type=Path)
    parser.add_argument("--protonation-previews", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def _required(value: Path | None, option: str) -> Path:
    if value is None:
        raise ValueError(f"{option} is required when executing verification.")
    return value


def main() -> int:
    from ankora_backend.validation.screening_benchmark_tautomer_verification import (
        run_screening_benchmark_tautomer_verification,
        verify_tautomer_verification_manifest,
        verify_tautomer_verification_spec,
    )

    args = _arguments()
    try:
        spec = verify_tautomer_verification_spec(args.spec)
        if args.check:
            manifest = verify_tautomer_verification_manifest(
                args.manifest,
                evidence_root=args.output,
                expected_spec_sha256=spec["spec_sha256"],
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
                    / "tautomer-verification"
                    / stamp
                )
            manifest = run_screening_benchmark_tautomer_verification(
                spec_path=args.spec,
                archive=_required(args.archive, "--archive"),
                structure_manifest_path=_required(
                    args.structure_manifest, "--structure-manifest"
                ),
                receptor_plan_manifest_path=_required(
                    args.receptor_plans, "--receptor-plans"
                ),
                protonation_preview_manifest_path=_required(
                    args.protonation_previews, "--protonation-previews"
                ),
                structures_dir=_required(args.structures, "--structures"),
                output_root=output,
                public_manifest_path=args.manifest,
                worker_limit=args.workers,
            )
    except (OSError, ValueError) as error:
        print(f"Tautomer verification failed: {error}", file=sys.stderr)
        return 1
    census = manifest["verification_census"]
    print(
        f"{manifest['verification_id']}: {census['completed']}/"
        f"{census['requested']} HIE candidates verified; "
        f"manifest SHA-256 {manifest['manifest_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
