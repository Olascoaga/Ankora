"""GNINA screening campaign contracts.

Every identifier and hash below is **synthetic**: these are hand-written
fixtures that exercise the model's invariants, not recorded GNINA output. No
docking is run and nothing here is a scientific result. That stays true for a
cheap reason - a campaign entry holds no score and no pose at all, only the
identity of the single job that owns them - so there is no engine number in
this file to get wrong.

What is being pinned down is honesty rather than shape: that a finished
campaign cannot claim a molecule is still docking, that every selected
molecule stays represented even when its library record was missing, that
selection order survives a reordered library, and that a campaign never
pretends the jobs it links to have been verified.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ankora_backend.schemas.docking import DockingFailure, DockingJobPhase, DockingJobStatus
from ankora_backend.schemas.gnina import GninaDockingParameters
from ankora_backend.schemas.gnina_screening import (
    GninaScreeningCampaignRecord,
    GninaScreeningEntry,
    GninaScreeningPreflightCode,
    GninaScreeningProgress,
    GninaScreeningRequest,
    GninaScreeningSelection,
)

# Synthetic 64-hex digests. Distinct so a swapped identity is visible.
_MANIFEST_SHA = "a1" * 32
_RECEPTOR_SHA = "b2" * 32
_LIGAND_SHA = "c3" * 32
_TOOL_SHA = "d4" * 32

_NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def _request(**overrides: object) -> GninaScreeningRequest:
    args: dict[str, object] = {
        "receptor_id": "receptor-synthetic",
        "binding_site_id": "site-synthetic",
        "library_id": "library-synthetic",
        "filter_run_id": "filter-run-synthetic",
        "parameters": GninaDockingParameters(compute="cpu"),
        "acknowledge_inputs_and_scoring": True,
    }
    return GninaScreeningRequest(**(args | overrides))  # type: ignore[arg-type]


def _selection(**overrides: object) -> GninaScreeningSelection:
    args: dict[str, object] = {
        "library_id": "library-synthetic",
        "filter_run_id": "filter-run-synthetic",
        "manifest_artifact_id": "manifest-synthetic",
        "manifest_sha256": _MANIFEST_SHA,
    }
    return GninaScreeningSelection(**(args | overrides))  # type: ignore[arg-type]


def _queued(ligand_id: str, source_index: int = 0, **overrides: object) -> GninaScreeningEntry:
    args: dict[str, object] = {
        "ligand_id": ligand_id,
        "source_index": source_index,
        "name": f"synthetic-{ligand_id}",
        "status": DockingJobStatus.QUEUED,
        "phase": DockingJobPhase.QUEUED,
    }
    return GninaScreeningEntry(**(args | overrides))  # type: ignore[arg-type]


def _completed(ligand_id: str, source_index: int = 0, **overrides: object) -> GninaScreeningEntry:
    args: dict[str, object] = {
        "ligand_id": ligand_id,
        "source_index": source_index,
        "name": f"synthetic-{ligand_id}",
        "ligand_preparation_id": f"prep-{ligand_id}",
        "ligand_sha256": _LIGAND_SHA,
        "chemical_state_id": f"state-{ligand_id}",
        "conformer_id": f"conformer-{ligand_id}",
        "conformer_sha256": "c" * 64,
        "status": DockingJobStatus.COMPLETED,
        "phase": DockingJobPhase.COMPLETE,
        "gnina_job_id": f"job-{ligand_id}",
        "completed_at": _NOW,
    }
    return GninaScreeningEntry(**(args | overrides))  # type: ignore[arg-type]


def _failure(code: str = "GNINA_SCREENING_SYNTHETIC") -> DockingFailure:
    return DockingFailure(code=code, message="synthetic failure fixture")


def _record(
    entries: list[GninaScreeningEntry], **overrides: object
) -> GninaScreeningCampaignRecord:
    """Counts are derived from `entries` unless a test overrides them on purpose."""
    args: dict[str, object] = {
        "campaign_id": "campaign-synthetic",
        "status": DockingJobStatus.RUNNING,
        "phase": DockingJobPhase.DOCKING,
        "created_at": _NOW,
        "request": _request(),
        "tool": {"version": "1.3.3", "sha256": _TOOL_SHA, "architecture": "x86_64"},
        "selection": _selection(),
        "receptor_output_artifact_id": "receptor-artifact-synthetic",
        "receptor_sha256": _RECEPTOR_SHA,
        "box": {
            "center_x": 35.561,
            "center_y": -4.298,
            "center_z": -0.660,
            "size_x": 12.585,
            "size_y": 10.101,
            "size_z": 11.617,
        },
        "selected_count": len(entries),
        "succeeded_count": sum(
            1 for entry in entries if entry.status is DockingJobStatus.COMPLETED
        ),
        "failed_count": sum(1 for entry in entries if entry.status is DockingJobStatus.FAILED),
        "canceled_count": sum(1 for entry in entries if entry.status is DockingJobStatus.CANCELED),
        "entries": entries,
    }
    args["completed_count"] = (
        args["succeeded_count"] + args["failed_count"] + args["canceled_count"]  # type: ignore[operator]
    )
    return GninaScreeningCampaignRecord(**(args | overrides))  # type: ignore[arg-type]


# --- what a campaign is allowed to say it produced -------------------------


def test_a_completed_entry_keeps_a_job_reference_and_no_result_of_its_own() -> None:
    """The single job owns the poses; a second copy here could drift from it.

    This is the whole reason the entry model is small, so it is asserted on the
    fields rather than left to a convention a later edit could quietly break.
    """
    fields = set(GninaScreeningEntry.model_fields)

    assert "gnina_job_id" in fields
    for result_field in (
        "poses",
        "cnn_score",
        "cnn_affinity",
        "minimized_affinity_kcal_mol",
        "execution",
        "command",
    ):
        assert result_field not in fields


def test_a_linked_job_is_recorded_but_never_described_as_verified() -> None:
    """Verification re-reads preserved inputs and hashes; that is storage's job."""
    for model in (GninaScreeningEntry, GninaScreeningCampaignRecord):
        assert not [name for name in model.model_fields if "verified" in name]


