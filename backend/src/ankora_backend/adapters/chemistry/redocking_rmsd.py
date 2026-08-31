"""Symmetry-aware heavy-atom RMSD between a docked pose and a reference pose.

Redocking asks one question: did the engine put the ligand where the crystal
says it is? Two details decide whether the answer means anything, and both were
found by measuring a real case before this module existed.

**The RMSD must be computed in place.** RDKit's `GetBestRMS` superimposes the
two molecules first and reports how similar their *shapes* are. On the reference
case it reported a pose that sits 10.7 A from the crystal as 1.330 A, because
after alignment a wrong binding mode looks fine. A redocking validator built on
it would pass almost everything. Only `CalcRMS`, which measures where the atoms
actually are, answers the question being asked - so it is the only one this
module exposes.

**A PDBQT's element column is an AutoDock type, not an element.** `A` is
aromatic carbon, `OA`/`NA`/`SA` are hydrogen-bond acceptors, `HD` is a polar
hydrogen. Handing those columns to a PDB parser fails outright, or worse
succeeds and invents elements. The mapping below is applied before anything is
parsed.

Hydrogens are excluded throughout: their crystallographic positions are usually
inferred rather than observed, so including them would measure the modelling
rather than the pose.
"""

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from ankora_backend.domain.errors import AnkoraDomainError

# Imported the way the rest of the project does: RDKit ships stubs mypy cannot
# parse, so it is reached through `import_module` rather than a direct import.
Chem: Any = import_module("rdkit.Chem")
AllChem: Any = import_module("rdkit.Chem.AllChem")
rdMolAlign: Any = import_module("rdkit.Chem.rdMolAlign")

_STAGE = "redocking_validation"

# AutoDock atom types, as they appear in columns 78-79 of a PDBQT, mapped to the
# element each one actually is.
_AUTODOCK_TYPE_TO_ELEMENT: dict[str, str] = {
    "A": "C", "C": "C",
    "N": "N", "NA": "N", "NS": "N",
    "O": "O", "OA": "O", "OS": "O",
    "S": "S", "SA": "S",
    "H": "H", "HD": "H", "HS": "H",
    "F": "F", "CL": "Cl", "BR": "Br", "I": "I",
    "P": "P",
    "FE": "Fe", "ZN": "Zn", "MG": "Mg", "MN": "Mn", "CA": "Ca",
    "SI": "Si", "B": "B",
}

# The criterion `REDOCKING_VALIDATION.md` documents. Passing means only that the
# evaluated configuration recovered the reference pose under this criterion.
DEFAULT_RMSD_THRESHOLD_ANGSTROM = 2.0


@dataclass(frozen=True, slots=True)
class PoseRmsd:
    """One docked pose measured against the reference."""

    run: int
    rank: int
    binding_energy_kcal_mol: float
    rmsd_angstrom: float

    def recovered(self, threshold: float) -> bool:
        return self.rmsd_angstrom <= threshold


def autodock_type_to_element(atom_type: str) -> str | None:
    """The element an AutoDock type stands for, or None when it is unknown.

    Unknown is returned rather than guessed: inventing an element would change
    the molecular graph and therefore the RMSD, silently.
    """
    return _AUTODOCK_TYPE_TO_ELEMENT.get(atom_type.strip().upper())


def pdbqt_to_pdb_block(document: str, *, keep_hydrogens: bool = False) -> str:
    """Rewrite a docked PDBQT as a PDB block a parser can read.

    Only the element column is corrected; coordinates and atom order are left
    exactly as the engine wrote them.
    """
    lines: list[str] = []
    for line in document.splitlines():
        if not line.startswith(("ATOM", "HETATM")):
            continue
        element = autodock_type_to_element(line[77:79])
        if element is None:
            raise _rejected(
                "REDOCKING_UNKNOWN_ATOM_TYPE",
                "This pose uses an AutoDock atom type Ankora cannot map to an element.",
                {"atom_type": line[77:79].strip(), "line": line[:30]},
            )
        if element == "H" and not keep_hydrogens:
            continue
        lines.append(f"{line[:76]}{element.upper().rjust(2)}  ")
    if not lines:
        raise _rejected(
            "REDOCKING_POSE_EMPTY",
            "This pose contains no heavy atoms to measure.",
            {},
        )
    return "\n".join(lines)


def load_reference(path: Path) -> Any:
    """The crystallographic pose, read from the immutable original."""
    molecule = Chem.MolFromMolFile(str(path), removeHs=True)
    if molecule is None:
        raise _rejected(
            "REDOCKING_REFERENCE_UNREADABLE",
            "The reference ligand could not be read as a molecule.",
            {"filename": path.name},
        )
    return molecule


def load_pose(document: str, reference: Any) -> Any:
    """Rebuild a docked pose with the reference's bond orders.

    A PDBQT carries no bond orders, so the graph is taken from the reference and
    the coordinates from the pose. If the two are not the same molecule this
    fails rather than measuring two different things against each other.
    """
    probe = Chem.MolFromPDBBlock(
        pdbqt_to_pdb_block(document), removeHs=True, sanitize=False
    )
    if probe is None:
        raise _rejected(
            "REDOCKING_POSE_UNREADABLE",
            "This docked pose could not be read as a molecule.",
            {},
        )
    try:
        matched = AllChem.AssignBondOrdersFromTemplate(reference, probe)
    except Exception as error:  # RDKit raises bare exceptions here
        raise _rejected(
            "REDOCKING_POSE_NOT_THE_REFERENCE_MOLECULE",
            (
                "The docked pose and the reference ligand are not the same "
                "molecule, so an RMSD between them would be meaningless."
            ),
            {
                "reference_heavy_atoms": reference.GetNumAtoms(),
                "pose_heavy_atoms": probe.GetNumAtoms(),
                "technical_message": str(error),
            },
        ) from error
    return Chem.RemoveHs(matched)


def in_place_rmsd(pose: Any, reference: Any) -> float:
    """Symmetry-aware heavy-atom RMSD, without superimposing anything.

    `CalcRMS` considers every symmetry-equivalent atom mapping - the two oxygens
    of a carboxylate, the flip of a phenyl ring - and takes the best, which is
    what makes the number chemically meaningful. What it does not do is move the
    pose, which is what makes it the right question for redocking.
    """
    return float(rdMolAlign.CalcRMS(pose, reference))


def _rejected(code: str, message: str, details: dict[str, object]) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code, stage=_STAGE, message=message, status_code=422, details=details
    )
