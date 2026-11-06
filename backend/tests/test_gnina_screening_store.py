"""Synthetic transactional persistence tests; no docking engine runs."""

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_gnina_screening_preparation import prepared as prepared
from test_gnina_screening_schema import _completed, _queued, _record, _request
from test_gnina_service import _setup
from test_ligand_filtering import _library

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.execution.cancellable_subprocess import CancellableToolExecution
from ankora_backend.persistence.gnina_screening_store import GninaScreeningStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.docking import DockingFailure, DockingJobPhase, DockingJobStatus
from ankora_backend.schemas.gnina_screening import GninaScreeningRequest, GninaScreeningSelection
from ankora_backend.schemas.ligands import ApplyLigandLibraryFilterRequest
from ankora_backend.services.ligand_filtering import apply_library_filters


def _initial(entries):
    entries = [
        entry
        if entry.chemical_state_id is not None
        else entry.model_copy(update={"chemical_state_id": f"state-{entry.ligand_id}"})
        for entry in entries
    ]
    return _record(
        entries,
        campaign_id=str(uuid4()),
        status=DockingJobStatus.QUEUED,
        phase=DockingJobPhase.QUEUED,
    )


def _create_synthetic(store, record, monkeypatch):
    """Stub a manifest only for transaction tests; real manifest is tested below."""
    selection = SimpleNamespace(
        artifact=SimpleNamespace(
            sha256=record.selection.manifest_sha256,
            filter_run_id=record.selection.manifest_artifact_id,
        ),
        selected_ligand_ids=list(record.selected_ligand_ids),
        evaluations=[
            SimpleNamespace(
                ligand_id=entry.ligand_id,
                state_id=entry.chemical_state_id,
                record_index=entry.source_index,
            )
            for entry in record.entries
        ],
    )
    monkeypatch.setattr(
        "ankora_backend.persistence.gnina_screening_store.verified_screening_selection",
        lambda **_kwargs: selection,
    )
    store.create_campaign(record)


def _failure(entry):
    return entry.model_copy(
        update={
            "status": DockingJobStatus.FAILED,
            "phase": DockingJobPhase.COMPLETE,
            "completed_at": datetime.now(UTC),
            "failure": DockingFailure(code="SYNTHETIC", message="synthetic failure"),
        }
    )


def test_persists_selection_order_and_small_progress_across_instances(tmp_path, monkeypatch):
    store = GninaScreeningStore(tmp_path)
    record = _initial([_queued("alpha", 8), _queued("beta", 2)])
    _create_synthetic(store, record, monkeypatch)
    failed = store.update_entry(record.campaign_id, _failure(record.entries[0]))
    assert failed.revision == 1
    reopened = GninaScreeningStore(tmp_path)
    progress = reopened.load_progress(record.campaign_id)
    assert progress.revision == 1
    assert (progress.selected_count, progress.completed_count, progress.failed_count) == (2, 1, 1)
    assert [entry.ligand_id for entry in reopened.load_campaign(record.campaign_id).entries] == [
        "alpha",
        "beta",
    ]
    assert [
        entry.ligand_id for entry in reopened.entries_after_revision(record.campaign_id, 0)
    ] == ["alpha"]
    assert (
        reopened.original_selection(record.campaign_id).entries[0].status is DockingJobStatus.QUEUED
    )


def test_stale_updates_are_rejected_across_store_instances(tmp_path, monkeypatch):
    first = GninaScreeningStore(tmp_path)
    second = GninaScreeningStore(tmp_path)
    record = _initial([_queued("alpha", 0, name=None)])
    _create_synthetic(first, record, monkeypatch)
    a = first.load_entry(record.campaign_id, "alpha")
    b = second.load_entry(record.campaign_id, "alpha")
    assert a is not None and b is not None
    first.update_entry(record.campaign_id, a.model_copy(update={"name": "resolved"}))
    with pytest.raises(AnkoraDomainError) as error:
        second.update_entry(record.campaign_id, b.model_copy(update={"name": "other"}))
    assert error.value.code == "GNINA_SCREENING_ENTRY_STALE"


