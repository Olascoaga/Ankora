"""Verify an applied selection before it can seed a GNINA campaign."""

import json
from hashlib import sha256

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.ligands import LigandFilterDisposition, LigandLibraryFilterRun


def verified_screening_selection(
    *, store: LigandArtifactStore, library_id: str, filter_run_id: str
) -> LigandLibraryFilterRun:
    """Return an applied filter record only when its immutable manifest agrees.

    This validates selection identity and chemical-state metadata. Preparation,
    receptor and binding-site identities are checked separately by callers.
    """
    record = store.load_filter_run(library_id, filter_run_id)
    artifact = record.artifact
    if artifact.library_id != library_id or artifact.filter_run_id != filter_run_id:
        raise _selection_error(library_id, filter_run_id)
    try:
        content = store.filter_run_content_path(library_id, filter_run_id).read_bytes()
        payload = json.loads(content)
    except (OSError, ValueError) as error:
        raise _selection_error(library_id, filter_run_id) from error
    if len(content) != artifact.size_bytes or sha256(content).hexdigest() != artifact.sha256:
        raise _selection_error(library_id, filter_run_id)
    expected = {
        "filter_run_id": artifact.filter_run_id,
        "library_id": artifact.library_id,
        "created_at": artifact.created_at.isoformat(),
        "rdkit_version": record.rdkit_version,
        "worker_count": record.worker_count,
        "plan": record.plan.model_dump(mode="json"),
        "microstate_plan": record.microstate_plan.model_dump(mode="json"),
        "summary": record.summary.model_dump(mode="json"),
        "selected_ligand_ids": record.selected_ligand_ids,
        "evaluations": [entry.model_dump(mode="json") for entry in record.evaluations],
    }
    if payload != expected:
        raise _selection_error(library_id, filter_run_id)
    eligible = [
        entry.ligand_id
        for entry in record.evaluations
        if entry.disposition is LigandFilterDisposition.ELIGIBLE
    ]
    if (
        len(set(eligible)) != len(eligible)
        or eligible != record.selected_ligand_ids
        or record.summary.eligible_count != len(eligible)
        or len({entry.ligand_id for entry in record.evaluations}) != len(record.evaluations)
    ):
        raise _selection_error(library_id, filter_run_id)
    if not eligible:
        raise AnkoraDomainError(
            code="GNINA_SELECTION_EMPTY",
            stage="gnina_screening",
            message="The applied library selection contains no eligible molecules.",
            status_code=409,
            details={"library_id": library_id, "filter_run_id": filter_run_id},
        )
    return record


def _selection_error(library_id: str, filter_run_id: str) -> AnkoraDomainError:
    return AnkoraDomainError(
        code="GNINA_SELECTION_INTEGRITY_FAILED",
        stage="gnina_screening",
        message="The applied library selection is missing, inconsistent or has changed.",
        status_code=409,
        details={"library_id": library_id, "filter_run_id": filter_run_id},
    )
