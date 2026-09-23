"""Freeze or verify the exact primary LIT-PCBA AutoDock Vina campaign plan."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "src"))

REFERENCE_ROOT = PROJECT_ROOT / "docs" / "validation" / "reference_cases"
PROTOCOL_PREFIX = "LIT_PCBA_ANKORA_VS_V1"


def _arguments() -> argparse.Namespace:
    available_threads = max(1, (os.cpu_count() or 1) - 1)
    default_workers = min(64, available_threads)
    parser = argparse.ArgumentParser(
        description=(
            "Bind every frozen benchmark parent to its exact Vina 1.2.7 inputs "
            "without executing docking or reading scores."
        )
    )
    parser.add_argument(
        "--spec",
        type=Path,
        default=REFERENCE_ROOT / f"{PROTOCOL_PREFIX}.spec.json",
    )
    parser.add_argument(
        "--geometry",
        type=Path,
        default=REFERENCE_ROOT / f"{PROTOCOL_PREFIX}.geometry-sentinels.json",
    )
    parser.add_argument(
        "--receptors",
        type=Path,
        default=REFERENCE_ROOT / f"{PROTOCOL_PREFIX}.final-receptors.json",
    )
    parser.add_argument(
        "--ligands",
        type=Path,
        default=REFERENCE_ROOT / f"{PROTOCOL_PREFIX}.ligand-preparation.json",
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
    parser.add_argument(
        "--output",
        type=Path,
        default=REFERENCE_ROOT / f"{PROTOCOL_PREFIX}.vina-primary-plan.json",
    )
    parser.add_argument("--total-cpu-threads", type=int, default=available_threads)
    parser.add_argument("--parallel-ligands", type=int, default=default_workers)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    from ankora_backend.adapters.engines.vina import probe_vina
    from ankora_backend.validation.screening_benchmark_vina_plan import (
        build_vina_campaign_plan,
        serialize_vina_campaign_plan,
        verify_vina_campaign_plan,
    )

    args = _arguments()
    try:
        installation = probe_vina()
        executable = Path(installation.executable)
        if args.check:
            manifest = verify_vina_campaign_plan(
                args.output,
                spec_path=args.spec,
                geometry_manifest_path=args.geometry,
                final_receptor_manifest_path=args.receptors,
                ligand_preparation_manifest_path=args.ligands,
                parser_source_path=args.parser_source,
                vina_executable_path=executable,
                final_receptor_evidence_root=args.final_receptor_evidence,
                ligand_preparation_evidence_root=args.ligand_preparation_evidence,
            )
        else:
            manifest = build_vina_campaign_plan(
                spec_path=args.spec,
                geometry_manifest_path=args.geometry,
                final_receptor_manifest_path=args.receptors,
                ligand_preparation_manifest_path=args.ligands,
                final_receptor_evidence_root=args.final_receptor_evidence,
                ligand_preparation_evidence_root=args.ligand_preparation_evidence,
                installation=installation,
                vina_executable_path=executable,
                parser_source_path=args.parser_source,
                total_cpu_threads=args.total_cpu_threads,
                parallel_ligands=args.parallel_ligands,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                serialize_vina_campaign_plan(manifest), encoding="utf-8"
            )
    except (OSError, ValueError) as error:
        print(f"Vina campaign plan failed: {error}", file=sys.stderr)
        return 1

    totals = manifest["totals"]
    print(
        f"{manifest['protocol_id']}: {totals['target_count']} target campaigns; "
        f"{totals['prepared_for_docking']}/{totals['source_parents']} ligand "
        f"PDBQTs ready; {totals['retained_unscored_worst_tie']} retained "
        f"unscored; no docking executed; manifest SHA-256 "
        f"{manifest['manifest_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