def test_project_isolation_and_invalid_campaign_id(tmp_path, monkeypatch):
    first = GninaScreeningStore(tmp_path, project_id="project-one")
    second = GninaScreeningStore(tmp_path, project_id="project-two")
    record = _initial([_queued("alpha", 0)])
    _create_synthetic(first, record, monkeypatch)
    with pytest.raises(AnkoraDomainError):
        second.load_campaign(record.campaign_id)
    with pytest.raises(AnkoraDomainError):
        first.campaign_directory("../../escape")


def test_a_new_campaign_cannot_start_with_unverified_success(tmp_path):
    store = GninaScreeningStore(tmp_path)
    record = _record(
        [_completed("alpha")],
        campaign_id=str(uuid4()),
        status=DockingJobStatus.COMPLETED,
        phase=DockingJobPhase.COMPLETE,
        completed_at=datetime.now(UTC),
    )
    with pytest.raises(AnkoraDomainError):
        store.create_campaign(record)
    assert not store.campaign_directory(record.campaign_id).exists()


def test_all_failed_campaign_is_failed_and_terminal_state_is_immutable(tmp_path, monkeypatch):
    store = GninaScreeningStore(tmp_path)
    record = _initial([_queued("alpha", 0)])
    _create_synthetic(store, record, monkeypatch)
    store.update_entry(record.campaign_id, _failure(record.entries[0]))
    progress = store.finalize_campaign(record.campaign_id)
    assert progress.status is DockingJobStatus.FAILED
    assert (progress.completed_count, progress.failed_count, progress.succeeded_count) == (1, 1, 0)
    with pytest.raises(AnkoraDomainError):
        store.finalize_campaign(record.campaign_id)
    with pytest.raises(AnkoraDomainError):
        store.update_entry(record.campaign_id, record.entries[0])


def test_all_canceled_campaign_is_canceled(tmp_path, monkeypatch):
    store = GninaScreeningStore(tmp_path)
    record = _initial([_queued("alpha", 0)])
    _create_synthetic(store, record, monkeypatch)
    canceled = record.entries[0].model_copy(
        update={
            "status": DockingJobStatus.CANCELED,
            "phase": DockingJobPhase.COMPLETE,
            "completed_at": datetime.now(UTC),
        }
    )
    store.update_entry(record.campaign_id, canceled)
    progress = store.finalize_campaign(record.campaign_id)
    assert progress.status is DockingJobStatus.CANCELED
    assert (progress.canceled_count, progress.succeeded_count) == (1, 0)


def test_cancel_intent_is_durable_idempotent_and_prevents_queued_start(tmp_path, monkeypatch):
    store = GninaScreeningStore(tmp_path)
    record = _initial([_queued("alpha", 0)])
    _create_synthetic(store, record, monkeypatch)
    requested = store.request_cancel(record.campaign_id)
    assert requested.status is DockingJobStatus.CANCEL_REQUESTED
    assert requested.revision == 1
    assert GninaScreeningStore(tmp_path).load_progress(record.campaign_id) == requested
    assert store.request_cancel(record.campaign_id) == requested
    attempted_start = record.entries[0].model_copy(
        update={
            "status": DockingJobStatus.RUNNING,
            "phase": DockingJobPhase.DOCKING,
            "gnina_job_id": str(uuid4()),
            "started_at": datetime.now(UTC),
        }
    )
    with pytest.raises(AnkoraDomainError) as error:
        store.update_entry(record.campaign_id, attempted_start)
    assert error.value.code == "GNINA_SCREENING_CANCEL_PENDING"
    canceled = record.entries[0].model_copy(
        update={
            "status": DockingJobStatus.CANCELED,
            "phase": DockingJobPhase.COMPLETE,
            "completed_at": datetime.now(UTC),
        }
    )
    store.update_entry(record.campaign_id, canceled)
    terminal = store.finalize_campaign(record.campaign_id)
    assert terminal.status is DockingJobStatus.CANCELED
    assert store.request_cancel(record.campaign_id) == terminal


