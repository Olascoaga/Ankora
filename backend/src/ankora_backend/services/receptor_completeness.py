"""Read-only standard-residue heavy-atom name checks, never reconstruction."""

from functools import lru_cache
from importlib import import_module

import gemmi

_STANDARD = dict(
    zip(
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
        "ARNDCQEGHILKMFPSTWYV",
        strict=True,
    )
)


@lru_cache(maxsize=20)
def expected_heavy_atoms(name: str) -> frozenset[str]:
    """RDKit's standard residue names; OXT is a polymer leaving/terminal atom.

    Absence of OXT is not proof of a missing atom or of a biological terminus.
    Hydrogens/protonation states and nonstandard/nucleic residues are excluded.
    """
    # Runtime binding avoids a malformed MolFromSequence signature in the
    # optional third-party rdkit-stubs package, not scientific validation.
    molecule = import_module("rdkit.Chem").MolFromSequence(_STANDARD[name])
    if molecule is None:
        raise RuntimeError(f"No standard heavy-atom template for {name}")
    return frozenset(
        atom.GetPDBResidueInfo().GetName().strip()
        for atom in molecule.GetAtoms()
        if atom.GetAtomicNum() > 1 and atom.GetPDBResidueInfo().GetName().strip() != "OXT"
    )


def missing_standard_heavy_atoms(
    model: gemmi.Model,
) -> list[tuple[gemmi.Chain, gemmi.Residue, list[str]]]:
    missing = []
    for chain in model:
        for residue in chain:
            if residue.entity_type is not gemmi.EntityType.Polymer or residue.name not in _STANDARD:
                continue
            # Union of observed alternate locations: selection remains an
            # explicit issue; this is not proof that each conformer is complete.
            names = {
                atom.name.strip()
                for atom in residue
                if atom.occ > 0 and not atom.element.is_hydrogen
            }
            if "OT1" in names:
                names.add("O")  # Conventional terminal oxygen synonym, not an added atom.
            absent = sorted(expected_heavy_atoms(residue.name) - names)
            if absent:
                missing.append((chain, residue, absent))
    return missing
