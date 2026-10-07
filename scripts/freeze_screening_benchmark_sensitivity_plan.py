"""Freeze or verify the post-primary LIT-PCBA sensitivity plan."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "src"))

REFERENCE_ROOT = PROJECT_ROOT / "docs" / "validation" / "reference_cases"
PROTOCOL_PREFIX = "LIT_PCBA_ANKORA_VS_V1"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Bind the frozen one-factor sensitivity variants without executing "
            "docking or computing a sensitivity metric."
        )
    )
    parser.add_argument(
        "--spec", default=REFERENCE_ROOT / f"{PROTOCOL_PREFIX}.spec.json", type=Path
    )
    parser.add_argument(
        "--geometry",
        default=REFERENCE_ROOT / f"{PROTOCOL_PREFIX}.geometry-sentinels.json",
        type=Path,
    )
    parser.add_argument(
        "--receptors",
        default=REFERENCE_ROOT / f"{PROTOCOL_PREFIX}.final-receptors.json",
        type=Path,
    )
    parser.add_argument(
        "--primary-plan",
        default=REFERENCE_ROOT / f"{PROTOCOL_PREFIX}.vina-primary-plan.json",
        type=Path,
    )
    parser.add_argument(
        "--primary-results",
        default=REFERENCE_ROOT / f"{PROTOCOL_PREFIX}.vina-primary-results.json",
        type=Path,
    )
    parser.add_argument(
        "--primary-metrics",
        default=REFERENCE_ROOT / f"{PROTOCOL_PREFIX}.vina-primary-metrics.json",
        type=Path,
    )
    parser.add_argument("--final-receptor-evidence", type=Path)
    parser.add_argument(
        "--output",
        default=REFERENCE_ROOT / f"{PROTOCOL_PREFIX}.vina-sensitivity-plan.json",
        type=Path,
    )
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    from ankora_backend.validation.screening_benchmark_sensitivity_plan import (
        build_sensitivity_plan,
        serialize_sensitivity_plan,
        verify_sensitivity_plan,
    )

    args = _arguments()
    # Historical verification binds the pre-primary Git blobs recorded by this
    # plan, not whatever runtime implementation happens to be checked out now.
    # These files are evidence only, never imported/executed by this script.
    source_root = REFERENCE_ROOT / f"{PROTOCOL_PREFIX}.sources"
    schema_source = source_root / "ligands.py.txt"
    service_source = source_root / "ligand_microstates.py.txt"
    dependencies = {
        "spec_path": args.spec,
        "geometry_manifest_path": args.geometry,
        "final_receptor_manifest_path": args.receptors,
        "primary_plan_path": args.primary_plan,
        "primary_result_path": args.primary_results,
        "primary_metrics_path": args.primary_metrics,
        "microstate_schema_path": schema_source,
        "microstate_service_path": service_source,
        "final_receptor_evidence_root": args.final_receptor_evidence,
    }
    try:
        if args.check:
            manifest = verify_sensitivity_plan(args.output, **dependencies)
        else:
            manifest = build_sensitivity_plan(**dependencies)
            serialized = serialize_sensitivity_plan(manifest)
            if (
                args.output.exists()
                and args.output.read_text(encoding="utf-8") != serialized
            ):
                raise ValueError(
                    "The sensitivity plan already exists with different bytes."
                )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(serialized, encoding="utf-8")
    except (OSError, ValueError) as error:
        print(f"Sensitivity plan failed: {error}", file=sys.stderr)
        return 1

    print(
        f"{manifest['protocol_id']}: {len(manifest['variants'])} frozen variants; "
        f"96 chemical-state sentinels; 11,412-parent full cohort; no sensitivity "
        f"execution; manifest SHA-256 {manifest['manifest_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
