"""Acquire or verify a pre-result RCSB holo-template selection manifest."""

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


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Freeze resolution-ranked LIT-PCBA holo templates before docking."
    )
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--retrieved-on",
        default=datetime.now(UTC).date().isoformat(),
    )
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


def _template_ids(input_manifest_path: Path) -> list[str]:
    document: Any = json.loads(input_manifest_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("targets"), list):
        raise TypeError("The source-population manifest has no target list.")
    values: list[str] = []
    for raw_target in document["targets"]:
        if not isinstance(raw_target, dict) or not isinstance(
            raw_target.get("template_ids"), list
        ):
            raise TypeError("A source-population target has no template list.")
        for raw_id in raw_target["template_ids"]:
            if not isinstance(raw_id, str):
                raise TypeError("A source template ID is not text.")
            values.append(raw_id.upper())
    return sorted(set(values))


def _fetch_entries(ids: list[str]) -> list[object]:
    from ankora_backend.validation.screening_benchmark_templates import (
        RCSB_GRAPHQL_ENDPOINT,
        RCSB_TEMPLATE_QUERY,
    )

    with httpx.Client(timeout=60.0, follow_redirects=False) as client:
        response = client.post(
            RCSB_GRAPHQL_ENDPOINT,
            json={"query": RCSB_TEMPLATE_QUERY, "variables": {"ids": ids}},
            headers={"User-Agent": "Ankora-validation/0.1"},
        )
        response.raise_for_status()
    payload: Any = response.json()
    if not isinstance(payload, dict) or payload.get("errors"):
        raise RuntimeError(f"RCSB GraphQL returned errors: {payload!r}")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise TypeError("RCSB GraphQL response has no entry list.")
    return data["entries"]


def main() -> int:
    from ankora_backend.validation.screening_benchmark_templates import (
        build_template_manifest,
        serialize_template_manifest,
        verify_template_manifest,
    )

    args = _arguments()
    if args.check:
        manifest = verify_template_manifest(
            input_manifest_path=args.inputs,
            template_manifest_path=args.manifest,
        )
    else:
        manifest = build_template_manifest(
            input_manifest_path=args.inputs,
            rcsb_entries=_fetch_entries(_template_ids(args.inputs)),
            retrieved_on=args.retrieved_on,
        )
        _write_create_only(args.manifest, serialize_template_manifest(manifest))
    selections = ", ".join(
        f"{target['target_id']}={target['primary_template']['pdb_id']}"
        for target in manifest["targets"]
    )
    print(f"{manifest['protocol_id']}: {selections}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
