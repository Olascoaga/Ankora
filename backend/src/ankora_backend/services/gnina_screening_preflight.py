"""Resolve every applied selection entry before starting GNINA screening."""

from dataclasses import dataclass
from datetime import datetime

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.docking import DockingFailure, DockingJobPhase, DockingJobStatus
from ankora_backend.schemas.gnina_screening import GninaScreeningEntry
from ankora_backend.schemas.ligands import LigandLibraryFilterRun
from ankora_backend.services.gnina_screening_preparation import verified_screening_preparation
from ankora_backend.services.gnina_screening_selection import verified_screening_selection


@dataclass(frozen=True, slots=True)
class GninaScreeningPreflight:
    """One verified selection and one outcome for each selected molecule."""

    selection: LigandLibraryFilterRun
    entries: tuple[GninaScreeningEntry, ...]


def prepare_screening_entries(
    *, store: LigandArtifactStore, library_id: str, filter_run_id: str, now: datetime
) -> GninaScreeningPreflight:
    """Inspect selected derivatives once without starting any GNINA work.

    Per-ligand failures remain in selection order; they do not prevent ready
    neighbors from being queued. A damaged or mismatched selection fails the
    whole preflight because its identities are no longer trustworthy.
    """
    selection = verified_screening_selection(
        store=store, library_id=library_id, filter_run_id=filter_run_id
    )
    library = store.load_library_record(library_id)
    preparations = store.load_preparation_status(library_id)
    if library.artifact.library_id != library_id or preparations.library_id != library_id:
        raise AnkoraDomainError(
            code="GNINA_SCREENING_LIBRARY_MISMATCH",
            stage="gnina_screening",
            message="The library or its preparation status belongs to another library.",
            status_code=409,
            details={"library_id": library_id},
        )
    sources = {}
    duplicate_ids = set()
    for library_entry in library.entries:
        if library_entry.ligand is not None:
            ligand_id = library_entry.ligand.artifact.ligand_id
            if ligand_id in sources:
                duplicate_ids.add(ligand_id)
            sources[ligand_id] = library_entry
    evaluations = {item.ligand_id: item for item in selection.evaluations}
    entries: list[GninaScreeningEntry] = []
    for ligand_id in selection.selected_ligand_ids:
        evaluation = evaluations[ligand_id]
        source = sources.get(ligand_id)
        if (
            source is None
            or source.ligand is None
            or ligand_id in duplicate_ids
            or source.record_index != evaluation.record_index
            or source.ligand.artifact.library_id != library_id
            or (
                source.ligand.artifact.library_record_index is not None
                and source.ligand.artifact.library_record_index != source.record_index
            )
        ):
            entries.append(
                _failure(
                    ligand_id=ligand_id,
                    state_id=evaluation.state_id,
                    source_index=None,
                    name=None,
                    now=now,
                    code="GNINA_SCREENING_LIBRARY_RECORD_MISSING",
                    message="The selected molecule's library record is missing or inconsistent.",
                )
            )
            continue
        preparation = preparations.entries.get(ligand_id)
        if preparation is None:
            entries.append(
                _failure(
                    ligand_id=ligand_id,
                    state_id=evaluation.state_id,
                    source_index=source.record_index,
                    name=source.ligand.inspection.name,
                    now=now,
                    code="GNINA_SCREENING_LIGAND_NOT_PREPARED",
                    message="The selected molecule has no recorded docking preparation.",
                )
            )
            continue
        try:
            pdbqt, conformer = verified_screening_preparation(
                store=store,
                ligand_id=ligand_id,
                expected_state_id=evaluation.state_id,
                preparation=preparation,
            )
        except (AnkoraDomainError, OSError, ValueError) as error:
            code = (
                error.code
                if isinstance(error, AnkoraDomainError)
                else "GNINA_SCREENING_PREPARATION_UNAVAILABLE"
            )
            entries.append(
                _failure(
                    ligand_id=ligand_id,
                    state_id=evaluation.state_id,
                    source_index=source.record_index,
                    name=source.ligand.inspection.name,
                    now=now,
                    code=code,
                    message="The selected molecule's prepared artifacts could not be verified.",
                )
            )
            continue
        entries.append(
            GninaScreeningEntry(
                ligand_id=ligand_id,
                chemical_state_id=evaluation.state_id,
                source_index=source.record_index,
                name=source.ligand.inspection.name,
                ligand_preparation_id=pdbqt.artifact.preparation_id,
                ligand_sha256=pdbqt.artifact.sha256,
                conformer_id=conformer.artifact.conformer_id,
                conformer_sha256=conformer.artifact.sha256,
                status=DockingJobStatus.QUEUED,
                phase=DockingJobPhase.QUEUED,
            )
        )
    return GninaScreeningPreflight(selection=selection, entries=tuple(entries))


def _failure(
    *,
    ligand_id: str,
    state_id: str,
    source_index: int | None,
    name: str | None,
    now: datetime,
    code: str,
    message: str,
) -> GninaScreeningEntry:
    return GninaScreeningEntry(
        ligand_id=ligand_id,
        chemical_state_id=state_id,
        source_index=source_index,
        name=name,
        status=DockingJobStatus.FAILED,
        phase=DockingJobPhase.COMPLETE,
        completed_at=now,
        failure=DockingFailure(code=code, message=message, details={"ligand_id": ligand_id}),
    )
