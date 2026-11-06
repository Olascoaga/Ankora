"""Synthetic library preflight; Meeko is faked and GNINA is never invoked."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from test_gnina_screening_schema import _record, _request
from test_ligand_filtering import _library

from ankora_backend.execution.subprocess_runner import ToolExecution
from ankora_backend.persistence.gnina_screening_store import GninaScreeningStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.docking import DockingJobPhase, DockingJobStatus
from ankora_backend.schemas.gnina_screening import GninaScreeningSelection
from ankora_backend.schemas.ligands import (
    ApplyLigandLibraryFilterRequest,
    GenerateLigandConformerRequest,
    PrepareLigandPdbqtRequest,
)
from ankora_backend.services.gnina_screening_preflight import prepare_screening_entries
from ankora_backend.services.ligand_filtering import apply_library_filters
from ankora_backend.services.ligand_minimization import generate_ligand_conformer
from ankora_backend.services.ligand_preparation import prepare_ligand_pdbqt


@pytest.fixture
def screening(tmp_path: Path):
    store = LigandArtifactStore(tmp_path)
    library = _library(store)
    selection = apply_library_filters(
        library_id=library.artifact.library_id,
        request=ApplyLigandLibraryFilterRequest(acknowledge_selection=True),
        store=store,
        worker_limit=1,
    )
    assert len(selection.selected_ligand_ids) == 2
    return store, library, selection


@pytest.fixture
def one_prepared(screening, monkeypatch):
    store, _library_record, selection = screening
    ligand_id = selection.selected_ligand_ids[0]
    state = next(item.state_id for item in selection.evaluations if item.ligand_id == ligand_id)
    conformer = generate_ligand_conformer(
        ligand_id=ligand_id,
        request=GenerateLigandConformerRequest(
            acknowledge_current_chemical_state=True, state_id=state, random_seed=73191
        ),
        store=store,
    )

    def fake_meeko(**kwargs):
        kwargs["output_pdbqt_path"].write_bytes(b"ROOT\nENDROOT\nTORSDOF 0\n")
        return ToolExecution(
            command=["synthetic-meeko"], exit_code=0, stdout="", stderr=""
        ), "0.7.1"

    monkeypatch.setattr(
        "ankora_backend.services.ligand_preparation.execute_meeko_ligand", fake_meeko
    )
    pdbqt = prepare_ligand_pdbqt(
        ligand_id=ligand_id,
        conformer_id=conformer.artifact.conformer_id,
        request=PrepareLigandPdbqtRequest(),
        store=store,
    )
    return screening, conformer, pdbqt


def _preflight(screening):
    store, library, selection = screening
    return prepare_screening_entries(
        store=store,
        library_id=library.artifact.library_id,
        filter_run_id=selection.artifact.filter_run_id,
        now=datetime.now(UTC),
    )


def test_unprepared_entries_are_retained_in_the_exact_selection_order(screening):
    result = _preflight(screening)
    assert [entry.ligand_id for entry in result.entries] == result.selection.selected_ligand_ids
    assert all(entry.status is DockingJobStatus.FAILED for entry in result.entries)
    assert all(
        entry.failure.code == "GNINA_SCREENING_LIGAND_NOT_PREPARED" for entry in result.entries
    )


def test_one_prepared_ligand_can_be_queued_while_its_neighbor_fails(one_prepared):
    screening, conformer, pdbqt = one_prepared
    result = _preflight(screening)
    first, second = result.entries
    assert first.status is DockingJobStatus.QUEUED
    assert first.ligand_sha256 == pdbqt.artifact.sha256
    assert first.conformer_sha256 == conformer.artifact.sha256
    assert first.chemical_state_id == conformer.artifact.chemical_state_id
    assert second.status is DockingJobStatus.FAILED


def test_changed_prepared_pdbqt_becomes_an_explicit_entry_failure(one_prepared):
    screening, _conformer, pdbqt = one_prepared
    store, _library_record, _selection = screening
    store.pdbqt_content_path(pdbqt.artifact.ligand_id, pdbqt.artifact.preparation_id).write_bytes(
        b"altered synthetic input"
    )
    first = _preflight(screening).entries[0]
    assert first.status is DockingJobStatus.FAILED
    assert first.failure.code == "GNINA_SCREENING_PREPARATION_INTEGRITY_FAILED"


def test_wrong_prepared_state_is_not_silently_used(one_prepared):
    screening, _conformer, pdbqt = one_prepared
    store, library, _selection = screening
    status = store.load_preparation_status(library.artifact.library_id).entries[
        pdbqt.artifact.ligand_id
    ]
    store.upsert_preparation_entry(
        library.artifact.library_id, status.model_copy(update={"chemical_state_id": "wrong-state"})
    )
    first = _preflight(screening).entries[0]
    assert first.status is DockingJobStatus.FAILED
    assert first.failure.code == "GNINA_SCREENING_STATE_MISMATCH"


def test_missing_library_row_is_retained_as_a_failed_entry(screening):
    store, library, selection = screening
    path = store.library_content_path(library.artifact.library_id).parent / "record.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    missing_id = selection.selected_ligand_ids[0]
    record["entries"] = [
        row
        for row in record["entries"]
        if row["ligand"] is None or row["ligand"]["artifact"]["ligand_id"] != missing_id
    ]
    path.write_text(json.dumps(record), encoding="utf-8")
    first = _preflight(screening).entries[0]
    assert first.ligand_id == missing_id and first.source_index is None
    assert first.failure.code == "GNINA_SCREENING_LIBRARY_RECORD_MISSING"


def test_preflight_outcomes_can_be_persisted_against_the_same_selection(one_prepared, tmp_path):
    screening, _conformer, _pdbqt = one_prepared
    _store, library, selection = screening
    result = _preflight(screening)
    request = _request(
        library_id=library.artifact.library_id, filter_run_id=selection.artifact.filter_run_id
    )
    pinned = GninaScreeningSelection(
        library_id=library.artifact.library_id,
        filter_run_id=selection.artifact.filter_run_id,
        manifest_artifact_id=selection.artifact.filter_run_id,
        manifest_sha256=selection.artifact.sha256,
    )
    campaign = _record(
        list(result.entries),
        campaign_id=str(uuid4()),
        status=DockingJobStatus.QUEUED,
        phase=DockingJobPhase.QUEUED,
        request=request,
        selection=pinned,
    )
    store = GninaScreeningStore(tmp_path)
    store.create_campaign(campaign)
    progress = store.load_progress(campaign.campaign_id)
    assert (progress.selected_count, progress.failed_count) == (2, 1)
    assert [entry.status for entry in store.load_campaign(campaign.campaign_id).entries] == [
        DockingJobStatus.QUEUED,
        DockingJobStatus.FAILED,
    ]
