from pathlib import Path

import pytest

from ankora_backend.adapters.tools.pdbfixer_worker import _relax_new_atoms

pytest.importorskip("openmm", reason="real OpenMM is only installed in the ankora-dev environment")


class _FakeFixer:
    def __init__(self, topology: object, positions: object) -> None:
        self.topology = topology
        self.positions = positions


def _build_three_atom_chain(tmp_path: Path) -> tuple[_FakeFixer, set[tuple[str, str, str, str]]]:
    """Old atom0 - new atom1 - new atom2, with atom2 placed pathologically
    close to atom0 (a collapsed 1-3 angle), mirroring exactly what PDBFixer's
    naive placement plus an unconstrained declash minimization produced for
    the real ARG A:271 case (Cbeta-Cdelta collapsing to 1.33 A across Cgamma)."""
    import openmm  # type: ignore[import-not-found]
    from openmm import unit
    from openmm.app import Element, Topology  # type: ignore[import-not-found]

    topology = Topology()
    chain = topology.addChain("A")
    residue = topology.addResidue("MOL", chain, id="1")
    carbon = Element.getBySymbol("C")
    atom0 = topology.addAtom("X0", carbon, residue)
    atom1 = topology.addAtom("X1", carbon, residue)
    atom2 = topology.addAtom("X2", carbon, residue)
    topology.addBond(atom0, atom1)
    topology.addBond(atom1, atom2)

    positions = openmm.unit.Quantity(
        [
            openmm.Vec3(0.0, 0.0, 0.0),
            openmm.Vec3(0.153, 0.0, 0.0),
            openmm.Vec3(0.05, 0.05, 0.0),
        ],
        unit.nanometer,
    )

    fixer = _FakeFixer(topology, positions)
    before_keys = {("A", "MOL", "1", "X0")}
    return fixer, before_keys


def test_relax_does_not_collapse_a_1_3_angle(tmp_path: Path) -> None:
    """Regression test for the real MEEKO_CONNECTIVITY_FAILURE this produced:
    a newly placed atom two bonds away from an anchor (a 1-3 pair, like
    CB-CD across CG) must not be left overlapping that anchor after
    relaxation just because it isn't directly bonded to it."""
    fixer, before_keys = _build_three_atom_chain(tmp_path)
    output_path = tmp_path / "relaxed.pdb"

    _relax_new_atoms(
        fixer,  # type: ignore[arg-type]
        before_keys,
        restraint_force_constant_kcal_mol_a2=200.0,
        max_iterations=200,
        output_path=output_path,
    )

    from openmm.app import PDBFile

    relaxed = PDBFile(str(output_path))
    positions = relaxed.getPositions(asNumpy=False)
    atom0_position = positions[0].value_in_unit(positions[0].unit)
    atom2_position = positions[2].value_in_unit(positions[2].unit)
    displacement = (
        sum((a - b) ** 2 for a, b in zip(atom0_position, atom2_position, strict=True)) ** 0.5
    )

    assert displacement > 0.15