def test_concurrent_distinct_updates_preserve_both_counters(tmp_path, monkeypatch):
    first = GninaScreeningStore(tmp_path)
    second = GninaScreeningStore(tmp_path)
    record = _initial([_queued("alpha", 0), _queued("beta", 1)])
    _create_synthetic(first, record, monkeypatch)
    gate = threading.Barrier(2)

    def update(store, entry):
        gate.wait(timeout=10)
        return store.update_entry(record.campaign_id, _failure(entry))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(update, first, record.entries[0]),
            executor.submit(update, second, record.entries[1]),
        ]
        for future in futures:
            future.result(timeout=10)
    progress = first.load_progress(record.campaign_id)
    assert (progress.revision, progress.completed_count, progress.failed_count) == (2, 2, 2)


def test_single_entry_update_does_not_count_or_rewrite_the_full_library(tmp_path, monkeypatch):
    store = GninaScreeningStore(tmp_path)
    record = _initial([_queued(f"ligand-{index}", index) for index in range(100)])
    _create_synthetic(store, record, monkeypatch)
    statements = []
    original_connect = sqlite3.connect

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", traced_connect)
    store.update_entry(record.campaign_id, _failure(record.entries[0]))
    assert not any("COUNT(" in statement.upper() for statement in statements)
    progress = store.load_progress(record.campaign_id)
    assert (progress.selected_count, progress.failed_count) == (100, 1)


@pytest.fixture
def synthetic_completed_prepared_job(prepared, tmp_path, monkeypatch):
    """Exercise identity links only; fake engine and topology are not scientific evidence."""
    ligand_store, ligand_id, prepared_entry, pdbqt, conformer = prepared
    service, job_store, arbiter, leases, initial, installation = _setup(
        tmp_path, monkeypatch, screening_campaign_id=str(uuid4())
    )
    pdbqt_bytes = ligand_store.pdbqt_content_path(
        ligand_id, pdbqt.artifact.preparation_id
    ).read_bytes()
    sdf_bytes = ligand_store.conformer_content_path(
        ligand_id, conformer.artifact.conformer_id
    ).read_bytes()
    job_store.output_path(initial.job_id, "ligand.pdbqt").write_bytes(pdbqt_bytes)
    job_store.output_path(initial.job_id, "conformer.sdf").write_bytes(sdf_bytes)
    request = initial.request.model_copy(
        update={
            "ligand_id": ligand_id,
            "ligand_preparation_id": pdbqt.artifact.preparation_id,
        }
    )
    job = initial.model_copy(
        update={
            "request": request,
            "ligand_sha256": pdbqt.artifact.sha256,
            "conformer_sha256": conformer.artifact.sha256,
        }
    )
    job_store.update_job(job)
    raw = (Path(__file__).parent / "fixtures" / "gnina_real_1hsg_mk1.pdbqt").read_bytes()

    def fake_execute(**kwargs):
        kwargs["output_path"].write_bytes(raw)
        return CancellableToolExecution(["synthetic-gnina"], 0, "", "", False, False)

    monkeypatch.setattr("ankora_backend.services.gnina_docking.execute_gnina", fake_execute)
    monkeypatch.setattr(
        "ankora_backend.services.gnina_docking.require_matching_topology", lambda *_: None
    )
    service._run(job.job_id, installation, threading.Event())
    assert job_store.load_job(job.job_id).status is DockingJobStatus.COMPLETED
    yield ligand_store, prepared_entry, pdbqt, conformer, job
    service.shutdown()
    leases.shutdown()
    assert not arbiter.snapshot().active_allocations


