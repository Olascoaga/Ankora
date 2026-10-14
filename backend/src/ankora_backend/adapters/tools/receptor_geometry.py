"""Versioned repair geometry guard, separate from full protein minimization.

The pinned PDBFixer model owns bonds/angles/torsions and freezes observed atoms.
Only its bounded soft steric wall is replaced, preserving its native selected
new-atom interaction group and handling of retained, unparameterized components.
"""

from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from typing import Any

import gemmi

from ankora_backend.domain.errors import AnkoraDomainError


def guarded_fixer(input_path: Path) -> Any:
    # PDBFixer's private force-field boundary is intentionally pinned. Never
    # silently fall back to a different worker/library on an incompatible stack.
    if version("pdbfixer") != "1.12.0":
        raise ValueError("topology_guard_v3 requires PDBFixer 1.12.0")
    import openmm
    from pdbfixer import PDBFixer

    class GuardedFixer(PDBFixer):  # type: ignore[misc]
        def _createForceField(self, topology: Any, water: bool) -> Any:
            if water:
                raise ValueError("The repair guard never performs solvated preparation")
            field = super()._createForceField(topology, water)

            class GuardedField:
                def createSystem(self, model: Any) -> Any:
                    system = field.createSystem(model)
                    original_keys = {
                        (
                            atom.residue.chain.id,
                            atom.residue.id,
                            atom.residue.insertionCode.strip(),
                            atom.name,
                        )
                        for atom in self_outer.topology.atoms()
                    }
                    rebuilt = {
                        atom.index
                        for atom in model.atoms()
                        if (
                            atom.residue.chain.id,
                            atom.residue.id,
                            atom.residue.insertionCode.strip(),
                            atom.name,
                        )
                        not in original_keys
                    }
                    for force in system.getForces():
                        if isinstance(force, openmm.HarmonicBondForce):
                            for i in range(force.getNumBonds()):
                                from openmm import unit

                                a, b, distance, strength = force.getBondParameters(i)
                                if a in rebuilt or b in rebuilt:
                                    strength_unit = unit.kilojoule_per_mole / unit.nanometer**2
                                    force.setBondParameters(
                                        i,
                                        a,
                                        b,
                                        distance,
                                        max(strength.value_in_unit(strength_unit), 300000.0)
                                        * strength_unit,
                                    )
                    indices = [
                        i
                        for i, force in enumerate(system.getForces())
                        if isinstance(force, openmm.CustomNonbondedForce)
                    ]
                    if len(indices) != 1:
                        raise ValueError("PDBFixer soft force-field boundary changed")
                    system.removeForce(indices[0])
                    wall = openmm.CustomNonbondedForce("C*(0.22/r)^12")
                    wall.addGlobalParameter("C", 1.0)
                    for _ in range(system.getNumParticles()):
                        wall.addParticle([])
                    wall.createExclusionsFromBonds(
                        [(a.index, b.index) for a, b in model.bonds()], 1
                    )
                    system.addForce(wall)
                    return system

            self_outer = self
            return GuardedField()

    fixer = GuardedFixer(filename=str(input_path))
    fixer.platform = openmm.Platform.getPlatformByName("Reference")
    return fixer


