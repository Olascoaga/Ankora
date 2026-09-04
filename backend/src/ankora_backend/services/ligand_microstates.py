"""Bounded, scientist-selected screening microstates.

Dimorphite-DL proposes protonation states and RDKit enumerates tautomers for
each proposal.  Neither tool supplies a population model here, so candidate
order is deterministic but scientifically unranked.  Only an explicitly
selected candidate becomes an immutable chemical-state derivative.
"""

from datetime import UTC, datetime
from hashlib import sha256
from importlib import import_module, metadata
from typing import Any

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligands import (
    LigandChemicalStateArtifact,
    LigandMicrostateCandidate,
    LigandMicrostateMode,
    LigandMicrostateOptions,
    LigandMicrostatePlan,
    LigandMicrostateRecord,
    LigandMicrostateSelection,
    ResolveLigandMicrostateRequest,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode
from ankora_backend.services.ligand_import import inspect_ligand_molecule

Chem: Any = import_module("rdkit.Chem")
rdBase: Any = import_module("rdkit.rdBase")
rdMolStandardize: Any = import_module("rdkit.Chem.MolStandardize.rdMolStandardize")
_dimorphite: Any = import_module("dimorphite_dl")


def microstate_options(
    *,
    ligand_id: str,
    parent_state_id: str,
    plan: LigandMicrostatePlan,
    store: LigandArtifactStore,
) -> LigandMicrostateOptions:
    if plan.mode is not LigandMicrostateMode.ENUMERATED_SELECTION:
        raise _microstate_error(
            "LIGAND_MICROSTATE_MODE_INVALID",
            "Microstate enumeration requires the enumerated-selection policy.",
        )
    molecule = _read_state(ligand_id, parent_state_id, store)
    return _enumerate_options(molecule, parent_state_id=parent_state_id, plan=plan)


def resolve_ligand_microstate(
    *,
    ligand_id: str,
    request: ResolveLigandMicrostateRequest,
    store: LigandArtifactStore,
) -> LigandMicrostateRecord:
    original = store.load_record(ligand_id)
    molecule = _read_state(ligand_id, request.parent_state_id, store)
    options = _enumerate_options(
        molecule,
        parent_state_id=request.parent_state_id,
        plan=request.plan,
    )
    try:
        chosen = options.candidates[request.candidate_index]
    except IndexError as error:
        raise _microstate_error(
            "LIGAND_MICROSTATE_SELECTION_INVALID",
            "The selected microstate is not one of the recorded bounded candidates.",
            details={"candidate_index": request.candidate_index},
        ) from error

    resolved = Chem.MolFromSmiles(chosen.canonical_isomeric_smiles)
    if resolved is None:
        raise _microstate_error(
            "LIGAND_MICROSTATE_SELECTION_INVALID",
            "The selected microstate could not be parsed back into a molecule.",
        )
    resolved.SetProp("_Name", original.inspection.name)
    inspection = inspect_ligand_molecule(resolved, original.inspection.name)
    content = (Chem.MolToMolBlock(resolved) + "\n$$$$\n").encode("utf-8")
    state_id = store.new_state_id()
    created_at = datetime.now(UTC)
    artifact = LigandChemicalStateArtifact(
        state_id=state_id,
        ligand_id=ligand_id,
        filename=f"{original.inspection.name}_selected_microstate.sdf",
        format="sdf",
        sha256=sha256(content).hexdigest(),
        size_bytes=len(content),
        created_at=created_at,
    )
    selection = LigandMicrostateSelection(
        candidate_index=chosen.index,
        candidate_count=len(options.candidates),
        microstate_key=chosen.microstate_key,
        protonation_candidate_index=chosen.protonation_candidate_index,
        tautomer_index=chosen.tautomer_index,
        plan=request.plan,
        enumeration_truncated=options.truncated,
    )
    warnings = _truncation_warnings(options)
    provenance = ProvenanceEvent(
        event_id=f"ligand_microstate_selected-{state_id}",
        event_type="ligand_microstate_selected",
        timestamp=created_at,
        input_artifacts=[request.parent_state_id],
        output_artifacts=[state_id],
        tool=ToolIdentity(
            name="Dimorphite-DL + RDKit TautomerEnumerator",
            version=(
                f"Dimorphite-DL {options.dimorphite_version}; "
                f"RDKit {options.rdkit_version}"
            ),
        ),
        parameters={
            "plan": request.plan.model_dump(mode="json"),
            "candidate_index": chosen.index,
            "candidate_count": len(options.candidates),
            "microstate_key": chosen.microstate_key,
            "canonical_isomeric_smiles": chosen.canonical_isomeric_smiles,
            "formal_charge": chosen.formal_charge,
            "protonation_candidate_index": chosen.protonation_candidate_index,
            "tautomer_index": chosen.tautomer_index,
            "matches_parent_state": chosen.matches_parent_state,
            "enumerated_candidate_count": options.enumerated_candidate_count,
            "enumeration_truncated": options.truncated,
            "selection_was_explicit": True,
            "candidate_order_is_not_a_population_ranking": True,
        },
        warnings=warnings,
        command=None,
    )
    record = LigandMicrostateRecord(
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


def _enumerate_options(
    molecule: Any,
    *,
    parent_state_id: str,
    plan: LigandMicrostatePlan,
) -> LigandMicrostateOptions:
    parent_smiles = Chem.MolToSmiles(molecule, isomericSmiles=True)
    protomers = _protonation_smiles(molecule, plan)
    raw: list[tuple[str, int, int, int]] = []
    per_protomer_truncated = False
    for protonation_index, protomer_smiles in enumerate(protomers):
        protomer = Chem.MolFromSmiles(protomer_smiles)
        if protomer is None:
            continue
        enumerator = rdMolStandardize.TautomerEnumerator()
        enumerator.SetMaxTautomers(plan.max_tautomers_per_protomer + 1)
        try:
            enumerated = list(enumerator.Enumerate(protomer))
        except (RuntimeError, ValueError) as error:
            raise _microstate_error(
                "LIGAND_TAUTOMER_ENUMERATION_FAILED",
                "RDKit could not enumerate tautomers for a proposed protonation state.",
                details={
                    "protonation_candidate_index": protonation_index,
                    "technical_message": str(error),
                },
            ) from error
        if not enumerated:
            enumerated = [protomer]
        canonical_tautomers = sorted(
            {
                Chem.MolToSmiles(candidate, isomericSmiles=True)
                for candidate in enumerated
            }
        )
        if len(canonical_tautomers) > plan.max_tautomers_per_protomer:
            per_protomer_truncated = True
            canonical_tautomers = canonical_tautomers[
                : plan.max_tautomers_per_protomer
            ]
        for tautomer_index, canonical in enumerate(canonical_tautomers):
            candidate = Chem.MolFromSmiles(canonical)
            if candidate is None:
                continue
            raw.append(
                (
                    canonical,
                    int(Chem.GetFormalCharge(candidate)),
                    protonation_index,
                    tautomer_index,
                )
            )

    by_smiles: dict[str, tuple[str, int, int, int]] = {}
    for item in sorted(raw, key=lambda value: (value[0], value[2], value[3])):
        by_smiles.setdefault(item[0], item)
    unique = list(by_smiles.values())
    if not unique:
        raise _microstate_error(
            "LIGAND_MICROSTATE_ENUMERATION_FAILED",
            "No usable protonation/tautomer microstates were generated.",
        )
    enumerated_count = len(unique)
    total_truncated = enumerated_count > plan.max_microstates_per_parent
    selected = unique[: plan.max_microstates_per_parent]
    candidates = [
        LigandMicrostateCandidate(
            index=index,
            microstate_key=sha256(canonical.encode("utf-8")).hexdigest(),
            canonical_isomeric_smiles=canonical,
            formal_charge=formal_charge,
            protonation_candidate_index=protonation_index,
            tautomer_index=tautomer_index,
            matches_parent_state=canonical == parent_smiles,
        )
        for index, (canonical, formal_charge, protonation_index, tautomer_index)
        in enumerate(selected)
    ]
    return LigandMicrostateOptions(
        parent_state_id=parent_state_id,
        plan=plan,
        candidates=candidates,
        protonation_candidate_count=len(protomers),
        enumerated_candidate_count=enumerated_count,
        truncated=per_protomer_truncated or total_truncated,
        dimorphite_version=_dimorphite_version(),
        rdkit_version=rdBase.rdkitVersion,
    )


def _protonation_smiles(molecule: Any, plan: LigandMicrostatePlan) -> list[str]:
    source_smiles = Chem.MolToSmiles(molecule, isomericSmiles=True)
    try:
        variants = _dimorphite.protonate_smiles(
            source_smiles,
            ph_min=plan.ph_min,
            ph_max=plan.ph_max,
            precision=plan.precision,
        )
    except Exception as error:
        raise _microstate_error(
            "LIGAND_PROTONATION_ENUMERATION_FAILED",
            "Dimorphite-DL could not enumerate protonation states for this molecule.",
            details={"technical_message": str(error)},
        ) from error
    canonical = {
        Chem.MolToSmiles(candidate, isomericSmiles=True)
        for value in variants
        if (candidate := Chem.MolFromSmiles(value)) is not None
    }
    if not canonical:
        raise _microstate_error(
            "LIGAND_PROTONATION_ENUMERATION_FAILED",
            "Dimorphite-DL returned no usable protonation states for this molecule.",
        )
    return sorted(canonical)


def _truncation_warnings(
    options: LigandMicrostateOptions,
) -> list[StructuredWarning]:
    if not options.truncated:
        return []
    return [
        StructuredWarning(
            code=WarningCode.LIG_MICROSTATE_ENUMERATION_TRUNCATED,
            message=(
                "The scientist accepted a bounded microstate set. Additional "
                "protonation/tautomer candidates may exist outside the recorded limits."
            ),
            stage="ligand_microstate_enumeration",
            details={
                "enumerated_candidate_count": options.enumerated_candidate_count,
                "retained_candidate_count": len(options.candidates),
                "max_tautomers_per_protomer": (
                    options.plan.max_tautomers_per_protomer
                ),
                "max_microstates_per_parent": (
                    options.plan.max_microstates_per_parent
                ),
            },
            recoverable=True,
        )
    ]


def _read_state(ligand_id: str, state_id: str, store: LigandArtifactStore) -> Any:
    supplier = Chem.SDMolSupplier(
        str(store.state_content_path(ligand_id, state_id)), removeHs=False
    )
    molecule = supplier[0] if len(supplier) else None
    if molecule is None:
        raise _microstate_error(
            "LIGAND_STATE_UNREADABLE",
            "The selected parent chemical state could not be read.",
        )
    return molecule


def _dimorphite_version() -> str:
    try:
        return metadata.version("dimorphite-dl")
    except metadata.PackageNotFoundError:
        return "unknown"


def _microstate_error(
    code: str,
    message: str,
    *,
    details: dict[str, object] | None = None,
) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code,
        stage="ligand_microstate_enumeration",
        message=message,
        status_code=422,
        details=details,
    )