def _queued_job_campaign(
    tmp_path,
    synthetic_completed_prepared_job,
    monkeypatch,
    *,
    extra=False,
    campaign_id=None,
    link=True,
):
    _ligands, _prepared_entry, pdbqt, conformer, job = synthetic_completed_prepared_job
    store = GninaScreeningStore(tmp_path)
    entry = _queued(
        job.request.ligand_id,
        0,
        chemical_state_id=conformer.artifact.chemical_state_id,
        ligand_preparation_id=pdbqt.artifact.preparation_id,
        ligand_sha256=pdbqt.artifact.sha256,
        conformer_id=conformer.artifact.conformer_id,
        conformer_sha256=conformer.artifact.sha256,
    )
    request = GninaScreeningRequest(
        receptor_id=job.request.receptor_id,
        binding_site_id=job.request.binding_site_id,
        library_id="library-synthetic",
        filter_run_id="filter-run-synthetic",
        parameters=job.request.parameters,
        acknowledge_inputs_and_scoring=True,
    )
    entries = [entry]
    if extra:
        entries.append(_queued("later", 3, chemical_state_id="state-later"))
    campaign = _record(
        entries,
        campaign_id=campaign_id or job.screening_campaign_id,
        status=DockingJobStatus.QUEUED,
        phase=DockingJobPhase.QUEUED,
        request=request,
        tool=job.tool,
        box=job.box,
        receptor_sha256=job.receptor_sha256,
        receptor_output_artifact_id=job.receptor_output_artifact_id,
    )
    _create_synthetic(store, campaign, monkeypatch)
    if not link:
        return store, campaign, entry
    running = store.update_entry(
        campaign.campaign_id,
        entry.model_copy(
            update={
                "status": DockingJobStatus.RUNNING,
                "phase": DockingJobPhase.DOCKING,
                "gnina_job_id": job.job_id,
                "started_at": datetime.now(UTC),
            }
        ),
    )
    return store, campaign, running


def test_before_launch_screening_job_must_match_the_recorded_campaign(
    tmp_path, synthetic_completed_prepared_job, monkeypatch
):
    store, campaign, entry = _queued_job_campaign(
        tmp_path, synthetic_completed_prepared_job, monkeypatch, link=False
    )
    job = synthetic_completed_prepared_job[-1]
    store.assert_can_start_job(job)
    altered = [
        job.model_copy(update={"receptor_sha256": "f" * 64}),
        job.model_copy(update={"ligand_sha256": "f" * 64}),
        job.model_copy(update={"conformer_sha256": "f" * 64}),
        job.model_copy(update={"receptor_output_artifact_id": "other"}),
        job.model_copy(update={"tool": job.tool.model_copy(update={"sha256": "f" * 64})}),
        job.model_copy(update={"box": job.box.model_copy(update={"center_x": 123})}),
        job.model_copy(
            update={"request": job.request.model_copy(update={"binding_site_id": "other"})}
        ),
        job.model_copy(update={"request": job.request.model_copy(update={"ligand_id": "other"})}),
        job.model_copy(update={"status": DockingJobStatus.RUNNING}),
    ]
    for candidate in altered:
        with pytest.raises(AnkoraDomainError):
            store.assert_can_start_job(candidate)
    ligands = synthetic_completed_prepared_job[0]
    path = ligands.pdbqt_content_path(entry.ligand_id, entry.ligand_preparation_id)
    original = path.read_bytes()
    path.write_bytes(original + b"tampered")
    with pytest.raises(AnkoraDomainError):
        store.assert_can_start_job(job)
    path.write_bytes(original)
    assert store.load_entry(campaign.campaign_id, entry.ligand_id) == entry
    store.request_cancel(campaign.campaign_id)
    with pytest.raises(AnkoraDomainError):
        store.assert_can_start_job(job)


