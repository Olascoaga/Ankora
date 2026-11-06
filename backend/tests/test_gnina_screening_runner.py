"""Synthetic runner lifecycle; no GNINA process or scientific result is produced."""

import threading
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from test_gnina_screening_preparation import prepared as prepared
from test_gnina_screening_store import _create_synthetic, _queued_job_campaign
from test_gnina_screening_store import (
    synthetic_completed_prepared_job as synthetic_completed_prepared_job,
)

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.work_lease_store import WorkLeaseStore
from ankora_backend.schemas.docking import DockingJobPhase, DockingJobStatus
from ankora_backend.services.gnina_screening_runner import GninaScreeningRunner
from ankora_backend.services.work_leases import WorkLeaseManager


class SyntheticDocking:
    def __init__(self, store, source, *, block=False):
        self.store = store
        self.source = source
        self.block = block
        self.entered = threading.Event()
        self.release = threading.Event()
        self.launched = []
        self.canceled = []

    def start(self, request, *, screening_campaign_id):
        assert not self.launched
        self.launched.append(request.ligand_id)
        source = self.store.jobs.load_job(self.source.job_id)
        job = source.model_copy(
            update={"job_id": str(uuid4()), "screening_campaign_id": screening_campaign_id}
        )
        if self.block:
            job = job.model_copy(
                update={
                    "status": DockingJobStatus.QUEUED,
                    "phase": DockingJobPhase.QUEUED,
                    "completed_at": None,
                    "poses": [],
                    "execution": None,
                }
            )
        self.store.jobs.create_job(job)
        for name in ("receptor.pdbqt", "ligand.pdbqt", "conformer.sdf"):
            self.store.jobs.write_artifact(
                job.job_id, name, self.store.jobs.output_path(source.job_id, name).read_bytes()
            )
        if not self.block:
            for pose in source.poses:
                self.store.jobs.write_artifact(
                    job.job_id,
                    pose.artifact.filename,
                    self.store.jobs.output_path(source.job_id, pose.artifact.filename).read_bytes(),
                )
        return job

    def get(self, job_id):
        self.entered.set()
        if self.block:
            assert self.release.wait(5)
        return self.store.jobs.load_job(job_id)

    def cancel(self, job_id):
        self.canceled.append(job_id)
        job = self.store.jobs.load_job(job_id)
        self.store.jobs.update_job(
            job.model_copy(
                update={
                    "status": DockingJobStatus.CANCELED,
                    "phase": DockingJobPhase.COMPLETE,
                    "completed_at": datetime.now(UTC),
                }
            )
        )
        self.release.set()


def _setup_runner(tmp_path, fixture, monkeypatch, *, block=False, extra=False):
    store, campaign, _ = _queued_job_campaign(
        tmp_path, fixture, monkeypatch, campaign_id=str(uuid4()), link=False, extra=extra
    )
    docking = SyntheticDocking(store, fixture[-1], block=block)
    leases = WorkLeaseManager(WorkLeaseStore(tmp_path))
    runner = GninaScreeningRunner(store=store, docking=docking, leases=leases, poll_seconds=0.001)
    return store, campaign, docking, leases, runner


def test_runner_records_verified_job_and_releases_lease(
    tmp_path, synthetic_completed_prepared_job, monkeypatch
):
    store, campaign, docking, leases, runner = _setup_runner(
        tmp_path, synthetic_completed_prepared_job, monkeypatch
    )
    try:
        progress = runner.run(campaign.campaign_id)
        assert progress.status is DockingJobStatus.COMPLETED
        assert progress.succeeded_count == 1
        result = store.load_campaign(campaign.campaign_id)
        assert result.entries[0].gnina_job_id is not None
        assert docking.launched == [result.entries[0].ligand_id]
        assert not runner.has_active_work()
        with pytest.raises(AnkoraDomainError):
            runner.run(campaign.campaign_id)
    finally:
        leases.shutdown()


def test_cancel_signals_running_job_and_does_not_launch_next(
    tmp_path, synthetic_completed_prepared_job, monkeypatch
):
    store, campaign, docking, leases, runner = _setup_runner(
        tmp_path, synthetic_completed_prepared_job, monkeypatch, block=True, extra=True
    )
    outcome = []
    errors = []

    def run():
        try:
            outcome.append(runner.run(campaign.campaign_id))
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert docking.entered.wait(5)
        runner.cancel(campaign.campaign_id)
        thread.join(5)
        assert not thread.is_alive()
        assert not errors
        assert outcome[0].status is DockingJobStatus.CANCELED
        assert outcome[0].canceled_count == 2
        assert len(docking.launched) == len(docking.canceled) == 1
        assert all(
            entry.status is DockingJobStatus.CANCELED
            for entry in store.load_campaign(campaign.campaign_id).entries
        )
        assert not runner.has_active_work()
    finally:
        docking.release.set()
        thread.join(5)
        leases.shutdown()


