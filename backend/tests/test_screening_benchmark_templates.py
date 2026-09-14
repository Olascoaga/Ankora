"""Synthetic tests for pre-result LIT-PCBA holo-template selection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ankora_backend.validation.screening_benchmark_templates import (
    SELECTION_RULE,
    ScreeningBenchmarkTemplateError,
    build_template_manifest,
    serialize_template_manifest,
    verify_template_manifest,
)


def _canonical_hash(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _member(target: str, pdb_id: str, kind: str) -> dict[str, object]:
    return {
        "path": f"source/{target}/{pdb_id}_{kind}.mol2",
        "size_bytes": 12,
        "sha256": hashlib.sha256(f"{target}/{pdb_id}/{kind}".encode()).hexdigest(),
    }


def _write_input_manifest(path: Path) -> None:
    targets = []
    for target_id, template_ids in (
        ("TARGET_A", ["1aaa", "2bbb", "3ccc"]),
        ("TARGET_B", ["4ddd", "5eee"]),
    ):
        targets.append(
            {
                "target_id": target_id,
                "template_ids": template_ids,
                "members": [
                    _member(target_id, pdb_id, kind)
                    for pdb_id in template_ids
                    for kind in ("protein", "ligand")
                ],
            }
        )
    manifest: dict[str, object] = {
        "schema_version": 1,
        "protocol_id": "SYNTHETIC_TEMPLATE_PLAN_V1",
        "targets": targets,
        "result_status": "inputs_inspected_no_docking_executed",
    }
    manifest["manifest_sha256"] = _canonical_hash(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")


def _entry(pdb_id: str, resolution: float) -> dict[str, object]:
    return {
        "rcsb_id": pdb_id.upper(),
        "exptl": [{"method": "X-RAY DIFFRACTION"}],
        "rcsb_entry_info": {"resolution_combined": [resolution]},
        "struct": {"title": f"Synthetic holo structure {pdb_id}"},
    }


def _entries() -> list[object]:
    return [
        _entry("1aaa", 2.0),
        _entry("2bbb", 1.5),
        _entry("3ccc", 1.5),
        _entry("4ddd", 1.8),
        _entry("5eee", 2.2),
    ]


def test_best_resolution_and_pdb_id_choose_primary_and_alternate(
    tmp_path: Path,
) -> None:
    inputs = tmp_path / "inputs.json"
    manifest_path = tmp_path / "templates.json"
    _write_input_manifest(inputs)

    manifest = build_template_manifest(
        input_manifest_path=inputs,
        rcsb_entries=_entries(),
        retrieved_on="2026-01-01",
    )
    manifest_path.write_text(serialize_template_manifest(manifest), encoding="utf-8")

    assert [
        (
            target["target_id"],
            target["primary_template"]["pdb_id"],
            target["alternate_template"]["pdb_id"],
        )
        for target in manifest["targets"]
    ] == [
        ("TARGET_A", "2bbb", "3ccc"),
        ("TARGET_B", "4ddd", "5eee"),
    ]
    assert all(target["selection_rule"] == SELECTION_RULE for target in manifest["targets"])
    assert manifest["targets"][0]["primary_template"]["source_receptor"] == (
        _member("TARGET_A", "2bbb", "protein")
    )
    assert verify_template_manifest(
        input_manifest_path=inputs,
        template_manifest_path=manifest_path,
    ) == manifest


def test_missing_or_unexpected_rcsb_entries_fail_closed(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs.json"
    _write_input_manifest(inputs)

    with pytest.raises(ScreeningBenchmarkTemplateError, match="does not close"):
        build_template_manifest(
            input_manifest_path=inputs,
            rcsb_entries=_entries()[:-1],
            retrieved_on="2026-01-01",
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"exptl": [{"method": "SOLUTION NMR"}]}, "not one unambiguous X-ray"),
        ({"rcsb_entry_info": {"resolution_combined": []}}, "no single positive"),
    ],
)
def test_non_xray_or_unresolved_templates_fail_closed(
    tmp_path: Path,
    mutation: dict[str, object],
    message: str,
) -> None:
    inputs = tmp_path / "inputs.json"
    _write_input_manifest(inputs)
    entries = _entries()
    entry = dict(entries[0])
    entry.update(mutation)
    entries[0] = entry

    with pytest.raises(ScreeningBenchmarkTemplateError, match=message):
        build_template_manifest(
            input_manifest_path=inputs,
            rcsb_entries=entries,
            retrieved_on="2026-01-01",
        )


def test_tampered_source_population_manifest_is_rejected(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs.json"
    _write_input_manifest(inputs)
    document = json.loads(inputs.read_text(encoding="utf-8"))
    document["protocol_id"] = "CHANGED_AFTER_HASH"
    inputs.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ScreeningBenchmarkTemplateError, match="manifest SHA-256"):
        build_template_manifest(
            input_manifest_path=inputs,
            rcsb_entries=_entries(),
            retrieved_on="2026-01-01",
        )