def test_before_launch_rechecks_campaign_selection_freshness(
    tmp_path, synthetic_completed_prepared_job, monkeypatch
):
    store, campaign, _ = _queued_job_campaign(
        tmp_path, synthetic_completed_prepared_job, monkeypatch, link=False
    )
    job = synthetic_completed_prepared_job[-1]

    def reject(ids):
        assert campaign.request.filter_run_id in ids
        raise AnkoraDomainError(
            code="PROJECT_INPUT_STALE",
            stage="test",
            message="synthetic stale selection",
            status_code=409,
        )

    monkeypatch.setattr(
        "ankora_backend.persistence.gnina_screening_store.ProjectDependencyService.for_project_root",
        lambda _root: SimpleNamespace(require_current=reject),
    )
    with pytest.raises(AnkoraDomainError) as error:
        store.assert_can_start_job(job)
    assert error.value.code == "PROJECT_INPUT_STALE"


def test_recovery_matches_one_verified_orphan_by_campaign_and_ligand(
    tmp_path, synthetic_completed_prepared_job, monkeypatch
):
    store, campaign, queued = _queued_job_campaign(
        tmp_path, synthetic_completed_prepared_job, monkeypatch, link=False
    )
    job = synthetic_completed_prepared_job[-1]
    assert queued.gnina_job_id is None
    progress = store.recover_interrupted_campaign(
        campaign.campaign_id, interrupted_at=datetime.now(UTC)
    )
    recovered = store.load_entry(campaign.campaign_id, queued.ligand_id)
    assert (progress.succeeded_count, progress.failed_count) == (1, 0)
    assert recovered.status is DockingJobStatus.COMPLETED
    assert recovered.gnina_job_id == job.job_id
    assert store.load_campaign(campaign.campaign_id).failure.details["unlinked_job_count"] == 0


def test_recovery_does_not_guess_between_multiple_orphan_jobs(
    tmp_path, synthetic_completed_prepared_job, monkeypatch
):
    store, campaign, queued = _queued_job_campaign(
        tmp_path, synthetic_completed_prepared_job, monkeypatch, link=False
    )
    job = store.jobs.load_job(synthetic_completed_prepared_job[-1].job_id)
    duplicate_id = store.jobs.new_job_id()
    store.jobs.create_job(job.model_copy(update={"job_id": duplicate_id}))
    progress = store.recover_interrupted_campaign(
        campaign.campaign_id, interrupted_at=datetime.now(UTC)
    )
    recovered = store.load_entry(campaign.campaign_id, queued.ligand_id)
    assert (progress.succeeded_count, progress.failed_count) == (0, 1)
    assert recovered.gnina_job_id is None
    assert recovered.failure.code == "GNINA_SCREENING_ORPHAN_AMBIGUOUS"
    details = store.load_campaign(campaign.campaign_id).failure.details
    assert details["unlinked_job_count"] == 2
    assert set(details["unlinked_job_ids"]) == {job.job_id, duplicate_id}


def test_recovery_does_not_attach_a_job_from_another_campaign(
    tmp_path, synthetic_completed_prepared_job, monkeypatch
):
    store, campaign, queued = _queued_job_campaign(
        tmp_path,
        synthetic_completed_prepared_job,
        monkeypatch,
        campaign_id=str(uuid4()),
        link=False,
    )
    progress = store.recover_interrupted_campaign(
        campaign.campaign_id, interrupted_at=datetime.now(UTC)
    )
    recovered = store.load_entry(campaign.campaign_id, queued.ligand_id)
    assert (progress.succeeded_count, progress.failed_count) == (0, 1)
    assert recovered.gnina_job_id is None
    assert recovered.failure.code == "GNINA_SCREENING_ENTRY_INTERRUPTED"


def test_a_job_cannot_be_attached_to_another_campaign(
    tmp_path, synthetic_completed_prepared_job, monkeypatch
):
    with pytest.raises(AnkoraDomainError):
        _queued_job_campaign(
            tmp_path, synthetic_completed_prepared_job, monkeypatch, campaign_id=str(uuid4())
        )


