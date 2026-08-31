"""Explicit create-only physiological protonation resolution for M3 ligands.

Dimorphite-DL enumerates ionization states across a pH range; it never picks one
silently. A single result means the range is unambiguous. Multiple results mean
the molecule's ionizable group sits near the range boundary and the scientist
must choose explicitly, the same way undefined stereocenters or disconnected
components already require an explicit decision before any derivative exists.
"""

from datetime import UTC, datetime
from hashlib import sha256
from importlib import import_module, metadata
from typing import Any

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligands import (
    LigandChemicalStateArtifact,
    LigandProtonationCandidate,
    LigandProtonationOptions,
    LigandProtonationRecord,
    LigandProtonationSelection,
    ResolveLigandProtonationRequest,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.services.ligand_import import inspect_ligand_molecule

Chem: Any = import_module("rdkit.Chem")
_dimorphite: Any = import_module("dimorphite_dl")


def protonation_options(
    *,
    ligand_id: str,
    parent_state_id: str,
    ph_min: float,
    ph_max: float,
    precision: float,
    store: LigandArtifactStore,
) -> LigandProtonationOptions:
    molecule = _read_state(ligand_id, parent_state_id, store)
    candidates = _enumerate_candidates(
        molecule, ph_min=ph_min, ph_max=ph_max, precision=precision
    )
    return LigandProtonationOptions(
        parent_state_id=parent_state_id,
        ph_min=ph_min,
        ph_max=ph_max,
        precision=precision,
        candidates=candidates,
        selection_required=len(candidates) > 1,
    )


def resolve_ligand_protonation(
    *,
    ligand_id: str,
    request: ResolveLigandProtonationRequest,
    store: LigandArtifactStore,
) -> LigandProtonationRecord:
    original = store.load_record(ligand_id)
    molecule = _read_state(ligand_id, request.parent_state_id, store)
    candidates = _enumerate_candidates(
        molecule, ph_min=request.ph_min, ph_max=request.ph_max, precision=request.precision
    )
    try:
        chosen = candidates[request.candidate_index]
    except IndexError as error:
        raise _protonation_error(
            "LIGAND_PROTONATION_SELECTION_INVALID",
            "The selected protonation state is not one of the enumerated candidates.",
            details={"candidate_index": request.candidate_index},
        ) from error
    resolved = Chem.MolFromSmiles(chosen.canonical_smiles)
    if resolved is None:
        raise _protonation_error(
            "LIGAND_PROTONATION_SELECTION_INVALID",
            "The selected protonation state could not be parsed back into a molecule.",
        )
    resolved.SetProp("_Name", original.inspection.name)
    inspection = inspect_ligand_molecule(resolved, original.inspection.name)
    content = (Chem.MolToMolBlock(resolved) + "\n$$$$\n").encode("utf-8")
    state_id = store.new_state_id()
    created_at = datetime.now(UTC)
    artifact = LigandChemicalStateArtifact(
        state_id=state_id,
        ligand_id=ligand_id,
        filename=f"{original.inspection.name}_protonated_state.sdf",
        format="sdf",
        sha256=sha256(content).hexdigest(),
        size_bytes=len(content),
        created_at=created_at,
    )
    selection = LigandProtonationSelection(
        candidate_index=request.candidate_index,
        candidate_count=len(candidates),
        ph_min=request.ph_min,
        ph_max=request.ph_max,
        precision=request.precision,
    )
    provenance = ProvenanceEvent(
        event_id=f"ligand_protonation_resolved-{state_id}",
        event_type="ligand_protonation_resolved",
        timestamp=created_at,
        input_artifacts=[request.parent_state_id],
        output_artifacts=[state_id],
        tool=ToolIdentity(name="Dimorphite-DL", version=_dimorphite_version()),
        parameters={
            **selection.model_dump(mode="json"),
            "canonical_smiles": chosen.canonical_smiles,
            "selection_was_explicit": True,
        },
        warnings=[],
        command=None,
    )
    record = LigandProtonationRecord(
        artifact=artifact,
        parent_state_id=request.parent_state_id,
        inspection=inspection,
        selection=selection,
        warnings=[],
        provenance=provenance,
        content_url=f"/ligands/{ligand_id}/states/{state_id}/content",
    )
    store.create_state(ligand_id, state_id, content, record)
    return record


def _enumerate_candidates(
    molecule: Any, *, ph_min: float, ph_max: float, precision: float
) -> list[LigandProtonationCandidate]:
    source_smiles = Chem.MolToSmiles(molecule, isomericSmiles=True)
    try:
        variants = _dimorphite.protonate_smiles(
            source_smiles, ph_min=ph_min, ph_max=ph_max, precision=precision
        )
    except Exception as error:
        raise _protonation_error(
            "LIGAND_PROTONATION_ENUMERATION_FAILED",
            "Dimorphite-DL could not enumerate protonation states for this molecule.",
            details={"technical_message": str(error)},
        ) from error
    candidates: list[LigandProtonationCandidate] = []
    seen_smiles: set[str] = set()
    for variant_smiles in variants:
        variant_mol = Chem.MolFromSmiles(variant_smiles)
        if variant_mol is None:
            continue
        canonical = Chem.MolToSmiles(variant_mol, isomericSmiles=True)
        if canonical in seen_smiles:
            continue
        seen_smiles.add(canonical)
        candidates.append(
            LigandProtonationCandidate(
                index=len(candidates),
                canonical_smiles=canonical,
                formal_charge=Chem.GetFormalCharge(variant_mol),
            )
        )
    if not candidates:
        raise _protonation_error(
            "LIGAND_PROTONATION_ENUMERATION_FAILED",
            "Dimorphite-DL returned no usable protonation states for this molecule.",
        )
    return candidates


def _dimorphite_version() -> str:
    try:
        return metadata.version("dimorphite-dl")
    except metadata.PackageNotFoundError:
        return "unknown"


def _read_state(ligand_id: str, state_id: str, store: LigandArtifactStore) -> Any:
    supplier = Chem.SDMolSupplier(
        str(store.state_content_path(ligand_id, state_id)), removeHs=False
    )
    molecule = supplier[0] if len(supplier) else None
    if molecule is None:
        raise _protonation_error(
            "LIGAND_STATE_UNREADABLE",
            "The selected ligand chemical state could not be read.",
        )
    return molecule


def _protonation_error(
    code: str, message: str, *, details: dict[str, object] | None = None
) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code,
        stage="ligand_protonation",
        message=message,
        status_code=422,
        details=details,
    )
