"""Verify a selected ligand's prepared derivatives before a GNINA campaign."""

from hashlib import sha256
from pathlib import Path

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligand_library_preparation import (
    LigandPreparationEntry,
    LigandPreparationStatus,
)
from ankora_backend.schemas.ligands import LigandConformerRecord, LigandPdbqtRecord


def verified_screening_preparation(
    *,
    store: LigandArtifactStore,
    ligand_id: str,
    expected_state_id: str,
    preparation: LigandPreparationEntry,
) -> tuple[LigandPdbqtRecord, LigandConformerRecord]:
    """Verify the recorded PDBQT and conformer for one selected chemical state.

    The caller is responsible for deriving the state identity from a verified
    applied selection and obtaining the entry from its own project and library.
    This check neither generates nor changes a chemical state or a conformer.
    """
    if (
        preparation.ligand_id != ligand_id
        or preparation.status is not LigandPreparationStatus.PREPARED
        or preparation.pdbqt_preparation_id is None
        or preparation.conformer_id is None
    ):
        raise _error("GNINA_SCREENING_LIGAND_NOT_PREPARED", ligand_id)
    if preparation.chemical_state_id != expected_state_id:
        raise _error("GNINA_SCREENING_STATE_MISMATCH", ligand_id)

    pdbqt = store.load_pdbqt_record(ligand_id, preparation.pdbqt_preparation_id)
    if (
        pdbqt.artifact.ligand_id != ligand_id
        or pdbqt.artifact.preparation_id != preparation.pdbqt_preparation_id
        or pdbqt.artifact.conformer_id != preparation.conformer_id
    ):
        raise _error("GNINA_SCREENING_PREPARATION_MISMATCH", ligand_id)
    conformer = store.load_conformer_record(ligand_id, preparation.conformer_id)
    if (
        conformer.artifact.ligand_id != ligand_id
        or conformer.artifact.conformer_id != preparation.conformer_id
        or conformer.artifact.chemical_state_id != expected_state_id
    ):
        raise _error("GNINA_SCREENING_STATE_MISMATCH", ligand_id)

    _verify_file(
        store.pdbqt_content_path(ligand_id, preparation.pdbqt_preparation_id),
        pdbqt.artifact.sha256,
        pdbqt.artifact.size_bytes,
        ligand_id,
    )
    _verify_file(
        store.conformer_content_path(ligand_id, preparation.conformer_id),
        conformer.artifact.sha256,
        conformer.artifact.size_bytes,
        ligand_id,
    )
    return pdbqt, conformer


def _verify_file(path: Path, expected_hash: str, expected_size: int, ligand_id: str) -> None:
    digest = sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
    except OSError as error:
        raise _error("GNINA_SCREENING_PREPARATION_INTEGRITY_FAILED", ligand_id) from error
    if size != expected_size or digest.hexdigest() != expected_hash:
        raise _error("GNINA_SCREENING_PREPARATION_INTEGRITY_FAILED", ligand_id)


def _error(code: str, ligand_id: str) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code,
        stage="gnina_screening",
        message="The selected ligand's prepared artifacts are unavailable or inconsistent.",
        status_code=409,
        details={"ligand_id": ligand_id},
    )
