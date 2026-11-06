"""Synthetic startup recovery; no scientific executable is invoked."""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from test_gnina_screening_schema import _queued
from test_gnina_screening_store import _create_synthetic, _failure, _initial
from test_work_retry import _service

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.gnina_screening_store import GninaScreeningStore
from ankora_backend.persistence.work_lease_store import WorkLeaseStore
from ankora_backend.schemas.docking import DockingJobStatus
from ankora_backend.schemas.work_recovery import (
    WorkKind,
    WorkLeaseRecord,
    WorkLeaseState,
    WorkRetryRequest,
)
from ankora_backend.services.work_recovery import InterruptedWorkRecovery


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


def test_retry_is_explicitly_unavailable_for_screening():
    with pytest.raises(AnkoraDomainError) as error:
        _service().retry(
            WorkKind.GNINA_SCREENING,
            str(uuid4()),
            WorkRetryRequest(acknowledge_new_immutable_attempt=True),
        )
    assert error.value.code == "WORK_RETRY_UNAVAILABLE"