def test_launch_failure_stops_orphan_before_reconciliation(
    tmp_path, synthetic_completed_prepared_job, monkeypatch
):
    store, campaign, docking, leases, runner = _setup_runner(
        tmp_path, synthetic_completed_prepared_job, monkeypatch, block=True, extra=True
    )
    original_start = docking.start

    def fail_after_creating_job(request, *, screening_campaign_id):
        original_start(request, screening_campaign_id=screening_campaign_id)
        raise RuntimeError("synthetic failure after job creation")

    docking.start = fail_after_creating_job
    try:
        with pytest.raises(RuntimeError, match="synthetic failure"):
            runner.run(campaign.campaign_id)
        progress = store.load_progress(campaign.campaign_id)
        assert progress.status is DockingJobStatus.FAILED
        assert progress.canceled_count == 1
        assert progress.failed_count == 1
        assert len(docking.canceled) == 1
        assert not runner.has_active_work()
    finally:
        leases.shutdown()


def test_two_runner_instances_cannot_start_the_same_campaign(
    tmp_path, synthetic_completed_prepared_job, monkeypatch
):
    store, campaign, docking, leases, runner = _setup_runner(
        tmp_path, synthetic_completed_prepared_job, monkeypatch, block=True
    )
    other = GninaScreeningRunner(store=store, docking=docking, leases=leases, poll_seconds=0.001)
    errors = []

    def run():
        try:
            runner.run(campaign.campaign_id)
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert docking.entered.wait(5)
        with pytest.raises(AnkoraDomainError):
            other.run(campaign.campaign_id)
        runner.cancel(campaign.campaign_id)
        thread.join(5)
        assert not thread.is_alive()
        assert not errors
        assert len(docking.launched) == 1
    finally:
        docking.release.set()
        thread.join(5)
        leases.shutdown()


def test_single_molecule_admission_failure_preserves_other_results(
    tmp_path, synthetic_completed_prepared_job, monkeypatch
):
    store, original, docking, leases, runner = _setup_runner(
        tmp_path, synthetic_completed_prepared_job, monkeypatch
    )
    bad = original.entries[0].model_copy(update={"ligand_id": "synthetic-bad"})
    campaign = original.model_copy(
        update={
            "campaign_id": str(uuid4()),
            "entries": [bad, original.entries[0]],
            "selected_count": 2,
        }
    )
    _create_synthetic(store, campaign, monkeypatch)
    original_start = docking.start

    def fail_later(request, *, screening_campaign_id):
        if request.ligand_id == "synthetic-bad":
            raise AnkoraDomainError(
                code="SYNTHETIC_ADMISSION_FAILURE",
                stage="test",
                message="synthetic failure",
                status_code=409,
            )
        return original_start(request, screening_campaign_id=screening_campaign_id)

    docking.start = fail_later
    try:
        progress = runner.run(campaign.campaign_id)
        assert progress.status is DockingJobStatus.COMPLETED
        assert (progress.succeeded_count, progress.failed_count) == (1, 1)
        entry = store.load_entry(campaign.campaign_id, "synthetic-bad")
        assert entry.failure.code == "SYNTHETIC_ADMISSION_FAILURE"
        assert entry.gnina_job_id is None
    finally:
        leases.shutdown()


def test_missing_terminal_timestamp_is_not_invented(
    tmp_path, synthetic_completed_prepared_job, monkeypatch
):
    store, campaign, docking, leases, runner = _setup_runner(
        tmp_path, synthetic_completed_prepared_job, monkeypatch
    )
    original_start = docking.start

    def start_without_timestamp(request, *, screening_campaign_id):
        job = original_start(request, screening_campaign_id=screening_campaign_id)
        job = job.model_copy(update={"completed_at": None})
        store.jobs.update_job(job)
        return job

    docking.start = start_without_timestamp
    try:
        with pytest.raises(AnkoraDomainError) as caught:
            runner.run(campaign.campaign_id)
        assert caught.value.code == "GNINA_SCREENING_JOB_INCOMPLETE"
        assert store.load_progress(campaign.campaign_id).succeeded_count == 0
        assert store.load_progress(campaign.campaign_id).status is DockingJobStatus.FAILED
    finally:
        leases.shutdown()


def test_cancel_during_submission_waits_for_job_to_be_linked(
    tmp_path, synthetic_completed_prepared_job, monkeypatch
):
    store, campaign, docking, leases, runner = _setup_runner(
        tmp_path, synthetic_completed_prepared_job, monkeypatch, block=True
    )
    created, allow_return, cancel_done = threading.Event(), threading.Event(), threading.Event()
    errors = []
    original_start = docking.start

    def slow_start(request, *, screening_campaign_id):
        job = original_start(request, screening_campaign_id=screening_campaign_id)
        created.set()
        assert allow_return.wait(5)
        return job

    docking.start = slow_start

    def run():
        try:
            runner.run(campaign.campaign_id)
        except Exception as error:
            errors.append(error)

    def cancel():
        try:
            runner.cancel(campaign.campaign_id)
            cancel_done.set()
        except Exception as error:
            errors.append(error)

    worker = threading.Thread(target=run)
    canceler = threading.Thread(target=cancel)
    worker.start()
    try:
        assert created.wait(5)
        canceler.start()
        assert not cancel_done.wait(0.05)
        allow_return.set()
        canceler.join(5)
        worker.join(5)
        assert not worker.is_alive() and not canceler.is_alive()
        assert not errors
        assert len(docking.canceled) == 1
        entry = store.load_campaign(campaign.campaign_id).entries[0]
        assert entry.gnina_job_id == docking.canceled[0]
        assert entry.status is DockingJobStatus.CANCELED
    finally:
        allow_return.set()
        docking.release.set()
        if canceler.ident is not None:
            canceler.join(5)
        worker.join(5)
        leases.shutdown()