def validate_repaired_geometry(
    input_path: Path, output_path: Path, *, observed_tolerance_angstrom: float = 0.002
) -> None:
    """Reject extra/missing heavy bonds and rebuilt template chirality errors.

    This QC is not a full force-field or biological validation. Original heavy
    coordinates/identities must survive exactly at written PDB precision.
    """
    from openmm.app import PDBFile

    # Keep the optional native scientific API behind a dynamic boundary, as in
    # the Meeko diagnostic adapter (vendor stubs vary with the Conda stack).
    Chem = import_module("rdkit.Chem")
    rdDetermineBonds = import_module("rdkit.Chem.rdDetermineBonds")

    def atoms_by_identity(path: Path) -> dict[tuple[str, str, int | None, str, str], gemmi.Atom]:
        return {
            (
                chain.name,
                residue.name,
                residue.seqid.num,
                residue.seqid.icode.strip(),
                atom.name,
            ): atom
            for chain in gemmi.read_structure(str(path))[0]
            for residue in chain
            for atom in residue
            if atom.element.name != "H"
        }

    before = atoms_by_identity(input_path)
    after = atoms_by_identity(output_path)
    changed = [
        list(key)
        for key, atom in before.items()
        if key not in after or atom.pos.dist(after[key].pos) > observed_tolerance_angstrom
    ]
    if changed:
        raise AnkoraDomainError(
            code="RECEPTOR_REPAIR_OBSERVED_ATOMS_CHANGED",
            stage="receptor_repair",
            status_code=422,
            message="Repair changed an observed heavy atom; this attempt was rejected.",
            details={"changed_atom_identities": changed},
        )
    topology = PDBFile(str(output_path)).topology
    from openmm import unit
    from pdbfixer import PDBFixer

    templates = PDBFixer(filename=str(output_path)).templates
    expected = {
        frozenset(
            (
                (a.residue.chain.id, int(a.residue.id), a.residue.insertionCode.strip(), a.name),
                (b.residue.chain.id, int(b.residue.id), b.residue.insertionCode.strip(), b.name),
            )
        )
        for a, b in topology.bonds()
    }
    affected = []
    for chain in gemmi.read_structure(str(output_path))[0]:
        for residue in chain:
            atoms = [atom for atom in residue if atom.element.name != "H"]
            new_names = {
                atom.name
                for atom in atoms
                if (
                    chain.name,
                    residue.name,
                    residue.seqid.num,
                    residue.seqid.icode.strip(),
                    atom.name,
                )
                not in before
            }
            if not new_names:
                continue
            molecule = Chem.RWMol()
            conformer = Chem.Conformer(len(atoms))
            for i, atom in enumerate(atoms):
                molecule.AddAtom(Chem.Atom(atom.element.atomic_number))
                conformer.SetAtomPosition(i, (atom.pos.x, atom.pos.y, atom.pos.z))
            molecule.AddConformer(conformer)
            rdDetermineBonds.DetermineConnectivity(molecule)
            extras = []
            inferred = set()
            for bond in molecule.GetBonds():
                a, b = atoms[bond.GetBeginAtomIdx()], atoms[bond.GetEndAtomIdx()]
                pair = frozenset(
                    (
                        (chain.name, residue.seqid.num, residue.seqid.icode.strip(), a.name),
                        (chain.name, residue.seqid.num, residue.seqid.icode.strip(), b.name),
                    )
                )
                inferred.add(pair)
                if pair not in expected and {a.name, b.name} & new_names:
                    extras.append(
                        {"atoms": [a.name, b.name], "distance_angstrom": a.pos.dist(b.pos)}
                    )
            required = {
                pair
                for pair in expected
                if all(
                    key[0] == chain.name
                    and key[1] == residue.seqid.num
                    and key[2] == residue.seqid.icode.strip()
                    for key in pair
                )
                and any(key[3] in new_names for key in pair)
            }
            missing = [sorted(key[3] for key in pair) for pair in required - inferred]
            chirality_errors = []
            centers = [("CA", ["N", "C", "CB"])]
            if residue.name == "ILE":
                centers.append(("CB", ["CA", "CG1", "CG2"]))
            if residue.name == "THR":
                centers.append(("CB", ["CA", "OG1", "CG2"]))
            template = templates.get(residue.name)
            if template is None:
                raise ValueError(f"No pinned standard repair template for {residue.name}")
            ideal = {
                atom.name: template.positions[atom.index].value_in_unit(unit.nanometer)
                for atom in template.topology.atoms()
            }
            actual = {atom.name: (atom.pos.x, atom.pos.y, atom.pos.z) for atom in atoms}
            for center, neighbors in centers:
                names = [center, *neighbors]
                if not set(names) & new_names or not all(
                    name in actual and name in ideal for name in names
                ):
                    continue
                if (
                    _signed_volume(actual, center, neighbors)
                    * _signed_volume(ideal, center, neighbors)
                    <= 0
                ):
                    chirality_errors.append(center)
            if extras or missing or chirality_errors:
                affected.append(
                    {
                        "chain_id": chain.name,
                        "residue_name": residue.name,
                        "sequence_number": residue.seqid.num,
                        "insertion_code": residue.seqid.icode.strip(),
                        "unexpected_bonds": extras,
                        "missing_bonds": missing,
                        "chirality_mismatch_centers": chirality_errors,
                    }
                )
    if affected:
        raise AnkoraDomainError(
            code="RECEPTOR_REPAIRED_GEOMETRY_INVALID",
            stage="receptor_repair",
            status_code=422,
            message=(
                "Reconstructed atoms have invalid inferred connectivity. "
                "Review these residues before protonation."
            ),
            details={"affected_residues": affected},
        )


def _signed_volume(positions: Any, center: str, neighbors: list[str]) -> float:
    a, b, c = [[positions[name][i] - positions[center][i] for i in range(3)] for name in neighbors]
    return float(
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )
