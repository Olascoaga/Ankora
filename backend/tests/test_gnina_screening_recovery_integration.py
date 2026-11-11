"""Synthetic startup recovery; no scientific executable is invoked."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from test_gnina_screening_preparation import prepared as prepared
from test_gnina_screening_schema import _queued
from test_gnina_screening_store import _create_synthetic, _failure, _initial, _queued_job_campaign
from test_gnina_screening_store import (
    synthetic_completed_prepared_job as synthetic_completed_prepared_job,
)
from test_work_retry import _service

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.project_context import project_scope
from ankora_backend.persistence.gnina_screening_store import GninaScreeningStore
from ankora_backend.persistence.work_lease_store import WorkLeaseStore
from ankora_backend.schemas.docking import DockingJobPhase, DockingJobStatus
from ankora_backend.schemas.work_recovery import (
    WorkKind,
    WorkLeaseRecord,
    WorkLeaseState,
    WorkRetryRequest,
)
from ankora_backend.services.work_recovery import InterruptedWorkRecovery
from ankora_backend.services.work_retry import WorkRetryService


def test_startup_reconciles_screening_without_rerun_or_changing_another_project(
    tmp_path, monkeypatch
):
    first = GninaScreeningStore(tmp_path, project_id="project-one")
    other = GninaScreeningStore(tmp_path, project_id="project-two")
    first_campaign = _initial([_queued("alpha", 0), _queued("beta", 1)])
    other_campaign = _initial([_queued("other", 0)])
    _create_synthetic(first, first_campaign, monkeypatch)
    _create_synthetic(other, other_campaign, monkeypatch)
    first.update_entry(first_campaign.campaign_id, _failure(first_campaign.entries[0]))
    leases = WorkLeaseStore(tmp_path, project_id="project-one")
    now = datetime.now(UTC)
    lease = WorkLeaseRecord(
        lease_id=str(uuid4()),
        work_kind=WorkKind.GNINA_SCREENING,
        work_id=first_campaign.campaign_id,
        owner_instance_id=str(uuid4()),
        acquired_at=now,
        heartbeat_at=now,
    )
    leases.write(lease)
    recovery = InterruptedWorkRecovery(
        docking=MagicMock(),
        autogrid=MagicMock(),
        autodock4=MagicMock(),
        autodock_gpu=MagicMock(),
        leases=leases,
        gnina_screening=first,
    )
    summary = recovery.reconcile()
    assert len(summary.items) == 1
    item = summary.items[0]
    assert item.work_kind is WorkKind.GNINA_SCREENING
    assert item.interrupted_entry_count == 1
    assert item.completed_entry_count == 0
    result = first.load_campaign(first_campaign.campaign_id)
    assert result.status is DockingJobStatus.FAILED
    assert [entry.failure.code for entry in result.entries] == [
        "SYNTHETIC",
        "GNINA_SCREENING_ENTRY_INTERRUPTED",
    ]
    assert (
        leases.load(WorkKind.GNINA_SCREENING, first_campaign.campaign_id).state
        is WorkLeaseState.RECONCILED
    )
    assert other.load_progress(other_campaign.campaign_id).status is DockingJobStatus.QUEUED
    assert recovery.reconcile().items == []


def test_retry_is_explicitly_unavailable_without_a_screening_service():
    with pytest.raises(AnkoraDomainError) as error:
        _service().retry(
            WorkKind.GNINA_SCREENING,
            str(uuid4()),
            WorkRetryRequest(acknowledge_new_immutable_attempt=True),
        )
    assert error.value.code == "WORK_RETRY_UNAVAILABLE"


def _screening_retry_service(store, screening):  # type: ignore[no-untyped-def]
    return WorkRetryService(
        docking_store=MagicMock(),
        autogrid_store=MagicMock(),
        autodock4_store=MagicMock(),
        autodock_gpu_store=MagicMock(),
        vina=MagicMock(),
        autogrid=MagicMock(),
        autodock4=MagicMock(),
        autodock_gpu=MagicMock(),
        gnina=MagicMock(),
        gnina_store=store.jobs,
        gnina_screening=screening,
        gnina_screening_store=store,
    )


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def test_retry_starts_reconciled_campaign_request_as_new_campaign(tmp_path, monkeypatch):
    """Synthetic: the new campaign is a mock; no GNINA process is started."""
    store = GninaScreeningStore(tmp_path)
    campaign = _initial([_queued("alpha", 0), _queued("beta", 1)])
    _create_synthetic(store, campaign, monkeypatch)
    store.update_entry(campaign.campaign_id, _failure(campaign.entries[0]))
    store.recover_interrupted_campaign(campaign.campaign_id, interrupted_at=datetime.now(UTC))
    interrupted = store.load_campaign(campaign.campaign_id)
    assert interrupted.failure.code == "GNINA_SCREENING_CAMPAIGN_INTERRUPTED"
    before = _snapshot(store.campaign_directory(campaign.campaign_id))
    assert before
    created_at = datetime.now(UTC)
    new_id = str(uuid4())
    screening = MagicMock()
    screening.start.return_value = SimpleNamespace(
        campaign_id=new_id,
        status=DockingJobStatus.QUEUED,
        created_at=created_at,
    )

    response = _screening_retry_service(store, screening).retry(
        WorkKind.GNINA_SCREENING,
        campaign.campaign_id,
        WorkRetryRequest(acknowledge_new_immutable_attempt=True),
    )

    screening.start.assert_called_once_with(interrupted.request)
    assert response.work_kind is WorkKind.GNINA_SCREENING
    assert response.interrupted_work_id == campaign.campaign_id
    assert response.new_work_id == new_id
    assert response.status == "queued"
    assert response.created_at == created_at
    assert store.load_campaign(campaign.campaign_id) == interrupted
    assert _snapshot(store.campaign_directory(campaign.campaign_id)) == before


def test_retry_rejects_screening_campaign_not_reconciled_as_interrupted(tmp_path, monkeypatch):
    store = GninaScreeningStore(tmp_path)
    campaign = _initial([_queued("alpha", 0)])
    _create_synthetic(store, campaign, monkeypatch)
    screening = MagicMock()

    with pytest.raises(AnkoraDomainError) as error:
        _screening_retry_service(store, screening).retry(
            WorkKind.GNINA_SCREENING,
            campaign.campaign_id,
            WorkRetryRequest(acknowledge_new_immutable_attempt=True),
        )

    assert error.value.code == "WORK_NOT_INTERRUPTED"
    assert error.value.details["expected_failure_code"] == "GNINA_SCREENING_CAMPAIGN_INTERRUPTED"
    screening.start.assert_not_called()


def test_screening_retry_requires_explicit_new_attempt_acknowledgement():
    store = MagicMock()
    screening = MagicMock()

    with pytest.raises(AnkoraDomainError) as error:
        _screening_retry_service(store, screening).retry(
            WorkKind.GNINA_SCREENING, str(uuid4()), WorkRetryRequest()
        )

    assert error.value.code == "WORK_RETRY_CONFIRMATION_REQUIRED"
    store.load_campaign.assert_not_called()
    screening.start.assert_not_called()


def test_retry_rejects_a_screening_child_job_independently_of_its_campaign(
    tmp_path, monkeypatch, synthetic_completed_prepared_job
):
    store, _campaign, _entry = _queued_job_campaign(
        tmp_path, synthetic_completed_prepared_job, monkeypatch
    )
    job = store.jobs.load_job(synthetic_completed_prepared_job[-1].job_id)
    assert job.screening_campaign_id is not None
    service = _screening_retry_service(store, MagicMock())

    with pytest.raises(AnkoraDomainError) as error:
        service.retry(
            WorkKind.GNINA_JOB,
            job.job_id,
            WorkRetryRequest(acknowledge_new_immutable_attempt=True),
        )

    assert error.value.code == "WORK_RETRY_CAMPAIGN_JOB_UNAVAILABLE"
    service._gnina.start.assert_not_called()


def test_environment_startup_reconciles_only_the_active_project(tmp_path, monkeypatch):
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    first = GninaScreeningStore(tmp_path, project_id="project-one")
    second = GninaScreeningStore(tmp_path, project_id="project-two")
    one = _initial([_queued("one", 0)])
    two = _initial([_queued("two", 0)])
    _create_synthetic(first, one, monkeypatch)
    _create_synthetic(second, two, monkeypatch)
    with project_scope("project-one"):
        summary = InterruptedWorkRecovery.from_environment().reconcile()
    assert [item.work_id for item in summary.items] == [one.campaign_id]
    assert first.load_progress(one.campaign_id).status is DockingJobStatus.FAILED
    assert second.load_progress(two.campaign_id).status is DockingJobStatus.QUEUED


@pytest.mark.parametrize("job_finished", [False, True])
@pytest.mark.parametrize("link", [False, True])
def test_startup_reconciles_linked_job_before_its_campaign(
    tmp_path, monkeypatch, request, job_finished, link
):
    synthetic_completed_prepared_job = request.getfixturevalue("synthetic_completed_prepared_job")
    store, campaign, _entry = _queued_job_campaign(
        tmp_path, synthetic_completed_prepared_job, monkeypatch, link=link
    )
    job = store.jobs.load_job(synthetic_completed_prepared_job[-1].job_id)
    if not job_finished:
        store.jobs.update_job(
            job.model_copy(
                update={
                    "status": DockingJobStatus.RUNNING,
                    "phase": DockingJobPhase.DOCKING,
                    "completed_at": None,
                    "execution": None,
                    "poses": [],
                }
            )
        )
    recovery = InterruptedWorkRecovery(
        docking=MagicMock(),
        autogrid=MagicMock(),
        autodock4=MagicMock(),
        autodock_gpu=MagicMock(),
        leases=WorkLeaseStore(tmp_path),
        gnina=store.jobs,
        gnina_screening=store,
    )
    summary = recovery.reconcile()
    saved = store.load_campaign(campaign.campaign_id)
    assert saved.status is DockingJobStatus.FAILED
    assert saved.entries[0].gnina_job_id == job.job_id
    if job_finished:
        assert saved.entries[0].status is DockingJobStatus.COMPLETED
        assert (saved.succeeded_count, saved.failed_count) == (1, 0)
        assert [item.work_kind for item in summary.items] == [WorkKind.GNINA_SCREENING]
    else:
        assert saved.entries[0].status is DockingJobStatus.FAILED
        assert saved.entries[0].failure.code == "GNINA_EXECUTION_INTERRUPTED"
        linked = next(item for item in summary.items if item.work_kind is WorkKind.GNINA_JOB)
        assert linked.screening_campaign_id == campaign.campaign_id
