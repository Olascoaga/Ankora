"""Explicit immutable 3D conformer generation and MMFF minimization."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import Any

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligand_library_preparation import LigandPreparationStatus
from ankora_backend.schemas.ligands import (
    GenerateLigandConformerRequest,
    LigandConformerArtifact,
    LigandConformerRecord,
    LigandConformerSelectionPolicy,
    LigandMinimizationResult,
    LigandRecord,
    MinimizeLigandRequest,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode
from ankora_backend.services.ligand_import import inspect_ligand_molecule
from ankora_backend.services.ligand_library_status import record_library_status

Chem: Any = import_module("rdkit.Chem")
AllChem: Any = import_module("rdkit.Chem.AllChem")
rdBase: Any = import_module("rdkit.rdBase")

# A single ETKDGv3 embed can converge to a high-energy local minimum, especially
# for flexible ligands or macrocycles whose ring conformation Vina/GNINA cannot
# later correct (they keep rings and bond geometry rigid during docking).
# Independent generation therefore embeds a pool and keeps the lowest-MMFF-energy
# member, rather than trusting a single embedding seed.
_CONFORMER_POOL_SIZE = 20

# Errors raised before a conformer exists that require an explicit user decision
# rather than representing a scientific/tool failure. A library batch run records
# these distinctly so the UI can route the ligand back to review, not "failed".
_NEEDS_DECISION_ERROR_CODES = {
    "LIGAND_STATE_CONFIRMATION_REQUIRED",
    WarningCode.LIG_STEREOCHEMISTRY_UNDEFINED.value,
    "LIGAND_MULTICOMPONENT_REQUIRES_DECISION",
}


@dataclass(frozen=True, slots=True)
class _MinimizationOutcome:
    conf_id: int
    initial_energy_kcal_mol: float
    final_energy_kcal_mol: float
    converged: bool
    warnings: list[StructuredWarning]


def _select_pool_outcome(
    outcomes: list[_MinimizationOutcome], *, max_iterations: int
) -> _MinimizationOutcome:
    """Prefer convergence before comparing energies within one MMFF pool."""
    if not outcomes:
        raise ValueError("A conformer pool selection requires at least one outcome.")
    converged = [outcome for outcome in outcomes if outcome.converged]
    candidates = converged or outcomes
    selected = min(
        candidates,
        key=lambda outcome: (outcome.final_energy_kcal_mol, outcome.conf_id),
    )
    if converged:
        return selected
    return replace(
        selected,
        warnings=[
            StructuredWarning(
                code=WarningCode.LIG_MINIMIZATION_NOT_CONVERGED,
                message=(
                    f"None of the {len(outcomes)} embedded conformers converged "
                    "within the configured MMFF iteration limit. The lowest-energy "
                    "nonconverged outcome is preserved for review and cannot be sent "
                    "to Meeko."
                ),
                stage="ligand_minimization",
                details={
                    "max_iterations": max_iterations,
                    "conformer_pool_size": len(outcomes),
                    "converged_count": 0,
                    "selected_conformer_id": selected.conf_id,
                    "selection_policy": "lowest_energy_nonconverged_fallback",
                },
                recoverable=True,
            )
        ],
    )


def _status_for_conformer_error(code: str) -> LigandPreparationStatus:
    return (
        LigandPreparationStatus.NEEDS_DECISION
        if code in _NEEDS_DECISION_ERROR_CODES
        else LigandPreparationStatus.FAILED
    )


def minimize_ligand(
    *,
    ligand_id: str,
    request: MinimizeLigandRequest,
    store: LigandArtifactStore,
) -> LigandConformerRecord:
    original = store.load_record(ligand_id)
    try:
        state_id, molecule = _load_confirmed_state(ligand_id, original, request, store)
        conformers = list(molecule.GetConformers())
        if len(conformers) != 1 or not conformers[0].Is3D():
            raise AnkoraDomainError(
                code="LIGAND_3D_CONFORMER_REQUIRED",
                stage="ligand_minimization",
                message=(
                    "A single 3D conformer is required. Generate an independent 3D "
                    "conformer for this ligand first."
                ),
                status_code=422,
            )
        molecule = Chem.AddHs(molecule, addCoords=True)
        outcome = _run_mmff_minimization(molecule, 0, request)
        record = _minimize_and_store(
            ligand_id=ligand_id,
            original=original,
            state_id=state_id,
            molecule=molecule,
            request=request,
            store=store,
            stage="minimized",
            embedding_method=None,
            random_seed=None,
            independent=False,
            outcome=outcome,
        )
    except AnkoraDomainError as error:
        record_library_status(
            store,
            original,
            status=_status_for_conformer_error(error.code),
            error_message=error.message,
        )
        raise
    record_library_status(
        store,
        original,
        status=LigandPreparationStatus.MINIMIZED
        if record.minimization.converged
        else LigandPreparationStatus.NONCONVERGED,
        conformer_id=record.artifact.conformer_id,
        final_energy_kcal_mol=record.minimization.final_energy_kcal_mol,
    )
    return record


def generate_ligand_conformer(
    *,
    ligand_id: str,
    request: GenerateLigandConformerRequest,
    store: LigandArtifactStore,
) -> LigandConformerRecord:
    original = store.load_record(ligand_id)
    try:
        state_id, molecule = _load_confirmed_state(ligand_id, original, request, store)
        molecule.RemoveAllConformers()
        molecule = Chem.AddHs(molecule)
        parameters = AllChem.ETKDGv3()
        parameters.randomSeed = request.random_seed
        parameters.enforceChirality = True
        parameters.clearConfs = True
        try:
            conformer_ids = list(
                AllChem.EmbedMultipleConfs(
                    molecule, numConfs=_CONFORMER_POOL_SIZE, params=parameters
                )
            )
        except RuntimeError as error:
            raise _generation_error(request.random_seed, str(error)) from error
        if not conformer_ids:
            raise _generation_error(
                request.random_seed, "RDKit could not embed any conformer in the pool"
            )
        outcomes = [
            _run_mmff_minimization(molecule, conf_id, request) for conf_id in conformer_ids
        ]
        best_outcome = _select_pool_outcome(
            outcomes, max_iterations=request.max_iterations
        )
        converged_count = sum(outcome.converged for outcome in outcomes)
        record = _minimize_and_store(
            ligand_id=ligand_id,
            original=original,
            state_id=state_id,
            molecule=molecule,
            request=request,
            store=store,
            stage="generated_minimized",
            embedding_method="ETKDGv3",
            random_seed=request.random_seed,
            independent=True,
            outcome=best_outcome,
            conformer_pool_size=len(conformer_ids),
            conformer_pool_converged_count=converged_count,
            conformer_selection_policy=(
                LigandConformerSelectionPolicy.LOWEST_ENERGY_CONVERGED
                if converged_count
                else LigandConformerSelectionPolicy.LOWEST_ENERGY_NONCONVERGED_FALLBACK
            ),
        )
    except AnkoraDomainError as error:
        record_library_status(
            store,
            original,
            status=_status_for_conformer_error(error.code),
            error_message=error.message,
        )
        raise
    record_library_status(
        store,
        original,
        status=LigandPreparationStatus.MINIMIZED
        if record.minimization.converged
        else LigandPreparationStatus.NONCONVERGED,
        conformer_id=record.artifact.conformer_id,
        final_energy_kcal_mol=record.minimization.final_energy_kcal_mol,
    )
    return record


def _load_confirmed_state(
    ligand_id: str,
    original: LigandRecord,
    request: MinimizeLigandRequest,
    store: LigandArtifactStore,
) -> tuple[str, Any]:
    if not request.acknowledge_current_chemical_state:
        raise AnkoraDomainError(
            code="LIGAND_STATE_CONFIRMATION_REQUIRED",
            stage="ligand_minimization",
            message=(
                "Confirm the currently inspected formal charge, bond orders, and "
                "stereochemistry before conformer generation or minimization."
            ),
            status_code=422,
            details={"ligand_id": ligand_id},
        )
    default_state_id = original.state.state_id if original.state is not None else ligand_id
    state_id = request.state_id or default_state_id
    molecule = _read_molecule(store.state_content_path(ligand_id, state_id))
    chiral_centers = Chem.FindMolChiralCenters(molecule, includeUnassigned=True)
    undefined_centers = [index for index, label in chiral_centers if label == "?"]
    if undefined_centers:
        raise AnkoraDomainError(
            code=WarningCode.LIG_STEREOCHEMISTRY_UNDEFINED.value,
            stage="ligand_minimization",
            message=(
                "Undefined stereocenters require an explicit state decision before "
                "conformer generation or minimization."
            ),
            status_code=422,
            details={"atom_indices": undefined_centers},
        )
    fragment_count = len(Chem.GetMolFrags(molecule))
    if fragment_count != 1:
        raise AnkoraDomainError(
            code="LIGAND_MULTICOMPONENT_REQUIRES_DECISION",
            stage="ligand_minimization",
            message=(
                "Multiple disconnected components require an explicit salt/component "
                "decision before conformer generation."
            ),
            status_code=422,
            details={"fragment_count": fragment_count},
        )
    return state_id, molecule


def _run_mmff_minimization(
    molecule: Any, conf_id: int, request: MinimizeLigandRequest
) -> _MinimizationOutcome:
    properties = AllChem.MMFFGetMoleculeProperties(
        molecule, mmffVariant=request.force_field.value
    )
    if properties is None:
        raise AnkoraDomainError(
            code="LIGAND_MMFF_UNAVAILABLE",
            stage="ligand_minimization",
            message="MMFF parameters are unavailable for the current ligand chemical state.",
            status_code=422,
            details={"force_field": request.force_field.value},
        )
    force_field = AllChem.MMFFGetMoleculeForceField(molecule, properties, confId=conf_id)
    if force_field is None:
        raise AnkoraDomainError(
            code="LIGAND_MMFF_SETUP_FAILED",
            stage="ligand_minimization",
            message="RDKit could not construct the requested MMFF force field.",
            status_code=422,
            details={"force_field": request.force_field.value},
        )
    initial_energy = float(force_field.CalcEnergy())
    try:
        status = int(force_field.Minimize(maxIts=request.max_iterations))
    except RuntimeError as error:
        raise AnkoraDomainError(
            code="LIGAND_MINIMIZATION_FAILED",
            stage="ligand_minimization",
            message="RDKit MMFF could not minimize the supplied starting geometry.",
            status_code=422,
            details={
                "force_field": request.force_field.value,
                "technical_message": str(error),
            },
        ) from error
    final_energy = float(force_field.CalcEnergy())
    return _MinimizationOutcome(
        conf_id=conf_id,
        initial_energy_kcal_mol=initial_energy,
        final_energy_kcal_mol=final_energy,
        converged=status == 0,
        warnings=_convergence_warnings(request.max_iterations, status),
    )


def _minimize_and_store(
    *,
    ligand_id: str,
    original: LigandRecord,
    state_id: str,
    molecule: Any,
    request: MinimizeLigandRequest,
    store: LigandArtifactStore,
    stage: str,
    embedding_method: str | None,
    random_seed: int | None,
    independent: bool,
    outcome: _MinimizationOutcome,
    conformer_pool_size: int | None = None,
    conformer_pool_converged_count: int | None = None,
    conformer_selection_policy: LigandConformerSelectionPolicy | None = None,
) -> LigandConformerRecord:
    for conformer in list(molecule.GetConformers()):
        if conformer.GetId() != outcome.conf_id:
            molecule.RemoveConformer(conformer.GetId())
    molecule.SetProp("_Name", original.inspection.name)
    content = (
        Chem.MolToMolBlock(molecule, confId=outcome.conf_id) + "\n$$$$\n"
    ).encode("utf-8")
    conformer_id = store.new_conformer_id()
    created_at = datetime.now(UTC)
    inspection = inspect_ligand_molecule(molecule, original.inspection.name)
    suffix = "ETKDGv3" if independent else "source_geometry"
    artifact = LigandConformerArtifact(
        conformer_id=conformer_id,
        ligand_id=ligand_id,
        stage=stage,
        filename=(
            f"{original.inspection.name}_{suffix}_"
            f"{request.force_field.value}_minimized.sdf"
        ),
        format="sdf",
        sha256=sha256(content).hexdigest(),
        size_bytes=len(content),
        created_at=created_at,
    )
    minimization = LigandMinimizationResult(
        force_field=request.force_field,
        max_iterations=request.max_iterations,
        converged=outcome.converged,
        initial_energy_kcal_mol=outcome.initial_energy_kcal_mol,
        final_energy_kcal_mol=outcome.final_energy_kcal_mol,
        embedding_method=embedding_method,
        random_seed=random_seed,
        independent_from_source_coordinates=independent,
        conformer_pool_size=conformer_pool_size,
        conformer_pool_converged_count=conformer_pool_converged_count,
        conformer_selection_policy=conformer_selection_policy,
    )
    parameters: dict[str, object] = {
        **request.model_dump(mode="json"),
        "explicit_hydrogens_added": True,
        "starting_coordinates": (
            "independent_ETKDGv3" if independent else "parent_ligand_conformer_0"
        ),
        "conformer_pool_size": conformer_pool_size,
        "conformer_pool_converged_count": conformer_pool_converged_count,
        "conformer_pool_nonconverged_count": (
            conformer_pool_size - conformer_pool_converged_count
            if conformer_pool_size is not None
            and conformer_pool_converged_count is not None
            else None
        ),
        "conformer_selection_policy": (
            conformer_selection_policy.value if conformer_selection_policy else None
        ),
        "selected_conformer_id": outcome.conf_id,
    }
    warnings = outcome.warnings
    provenance = ProvenanceEvent(
        event_id=f"ligand_conformer-{conformer_id}",
        event_type=(
            "ligand_conformer_generated_and_minimized"
            if independent
            else "ligand_conformer_minimized"
        ),
        timestamp=created_at,
        input_artifacts=[state_id],
        output_artifacts=[conformer_id],
        tool=ToolIdentity(name="RDKit ETKDG/MMFF", version=rdBase.rdkitVersion),
        parameters=parameters,
        warnings=warnings,
        command=None,
    )
    record = LigandConformerRecord(
        artifact=artifact,
        inspection=inspection,
        minimization=minimization,
        warnings=warnings,
        provenance=provenance,
        content_url=f"/ligands/{ligand_id}/conformers/{conformer_id}/content",
    )
    store.create_conformer(ligand_id, conformer_id, content, record)
    return record


def _read_molecule(path: Path) -> Any:
    supplier = Chem.SDMolSupplier(str(path), removeHs=False)
    molecule = supplier[0] if len(supplier) else None
    if molecule is None:
        raise AnkoraDomainError(
            code="LIGAND_STATE_UNREADABLE",
            stage="ligand_minimization",
            message="The inspected ligand chemical state could not be read.",
            status_code=422,
        )
    return molecule


def _convergence_warnings(
    max_iterations: int, status: int
) -> list[StructuredWarning]:
    if status == 0:
        return []
    return [
        StructuredWarning(
            code=WarningCode.LIG_MINIMIZATION_NOT_CONVERGED,
            message=(
                "MMFF reached the configured iteration limit. The derivative is preserved "
                "for review but is not marked converged."
            ),
            stage="ligand_minimization",
            details={"max_iterations": max_iterations, "status": status},
            recoverable=True,
        )
    ]


def _generation_error(random_seed: int, technical_message: str) -> AnkoraDomainError:
    return AnkoraDomainError(
        code="LIGAND_CONFORMER_GENERATION_FAILED",
        stage="ligand_conformer_generation",
        message="RDKit ETKDGv3 could not generate an independent 3D conformer.",
        status_code=422,
        details={"random_seed": random_seed, "technical_message": technical_message},
    )
