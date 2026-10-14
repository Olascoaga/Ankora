"""Synthetic mutation tests; no affinity or biological reference is invented."""

import importlib
from pathlib import Path
from types import SimpleNamespace

import gemmi
import pytest

from ankora_backend.adapters.tools.pdbfixer_worker import _atom_key, _residue_key
from ankora_backend.adapters.tools.receptor_geometry import (
    guarded_fixer,
    validate_repaired_geometry,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.receptors import ReceptorPreparationRequest


def test_legacy_request_serialization_preserves_existing_fingerprint_shape() -> None:
    request = ReceptorPreparationRequest(
        selected_chains=["A"], water_action="remove", component_decisions=[], issue_decisions=[]
    )
    assert "repair_method" not in request.model_dump(mode="json")
    assert "repair_seed" not in request.model_dump(mode="json")
    guarded = request.model_copy(update={"repair_method": "topology_guard_v3"})
    assert guarded.model_dump()["repair_method"] == "topology_guard_v3"
    assert guarded.model_dump()["repair_seed"] == 20261014


def test_worker_identity_retains_separate_insertion_code() -> None:
    residue = SimpleNamespace(
        id="100", insertionCode="A", name="ALA", chain=SimpleNamespace(id="B")
    )
    assert _residue_key(residue) == ("B", "ALA", "100", "A")
    assert _atom_key(SimpleNamespace(residue=residue, name="CB")) == ("B", "ALA", "100A", "CB")
    residue.insertionCode = " "
    assert _residue_key(residue)[3] == ""


def _template_pair(
    tmp_path: Path, insertion: str = "", residue_name: str = "ALA"
) -> tuple[Path, Path]:
    """Use pinned standard templates, not hand-authored chemical expectations."""
    pytest.importorskip("openmm")
    pdbfixer = pytest.importorskip("pdbfixer")
    from openmm import unit

    seed = tmp_path / "seed.pdb"
    seed.write_text(
        "ATOM      1  N   ALA A 100       0.000   0.000   0.000  1.00  0.00           N\nEND\n"
    )
    template = pdbfixer.PDBFixer(filename=str(seed)).templates[residue_name]
    structure = gemmi.Structure()
    model = gemmi.Model("1")
    chain = gemmi.Chain("A")
    residue = gemmi.Residue()
    residue.name = residue_name
    residue.seqid = gemmi.SeqId(100, insertion or " ")
    residue.het_flag = "A"
    for source in template.topology.atoms():
        if source.element.symbol == "H":
            continue
        atom = gemmi.Atom()
        atom.name = source.name
        atom.element = gemmi.Element(source.element.symbol)
        xyz = template.positions[source.index].value_in_unit(unit.angstrom)
        atom.pos = gemmi.Position(*xyz)
        atom.occ = 1.0
        residue.add_atom(atom)
    chain.add_residue(residue)
    model.add_chain(chain)
    structure.add_model(model)
    output = tmp_path / "complete.pdb"
    structure.write_pdb(str(output))
    for name in [atom.name for atom in structure[0][0][0]]:
        if (residue_name == "GLY" and name == "O") or (
            residue_name != "GLY" and name not in {"N", "CA", "C", "O"}
        ):
            structure[0][0][0].remove_atom(name, "\x00")
    original = tmp_path / "incomplete.pdb"
    structure.write_pdb(str(original))
    return original, output


@pytest.mark.parametrize(
    "residue_name",
    [
        "ALA",
        "ARG",
        "ASN",
        "ASP",
        "CYS",
        "GLN",
        "GLU",
        "GLY",
        "HIS",
        "ILE",
        "LEU",
        "LYS",
        "MET",
        "PHE",
        "PRO",
        "SER",
        "THR",
        "TRP",
        "TYR",
        "VAL",
    ],
)
def test_guarded_reconstruction_of_all_standard_templates(
    tmp_path: Path, residue_name: str
) -> None:
    """Synthetic native-tool regression, not proof of any biological rotamer."""
    original, reference = _template_pair(tmp_path, residue_name=residue_name)
    original_bytes = original.read_bytes()
    fixer = guarded_fixer(original)
    fixer.findMissingResidues()
    fixer.missingResidues = {}
    fixer.findMissingAtoms()
    fixer.missingTerminals = {}
    fixer.addMissingAtoms(seed=20261014)
    from openmm.app import PDBFile

    output = tmp_path / "reconstructed.pdb"
    with output.open("x") as stream:
        PDBFile.writeFile(fixer.topology, fixer.positions, stream, keepIds=True)
    validate_repaired_geometry(original, output)
    assert original.read_bytes() == original_bytes
    assert {atom.name for atom in gemmi.read_structure(str(output))[0][0][0]} == {
        atom.name for atom in gemmi.read_structure(str(reference))[0][0][0]
    }


@pytest.mark.parametrize("insertion", ["", "A"])
def test_geometry_accepts_template_completion_and_normalizes_blank_insertion(
    tmp_path: Path, insertion: str
) -> None:
    original, output = _template_pair(tmp_path, insertion)
    validate_repaired_geometry(original, output)


@pytest.mark.parametrize(
    "mutation", ["observed", "missing_bond", "extra_bond", "mirror", "stretched"]
)
def test_geometry_rejects_synthetic_mutations(tmp_path: Path, mutation: str) -> None:
    original, output = _template_pair(tmp_path)
    structure = gemmi.read_structure(str(output))
    residue = structure[0][0][0]
    cb = residue.find_atom("CB", "*")
    ca = residue.find_atom("CA", "*")
    if mutation == "observed":
        ca.pos.x += 0.1
    elif mutation == "missing_bond":
        cb.pos.x += 10.0
    elif mutation == "extra_bond":
        cb.pos = residue.find_atom("O", "*").pos + gemmi.Position(0.0, 0.0, 0.8)
    elif mutation == "stretched":
        delta = cb.pos - ca.pos
        cb.pos = ca.pos + delta * ((delta.length() + 0.3) / delta.length())
    else:
        # Reflect CB through the backbone plane, retaining its CA bond length.
        import numpy as np

        point = np.array([cb.pos.x, cb.pos.y, cb.pos.z])
        center = np.array([ca.pos.x, ca.pos.y, ca.pos.z])
        n = residue.find_atom("N", "*").pos
        c = residue.find_atom("C", "*").pos
        normal = np.cross(np.array([n.x, n.y, n.z]) - center, np.array([c.x, c.y, c.z]) - center)
        normal = normal / np.linalg.norm(normal)
        cb.pos = gemmi.Position(*(point - 2 * np.dot(point - center, normal) * normal))
    structure.write_pdb(str(output))
    with pytest.raises(AnkoraDomainError) as captured:
        validate_repaired_geometry(original, output)
    if mutation == "observed":
        assert captured.value.code == "RECEPTOR_REPAIR_OBSERVED_ATOMS_CHANGED"
    else:
        assert captured.value.code == "RECEPTOR_REPAIRED_GEOMETRY_INVALID"
        affected = captured.value.details["affected_residues"][0]
        field = {
            "missing_bond": "missing_bonds",
            "extra_bond": "unexpected_bonds",
            "mirror": "chirality_mismatch_centers",
            "stretched": "distorted_bonds",
        }[mutation]
        assert affected[field]


def test_guarded_native_repair_preserves_observed_atoms_and_retained_metal(tmp_path: Path) -> None:
    original, _ = _template_pair(tmp_path)
    structure = gemmi.read_structure(str(original))
    zinc_chain = gemmi.Chain("Z")
    residue = gemmi.Residue()
    residue.name = "ZN"
    residue.seqid = gemmi.SeqId(1, " ")
    residue.het_flag = "H"
    atom = gemmi.Atom()
    atom.name = "ZN"
    atom.element = gemmi.Element("Zn")
    atom.pos = gemmi.Position(20, 20, 20)
    residue.add_atom(atom)
    zinc_chain.add_residue(residue)
    structure[0].add_chain(zinc_chain)
    structure.write_pdb(str(original))
    fixer = guarded_fixer(original)
    fixer.findMissingResidues()
    fixer.missingResidues = {}
    fixer.findMissingAtoms()
    fixer.missingTerminals = {}
    fixer.addMissingAtoms(seed=20261014)
    from openmm.app import PDBFile

    output = tmp_path / "guarded.pdb"
    with output.open("x") as stream:
        PDBFile.writeFile(fixer.topology, fixer.positions, stream, keepIds=True)
    validate_repaired_geometry(original, output)
    assert gemmi.read_structure(str(output))[0]["Z"][0][0].element.name == "Zn"


def test_guard_refuses_an_unvalidated_pdbfixer_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = importlib.import_module("ankora_backend.adapters.tools.receptor_geometry")
    monkeypatch.setattr(module, "version", lambda _name: "synthetic-unvalidated-version")
    with pytest.raises(ValueError, match="requires PDBFixer 1.12.0"):
        guarded_fixer(tmp_path / "unused.pdb")
