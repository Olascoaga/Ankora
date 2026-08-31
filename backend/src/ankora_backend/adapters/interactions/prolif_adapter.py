"""ProLIF adapter that returns Ankora's structured evidence, never a plot."""

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from numbers import Real
from pathlib import Path
from typing import Any

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.pose_interactions import (
    InteractionContact,
    InteractionProfile,
    LigandDiagram,
    LigandDiagramAtom,
    LigandDiagramBond,
    Point3D,
)
from ankora_backend.schemas.receptors import ResidueLocator

_STAGE = "pose_interaction_detection"

_DISPLAY_TYPES = {
    "Hydrophobic": "Hydrophobic",
    "HBDonor": "H-bond · ligand donor",
    "HBAcceptor": "H-bond · ligand acceptor",
    "FaceToFace": "π-stacking · face-to-face",
    "EdgeToFace": "π-stacking · edge-to-face",
    "CationPi": "Cation–π · ligand cation",
    "PiCation": "Cation–π · ligand π-system",
    "Anionic": "Ionic · ligand anion",
    "Cationic": "Ionic · ligand cation",
    "XBAcceptor": "Halogen bond · ligand acceptor",
    "XBDonor": "Halogen bond · ligand donor",
    "MetalAcceptor": "Metal contact · ligand acceptor",
    "MetalDonor": "Metal contact · ligand donor",
}


class ProlifInteractionAdapter:
    @staticmethod
    def version() -> str:
        try:
            return version("prolif")
        except PackageNotFoundError as error:
            raise _failure(
                "POSE_INTERACTION_DETECTOR_MISSING",
                "ProLIF is required to analyze pose interactions but is not installed.",
            ) from error

    def analyze(
        self,
        *,
        pose_path: Path,
        conformer_path: Path,
        receptor_path: Path,
        profile: InteractionProfile,
    ) -> tuple[list[InteractionContact], LigandDiagram]:
        try:
            plf = import_module("prolif")
            meeko = import_module("meeko")
            Chem = import_module("rdkit.Chem")
            rdDepictor = import_module("rdkit.Chem.rdDepictor")
        except ImportError as error:
            raise _failure(
                "POSE_INTERACTION_DETECTOR_MISSING",
                "ProLIF and Meeko are required to analyze pose interactions.",
                details={"missing_module": error.name or "unknown"},
            ) from error

        try:
            pdbqt = meeko.PDBQTMolecule.from_file(str(pose_path), skip_typing=True)
            reconstructed = meeko.RDKitMolCreate.from_pdbqt_mol(pdbqt)
            ligand = next((item for item in reconstructed if item is not None), None)
        except Exception as error:
            raise _failure(
                "POSE_INTERACTION_LIGAND_RECONSTRUCTION_FAILED",
                "The selected PDBQT pose could not be reconstructed with its recorded topology.",
                details={"reason": str(error)},
            ) from error
        if ligand is None:
            raise _failure(
                "POSE_INTERACTION_LIGAND_RECONSTRUCTION_FAILED",
                "The selected PDBQT pose did not contain a reconstructable ligand.",
            )

        supplier = Chem.SDMolSupplier(str(conformer_path), removeHs=False, sanitize=True)
        template = next((item for item in supplier if item is not None), None)
        if template is None:
            raise _failure(
                "POSE_INTERACTION_CONFORMER_INVALID",
                "The exact minimized conformer could not be read for topology validation.",
            )
        if _canonical_smiles(Chem, ligand) != _canonical_smiles(Chem, template):
            raise _failure(
                "POSE_INTERACTION_TOPOLOGY_MISMATCH",
                "The selected pose topology does not match the exact minimized "
                "conformer that produced it.",
                details={
                    "pose_smiles": _canonical_smiles(Chem, ligand),
                    "conformer_smiles": _canonical_smiles(Chem, template),
                },
            )

        try:
            protein = Chem.MolFromPDBFile(
                str(receptor_path), removeHs=False, sanitize=True, proximityBonding=True
            )
        except Exception as error:
            raise _failure(
                "POSE_INTERACTION_RECEPTOR_INVALID",
                "The exact prepared receptor could not be converted for interaction analysis.",
                details={"reason": str(error)},
            ) from error
        if protein is None:
            raise _failure(
                "POSE_INTERACTION_RECEPTOR_INVALID",
                "The exact prepared receptor could not be converted for interaction analysis.",
            )

        try:
            fingerprint = plf.Fingerprint(
                interactions=profile.interactions,
                count=True,
                vicinity_cutoff=profile.vicinity_cutoff_angstrom,
                implicit_hydrogens=False,
            )
            result = fingerprint.generate(
                plf.Molecule.from_rdkit(ligand),
                plf.Molecule.from_rdkit(protein),
                metadata=True,
            )
        except Exception as error:
            raise _failure(
                "POSE_INTERACTION_DETECTION_FAILED",
                "ProLIF could not calculate contacts for this exact pose and receptor.",
                details={"reason": str(error)},
            ) from error

        contacts = _contacts_from_ifp(result, ligand, protein)
        diagram_mol = Chem.Mol(ligand)
        rdDepictor.Compute2DCoords(diagram_mol)
        return contacts, _diagram_from_mol(diagram_mol)


