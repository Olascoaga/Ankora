"""Execute, resume, or verify frozen LIT-PCBA ligand preparation."""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "src"))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare every frozen benchmark parent with exact-state ETKDGv3, "
            "MMFF94s, and Meeko while retaining every failure as evidence."
        )
    )
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def _required(value: Path | None, option: str) -> Path:
    if value is None:
        raise ValueError(f"{option} is required when preparing benchmark ligands.")
    return value


class _Progress:
    def __init__(self) -> None:
        self._started = time.monotonic()
        self._last_print = 0.0
        self._statuses: Counter[str] = Counter()

    def __call__(self, completed: int, total: int, status: str) -> None:
        self._statuses[status] += 1
        now = time.monotonic()
        if completed != total and completed % 50 and now - self._last_print < 15:
            return
        elapsed = max(0.001, now - self._started)
        rate = completed / elapsed
        remaining = (total - completed) / rate if rate else 0.0
        census = ", ".join(
            f"{key}={value}" for key, value in sorted(self._statuses.items())
        )
        print(
            f"[{completed}/{total}] {completed / total:.1%} · {rate:.2f} parents/s · "
            f"ETA {remaining / 60:.1f} min · {census}",
            flush=True,
        )
        self._last_print = now


def main() -> int:
    from ankora_backend.validation.screening_benchmark_ligand_preparation import (
        run_screening_benchmark_ligand_preparation,
        verify_ligand_preparation_manifest,
    )

    args = _arguments()
    try:
        if args.check:
            manifest = verify_ligand_preparation_manifest(
                args.manifest,
                evidence_root=args.output,
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
                    / "LIT_PCBA_ANKORA_VS_V1"
                    / "ligand-preparation"
                    / stamp
                )
            manifest = run_screening_benchmark_ligand_preparation(
                archive=_required(args.archive, "--archive"),
                input_manifest_path=_required(args.inputs, "--inputs"),
                plan_manifest_path=args.plan,
                output_root=output,
                public_manifest_path=args.manifest,
                worker_limit=args.workers,
                progress_callback=_Progress(),
            )
    except (OSError, ValueError) as error:
        print(f"Ligand-preparation run failed: {error}", file=sys.stderr)
        return 1
    census = manifest["preparation_census"]
    print(
        f"{manifest['protocol_id']}: {census['terminal']}/{census['requested']} "
        f"parents terminal; {census['prepared']} prepared; "
        f"{census['unscored_worst_tie']} retained unscored; no docking executed; "
        f"manifest SHA-256 {manifest['manifest_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
