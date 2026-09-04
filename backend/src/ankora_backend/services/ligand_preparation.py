"""Create-only ligand PDBQT preparation from an accepted converged conformer."""

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from ankora_backend.adapters.tools.ligand_preparation import execute_meeko_ligand
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligand_library_preparation import LigandPreparationStatus
from ankora_backend.schemas.ligands import (
    LigandPdbqtArtifact,
    LigandPdbqtRecord,
    LigandRecord,
    PrepareLigandPdbqtRequest,
)
from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.services.ligand_library_status import record_library_status


def prepare_ligand_pdbqt(
    *,
    ligand_id: str,
    conformer_id: str,
    request: PrepareLigandPdbqtRequest,
    store: LigandArtifactStore,
) -> LigandPdbqtRecord:
    original = store.load_record(ligand_id)
    conformer = store.load_conformer_record(ligand_id, conformer_id)
    try:
        record = _prepare_and_store_pdbqt(
            ligand_id=ligand_id,
            conformer_id=conformer_id,
            request=request,
            store=store,
            original=original,
        )
    except AnkoraDomainError as error:
        record_library_status(
            store,
            original,
            status=LigandPreparationStatus.FAILED,
            conformer_id=conformer_id,
            chemical_state_id=conformer.artifact.chemical_state_id,
            chemical_state_formal_charge=conformer.inspection.formal_charge,
            initial_energy_kcal_mol=conformer.minimization.initial_energy_kcal_mol,
            final_energy_kcal_mol=conformer.minimization.final_energy_kcal_mol,
            error_message=error.message,
        )
        raise
    record_library_status(
        store,
        original,
        status=LigandPreparationStatus.PREPARED,
        conformer_id=conformer_id,
        pdbqt_preparation_id=record.artifact.preparation_id,
        chemical_state_id=conformer.artifact.chemical_state_id,
        chemical_state_formal_charge=conformer.inspection.formal_charge,
        initial_energy_kcal_mol=conformer.minimization.initial_energy_kcal_mol,
        final_energy_kcal_mol=conformer.minimization.final_energy_kcal_mol,
    )
    return record


def _prepare_and_store_pdbqt(
    *,
    ligand_id: str,
    conformer_id: str,
    request: PrepareLigandPdbqtRequest,
    store: LigandArtifactStore,
    original: LigandRecord,
) -> LigandPdbqtRecord:
    conformer = store.load_conformer_record(ligand_id, conformer_id)
    if conformer.artifact.ligand_id != ligand_id:
        raise _preparation_error(
            "LIGAND_CONFORMER_MISMATCH",
            "The selected conformer does not belong to this ligand.",
        )
    if not conformer.minimization.converged:
        raise _preparation_error(
            "LIGAND_CONFORMER_NOT_CONVERGED",
            "Meeko preparation requires a conformer whose MMFF minimization converged.",
            details={"conformer_id": conformer_id},
        )
    preparation_id = store.new_preparation_id()
    created_at = datetime.now(UTC)
    with TemporaryDirectory(prefix="ankora-meeko-ligand-") as temporary_directory:
        output_path = Path(temporary_directory) / "prepared_ligand.pdbqt"
        execution, version = execute_meeko_ligand(
            input_sdf_path=store.conformer_content_path(ligand_id, conformer_id),
            output_pdbqt_path=output_path,
            charge_model=request.charge_model,
        )
        if execution.exit_code != 0 or not output_path.is_file():
            details: dict[str, object] = {
                "preparation_id": preparation_id,
                "conformer_id": conformer_id,
                "tool_version": version,
                "command": execution.command,
                "exit_code": execution.exit_code,
                "stdout": execution.stdout,
                "stderr": execution.stderr,
            }
            store.create_pdbqt_failure(
                ligand_id,
                preparation_id,
                {
                    "code": "MEEKO_LIGAND_PREPARATION_FAILED",
                    "stage": "ligand_pdbqt",
                    "created_at": created_at.isoformat(),
                    **details,
                },
                execution.stdout,
                execution.stderr,
            )
            raise _preparation_error(
                "MEEKO_LIGAND_PREPARATION_FAILED",
                "Meeko could not generate a docking-ready ligand from the converged conformer.",
                details=details,
            )
        content = output_path.read_bytes()
    if not content:
        raise _preparation_error(
            "MEEKO_LIGAND_OUTPUT_EMPTY",
            "Meeko reported success but produced an empty ligand PDBQT file.",
        )
    artifact = LigandPdbqtArtifact(
        preparation_id=preparation_id,
        ligand_id=ligand_id,
        conformer_id=conformer_id,
        filename=f"{original.inspection.name}_prepared.pdbqt",
        format="pdbqt",
        sha256=sha256(content).hexdigest(),
        size_bytes=len(content),
        created_at=created_at,
    )
    tool = ToolIdentity(name="Meeko ligand preparation", version=version)
    provenance = ProvenanceEvent(
        event_id=f"ligand_pdbqt-{preparation_id}",
        event_type="ligand_pdbqt_prepared",
        timestamp=created_at,
        input_artifacts=[conformer_id],
        output_artifacts=[preparation_id],
        tool=tool,
        parameters={
            **request.model_dump(mode="json"),
            "conformer_converged": True,
            "source_conformer_sha256": conformer.artifact.sha256,
        },
        warnings=[],
        command=execution.command,
    )
    record = LigandPdbqtRecord(
        artifact=artifact,
        charge_model=request.charge_model,
        tool=tool,
        command=execution.command,
        stdout=execution.stdout,
        stderr=execution.stderr,
        provenance=provenance,
        content_url=f"/ligands/{ligand_id}/preparations/{preparation_id}/content",
    )
    store.create_pdbqt(ligand_id, preparation_id, content, record)
    return record


def _preparation_error(
    code: str, message: str, *, details: dict[str, object] | None = None
) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code,
        stage="ligand_pdbqt",
        message=message,
        status_code=422,
        details=details,
    )
