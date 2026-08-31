"""Explicit create-only component and stereochemistry resolution for M3 ligands."""

from datetime import UTC, datetime
from hashlib import sha256
from importlib import import_module
from typing import Any

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligands import (
    LigandChemicalStateArtifact,
    LigandChemicalStateRecord,
    LigandComponentOption,
    LigandStateResolutionOptions,
    LigandStateSelection,
    LigandStereoisomerOption,
    ResolveLigandStateRequest,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.warnings import WarningCode
from ankora_backend.services.ligand_import import inspect_ligand_molecule

Chem: Any = import_module("rdkit.Chem")
rdBase: Any = import_module("rdkit.rdBase")
rdMolDescriptors: Any = import_module("rdkit.Chem.rdMolDescriptors")
stereo_module: Any = import_module("rdkit.Chem.EnumerateStereoisomers")

MAX_STEREOISOMERS = 64


def state_resolution_options(
    *,
    ligand_id: str,
    parent_state_id: str,
    component_index: int | None,
    store: LigandArtifactStore,
) -> LigandStateResolutionOptions:
    original = store.load_record(ligand_id)
    molecule = _read_state(ligand_id, parent_state_id, store)
    components = list(Chem.GetMolFrags(molecule, asMols=True, sanitizeFrags=True))
    component_options = [_component_option(index, item) for index, item in enumerate(components)]
    selected_index = component_index
    if selected_index is None and len(components) == 1:
        selected_index = 0
    stereoisomer_options: list[LigandStereoisomerOption] = []
    stereoisomer_selection_required = False
    if selected_index is not None:
        selected = _selected_component(components, selected_index)
        stereoisomers = _enumerate_stereoisomers(selected)
        stereoisomer_options = [
            LigandStereoisomerOption(
                index=index,
                canonical_isomeric_smiles=Chem.MolToSmiles(item, isomericSmiles=True),
            )
            for index, item in enumerate(stereoisomers)
        ]
        stereoisomer_selection_required = _undefined_stereocenter_count(selected) > 0
    if original.state is None:
        raise _state_error(
            "LIGAND_STATE_NOT_AVAILABLE",
            "The imported ligand does not have an inspected chemical state.",
        )
    return LigandStateResolutionOptions(
        parent_state_id=parent_state_id,
        component_options=component_options,
        selected_component_index=selected_index,
        stereoisomer_options=stereoisomer_options,
        component_selection_required=len(components) > 1 and component_index is None,
        stereoisomer_selection_required=stereoisomer_selection_required,
    )


def resolve_ligand_state(
    *,
    ligand_id: str,
    request: ResolveLigandStateRequest,
    store: LigandArtifactStore,
) -> LigandChemicalStateRecord:
    original = store.load_record(ligand_id)
    molecule = _read_state(ligand_id, request.parent_state_id, store)
    components = list(Chem.GetMolFrags(molecule, asMols=True, sanitizeFrags=True))
    selected = _selected_component(components, request.component_index)
    stereoisomers = _enumerate_stereoisomers(selected)
    undefined_count = _undefined_stereocenter_count(selected)
    if undefined_count and request.stereoisomer_index is None:
        raise _state_error(
            WarningCode.LIG_STEREOCHEMISTRY_UNDEFINED.value,
            "Choose one explicit stereoisomer before creating the chemical state.",
            details={"stereoisomer_count": len(stereoisomers)},
        )
    stereoisomer_index = request.stereoisomer_index or 0
    try:
        resolved = Chem.Mol(stereoisomers[stereoisomer_index])
    except IndexError as error:
        raise _state_error(
            "LIGAND_STEREOISOMER_SELECTION_INVALID",
            "The selected stereoisomer is not one of the enumerated choices.",
            details={"stereoisomer_index": stereoisomer_index},
        ) from error
    resolved.SetProp("_Name", original.inspection.name)
    Chem.AssignStereochemistry(resolved, cleanIt=True, force=True)
    inspection = inspect_ligand_molecule(resolved, original.inspection.name)
    if inspection.fragment_count != 1 or inspection.undefined_stereocenter_count:
        raise _state_error(
            "LIGAND_STATE_RESOLUTION_INCOMPLETE",
            "The selected component and stereoisomer did not produce a resolved state.",
        )
    content = (Chem.MolToMolBlock(resolved) + "\n$$$$\n").encode("utf-8")
    state_id = store.new_state_id()
    created_at = datetime.now(UTC)
    artifact = LigandChemicalStateArtifact(
        state_id=state_id,
        ligand_id=ligand_id,
        filename=f"{original.inspection.name}_resolved_state.sdf",
        format="sdf",
        sha256=sha256(content).hexdigest(),
        size_bytes=len(content),
        created_at=created_at,
    )
    excluded_codes = {
        WarningCode.LIG_MULTICOMPONENT_STATE,
        WarningCode.LIG_STEREOCHEMISTRY_UNDEFINED,
    }
    warnings = [item for item in original.warnings if item.code not in excluded_codes]
    selection = LigandStateSelection(
        component_index=request.component_index,
        source_fragment_count=len(components),
        stereoisomer_index=(stereoisomer_index if undefined_count else None),
        stereoisomer_count=len(stereoisomers),
    )
    provenance = ProvenanceEvent(
        event_id=f"ligand_state_resolved-{state_id}",
        event_type="ligand_chemical_state_resolved",
        timestamp=created_at,
        input_artifacts=[request.parent_state_id],
        output_artifacts=[state_id],
        tool=ToolIdentity(name="RDKit state resolver", version=rdBase.rdkitVersion),
        parameters={
            **selection.model_dump(mode="json"),
            "canonical_isomeric_smiles": Chem.MolToSmiles(
                resolved, isomericSmiles=True
            ),
            "selection_was_explicit": True,
        },
        warnings=warnings,
        command=None,
    )
    record = LigandChemicalStateRecord(
        artifact=artifact,
        parent_state_id=request.parent_state_id,
        inspection=inspection,
        selection=selection,
        warnings=warnings,
        provenance=provenance,
        content_url=f"/ligands/{ligand_id}/states/{state_id}/content",
    )
    store.create_state(ligand_id, state_id, content, record)
    return record


def _read_state(ligand_id: str, state_id: str, store: LigandArtifactStore) -> Any:
    supplier = Chem.SDMolSupplier(
        str(store.state_content_path(ligand_id, state_id)), removeHs=False
    )
    molecule = supplier[0] if len(supplier) else None
    if molecule is None:
        raise _state_error(
            "LIGAND_STATE_UNREADABLE",
            "The selected ligand chemical state could not be read.",
        )
    return molecule


def _component_option(index: int, molecule: Any) -> LigandComponentOption:
    return LigandComponentOption(
        index=index,
        formula=rdMolDescriptors.CalcMolFormula(molecule),
        formal_charge=Chem.GetFormalCharge(molecule),
        heavy_atom_count=molecule.GetNumHeavyAtoms(),
        canonical_smiles=Chem.MolToSmiles(molecule, isomericSmiles=True),
    )


def _selected_component(components: list[Any], component_index: int) -> Any:
    try:
        return components[component_index]
    except IndexError as error:
        raise _state_error(
            "LIGAND_COMPONENT_SELECTION_INVALID",
            "The selected component is not one of the inspected disconnected components.",
            details={"component_index": component_index},
        ) from error


def _enumerate_stereoisomers(molecule: Any) -> list[Any]:
    undefined_count = _undefined_stereocenter_count(molecule)
    if undefined_count and 2**undefined_count > MAX_STEREOISOMERS:
        raise _state_error(
            "LIGAND_STEREOISOMER_LIMIT_EXCEEDED",
            "This state has too many undefined stereoisomers for explicit enumeration.",
            details={
                "undefined_stereocenter_count": undefined_count,
                "maximum_isomers": MAX_STEREOISOMERS,
            },
        )
    options = stereo_module.StereoEnumerationOptions(
        onlyUnassigned=True,
        unique=True,
        maxIsomers=MAX_STEREOISOMERS,
        tryEmbedding=False,
    )
    isomers = list(stereo_module.EnumerateStereoisomers(molecule, options=options))
    return isomers or [Chem.Mol(molecule)]


def _undefined_stereocenter_count(molecule: Any) -> int:
    Chem.AssignStereochemistry(molecule, cleanIt=True, force=True)
    centers = Chem.FindMolChiralCenters(molecule, includeUnassigned=True)
    return sum(label == "?" for _, label in centers)


def _state_error(
    code: str, message: str, *, details: dict[str, object] | None = None
) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code,
        stage="ligand_state_resolution",
        message=message,
        status_code=422,
        details=details,
    )
