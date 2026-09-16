"""Synthetic tests for pre-docking box and sentinel closure."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from ankora_backend.validation.screening_benchmark_geometry import (
    SENTINELS_PER_CLASS_PER_TARGET,
    ScreeningBenchmarkGeometryError,
    build_geometry_manifest,
    serialize_geometry_manifest,
    verify_geometry_manifest,
)


def _canonical_hash(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _add_member(source: tarfile.TarFile, path: str, content: bytes) -> dict[str, object]:
    info = tarfile.TarInfo(path)
    info.size = len(content)
    source.addfile(info, io.BytesIO(content))
    return {
        "path": path,
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _smiles_rows(prefix: str, start: int, count: int) -> bytes:
    rows = [
        f"{'C' * index} {prefix}-{index}" for index in range(start, start + count)
    ]
    return ("\n".join(rows) + "\n").encode()


def _mol2() -> bytes:
    return b"""@<TRIPOS>MOLECULE
synthetic
3 0 0 0 0
SMALL
NO_CHARGES

@<TRIPOS>ATOM
1 C1 -1.0000 2.0000 3.0000 C.3 1 LIG 0.0
2 O1 5.0000 -4.0000 7.0000 O.2 1 LIG 0.0
3 H1 6.0000 0.0000 1.0000 H 1 LIG 0.0
@<TRIPOS>BOND
"""


def _write_fixture(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path]:
    archive = tmp_path / "synthetic.tar.gz"
    input_path = tmp_path / "inputs.json"
    template_path = tmp_path / "templates.json"
    geometry_path = tmp_path / "geometry.json"
    member_identities: list[dict[str, object]] = []
    ligand_identities: dict[str, dict[str, object]] = {}
    with tarfile.open(archive, "w:gz") as source:
        for filename, content in (
            ("active_T.smi", _smiles_rows("AT", 1, 8)),
            ("active_V.smi", _smiles_rows("AV", 9, 8)),
            ("inactive_T.smi", _smiles_rows("IT", 17, 8)),
            ("inactive_V.smi", _smiles_rows("IV", 25, 8)),
        ):
            member_identities.append(
                _add_member(source, f"source/TARGET/{filename}", content)
            )
        for pdb_id in ("1aaa", "2bbb"):
            receptor = _add_member(
                source,
                f"source/TARGET/{pdb_id}_protein.mol2",
                b"synthetic receptor\n",
            )
            ligand = _add_member(
                source,
                f"source/TARGET/{pdb_id}_ligand.mol2",
                _mol2(),
            )
            member_identities.extend((receptor, ligand))
            ligand_identities[pdb_id] = ligand
    source_identity = {
        "filename": archive.name,
        "size_bytes": archive.stat().st_size,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    }
    inputs: dict[str, object] = {
        "schema_version": 1,
        "protocol_id": "SYNTHETIC_GEOMETRY_V1",
        "source": source_identity,
        "targets": [
            {
                "target_id": "TARGET",
                "source_directory": "TARGET",
                "source_census": {"active_rows": 16, "inactive_rows": 16},
                "members": member_identities,
            }
        ],
        "result_status": "inputs_inspected_no_docking_executed",
    }
    inputs["manifest_sha256"] = _canonical_hash(inputs)
    input_path.write_text(json.dumps(inputs), encoding="utf-8")
    templates: dict[str, object] = {
        "schema_version": 1,
        "protocol_id": "SYNTHETIC_GEOMETRY_V1",
        "targets": [
            {
                "target_id": "TARGET",
                "primary_template": {
                    "pdb_id": "1aaa",
                    "source_ligand": ligand_identities["1aaa"],
                },
                "alternate_template": {
                    "pdb_id": "2bbb",
                    "source_ligand": ligand_identities["2bbb"],
                },
            }
        ],
        "result_status": "templates_selected_no_docking_executed",
    }
    templates["manifest_sha256"] = _canonical_hash(templates)
    template_path.write_text(json.dumps(templates), encoding="utf-8")
    return archive, input_path, template_path, geometry_path


def test_geometry_and_sentinels_reproduce_from_exact_source(tmp_path: Path) -> None:
    archive, inputs, templates, geometry_path = _write_fixture(tmp_path)

    manifest = build_geometry_manifest(
        archive=archive,
        input_manifest_path=inputs,
        template_manifest_path=templates,
    )
    geometry_path.write_text(serialize_geometry_manifest(manifest), encoding="utf-8")

    [target] = manifest["targets"]
    assert target["primary_template_id"] == "1aaa"
    assert target["alternate_template_id"] == "2bbb"
    assert target["co_crystal_box"] == {
        "source_ligand": json.loads(templates.read_text())["targets"][0][
            "primary_template"
        ]["source_ligand"],
        "atom_count": 3,
        "heavy_atom_count": 2,
        "explicit_hydrogen_count": 1,
        "coordinate_bounds_angstrom": {
            "min_x": -1.0,
            "max_x": 5.0,
            "min_y": -4.0,
            "max_y": 2.0,
            "min_z": 3.0,
            "max_z": 7.0,
        },
        "primary_box_angstrom": {
            "center_x": 2.0,
            "center_y": -1.0,
            "center_z": 5.0,
            "size_x": 16.0,
            "size_y": 16.0,
            "size_z": 14.0,
        },
        "expanded_sensitivity_box_angstrom": {
            "center_x": 2.0,
            "center_y": -1.0,
            "center_z": 5.0,
            "size_x": 22.0,
            "size_y": 22.0,
            "size_z": 20.0,
        },
    }
    sentinels = target["chemical_state_sentinels"]
    assert len(sentinels["active"]) == SENTINELS_PER_CLASS_PER_TARGET
    assert len(sentinels["inactive"]) == SENTINELS_PER_CLASS_PER_TARGET
    assert sentinels["total"] == 2 * SENTINELS_PER_CLASS_PER_TARGET
    assert [item["selection_rank"] for item in sentinels["active"]] == list(
        range(1, SENTINELS_PER_CLASS_PER_TARGET + 1)
    )
    assert verify_geometry_manifest(
        archive=archive,
        input_manifest_path=inputs,
        template_manifest_path=templates,
        geometry_manifest_path=geometry_path,
    ) == manifest


def test_tampered_source_member_fails_closed(tmp_path: Path) -> None:
    archive, inputs, templates, _geometry_path = _write_fixture(tmp_path)
    template_document = json.loads(templates.read_text())
    template_document["targets"][0]["primary_template"]["source_ligand"][
        "sha256"
    ] = "0" * 64
    template_document["manifest_sha256"] = _canonical_hash(
        {key: value for key, value in template_document.items() if key != "manifest_sha256"}
    )
    templates.write_text(json.dumps(template_document), encoding="utf-8")

    with pytest.raises(ScreeningBenchmarkGeometryError, match="SHA-256 changed"):
        build_geometry_manifest(
            archive=archive,
            input_manifest_path=inputs,
            template_manifest_path=templates,
        )


def test_too_few_parents_for_a_class_fails_closed(tmp_path: Path) -> None:
    archive, inputs, templates, _geometry_path = _write_fixture(tmp_path)
    input_document = json.loads(inputs.read_text())
    input_document["targets"][0]["source_census"]["active_rows"] = 15
    input_document["manifest_sha256"] = _canonical_hash(
        {key: value for key, value in input_document.items() if key != "manifest_sha256"}
    )
    inputs.write_text(json.dumps(input_document), encoding="utf-8")

    with pytest.raises(ScreeningBenchmarkGeometryError, match="active census changed"):
        build_geometry_manifest(
            archive=archive,
            input_manifest_path=inputs,
            template_manifest_path=templates,
        )
