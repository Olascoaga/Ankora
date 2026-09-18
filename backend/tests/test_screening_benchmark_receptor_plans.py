"""Synthetic contracts for the pre-result benchmark receptor plans."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import gemmi
import pytest

from ankora_backend.validation.screening_benchmark_receptor_plans import (
    ScreeningBenchmarkReceptorPlanError,
    build_receptor_plan_manifest,
    serialize_receptor_plan_manifest,
    verify_receptor_plan_manifest,
)


def _canonical_hash(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _add_atom(
    residue: gemmi.Residue,
    *,
    name: str,
    element: str,
    x: float,
    y: float,
    z: float,
    altloc: str = "",
) -> None:
    atom = gemmi.Atom()
    atom.name = name
    atom.element = gemmi.Element(element)
    atom.pos = gemmi.Position(x, y, z)
    if altloc:
        atom.altloc = altloc
        atom.occ = 0.5
    residue.add_atom(atom)


def _residue(name: str, number: int, het_flag: str = "A") -> gemmi.Residue:
    residue = gemmi.Residue()
    residue.name = name
    residue.seqid = gemmi.SeqId(number, " ")
    residue.het_flag = het_flag
    return residue


def _official_pdb(pdb_id: str) -> bytes:
    structure = gemmi.Structure()
    structure.name = pdb_id.upper()
    model = gemmi.Model(1)
    chain = gemmi.Chain("A")

    ser = _residue("SER", 1)
    _add_atom(ser, name="N", element="N", x=0.0, y=0.0, z=0.0)
    _add_atom(ser, name="CA", element="C", x=1.0, y=0.0, z=0.0)
    _add_atom(ser, name="C", element="C", x=2.0, y=0.0, z=0.0)
    _add_atom(ser, name="O", element="O", x=3.0, y=0.0, z=0.0)
    _add_atom(ser, name="OG", element="O", x=1.0, y=1.0, z=0.0, altloc="A")
    _add_atom(ser, name="OG", element="O", x=1.0, y=-1.0, z=0.0, altloc="B")
    chain.add_residue(ser)

    glu = _residue("GLU", 2)
    _add_atom(glu, name="N", element="N", x=4.0, y=0.0, z=0.0)
    _add_atom(glu, name="CA", element="C", x=5.0, y=0.0, z=0.0)
    _add_atom(glu, name="C", element="C", x=6.0, y=0.0, z=0.0)
    _add_atom(glu, name="O", element="O", x=7.0, y=0.0, z=0.0)
    _add_atom(glu, name="CB", element="C", x=5.0, y=1.0, z=0.0)
    chain.add_residue(glu)

    ligand = _residue("LIG", 900, "H")
    _add_atom(ligand, name="C1", element="C", x=10.0, y=0.0, z=0.0)
    chain.add_residue(ligand)
    zinc = _residue("ZN", 901, "H")
    _add_atom(zinc, name="ZN", element="Zn", x=8.0, y=0.0, z=0.0)
    chain.add_residue(zinc)
    water = _residue("HOH", 902, "H")
    _add_atom(water, name="O", element="O", x=9.0, y=1.0, z=0.0, altloc="A")
    _add_atom(water, name="O", element="O", x=9.0, y=-1.0, z=0.0, altloc="B")
    chain.add_residue(water)
    model.add_chain(chain)

    other = gemmi.Chain("B")
    ala = _residue("ALA", 1)
    _add_atom(ala, name="CA", element="C", x=20.0, y=0.0, z=0.0)
    other.add_residue(ala)
    model.add_chain(other)
    structure.add_model(model)
    remarks = (
        "REMARK 465 ALA A 3\n"
        "REMARK 470 GLU A 2 CG CD OE1 OE2\n"
    )
    return (remarks + structure.make_pdb_string()).encode("utf-8")


def _source_receptor_mol2(*, ambiguous_altloc: bool = False) -> bytes:
    atoms = [
        ("N", 0.0, 0.0, 0.0, "N", "SER1"),
        ("CA", 1.0, 0.0, 0.0, "C", "SER1"),
        ("C", 2.0, 0.0, 0.0, "C", "SER1"),
        ("O", 3.0, 0.0, 0.0, "O", "SER1"),
        ("OG", 1.0, 1.0, 0.0, "O", "SER1"),
        ("N", 4.0, 0.0, 0.0, "N", "GLU2"),
        ("CA", 5.0, 0.0, 0.0, "C", "GLU2"),
        ("C", 6.0, 0.0, 0.0, "C", "GLU2"),
        ("O", 7.0, 0.0, 0.0, "O", "GLU2"),
        ("CB", 5.0, 1.0, 0.0, "C", "GLU2"),
    ]
    if ambiguous_altloc:
        atoms.append(("OG2", 1.0, -1.0, 0.0, "O", "SER1"))
    rows = [
        "@<TRIPOS>MOLECULE",
        "SYNTHETIC_RECEPTOR",
        f"{len(atoms)} 0 0 0 0",
        "PROTEIN",
        "NO_CHARGES",
        "",
        "@<TRIPOS>ATOM",
    ]
    rows.extend(
        f"{index} {name} {x:.4f} {y:.4f} {z:.4f} {element}.3 1 {residue} 0.0"
        for index, (name, x, y, z, element, residue) in enumerate(atoms, start=1)
    )
    rows.append("@<TRIPOS>BOND")
    return ("\n".join(rows) + "\n").encode("utf-8")


def _add_member(
    source: tarfile.TarFile, path: str, content: bytes
) -> dict[str, object]:
    info = tarfile.TarInfo(path)
    info.size = len(content)
    source.addfile(info, io.BytesIO(content))
    return {
        "path": path,
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _fixture(
    tmp_path: Path, *, ambiguous_altloc: bool = False
) -> tuple[Path, Path, Path, Path]:
    archive = tmp_path / "synthetic-receptors.tar.gz"
    structures_dir = tmp_path / "structures"
    structures_dir.mkdir()
    identities: dict[str, dict[str, object]] = {}
    with tarfile.open(archive, mode="w:gz") as source:
        for pdb_id in ("1aaa", "2bbb"):
            receptor = _source_receptor_mol2(ambiguous_altloc=ambiguous_altloc)
            identities[pdb_id] = _add_member(
                source, f"synthetic/{pdb_id}_protein.mol2", receptor
            )
            (structures_dir / f"{pdb_id}.pdb").write_bytes(_official_pdb(pdb_id))

    targets: list[dict[str, object]] = []
    target: dict[str, object] = {"target_id": "SYNTHETIC_TARGET"}
    for role, pdb_id in (("primary_template", "1aaa"), ("alternate_template", "2bbb")):
        path = structures_dir / f"{pdb_id}.pdb"
        target[role] = {
            "role": role.removesuffix("_template"),
            "pdb_id": pdb_id,
            "source_receptor": identities[pdb_id],
            "source_receptor_frame_evidence": {
                "matched_author_chain_ids": ["A"]
            },
            "source_ligand_frame_evidence": {
                "matched_official_residue": {
                    "author_chain_id": "A",
                    "residue_name": "LIG",
                    "author_sequence_number": 900,
                    "insertion_code": "",
                }
            },
            "official_structure": {
                "filename": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "source_uri": f"https://example.invalid/{pdb_id}.pdb",
            },
        }
    targets.append(target)
    structure_manifest: dict[str, object] = {
        "schema_version": 1,
        "protocol_id": "SYNTHETIC_RECEPTOR_PLAN_V1",
        "targets": targets,
    }
    structure_manifest["manifest_sha256"] = _canonical_hash(structure_manifest)
    structure_manifest_path = tmp_path / "structures.json"
    structure_manifest_path.write_text(
        json.dumps(structure_manifest), encoding="utf-8"
    )
    return archive, structure_manifest_path, structures_dir, tmp_path / "plans.json"


def test_receptor_plan_freezes_explicit_source_aligned_decisions(
    tmp_path: Path,
) -> None:
    archive, structures_manifest, structures, plan_path = _fixture(tmp_path)

    manifest = build_receptor_plan_manifest(
        archive=archive,
        structure_manifest_path=structures_manifest,
        structures_dir=structures,
        frozen_on="2026-09-17",
    )
    plan_path.write_text(serialize_receptor_plan_manifest(manifest), encoding="utf-8")

    primary = manifest["targets"][0]["primary_template"]
    request = primary["preparation_request"]
    assert request["selected_chains"] == ["A"]
    assert request["water_action"] == "remove"
    assert request["component_decisions"] == [
        {"component_id": "ligand|A|LIG|900|", "action": "remove"},
        {"component_id": "metal|A|ZN|901|", "action": "keep"},
    ]
    decisions = {item["issue_id"]: item for item in request["issue_decisions"]}
    assert decisions["alternate_location|A|SER|1|"] == {
        "issue_id": "alternate_location|A|SER|1|",
        "action": "repair",
        "selected_altloc": "A",
    }
    assert decisions["missing_atoms|A|GLU|2|"]["action"] == "repair"
    assert decisions["missing_residue|A|ALA|3|"]["action"] == "leave"
    assert decisions["alternate_location|A|HOH|902|"]["action"] == "remove"
    assert request["relaxation"]["enabled"] is True
    assert request["protonation"]["authorized_terminal_heavy_atom_additions"] == [
        {
            "chain_id": "A",
            "residue_name": "GLU",
            "sequence_number": 2,
            "insertion_code": "",
            "atom_name": "OXT",
        }
    ]
    assert verify_receptor_plan_manifest(
        archive=archive,
        structure_manifest_path=structures_manifest,
        structures_dir=structures,
        receptor_plan_manifest_path=plan_path,
    ) == manifest


def test_ambiguous_source_altloc_evidence_fails_closed(tmp_path: Path) -> None:
    archive, structures_manifest, structures, _plan_path = _fixture(
        tmp_path, ambiguous_altloc=True
    )

    with pytest.raises(
        ScreeningBenchmarkReceptorPlanError,
        match="no unique source-coordinate match",
    ):
        build_receptor_plan_manifest(
            archive=archive,
            structure_manifest_path=structures_manifest,
            structures_dir=structures,
            frozen_on="2026-09-17",
        )


def test_changed_official_structure_fails_before_planning(tmp_path: Path) -> None:
    archive, structures_manifest, structures, _plan_path = _fixture(tmp_path)
    with (structures / "1aaa.pdb").open("ab") as destination:
        destination.write(b"REMARK changed\n")

    with pytest.raises(ScreeningBenchmarkReceptorPlanError, match="size changed"):
        build_receptor_plan_manifest(
            archive=archive,
            structure_manifest_path=structures_manifest,
            structures_dir=structures,
            frozen_on="2026-09-17",
        )
