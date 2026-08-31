"""Isolated PDBFixer worker. Invoked only through an argument-array subprocess."""

import argparse
import json
from pathlib import Path
from typing import Any, Protocol, cast

# Bondi (1964) van der Waals radii in nanometers, for the subset of elements that
# occur in standard amino acids plus common metals/halogens. Only used to size the
# purely repulsive declash potential; not a claim of forcefield-grade accuracy.
_VDW_RADIUS_NM = {
    "H": 0.120,
    "C": 0.170,
    "N": 0.155,
    "O": 0.152,
    "S": 0.180,
    "P": 0.180,
    "F": 0.147,
    "CL": 0.175,
    "BR": 0.185,
    "I": 0.198,
}
_DEFAULT_VDW_RADIUS_NM = 0.170
# The repulsive wall sits inside the literal VDW-radius sum: structures routinely
# have non-bonded heavy atoms somewhat closer than that without it being the kind
# of overlap PDBFixer's blind placement actually produces. This scale was picked
# empirically so an already-acceptable ~2.4 A contact is left alone.
_VDW_RADIUS_SCALE = 0.7
_KCAL_MOL_A2_TO_KJ_MOL_NM2 = 418.4
_NONBONDED_CUTOFF_NM = 1.0
_BOND_FORCE_CONSTANT_KJ_MOL_NM2 = 300000.0


class _Chain(Protocol):
    id: str


class _Residue(Protocol):
    id: str
    name: str
    chain: _Chain


class _Atom(Protocol):
    index: int
    name: str
    residue: _Residue
    element: Any


class _Fixer(Protocol):
    missingResidues: dict[tuple[int, int], list[str]]
    missingAtoms: dict[_Residue, list[object]]
    missingTerminals: dict[_Residue, list[str]]
    nonstandardResidues: list[tuple[_Residue, str]]
    topology: Any
    positions: Any

    def findMissingResidues(self) -> None: ...
    def findNonstandardResidues(self) -> None: ...
    def findMissingAtoms(self) -> None: ...
    def addMissingAtoms(self) -> None: ...


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repair", action="append", default=[])
    parser.add_argument("--relax", action="store_true")
    parser.add_argument("--relaxed-output", type=Path, default=None)
    parser.add_argument("--restraint-force-constant", type=float, default=200.0)
    parser.add_argument("--relax-max-iterations", type=int, default=200)
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    if args.relax and args.relaxed_output is None:
        # A bare `assert` here disappears under `python -O`, which would
        # let execution reach `_relax_new_atoms(..., output_path=None)` and
        # fail with a much less clear error deep inside OpenMM instead of
        # this immediate, standard argparse usage error (exit code 2).
        parser.error("--relax requires --relaxed-output")
    from openmm.app import PDBFile
    from pdbfixer import PDBFixer

    requested = {tuple(value.split("|")) for value in args.repair}
    fixer = cast(_Fixer, PDBFixer(filename=str(args.input)))
    fixer.findMissingResidues()
    fixer.missingResidues = {}
    fixer.findNonstandardResidues()
    fixer.nonstandardResidues = []
    fixer.findMissingAtoms()

    selected_atoms = {
        residue: atoms
        for residue, atoms in fixer.missingAtoms.items()
        if _residue_key(residue) in requested
    }
    selected_terminals = {
        residue: atoms
        for residue, atoms in fixer.missingTerminals.items()
        if _residue_key(residue) in requested
    }
    fixer.missingAtoms = selected_atoms
    fixer.missingTerminals = selected_terminals

    before_keys = {_atom_key(atom) for atom in fixer.topology.atoms()}
    fixer.addMissingAtoms()

    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        PDBFile.writeFile(fixer.topology, fixer.positions, stream, keepIds=True)

    relaxation_report: dict[str, object] | None = None
    if args.relax:
        assert args.relaxed_output is not None
        relaxation_report = _relax_new_atoms(
            fixer,
            before_keys,
            restraint_force_constant_kcal_mol_a2=args.restraint_force_constant,
            max_iterations=args.relax_max_iterations,
            output_path=args.relaxed_output,
        )

    print(
        json.dumps(
            {
                "requested_residues": len(requested),
                "matched_residues": len(set(selected_atoms) | set(selected_terminals)),
                "relaxation": relaxation_report,
            },
            sort_keys=True,
        )
    )


def _residue_key(residue: _Residue) -> tuple[str, str, str, str]:
    residue_id = residue.id.strip()
    number = "".join(character for character in residue_id if character in "-0123456789")
    insertion = residue_id[len(number) :] if residue_id.startswith(number) else ""
    return residue.chain.id, residue.name, number, insertion


def _atom_key(atom: _Atom) -> tuple[str, str, str, str]:
    return (atom.residue.chain.id, atom.residue.name, atom.residue.id, atom.name)