def test_a_successful_campaign_records_its_selection_and_each_attempt() -> None:
    record = _record(
        [_completed("lig-a", 0), _completed("lig-b", 1)],
        status=DockingJobStatus.COMPLETED,
        phase=DockingJobPhase.COMPLETE,
        completed_at=_NOW,
    )

    assert record.engine == "gnina"
    assert record.selected_ligand_ids == ("lig-a", "lig-b")
    assert record.succeeded_count == 2
    assert [entry.gnina_job_id for entry in record.entries] == ["job-lig-a", "job-lig-b"]


def test_one_job_at_a_time_is_recorded_as_a_fact_not_offered_as_a_knob() -> None:
    """The present GNINA executor runs a single job; concurrency is unimplemented."""
    assert _record([_queued("lig-a")]).worker_count == 1

    with pytest.raises(ValidationError):
        _record([_queued("lig-a")], worker_count=2)


# --- failures, cancellation and molecules that never reached the engine ----


def test_a_missing_library_record_is_an_explicit_preflight_failure() -> None:
    """The molecule stays in the selection rather than vanishing from it."""
    entry = GninaScreeningEntry(
        ligand_id="lig-missing",
        source_index=None,
        status=DockingJobStatus.FAILED,
        phase=DockingJobPhase.QUEUED,
        failure=_failure(GninaScreeningPreflightCode.LIBRARY_RECORD_MISSING),
        completed_at=_NOW,
    )

    assert entry.is_preflight_failure
    assert entry.is_terminal
    assert entry.gnina_job_id is None
    record = _record([_completed("lig-a", 0), entry])
    assert record.selected_count == 2
    assert record.failed_count == 1
    assert record.selected_ligand_ids == ("lig-a", "lig-missing")