def test_recovery_preserves_success_and_marks_unfinished_campaign_failed(
    tmp_path, synthetic_completed_prepared_job, monkeypatch
):
    store, campaign, running = _queued_job_campaign(
        tmp_path, synthetic_completed_prepared_job, monkeypatch, extra=True
    )
    done = running.model_copy(
        update={
            "status": DockingJobStatus.COMPLETED,
            "phase": DockingJobPhase.COMPLETE,
            "completed_at": datetime.now(UTC),
        }
    )
    store.update_entry(campaign.campaign_id, done)
    original = store.original_selection(campaign.campaign_id)
    original_bytes = (store.campaign_directory(campaign.campaign_id) / "record.json").read_bytes()
    progress = store.recover_interrupted_campaign(
        campaign.campaign_id, interrupted_at=datetime.now(UTC)
    )
    assert progress.status is DockingJobStatus.FAILED
    assert (progress.selected_count, progress.succeeded_count, progress.failed_count) == (2, 1, 1)
    first, second = store.load_campaign(campaign.campaign_id).entries
    assert first.status is DockingJobStatus.COMPLETED
    assert first.gnina_job_id == running.gnina_job_id
    assert second.status is DockingJobStatus.FAILED
    assert second.failure.code == "GNINA_SCREENING_ENTRY_INTERRUPTED"
    assert store.original_selection(campaign.campaign_id) == original
    assert (
        store.campaign_directory(campaign.campaign_id) / "record.json"
    ).read_bytes() == original_bytes
    assert (
        store.recover_interrupted_campaign(campaign.campaign_id, interrupted_at=datetime.now(UTC))
        == progress
    )


def test_recovery_preserves_missing_job_identity(
    tmp_path, synthetic_completed_prepared_job, monkeypatch
):
    store, campaign, running = _queued_job_campaign(
        tmp_path, synthetic_completed_prepared_job, monkeypatch
    )
    store.jobs.output_path(running.gnina_job_id, "record.json").unlink()
    progress = store.recover_interrupted_campaign(
        campaign.campaign_id, interrupted_at=datetime.now(UTC)
    )
    recovered = store.load_entry(campaign.campaign_id, running.ligand_id)
    assert progress.status is DockingJobStatus.FAILED
    assert recovered.gnina_job_id == running.gnina_job_id
    assert recovered.failure.code == "GNINA_SCREENING_RECOVERY_UNVERIFIED"


def test_recovery_keeps_a_completed_job_that_finished_before_the_campaign_update(
    tmp_path, synthetic_completed_prepared_job, monkeypatch
):
    store, campaign, running = _queued_job_campaign(
        tmp_path, synthetic_completed_prepared_job, monkeypatch
    )
    job = store.jobs.load_job(running.gnina_job_id)
    progress = store.recover_interrupted_campaign(
        campaign.campaign_id, interrupted_at=datetime.now(UTC)
    )
    recovered = store.load_entry(campaign.campaign_id, running.ligand_id)
    assert progress.status is DockingJobStatus.FAILED
    assert (progress.succeeded_count, progress.failed_count) == (1, 0)
    assert recovered.status is DockingJobStatus.COMPLETED
    assert recovered.completed_at == job.completed_at
    assert recovered.gnina_job_id == job.job_id


def test_recovery_does_not_publish_a_completed_job_with_altered_pose(
    tmp_path, synthetic_completed_prepared_job, monkeypatch
):
    store, campaign, running = _queued_job_campaign(
        tmp_path, synthetic_completed_prepared_job, monkeypatch
    )
    store.jobs.output_path(running.gnina_job_id, "pose_1.pdbqt").write_bytes(
        b"altered synthetic pose"
    )
    progress = store.recover_interrupted_campaign(
        campaign.campaign_id, interrupted_at=datetime.now(UTC)
    )
    recovered = store.load_entry(campaign.campaign_id, running.ligand_id)
    assert (progress.succeeded_count, progress.failed_count) == (0, 1)
    assert recovered.status is DockingJobStatus.FAILED
    assert recovered.gnina_job_id == running.gnina_job_id


