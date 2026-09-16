"""Acquire or verify official LIT-PCBA structures and their coordinate frames."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "src"))
MAX_MMCIF_BYTES = 20 * 1024 * 1024


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze official RCSB mmCIF identities and direct coordinate-frame "
            "evidence before receptor preparation."
        )
    )
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--templates", type=Path, required=True)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--structures-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--retrieved-on",
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


def _selected_pdb_ids(template_manifest_path: Path) -> list[str]:
    document: Any = json.loads(template_manifest_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("targets"), list):
        raise TypeError("The template manifest has no target list.")
    pdb_ids: list[str] = []
    for raw_target in document["targets"]:
        if not isinstance(raw_target, dict):
            raise TypeError("A template target is not an object.")
        for role in ("primary_template", "alternate_template"):
            template = raw_target.get(role)
            if not isinstance(template, dict) or not isinstance(template.get("pdb_id"), str):
                raise TypeError(f"A template target has no {role} PDB ID.")
            pdb_ids.append(template["pdb_id"].lower())
    if len(pdb_ids) != len(set(pdb_ids)):
        raise ValueError("Selected PDB IDs must be unique across benchmark roles.")
    return sorted(pdb_ids)


def _acquire_structures(pdb_ids: list[str], destination: Path) -> None:
    from ankora_backend.validation.screening_benchmark_structures import (
        RCSB_DOWNLOAD_URL,
    )

    destination.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=60.0, follow_redirects=False) as client:
        for pdb_id in pdb_ids:
            path = destination / f"{pdb_id}.cif"
            if path.exists():
                continue
            url = RCSB_DOWNLOAD_URL.format(pdb_id=pdb_id.upper())
            response = client.get(
                url,
                headers={"User-Agent": "Ankora-validation/0.1"},
            )
            response.raise_for_status()
            content = response.content
            if not content or len(content) > MAX_MMCIF_BYTES:
                raise ValueError(f"RCSB mmCIF for {pdb_id} has an invalid size.")
            _write_create_only(path, content)


def main() -> int:
    from ankora_backend.validation.screening_benchmark_structures import (
        build_structure_manifest,
        serialize_structure_manifest,
        verify_structure_manifest,
    )

    args = _arguments()
    if args.check:
        manifest = verify_structure_manifest(
            archive=args.archive,
            input_manifest_path=args.inputs,
            template_manifest_path=args.templates,
            geometry_manifest_path=args.geometry,
            structures_dir=args.structures_dir,
            structure_manifest_path=args.manifest,
        )
    else:
        _acquire_structures(_selected_pdb_ids(args.templates), args.structures_dir)
        manifest = build_structure_manifest(
            archive=args.archive,
            input_manifest_path=args.inputs,
            template_manifest_path=args.templates,
            geometry_manifest_path=args.geometry,
            structures_dir=args.structures_dir,
            retrieved_on=args.retrieved_on,
        )
        _write_create_only(
            args.manifest,
            serialize_structure_manifest(manifest).encode("utf-8"),
        )
    summary = ", ".join(
        f"{target['target_id']}="
        f"{target['primary_template']['pdb_id']}/"
        f"{target['alternate_template']['pdb_id']}"
        for target in manifest["targets"]
    )
    print(
        f"{manifest['protocol_id']}: {summary}; "
        f"manifest SHA-256 {manifest['manifest_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