def test_an_engine_failure_keeps_the_job_it_failed_in() -> None:
    entry = GninaScreeningEntry(
        ligand_id="lig-failed",
        source_index=3,
        status=DockingJobStatus.FAILED,
        phase=DockingJobPhase.DOCKING,
        gnina_job_id="job-lig-failed",
        failure=_failure("GNINA_SCREENING_SYNTHETIC_ENGINE_FAILURE"),
        completed_at=_NOW,
    )

    assert not entry.is_preflight_failure
    assert _record([entry]).failed_count == 1


def test_a_canceled_molecule_is_recorded_whether_or_not_a_job_was_created() -> None:
    """Cancellation can land before submission or after it; both are terminal."""
    never_submitted = _queued("lig-early").model_copy(
        update={"status": DockingJobStatus.CANCELED, "completed_at": _NOW}
    )
    submitted = GninaScreeningEntry(
        ligand_id="lig-late",
        source_index=1,
        status=DockingJobStatus.CANCELED,
        phase=DockingJobPhase.DOCKING,
        gnina_job_id="job-lig-late",
        completed_at=_NOW,
    )
    record = _record(
        [never_submitted, submitted],
        status=DockingJobStatus.CANCELED,
        phase=DockingJobPhase.COMPLETE,
        completed_at=_NOW,
    )

    assert record.canceled_count == 2
    assert record.succeeded_count == 0


def test_a_queued_molecule_may_already_hold_a_job_queued_behind_an_active_one() -> None:
    """The service queues jobs itself, so 'queued with a job id' is honest.

    Calling such an entry `running` would be the dishonest alternative.
    """
    entry = _queued("lig-a", gnina_job_id="job-lig-a")

    assert entry.status is DockingJobStatus.QUEUED
    assert entry.gnina_job_id == "job-lig-a"


def test_a_failure_and_a_failed_status_cannot_exist_without_each_other() -> None:
    with pytest.raises(ValidationError, match="exactly when"):
        _queued("lig-a", failure=_failure())
    with pytest.raises(ValidationError, match="exactly when"):
        GninaScreeningEntry(
            ligand_id="lig-a",
            source_index=0,
            status=DockingJobStatus.FAILED,
            phase=DockingJobPhase.QUEUED,
        )


# --- selection order is not the library's numbering ------------------------


def test_selection_order_survives_a_reordered_or_sparse_library_index() -> None:
    """Entries are the applied selection in order; `source_index` never sorts them."""
    record = _record(
        [_completed("lig-x", 7), _completed("lig-y", 2), _completed("lig-z", 5)],
        status=DockingJobStatus.COMPLETED,
        phase=DockingJobPhase.COMPLETE,
        completed_at=_NOW,
    )

    assert record.selected_ligand_ids == ("lig-x", "lig-y", "lig-z")
    assert [entry.source_index for entry in record.entries] == [7, 2, 5]


def test_one_library_row_may_yield_two_selected_chemical_states() -> None:
    """Two protonation microstates of one compound are two ligands, not a duplicate."""
    record = _record(
        [
            _completed("lig-a-state-1", 4, chemical_state_id="state-1"),
            _completed("lig-a-state-2", 4, chemical_state_id="state-2"),
        ]
    )

    assert record.selected_count == 2


def test_a_molecule_with_no_library_record_cannot_be_the_one_docking() -> None:
    """Resolution precedes execution, so this combination is incoherent."""
    with pytest.raises(ValidationError, match="cannot be running"):
        _queued(
            "lig-a",
            source_index=None,
            status=DockingJobStatus.RUNNING,
            phase=DockingJobPhase.DOCKING,
            gnina_job_id="job-lig-a",
        )


@pytest.mark.parametrize(
    "missing",
    [
        "source_index",
        "chemical_state_id",
        "ligand_preparation_id",
        "ligand_sha256",
        "conformer_id",
        "conformer_sha256",
        "gnina_job_id",
    ],
)
def test_a_completed_entry_cannot_omit_what_it_docked_or_where(missing: str) -> None:
    with pytest.raises(ValidationError, match="completed screening entry"):
        _completed("lig-a", **{missing: None})


# --- contradictions a full record must refuse ------------------------------


def test_the_same_prepared_ligand_state_cannot_be_selected_twice() -> None:
    with pytest.raises(ValidationError, match="cannot be selected twice"):
        _record([_completed("lig-a", 0), _completed("lig-a", 1)])


