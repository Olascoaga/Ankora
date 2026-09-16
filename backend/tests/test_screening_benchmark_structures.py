"""Synthetic tests for official structure intake and coordinate-frame closure."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import gemmi
import pytest

from ankora_backend.validation.screening_benchmark_structures import (
    ScreeningBenchmarkStructureError,
    build_structure_manifest,
    serialize_structure_manifest,
    verify_structure_manifest,
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


def _mol2(name: str, atoms: list[tuple[str, float, float, float, str]]) -> bytes:
    rows = [
        "@<TRIPOS>MOLECULE",
        name,
        f"{len(atoms)} 0 0 0 0",
        "SMALL",
        "NO_CHARGES",
        "",
        "@<TRIPOS>ATOM",
    ]
    rows.extend(
        f"{index} {atom_name} {x:.4f} {y:.4f} {z:.4f} {element}.3 1 {name} 0.0"
        for index, (atom_name, x, y, z, element) in enumerate(atoms, start=1)
    )
    rows.append("@<TRIPOS>BOND")
    return ("\n".join(rows) + "\n").encode()


def _add_atom(
    residue: gemmi.Residue,
    *,
    name: str,
    element: str,
    x: float,
    y: float,
    z: float,
) -> None:
    atom = gemmi.Atom()
    atom.name = name
    atom.element = gemmi.Element(element)
    atom.pos = gemmi.Position(x, y, z)
    residue.add_atom(atom)


def _write_official(path: Path, pdb_id: str, *, ligand_shift: float = 0.0) -> None:
    structure = gemmi.Structure()
    structure.name = pdb_id.upper()
    model = gemmi.Model(1)
    chain = gemmi.Chain("A")
    receptor = gemmi.Residue()
    receptor.name = "ALA"
    receptor.seqid = gemmi.SeqId(1, " ")
    _add_atom(receptor, name="CA", element="C", x=0.0, y=0.0, z=0.0)
    _add_atom(receptor, name="N", element="N", x=1.0, y=0.0, z=0.0)
    _add_atom(receptor, name="O", element="O", x=0.0, y=1.0, z=0.0)
    chain.add_residue(receptor)
    ligand = gemmi.Residue()
    ligand.name = "LIG"
    ligand.seqid = gemmi.SeqId(900, " ")
    _add_atom(
        ligand,
        name="C1",
        element="C",
        x=10.0 + ligand_shift,
        y=0.0,
        z=0.0,
    )
    _add_atom(ligand, name="O1", element="O", x=11.0, y=0.0, z=0.0)
    chain.add_residue(ligand)
    model.add_chain(chain)
    structure.add_model(model)
    structure.make_mmcif_document().write_file(str(path))


def _write_fixture(
    tmp_path: Path,
    *,
    ligand_shift: float = 0.0,
) -> tuple[Path, Path, Path, Path, Path, Path]:
    archive = tmp_path / "synthetic.tar.gz"
    inputs_path = tmp_path / "inputs.json"
    templates_path = tmp_path / "templates.json"
    geometry_path = tmp_path / "geometry.json"
    structures_dir = tmp_path / "structures"
    structure_manifest_path = tmp_path / "structures.json"
    structures_dir.mkdir()
    receptor = _mol2(
        "ALA1",
        [
            ("CA", 0.0, 0.0, 0.0, "C"),
            ("N", 1.0, 0.0, 0.0, "N"),
            ("O", 0.0, 1.0, 0.0, "O"),
        ],
    )
    ligand = _mol2(
        "LIG",
        [("C1", 10.0, 0.0, 0.0, "C"), ("O1", 11.0, 0.0, 0.0, "O")],
    )
    identities: dict[str, dict[str, object]] = {}
    with tarfile.open(archive, "w:gz") as source:
        for pdb_id in ("1aaa", "2bbb"):
            identities[f"{pdb_id}_receptor"] = _add_member(
                source, f"source/TARGET/{pdb_id}_protein.mol2", receptor
            )
            identities[f"{pdb_id}_ligand"] = _add_member(
                source, f"source/TARGET/{pdb_id}_ligand.mol2", ligand
            )
            _write_official(
                structures_dir / f"{pdb_id}.cif",
                pdb_id,
                ligand_shift=ligand_shift,
            )

    inputs: dict[str, object] = {
        "schema_version": 1,
        "protocol_id": "SYNTHETIC_STRUCTURE_V1",
        "source": {
            "filename": archive.name,
            "size_bytes": archive.stat().st_size,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        },
        "targets": [{"target_id": "TARGET"}],
    }
    inputs["manifest_sha256"] = _canonical_hash(inputs)
    inputs_path.write_text(json.dumps(inputs), encoding="utf-8")

    templates: dict[str, object] = {
        "schema_version": 1,
        "protocol_id": "SYNTHETIC_STRUCTURE_V1",
        "targets": [
            {
                "target_id": "TARGET",
                "primary_template": {
                    "pdb_id": "1aaa",
                    "source_receptor": identities["1aaa_receptor"],
                    "source_ligand": identities["1aaa_ligand"],
                },
                "alternate_template": {
                    "pdb_id": "2bbb",
                    "source_receptor": identities["2bbb_receptor"],
                    "source_ligand": identities["2bbb_ligand"],
                },
            }
        ],
    }
    templates["manifest_sha256"] = _canonical_hash(templates)
    templates_path.write_text(json.dumps(templates), encoding="utf-8")

    geometry: dict[str, object] = {
        "schema_version": 1,
        "protocol_id": "SYNTHETIC_STRUCTURE_V1",
        "targets": [
            {
                "target_id": "TARGET",
                "primary_template_id": "1aaa",
                "alternate_template_id": "2bbb",
            }
        ],
    }
    geometry["manifest_sha256"] = _canonical_hash(geometry)
    geometry_path.write_text(json.dumps(geometry), encoding="utf-8")
    return (
        archive,
        inputs_path,
        templates_path,
        geometry_path,
        structures_dir,
        structure_manifest_path,
    )


def test_official_structures_reproduce_direct_coordinate_frames(tmp_path: Path) -> None:
    archive, inputs, templates, geometry, structures, manifest_path = _write_fixture(
        tmp_path
    )

    manifest = build_structure_manifest(
        archive=archive,
        input_manifest_path=inputs,
        template_manifest_path=templates,
        geometry_manifest_path=geometry,
        structures_dir=structures,
        retrieved_on="2026-09-15",
    )
    manifest_path.write_text(serialize_structure_manifest(manifest), encoding="utf-8")

    [target] = manifest["targets"]
    primary = target["primary_template"]
    assert primary["official_structure"]["filename"] == "1aaa.cif"
    assert primary["source_receptor_frame_evidence"] == {
        "source_heavy_atom_count": 3,
        "exact_element_coordinate_matches": 3,
        "exact_match_fraction": 1.0,
        "matched_coordinate_rmsd_angstrom": 0.0,
        "matched_author_chain_ids": ["A"],
        "unmatched_source_heavy_atom_count": 0,
        "unmatched_source_heavy_atoms": [],
    }
    assert primary["source_ligand_frame_evidence"]["matched_official_residue"] == {
        "author_chain_id": "A",
        "residue_name": "LIG",
        "author_sequence_number": 900,
        "insertion_code": "",
        "alternate_locations": [],
    }
    assert primary["coordinate_frame_congruent"] is True
    assert verify_structure_manifest(
        archive=archive,
        input_manifest_path=inputs,
        template_manifest_path=templates,
        geometry_manifest_path=geometry,
        structures_dir=structures,
        structure_manifest_path=manifest_path,
    ) == manifest


def test_shifted_source_ligand_frame_fails_closed(tmp_path: Path) -> None:
    archive, inputs, templates, geometry, structures, _manifest_path = _write_fixture(
        tmp_path, ligand_shift=1.0
    )

    with pytest.raises(ScreeningBenchmarkStructureError, match="every source ligand"):
        build_structure_manifest(
            archive=archive,
            input_manifest_path=inputs,
            template_manifest_path=templates,
            geometry_manifest_path=geometry,
            structures_dir=structures,
            retrieved_on="2026-09-15",
        )


def test_tampered_official_structure_fails_offline_reproduction(tmp_path: Path) -> None:
    archive, inputs, templates, geometry, structures, manifest_path = _write_fixture(
        tmp_path
    )
    manifest = build_structure_manifest(
        archive=archive,
        input_manifest_path=inputs,
        template_manifest_path=templates,
        geometry_manifest_path=geometry,
        structures_dir=structures,
        retrieved_on="2026-09-15",
    )
    manifest_path.write_text(serialize_structure_manifest(manifest), encoding="utf-8")
    with (structures / "1aaa.cif").open("a", encoding="utf-8") as destination:
        destination.write("# tampered\n")

    with pytest.raises(ScreeningBenchmarkStructureError, match="does not reproduce"):
        verify_structure_manifest(
            archive=archive,
            input_manifest_path=inputs,
            template_manifest_path=templates,
            geometry_manifest_path=geometry,
            structures_dir=structures,
            structure_manifest_path=manifest_path,
        )
