"""Crystallographic ligand extraction with mmCIF topology and observed coordinates."""

from datetime import UTC, datetime
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import Any

import gemmi

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligands import (
    ExtractLigandRequest,
    LigandArtifact,
    LigandChemicalStateArtifact,
    LigandFormat,
    LigandInspection,
    LigandRecord,
    LigandSource,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode

Chem: Any = import_module("rdkit.Chem")
rdBase: Any = import_module("rdkit.rdBase")
Lipinski: Any = import_module("rdkit.Chem.Lipinski")
Descriptors: Any = import_module("rdkit.Chem.Descriptors")
rdMolDescriptors: Any = import_module("rdkit.Chem.rdMolDescriptors")

_BOND_TYPES: dict[str, Any] = {
    "sing": Chem.BondType.SINGLE,
    "doub": Chem.BondType.DOUBLE,
    "trip": Chem.BondType.TRIPLE,
    "arom": Chem.BondType.AROMATIC,
}


def extract_crystallographic_ligand(
    *,
    source_artifact_id: str,
    request: ExtractLigandRequest,
    structure_store: StructureArtifactStore,
    ligand_store: LigandArtifactStore,
) -> LigandRecord:
    source = structure_store.load_record(source_artifact_id)
    if source.artifact.format.value != "mmcif":
        raise AnkoraDomainError(
            code="LIGAND_TOPOLOGY_UNAVAILABLE",
            stage="ligand_extraction",
            message="Crystallographic extraction requires mmCIF chemical-component topology.",
            status_code=422,
            details={"source_format": source.artifact.format.value},
        )
    source_path = structure_store.content_path(source_artifact_id)
    residue = _find_residue(source_path, request)
    molecule, charges_deposited = _build_observed_molecule(source_path, residue, request)
    molecule.SetProp("_Name", request.locator.component_name)
    content = (Chem.MolToMolBlock(molecule) + "\n$$$$\n").encode("utf-8")
    ligand_id = ligand_store.new_ligand_id()
    state_id = ligand_store.new_state_id()
    created_at = datetime.now(UTC)
    filename = (
        f"{request.locator.component_name}_{request.locator.chain_id}_"
        f"{request.locator.sequence_number}.sdf"
    )
    formula = rdMolDescriptors.CalcMolFormula(molecule)
    deposited_formula = _deposited_formula(source_path, request.locator.component_name)
    if deposited_formula is not None and formula != deposited_formula:
        raise AnkoraDomainError(
            code="LIGAND_FORMULA_MISMATCH",
            stage="ligand_extraction",
            message="Observed atoms and deposited topology do not reproduce the component formula.",
            status_code=422,
            details={"calculated_formula": formula, "deposited_formula": deposited_formula},
        )
    warnings = [] if charges_deposited else [
        StructuredWarning(
            code=WarningCode.LIG_FORMAL_CHARGE_INFERRED,
            message=(
                "The source mmCIF omits atom formal charges; RDKit inferred neutral valence "
                "from deposited bonds and the result matches the deposited formula."
            ),
            stage="ligand_extraction",
            details={"calculated_formula": formula, "deposited_formula": deposited_formula},
            recoverable=True,
        )
    ]
    chiral_centers = Chem.FindMolChiralCenters(molecule, includeUnassigned=True)
    inspection = LigandInspection(
        name=request.locator.component_name,
        formula=formula,
        molecular_weight_g_mol=Descriptors.MolWt(molecule),
        exact_mass_da=rdMolDescriptors.CalcExactMolWt(molecule),
        formal_charge=Chem.GetFormalCharge(molecule),
        atom_count=molecule.GetNumAtoms(),
        heavy_atom_count=molecule.GetNumHeavyAtoms(),
        rotatable_bond_count=Lipinski.NumRotatableBonds(molecule),
        aromatic_ring_count=rdMolDescriptors.CalcNumAromaticRings(molecule),
        stereocenter_count=len(chiral_centers),
        undefined_stereocenter_count=sum(label == "?" for _, label in chiral_centers),
        fragment_count=len(Chem.GetMolFrags(molecule)),
        conformer_count=molecule.GetNumConformers(),
        has_3d_coordinates=True,
        canonical_smiles=Chem.MolToSmiles(molecule, isomericSmiles=True),
    )
    artifact = LigandArtifact(
        ligand_id=ligand_id,
        source=LigandSource.CRYSTALLOGRAPHIC,
        source_structure_id=source_artifact_id,
        locator=request.locator,
        filename=filename,
        format=LigandFormat.SDF,
        sha256=sha256(content).hexdigest(),
        size_bytes=len(content),
        created_at=created_at,
    )
    state = LigandChemicalStateArtifact(
        state_id=state_id,
        ligand_id=ligand_id,
        filename="inspected_state.sdf",
        format="sdf",
        sha256=sha256(content).hexdigest(),
        size_bytes=len(content),
        created_at=created_at,
    )
    provenance = ProvenanceEvent(
        event_id=f"ligand_extracted-{ligand_id}",
        event_type="crystallographic_ligand_extracted",
        timestamp=created_at,
        input_artifacts=[source_artifact_id],
        output_artifacts=[ligand_id, state_id],
        tool=ToolIdentity(name="RDKit/mmCIF topology", version=rdBase.rdkitVersion),
        parameters={"locator": request.locator.model_dump(mode="json"), "coordinates": "observed"},
        warnings=warnings,
        command=None,
    )
    record = LigandRecord(
        artifact=artifact,
        state=state,
        inspection=inspection,
        warnings=warnings,
        provenance=provenance,
        content_url=f"/ligands/{ligand_id}/states/{state_id}/content",
        original_content_url=f"/ligands/{ligand_id}/content",
    )
    ligand_store.create(ligand_id, content, record, state_content=content)
    return record


def _find_residue(source_path: Path, request: ExtractLigandRequest) -> gemmi.Residue:
    structure = gemmi.read_structure(str(source_path))
    locator = request.locator
    matches = [
        residue
        for chain in structure[0]
        if chain.name == locator.chain_id
        for residue in chain
        if residue.name == locator.component_name
        and residue.seqid.num == locator.sequence_number
        and residue.seqid.icode.strip() == locator.insertion_code
    ]
    if len(matches) != 1:
        raise AnkoraDomainError(
            code="LIGAND_COMPONENT_NOT_FOUND",
            stage="ligand_extraction",
            message="The selected crystallographic component was not found exactly once.",
            status_code=404,
            details={"locator": locator.model_dump(mode="json"), "match_count": len(matches)},
        )
    return matches[0]


def _build_observed_molecule(
    source_path: Path, residue: gemmi.Residue, request: ExtractLigandRequest
) -> tuple[Any, bool]:
    locator = request.locator
    observed = {atom.name.strip(): atom for atom in residue if atom.element.name != "H"}
    if any(atom.altloc not in {"\x00", " ", "A"} for atom in residue):
        raise AnkoraDomainError(
            code="LIGAND_ALTLOC_REQUIRES_DECISION",
            stage="ligand_extraction",
            message=(
                "The ligand has alternate coordinates that require an explicit "
                "conformation choice."
            ),
            status_code=422,
            details={"locator": locator.model_dump(mode="json")},
        )
    block = gemmi.cif.read_file(str(source_path)).sole_block()
    atom_rows = block.find_mmcif_category("_chem_comp_atom.")
    bond_rows = block.find_mmcif_category("_chem_comp_bond.")
    builder = Chem.RWMol()
    indices: dict[str, int] = {}
    charge_tag = next(
        (
            tag
            for tag in ("_chem_comp_atom.charge", "_chem_comp_atom.pdbx_formal_charge")
            if tag in atom_rows.tags
        ),
        None,
    )
    for row in atom_rows:
        if row["_chem_comp_atom.comp_id"] != locator.component_name:
            continue
        name = row["_chem_comp_atom.atom_id"]
        if name not in observed:
            continue
        atom = Chem.Atom(gemmi.Element(row["_chem_comp_atom.type_symbol"]).atomic_number)
        charge = row[charge_tag] if charge_tag is not None else None
        if charge is not None and charge not in {"?", "."}:
            atom.SetFormalCharge(int(charge))
        indices[name] = builder.AddAtom(atom)
    if set(indices) != set(observed):
        raise AnkoraDomainError(
            code="LIGAND_TOPOLOGY_INCOMPLETE",
            stage="ligand_extraction",
            message="mmCIF topology does not cover every observed ligand atom.",
            status_code=422,
            details={"missing_topology_atoms": sorted(set(observed) - set(indices))},
        )
    for row in bond_rows:
        if row["_chem_comp_bond.comp_id"] != locator.component_name:
            continue
        left = row["_chem_comp_bond.atom_id_1"]
        right = row["_chem_comp_bond.atom_id_2"]
        if left in indices and right in indices:
            order = row["_chem_comp_bond.value_order"]
            builder.AddBond(
                indices[left],
                indices[right],
                _BOND_TYPES.get(order, Chem.BondType.SINGLE),
            )
    molecule = builder.GetMol()
    conformer = Chem.Conformer(molecule.GetNumAtoms())
    for name, index in indices.items():
        position = observed[name].pos
        conformer.SetAtomPosition(index, (position.x, position.y, position.z))
    molecule.AddConformer(conformer, assignId=True)
    Chem.SanitizeMol(molecule)
    # The coordinate model is part of the crystallographic observation. Assign
    # tetrahedral tags before inspecting or serializing so the structured record
    # describes the same stereochemistry that RDKit will recover when the 3D SDF
    # is opened later. Without this, a deposited chiral ligand could be recorded
    # as ``undefined`` even though its retained coordinates determine the centers.
    Chem.AssignAtomChiralTagsFromStructure(
        molecule,
        confId=0,
        replaceExistingTags=True,
    )
    Chem.AssignStereochemistry(molecule, cleanIt=True, force=True)
    _verify_deposited_stereochemistry(
        molecule=molecule,
        atom_rows=atom_rows,
        component_name=locator.component_name,
        indices=indices,
    )
    return molecule, charge_tag is not None


def _verify_deposited_stereochemistry(
    *,
    molecule: Any,
    atom_rows: Any,
    component_name: str,
    indices: dict[str, int],
) -> None:
    stereo_tag = "_chem_comp_atom.pdbx_stereo_config"
    if stereo_tag not in atom_rows.tags:
        return
    mismatches: list[dict[str, str | None]] = []
    for row in atom_rows:
        if row["_chem_comp_atom.comp_id"] != component_name:
            continue
        expected = row[stereo_tag].upper()
        atom_name = row["_chem_comp_atom.atom_id"]
        if expected not in {"R", "S"} or atom_name not in indices:
            continue
        atom = molecule.GetAtomWithIdx(indices[atom_name])
        observed = atom.GetProp("_CIPCode") if atom.HasProp("_CIPCode") else None
        if observed != expected:
            mismatches.append(
                {"atom_id": atom_name, "deposited": expected, "observed": observed}
            )
    if mismatches:
        raise AnkoraDomainError(
            code="LIGAND_STEREOCHEMISTRY_MISMATCH",
            stage="ligand_extraction",
            message=(
                "Observed coordinates do not reproduce the stereochemistry "
                "declared by the mmCIF chemical component."
            ),
            status_code=422,
            details={"component_name": component_name, "mismatches": mismatches},
        )


def _deposited_formula(source_path: Path, component_name: str) -> str | None:
    block = gemmi.cif.read_file(str(source_path)).sole_block()
    component_rows = block.find_mmcif_category("_chem_comp.")
    if "_chem_comp.formula" not in component_rows.tags:
        return None
    for row in component_rows:
        if row["_chem_comp.id"] == component_name:
            value = row["_chem_comp.formula"].strip("'\"")
            return value.replace(" ", "") if value not in {"?", "."} else None
    return None