def test_one_single_job_cannot_be_the_attempt_for_two_molecules() -> None:
    with pytest.raises(ValidationError, match="two molecules"):
        _record([_completed("lig-a", 0), _completed("lig-b", 1, gnina_job_id="job-lig-a")])


def test_a_finished_campaign_cannot_still_have_a_molecule_docking() -> None:
    running = _queued(
        "lig-b",
        1,
        status=DockingJobStatus.RUNNING,
        phase=DockingJobPhase.DOCKING,
        gnina_job_id="job-lig-b",
    )

    with pytest.raises(ValidationError, match="still have a molecule docking"):
        _record(
            [_completed("lig-a", 0), running],
            status=DockingJobStatus.COMPLETED,
            phase=DockingJobPhase.COMPLETE,
        )


def test_a_completed_campaign_cannot_still_have_pending_work() -> None:
    with pytest.raises(ValidationError, match="pending work"):
        _record(
            [_completed("lig-a", 0), _queued("lig-b", 1)],
            status=DockingJobStatus.COMPLETED,
            phase=DockingJobPhase.COMPLETE,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("selected_count", 5),
        ("succeeded_count", 2),
        ("failed_count", 1),
        ("canceled_count", 1),
        ("completed_count", 0),
    ],
)
def test_a_count_that_disagrees_with_the_entries_is_refused(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        _record([_completed("lig-a", 0)], **{field: value})


@pytest.mark.parametrize("field", ["library_id", "filter_run_id"])
def test_the_pinned_selection_and_the_request_must_name_the_same_inputs(field: str) -> None:
    with pytest.raises(ValidationError, match="different"):
        _record([_queued("lig-a")], selection=_selection(**{field: "something-else"}))


def test_screening_requires_the_same_explicit_acknowledgement_a_single_job_does() -> None:
    with pytest.raises(ValidationError, match="acknowledge_inputs_and_scoring"):
        _request(acknowledge_inputs_and_scoring=False)


def test_the_pinned_selection_identity_cannot_be_rewritten_in_place() -> None:
    """Changing it would silently restate what the campaign screened."""
    selection = _selection()

    with pytest.raises(ValidationError):
        selection.manifest_sha256 = "e5" * 32  # type: ignore[misc]


def test_an_unknown_campaign_field_is_refused_rather_than_ignored() -> None:
    with pytest.raises(ValidationError):
        _record([_queued("lig-a")], best_cnn_score=0.91)


# --- the small polling header ----------------------------------------------


def test_the_progress_header_carries_counts_instead_of_every_entry() -> None:
    """Polling a long campaign must not resend the whole selection each time."""
    assert "entries" not in GninaScreeningProgress.model_fields

    record = _record(
        [_completed("lig-a", 0), _queued("lig-b", 1)],
        revision=4,
    )
    progress = record.progress()

    assert progress.campaign_id == record.campaign_id
    assert progress.revision == 4
    assert progress.selected_count == 2
    assert progress.completed_count == 1
    assert progress.succeeded_count == 1


def _progress(**overrides: object) -> GninaScreeningProgress:
    args: dict[str, object] = {
        "campaign_id": "campaign-synthetic",
        "status": DockingJobStatus.RUNNING,
        "phase": DockingJobPhase.DOCKING,
        "revision": 1,
        "selected_count": 4,
        "completed_count": 2,
        "succeeded_count": 1,
        "failed_count": 1,
        "canceled_count": 0,
    }
    return GninaScreeningProgress(**(args | overrides))  # type: ignore[arg-type]


def test_progress_cannot_report_more_finished_molecules_than_were_selected() -> None:
    with pytest.raises(ValidationError, match="cannot exceed selected_count"):
        _progress(selected_count=1, completed_count=2, succeeded_count=2, failed_count=0)


def test_progress_counts_must_add_up() -> None:
    with pytest.raises(ValidationError, match="must equal"):
        _progress(completed_count=3)


def test_progress_counts_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        _progress(failed_count=-1)