def test_recovery_rolls_back_every_entry_if_a_write_fails(tmp_path, monkeypatch):
    store = GninaScreeningStore(tmp_path)
    campaign = _initial([_queued("alpha", 0), _queued("beta", 1)])
    _create_synthetic(store, campaign, monkeypatch)
    write_entry = store._write_entry
    calls = []

    def failing_write(*args, **kwargs):
        write_entry(*args, **kwargs)
        calls.append(1)
        if len(calls) == 2:
            raise OSError("synthetic interruption during recovery")

    monkeypatch.setattr(store, "_write_entry", failing_write)
    with pytest.raises(OSError, match="synthetic interruption"):
        store.recover_interrupted_campaign(campaign.campaign_id, interrupted_at=datetime.now(UTC))
    progress = store.load_progress(campaign.campaign_id)
    assert progress.revision == 0 and progress.completed_count == 0
    assert all(
        entry.status is DockingJobStatus.QUEUED
        for entry in store.load_campaign(campaign.campaign_id).entries
    )


def test_verified_job_can_finish_and_finalize_a_synthetic_campaign(
    tmp_path, synthetic_completed_prepared_job, monkeypatch
):
    store, campaign, running = _queued_job_campaign(
        tmp_path, synthetic_completed_prepared_job, monkeypatch
    )
    done = running.model_copy(
        update={
            "status": DockingJobStatus.COMPLETED,
            "phase": DockingJobPhase.COMPLETE,
            "completed_at": datetime.now(UTC),
        }
    )
    store.update_entry(campaign.campaign_id, done)
    progress = store.finalize_campaign(campaign.campaign_id)
    assert progress.status is DockingJobStatus.COMPLETED
    assert (progress.succeeded_count, progress.failed_count) == (1, 0)


def test_changed_source_conformer_cannot_be_published(
    tmp_path, synthetic_completed_prepared_job, monkeypatch
):
    store, campaign, running = _queued_job_campaign(
        tmp_path, synthetic_completed_prepared_job, monkeypatch
    )
    ligand_store, _entry, _pdbqt, conformer, job = synthetic_completed_prepared_job
    path = ligand_store.conformer_content_path(
        job.request.ligand_id, conformer.artifact.conformer_id
    )
    path.write_bytes(b"altered synthetic conformer")
    done = running.model_copy(
        update={
            "status": DockingJobStatus.COMPLETED,
            "phase": DockingJobPhase.COMPLETE,
            "completed_at": datetime.now(UTC),
        }
    )
    with pytest.raises(AnkoraDomainError):
        store.update_entry(campaign.campaign_id, done)
    assert (
        store.load_entry(campaign.campaign_id, running.ligand_id).status is DockingJobStatus.RUNNING
    )
    assert store.load_progress(campaign.campaign_id).succeeded_count == 0


def test_changed_job_identity_cannot_be_published(
    tmp_path, synthetic_completed_prepared_job, monkeypatch
):
    store, campaign, running = _queued_job_campaign(
        tmp_path, synthetic_completed_prepared_job, monkeypatch
    )
    _ligands, _entry, _pdbqt, _conformer, job = synthetic_completed_prepared_job
    recorded = store.jobs.load_job(job.job_id)
    changed_request = recorded.request.model_copy(update={"receptor_id": "different-receptor"})
    store.jobs.update_job(recorded.model_copy(update={"request": changed_request}))
    done = running.model_copy(
        update={
            "status": DockingJobStatus.COMPLETED,
            "phase": DockingJobPhase.COMPLETE,
            "completed_at": datetime.now(UTC),
        }
    )
    with pytest.raises(AnkoraDomainError):
        store.update_entry(campaign.campaign_id, done)
    assert store.load_progress(campaign.campaign_id).succeeded_count == 0


