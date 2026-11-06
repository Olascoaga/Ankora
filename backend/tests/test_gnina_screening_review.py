"""Independent lifecycle regression cases using entirely synthetic campaign records."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.docking import DockingFailure, DockingJobPhase, DockingJobStatus
from ankora_backend.schemas.gnina import GninaDockingParameters, GninaToolIdentity
from ankora_backend.schemas.gnina_screening import (
    GninaScreeningCampaignRecord,
    GninaScreeningEntry,
    GninaScreeningProgress,
    GninaScreeningRequest,
    GninaScreeningSelection,
)


def _record(status, entry, **overrides):
    now = datetime.now(UTC)
    counts = {
        "completed_count": int(
            entry.status
            in {DockingJobStatus.COMPLETED, DockingJobStatus.FAILED, DockingJobStatus.CANCELED}
        ),
        "succeeded_count": int(entry.status is DockingJobStatus.COMPLETED),
        "failed_count": int(entry.status is DockingJobStatus.FAILED),
        "canceled_count": int(entry.status is DockingJobStatus.CANCELED),
    }
    args = dict(
        campaign_id="campaign-1",
        status=status,
        phase=DockingJobPhase.COMPLETE,
        created_at=now,
        started_at=now,
        completed_at=now,
        request=GninaScreeningRequest(
            receptor_id="receptor",
            binding_site_id="site",
            library_id="library",
            filter_run_id="filter",
            parameters=GninaDockingParameters(compute="cpu"),
            acknowledge_inputs_and_scoring=True,
        ),
        selection=GninaScreeningSelection(
            library_id="library",
            filter_run_id="filter",
            manifest_artifact_id="filter",
            manifest_sha256="a" * 64,
        ),
        tool=GninaToolIdentity(version="synthetic", sha256="b" * 64, architecture="x86_64"),
        receptor_output_artifact_id="receptor-output",
        receptor_sha256="c" * 64,
        box=BindingBox(center_x=0, center_y=0, center_z=0, size_x=10, size_y=10, size_z=10),
        selected_count=1,
        entries=[entry],
        **counts,
    )
    args.update(overrides)
    return GninaScreeningCampaignRecord(**args)


@pytest.mark.parametrize("status", [DockingJobStatus.FAILED, DockingJobStatus.CANCELED])
def test_unsuccessful_terminal_entry_can_use_the_existing_complete_phase(status):
    failure = DockingFailure(code="SYNTHETIC", message="synthetic", details={})
    entry = GninaScreeningEntry(
        ligand_id="ligand",
        status=status,
        phase=DockingJobPhase.COMPLETE,
        failure=failure if status is DockingJobStatus.FAILED else None,
        completed_at=datetime.now(UTC),
    )
    assert entry.status is status


@pytest.mark.parametrize("status", [DockingJobStatus.FAILED, DockingJobStatus.CANCELED])
def test_terminal_campaign_cannot_leave_a_queued_entry(status):
    entry = GninaScreeningEntry(
        ligand_id="ligand", status=DockingJobStatus.QUEUED, phase=DockingJobPhase.QUEUED
    )
    with pytest.raises(ValidationError):
        _record(status, entry)


def test_all_failed_campaign_cannot_claim_completed():
    entry = GninaScreeningEntry(
        ligand_id="ligand",
        status=DockingJobStatus.FAILED,
        phase=DockingJobPhase.COMPLETE,
        failure=DockingFailure(code="SYNTHETIC", message="synthetic", details={}),
        completed_at=datetime.now(UTC),
    )
    with pytest.raises(ValidationError):
        _record(DockingJobStatus.COMPLETED, entry)


def test_mutated_nested_entry_is_revalidated_before_recording():
    queued = GninaScreeningEntry(
        ligand_id="ligand", status=DockingJobStatus.QUEUED, phase=DockingJobPhase.QUEUED
    )
    forged = queued.model_copy(update={"status": DockingJobStatus.FAILED})
    with pytest.raises(ValidationError):
        _record(DockingJobStatus.FAILED, forged)


def test_terminal_progress_cannot_hide_unfinished_entries():
    with pytest.raises(ValidationError):
        GninaScreeningProgress(
            campaign_id="campaign-1",
            status=DockingJobStatus.CANCELED,
            phase=DockingJobPhase.COMPLETE,
            revision=1,
            selected_count=2,
            completed_count=1,
            succeeded_count=0,
            failed_count=0,
            canceled_count=1,
            completed_at=datetime.now(UTC),
        )
