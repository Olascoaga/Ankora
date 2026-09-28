"""Create or verify the preregistered LIT-PCBA primary metric manifest."""

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
            "Compute the frozen primary virtual-screening metrics without "
            "dropping failed parent compounds."
        )
    )
    parser.add_argument(
        "--primary-results",
        type=Path,
        default=REFERENCE_ROOT / f"{PROTOCOL_PREFIX}.vina-primary-results.json",
    )
    parser.add_argument(
        "--primary-plan",
        type=Path,
        default=REFERENCE_ROOT / f"{PROTOCOL_PREFIX}.vina-primary-plan.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REFERENCE_ROOT / f"{PROTOCOL_PREFIX}.vina-primary-metrics.json",
    )
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    from ankora_backend.validation.screening_benchmark_primary_metrics import (
        ScreeningBenchmarkPrimaryMetricsError,
        create_primary_metrics_manifest,
        verify_primary_metrics_manifest,
    )

    args = _arguments()
    try:
        if args.check:
            manifest = verify_primary_metrics_manifest(
                args.output,
                primary_result_path=args.primary_results,
                primary_plan_path=args.primary_plan,
            )
        else:
            manifest = create_primary_metrics_manifest(
                primary_result_path=args.primary_results,
                primary_plan_path=args.primary_plan,
                output_path=args.output,
            )
    except (OSError, ValueError, ScreeningBenchmarkPrimaryMetricsError) as error:
        print(f"Primary metric evaluation failed: {error}", file=sys.stderr)
        return 1

    estimate = manifest["estimate"]
    macro = estimate["macro_point"]
    print(
        f"{manifest['protocol_id']}: EF1%={macro['enrichment_factor']:.6f}; "
        f"BEDROC={macro['bedroc']:.6f}; ROC-AUC={macro['roc_auc']:.6f}; "
        f"PR-AUC={macro['pr_auc']:.6f}; manifest SHA-256 "
        f"{manifest['manifest_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
