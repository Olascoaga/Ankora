"""Verify the complete pre-result protonation decision review."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "src"))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--protonation-previews", type=Path, required=True)
    parser.add_argument("--tautomer-verification", type=Path, required=True)
    parser.add_argument("--require-confirmed", action="store_true")
    return parser.parse_args()


def main() -> int:
    from ankora_backend.validation.screening_benchmark_protonation_decisions import (
        ScreeningBenchmarkProtonationDecisionError,
        verify_protonation_decision_review,
    )

    args = _arguments()
    try:
        review = verify_protonation_decision_review(
            args.review,
            preview_manifest_path=args.protonation_previews,
            tautomer_manifest_path=args.tautomer_verification,
            require_scientist_confirmation=args.require_confirmed,
        )
    except (OSError, ScreeningBenchmarkProtonationDecisionError) as error:
        print(f"Protonation decision review failed: {error}", file=sys.stderr)
        return 1
    census = review["decision_census"]
    status = review["scientist_confirmation"]["status"]
    print(
        f"{review['review_id']}: {census['source_proposals']} proposals covered; "
        f"{census['explicit_overrides']} overrides; scientist review {status}; "
        f"SHA-256 {review['review_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