def test_failure_is_recorded_even_if_source_conformer_disappears(
    tmp_path, synthetic_completed_prepared_job, monkeypatch
):
    store, campaign, running = _queued_job_campaign(
        tmp_path, synthetic_completed_prepared_job, monkeypatch
    )
    ligand_store, _entry, _pdbqt, conformer, job = synthetic_completed_prepared_job
    recorded = store.jobs.load_job(job.job_id)
    failure = DockingFailure(code="SYNTHETIC", message="synthetic engine failure")
    store.jobs.update_job(
        recorded.model_copy(
            update={
                "status": DockingJobStatus.FAILED,
                "poses": [],
                "failure": failure,
            }
        )
    )
    path = ligand_store.conformer_content_path(
        job.request.ligand_id, conformer.artifact.conformer_id
    )
    path.unlink()
    failed = running.model_copy(
        update={
            "status": DockingJobStatus.FAILED,
            "phase": DockingJobPhase.COMPLETE,
            "failure": failure,
            "completed_at": datetime.now(UTC),
        }
    )
    store.update_entry(campaign.campaign_id, failed)
    assert store.finalize_campaign(campaign.campaign_id).status is DockingJobStatus.FAILED


def test_campaign_is_bound_to_an_actual_applied_selection(tmp_path):
    ligand_store = LigandArtifactStore(tmp_path)
    library = _library(ligand_store)
    selection = apply_library_filters(
        library_id=library.artifact.library_id,
        request=ApplyLigandLibraryFilterRequest(acknowledge_selection=True),
        store=ligand_store,
        worker_limit=1,
    )
    evaluations = {item.ligand_id: item for item in selection.evaluations}
    entries = [
        _queued(
            ligand_id,
            evaluations[ligand_id].record_index,
            chemical_state_id=evaluations[ligand_id].state_id,
        )
        for ligand_id in selection.selected_ligand_ids
    ]
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
        entries,
        campaign_id=str(uuid4()),
        status=DockingJobStatus.QUEUED,
        phase=DockingJobPhase.QUEUED,
        request=request,
        selection=pinned,
    )
    store = GninaScreeningStore(tmp_path)
    store.create_campaign(campaign)
    altered = campaign.model_copy(
        update={"campaign_id": str(uuid4()), "entries": list(reversed(entries))}
    )
    with pytest.raises(AnkoraDomainError):
        store.create_campaign(altered)

    wrong_index = entries[0].model_copy(update={"source_index": entries[0].source_index + 100})
    altered = campaign.model_copy(
        update={"campaign_id": str(uuid4()), "entries": [wrong_index, *entries[1:]]}
    )
    with pytest.raises(AnkoraDomainError):
        store.create_campaign(altered)

    wrong_state = entries[0].model_copy(update={"chemical_state_id": "other-state"})
    altered = campaign.model_copy(
        update={
            "campaign_id": str(uuid4()),
            "entries": [wrong_state, *entries[1:]],
        }
    )
    with pytest.raises(AnkoraDomainError):
        store.create_campaign(altered)

    missing_source = entries[0].model_copy(
        update={
            "source_index": None,
            "status": DockingJobStatus.FAILED,
            "phase": DockingJobPhase.COMPLETE,
            "completed_at": datetime.now(UTC),
            "failure": DockingFailure(code="SYNTHETIC_MISSING", message="synthetic missing record"),
        }
    )
    preflight = _record(
        [missing_source, *entries[1:]],
        campaign_id=str(uuid4()),
        status=DockingJobStatus.QUEUED,
        phase=DockingJobPhase.QUEUED,
        request=request,
        selection=pinned,
    )
    store.create_campaign(preflight)
    assert store.load_progress(preflight.campaign_id).failed_count == 1
