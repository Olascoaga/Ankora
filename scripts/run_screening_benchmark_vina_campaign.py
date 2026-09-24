"""Execute, resume, or verify the frozen primary LIT-PCBA Vina campaign."""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "src"))

REFERENCE_ROOT = PROJECT_ROOT / "docs" / "validation" / "reference_cases"
PROTOCOL_PREFIX = "LIT_PCBA_ANKORA_VS_V1"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the exact frozen primary Vina campaign with create-only, "
            "incremental, restartable evidence."
        )
    )
    parser.add_argument(
        "--plan",
        type=Path,
        default=REFERENCE_ROOT / f"{PROTOCOL_PREFIX}.vina-primary-plan.json",
    )
    parser.add_argument("--final-receptor-evidence", type=Path, required=True)
    parser.add_argument("--ligand-preparation-evidence", type=Path, required=True)
    parser.add_argument(
        "--parser-source",
        type=Path,
        default=(
            PROJECT_ROOT
            / "backend"
            / "src"
            / "ankora_backend"
            / "adapters"
            / "engines"
            / "vina.py"
        ),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REFERENCE_ROOT / f"{PROTOCOL_PREFIX}.vina-primary-results.json",
    )
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


class _Progress:
    def __init__(self) -> None:
        self._started = time.monotonic()
        self._last_print = 0.0
        self._statuses: Counter[str] = Counter()

    def __call__(self, completed: int, total: int, status: str) -> None:
        self._statuses[status] += 1
        now = time.monotonic()
        if completed != total and completed % 25 and now - self._last_print < 15:
            return
        elapsed = max(0.001, now - self._started)
        rate = completed / elapsed
        remaining = (total - completed) / rate if rate else 0.0
        census = ", ".join(
            f"{key}={value}" for key, value in sorted(self._statuses.items())
        )
        print(
            f"[{completed}/{total}] {completed / total:.1%} · "
            f"{rate:.2f} parents/s · ETA {remaining / 60:.1f} min · {census}",
            flush=True,
        )
        self._last_print = now


def _required_output(value: Path | None) -> Path:
    if value is None:
        raise ValueError("--output is required with --check.")
    return value


def main() -> int:
    from ankora_backend.adapters.engines.vina import probe_vina
    from ankora_backend.validation.screening_benchmark_vina_execution import (
        run_screening_benchmark_vina_campaign,
        verify_vina_campaign_manifest,
    )
    from ankora_backend.validation.screening_benchmark_vina_plan import (
        verify_vina_campaign_plan,
    )

    args = _arguments()
    try:
        if args.check:
            installation = probe_vina()
            verify_vina_campaign_plan(
                args.plan,
                parser_source_path=args.parser_source,
                vina_executable_path=Path(installation.executable),
                final_receptor_evidence_root=args.final_receptor_evidence,
                ligand_preparation_evidence_root=args.ligand_preparation_evidence,
            )
            manifest = verify_vina_campaign_manifest(
                args.manifest,
                evidence_root=_required_output(args.output),
                plan_manifest_path=args.plan,
            )
        else:
            output = args.output
            if output is None:
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                output = (
                    PROJECT_ROOT
                    / ".ankora-data"
                    / "validation"
                    / PROTOCOL_PREFIX
                    / "vina-primary"
                    / stamp
                )
            manifest = run_screening_benchmark_vina_campaign(
                plan_manifest_path=args.plan,
                final_receptor_evidence_root=args.final_receptor_evidence,
                ligand_preparation_evidence_root=args.ligand_preparation_evidence,
                parser_source_path=args.parser_source,
                installation=probe_vina(),
                output_root=output,
                public_manifest_path=args.manifest,
                progress_callback=_Progress(),
            )
    except KeyboardInterrupt:
        print(
            "Vina campaign interrupted; completed evidence is preserved for resume.",
            file=sys.stderr,
        )
        return 130
    except (OSError, ValueError) as error:
        print(f"Vina campaign failed: {error}", file=sys.stderr)
        return 1

    census = manifest["campaign_census"]
    print(
        f"{manifest['protocol_id']}: {census['terminal']}/{census['requested']} "
        f"parents terminal; {census['scored']} scored; "
        f"{census['unscored_worst_tie']} retained unscored; no metrics computed; "
        f"manifest SHA-256 {manifest['manifest_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