def _relax_new_atoms(
    fixer: _Fixer,
    before_keys: set[tuple[str, str, str, str]],
    *,
    restraint_force_constant_kcal_mol_a2: float,
    max_iterations: int,
    output_path: Path,
) -> dict[str, object]:
    """Relax only the atoms PDBFixer just placed against a purely repulsive
    declash potential, holding every previously observed atom under a strong
    positional restraint. This never adds hydrogens or a full biomolecular
    forcefield: it only resolves the specific steric-overlap failure mode
    `addMissingAtoms()` is known to produce, nothing more."""
    import openmm
    from openmm import unit
    from openmm.app import PDBFile

    atoms = list(fixer.topology.atoms())
    new_indices = [atom.index for atom in atoms if _atom_key(atom) not in before_keys]
    if not new_indices:
        return {"relaxed": False, "reason": "no_new_atoms"}
    new_index_set = set(new_indices)
    original_positions = fixer.positions

    system = openmm.System()
    sigmas_nm: list[float] = []
    for atom in atoms:
        element = atom.element
        symbol = element.symbol.upper() if element is not None else "C"
        mass = element.mass if element is not None else 12.0 * unit.dalton
        system.addParticle(mass)
        radius_nm = _VDW_RADIUS_NM.get(symbol, _DEFAULT_VDW_RADIUS_NM)
        sigmas_nm.append(radius_nm * _VDW_RADIUS_SCALE)

    nonbonded = openmm.CustomNonbondedForce("4*100*((sigma/r)^12); sigma=(sigma1+sigma2)")
    nonbonded.addPerParticleParameter("sigma")
    nonbonded.setNonbondedMethod(openmm.CustomNonbondedForce.CutoffNonPeriodic)
    nonbonded.setCutoffDistance(_NONBONDED_CUTOFF_NM * unit.nanometer)
    for sigma in sigmas_nm:
        nonbonded.addParticle([sigma])
    bond_pairs = [(bond[0].index, bond[1].index) for bond in fixer.topology.bonds()]
    # Exclude only direct (1-2) bonds, not 1-3/1-4 pairs. This force field has
    # no angle or dihedral term, so a 1-3 pair (e.g. CB-CD across CG) has
    # nothing else constraining its distance - excluding it here would let a
    # newly placed side chain fold back on itself (angle collapsing toward 0)
    # while every bond length stays perfectly valid. Letting 1-3/1-4 pairs
    # repel like any other nonbonded pair acts as a crude but effective
    # angle constraint instead.
    nonbonded.createExclusionsFromBonds(bond_pairs, 1)
    # Only atom pairs where at least one side is newly placed can repel each
    # other. Two previously observed atoms that merely sit close together (a
    # tight metal coordination, a naturally packed pocket) are not this
    # feature's business to "fix" - only PDBFixer's own placements are.
    nonbonded.addInteractionGroup(new_indices, list(range(len(atoms))))
    system.addForce(nonbonded)

    bonds_force = openmm.HarmonicBondForce()
    for a1, a2 in bond_pairs:
        length_nm = _distance_nm(original_positions[a1], original_positions[a2])
        bonds_force.addBond(a1, a2, length_nm, _BOND_FORCE_CONSTANT_KJ_MOL_NM2)
    system.addForce(bonds_force)

    restraint = openmm.CustomExternalForce("k*((x-x0)^2+(y-y0)^2+(z-z0)^2)")
    restraint.addGlobalParameter(
        "k", restraint_force_constant_kcal_mol_a2 * _KCAL_MOL_A2_TO_KJ_MOL_NM2
    )
    restraint.addPerParticleParameter("x0")
    restraint.addPerParticleParameter("y0")
    restraint.addPerParticleParameter("z0")
    for atom in atoms:
        if atom.index not in new_index_set:
            position = original_positions[atom.index].value_in_unit(unit.nanometer)
            restraint.addParticle(atom.index, list(position))
    system.addForce(restraint)

    integrator = openmm.VerletIntegrator(1.0 * unit.femtoseconds)
    platform = openmm.Platform.getPlatformByName("Reference")
    context = openmm.Context(system, integrator, platform)
    context.setPositions(original_positions)

    min_pair_before_nm = _min_new_atom_pair_distance_nm(
        original_positions, new_index_set, bond_pairs
    )
    openmm.LocalEnergyMinimizer.minimize(context, maxIterations=max_iterations)
    relaxed_state = context.getState(getPositions=True)
    relaxed_positions = relaxed_state.getPositions()

    max_restrained_displacement_nm = 0.0
    for atom in atoms:
        if atom.index not in new_index_set:
            displacement = _distance_nm(
                original_positions[atom.index], relaxed_positions[atom.index]
            )
            max_restrained_displacement_nm = max(max_restrained_displacement_nm, displacement)

    min_pair_after_nm = _min_new_atom_pair_distance_nm(
        relaxed_positions, new_index_set, bond_pairs
    )

    with output_path.open("x", encoding="utf-8", newline="\n") as stream:
        PDBFile.writeFile(fixer.topology, relaxed_positions, stream, keepIds=True)

    return {
        "relaxed": True,
        "new_atom_count": len(new_indices),
        "restraint_force_constant_kcal_mol_a2": restraint_force_constant_kcal_mol_a2,
        "max_iterations": max_iterations,
        "max_restrained_atom_displacement_angstrom": max_restrained_displacement_nm * 10,
        "min_new_atom_pair_distance_before_angstrom": (
            min_pair_before_nm * 10 if min_pair_before_nm is not None else None
        ),
        "min_new_atom_pair_distance_after_angstrom": (
            min_pair_after_nm * 10 if min_pair_after_nm is not None else None
        ),
    }


def _distance_nm(position_a: Any, position_b: Any) -> float:
    from openmm import unit

    a = position_a.value_in_unit(unit.nanometer)
    b = position_b.value_in_unit(unit.nanometer)
    return float(sum((ai - bi) ** 2 for ai, bi in zip(a, b, strict=True)) ** 0.5)


def _min_new_atom_pair_distance_nm(
    positions: list[Any], new_index_set: set[int], bond_pairs: list[tuple[int, int]]
) -> float | None:
    bonded = {frozenset(pair) for pair in bond_pairs}
    nearest: float | None = None
    for new_index in new_index_set:
        for other_index in range(len(positions)):
            if other_index == new_index or frozenset((new_index, other_index)) in bonded:
                continue
            distance = _distance_nm(positions[new_index], positions[other_index])
            if nearest is None or distance < nearest:
                nearest = distance
    return nearest


if __name__ == "__main__":
    main()