def _canonical_smiles(chem: Any, molecule: Any) -> str:
    return str(chem.MolToSmiles(chem.RemoveHs(molecule), isomericSmiles=True))


def _contacts_from_ifp(result: Any, ligand: Any, protein: Any) -> list[InteractionContact]:
    contacts: list[InteractionContact] = []
    for (_, residue_id), interactions in result.items():
        for detector_type, occurrences in interactions.items():
            for metadata in occurrences:
                parents = metadata.get("parent_indices", {})
                ligand_indices = [int(value) for value in parents.get("ligand", ())]
                protein_indices = [int(value) for value in parents.get("protein", ())]
                residue = _residue_locator(protein, protein_indices, residue_id)
                geometry = {
                    str(key): float(value)
                    for key, value in metadata.items()
                    if key not in {"indices", "parent_indices"}
                    and isinstance(value, Real)
                    and not isinstance(value, bool)
                }
                contacts.append(
                    InteractionContact(
                        contact_id=f"contact-{len(contacts) + 1}",
                        detector_type=str(detector_type),
                        display_type=_DISPLAY_TYPES.get(
                            str(detector_type), str(detector_type)
                        ),
                        residue=residue,
                        ligand_atom_indices=ligand_indices,
                        protein_atom_indices=protein_indices,
                        ligand_atom_labels=[
                            _atom_label(ligand.GetAtomWithIdx(index), index)
                            for index in ligand_indices
                        ],
                        protein_atom_labels=[
                            _atom_label(protein.GetAtomWithIdx(index), index)
                            for index in protein_indices
                        ],
                        distance_angstrom=geometry.get("distance"),
                        geometry=geometry,
                        ligand_point=_centroid(ligand, ligand_indices),
                        protein_point=_centroid(protein, protein_indices),
                    )
                )
    contacts.sort(
        key=lambda item: (
            item.residue.chain_id,
            item.residue.sequence_number,
            item.residue.insertion_code,
            item.detector_type,
            item.distance_angstrom if item.distance_angstrom is not None else float("inf"),
        )
    )
    for index, contact in enumerate(contacts, start=1):
        contact.contact_id = f"contact-{index}"
    return contacts


def _centroid(molecule: Any, indices: list[int]) -> Point3D | None:
    """Where the detector found this end of the contact.

    The mean of the very atoms ProLIF matched, in the coordinates they already
    carry. Nothing is re-derived: a line drawn between two of these points is
    the contact that was measured, not a plausible-looking approximation of it.
    """
    if not indices:
        return None
    try:
        conformer = molecule.GetConformer()
    except (ValueError, RuntimeError):
        return None
    positions = [conformer.GetAtomPosition(index) for index in indices]
    count = float(len(positions))
    return Point3D(
        x=sum(float(point.x) for point in positions) / count,
        y=sum(float(point.y) for point in positions) / count,
        z=sum(float(point.z) for point in positions) / count,
    )


def _residue_locator(protein: Any, indices: list[int], residue_id: Any) -> ResidueLocator:
    if indices:
        info = protein.GetAtomWithIdx(indices[0]).GetPDBResidueInfo()
        if info is not None:
            return ResidueLocator(
                chain_id=info.GetChainId().strip(),
                residue_name=info.GetResidueName().strip() or str(residue_id.name),
                sequence_number=int(info.GetResidueNumber()),
                insertion_code=info.GetInsertionCode().strip(),
            )
    return ResidueLocator(
        chain_id=str(residue_id.chain or ""),
        residue_name=str(residue_id.name),
        sequence_number=int(residue_id.number),
    )


def _atom_label(atom: Any, index: int) -> str:
    info = atom.GetPDBResidueInfo()
    if info is not None and info.GetName().strip():
        return str(info.GetName()).strip()
    return f"{atom.GetSymbol()}{index + 1}"


def _diagram_from_mol(molecule: Any) -> LigandDiagram:
    conformer = molecule.GetConformer()
    atoms = []
    for atom in molecule.GetAtoms():
        index = int(atom.GetIdx())
        point = conformer.GetAtomPosition(index)
        atoms.append(
            LigandDiagramAtom(
                atom_index=index,
                element=str(atom.GetSymbol()),
                label=_atom_label(atom, index),
                x=float(point.x),
                y=float(point.y),
            )
        )
    bonds = [
        LigandDiagramBond(
            begin_atom_index=int(bond.GetBeginAtomIdx()),
            end_atom_index=int(bond.GetEndAtomIdx()),
            order=float(bond.GetBondTypeAsDouble()),
        )
        for bond in molecule.GetBonds()
    ]
    return LigandDiagram(atoms=atoms, bonds=bonds)


def _failure(
    code: str, message: str, *, details: dict[str, object] | None = None
) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code,
        stage=_STAGE,
        message=message,
        status_code=422,
        details=details,
    )
