"""Project-scoped, transactional persistence for GNINA screening campaigns.

This is step 1 of `docs/validation/GNINA_SCREENING_PLAN.md`: a storage
foundation, **not** an executable workflow. Nothing here starts a job, schedules
work, reserves a device or runs GNINA. Orchestration and the localhost API are
separate items of that plan.

**The created campaign is the immutable account of what was selected.**
`record.json` is written once, at creation, and never rewritten. It holds the
applied selection in selection order together with each entry's scientific
identifiers. Live lifecycle state lives in a SQLite sidecar beside it, so an
update can never edit, reorder or renumber the original selection.

**Selection order is a stored column, not a sort key.** Entries are addressed by
`ligand_id` and ordered by `selection_order`, the position the scientist's
applied selection gave them. `source_index` is library provenance: it may be
absent and two entries may share one, so it is never used to order or identify
anything. See the `schemas/gnina_screening.py` docstring.

**An entry row is written one at a time.** A screening campaign is polled while
it runs, and the execution path finishes one molecule at a time, so
`update_entry` touches exactly one row and `load_progress` reads only the stored
header. Neither is O(selection size), and neither rewrites `record.json`.

**A completed entry is verified before it is believed.** `update_entry` refuses
to record success until the referenced GNINA single job has been re-read and
still matches this campaign's receptor, box, tool build, settings and this
entry's prepared ligand, with its preserved input and pose bytes intact
(`services/gnina_screening_evidence.py`). The verified pose is used as a gate
and then discarded: no score, affinity or pose is ever copied into campaign
storage, because the single job already owns them and a second copy could drift
from the job it came from.

**Terminal entries are frozen and the campaign's outcome is derived.** An entry
that completed, failed or was canceled is never updated again, and
`finalize_campaign` computes the campaign's terminal status from its entries
rather than accepting one, so a run that produced no successful job cannot be
recorded as completed.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.project_context import resolve_project_root
from ankora_backend.persistence.gnina_store import GninaJobStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.schemas.binding_sites import BindingBox
from ankora_backend.schemas.docking import DockingFailure, DockingJobPhase, DockingJobStatus
from ankora_backend.schemas.gnina import GninaDockingRequest, GninaJobRecord, GninaToolIdentity
from ankora_backend.schemas.gnina_screening import (
    TERMINAL_CAMPAIGN_STATES,
    TERMINAL_ENTRY_STATES,
    GninaScreeningCampaignRecord,
    GninaScreeningEntry,
    GninaScreeningProgress,
    GninaScreeningRequest,
)
from ankora_backend.schemas.ligand_library_preparation import (
    LigandPreparationEntry,
    LigandPreparationStatus,
)
from ankora_backend.services.gnina_screening_evidence import verified_screening_pose
from ankora_backend.services.gnina_screening_preparation import verified_screening_preparation
from ankora_backend.services.gnina_screening_selection import verified_screening_selection

_DATABASE_NAME = "campaign_state.sqlite3"
_RECORD_NAME = "record.json"
_SCHEMA_VERSION = "1"
_CAMPAIGNS_DIRECTORY = "gnina_screening_campaigns"

# Lifecycle moves a selected molecule can still make. A state absent from this
# map is terminal and has no outgoing transition at all.
#
# `cancel_requested -> completed` is deliberately absent. A job that finished
# while cancellation was already requested loses nothing by being recorded as
# canceled: the single job keeps its own poses, raw outputs and execution
# evidence either way, and the campaign stays honest about the scientist having
# stopped the run. Publishing it as a campaign success instead would overrule
# that decision in storage.
_ALLOWED_ENTRY_TRANSITIONS: dict[DockingJobStatus, frozenset[DockingJobStatus]] = {
    DockingJobStatus.QUEUED: frozenset(
        {
            DockingJobStatus.QUEUED,
            DockingJobStatus.RUNNING,
            DockingJobStatus.CANCEL_REQUESTED,
            # A preflight refusal and a cancellation before submission.
            DockingJobStatus.FAILED,
            DockingJobStatus.CANCELED,
        }
    ),
    DockingJobStatus.RUNNING: frozenset(
        {
            DockingJobStatus.RUNNING,
            DockingJobStatus.CANCEL_REQUESTED,
            DockingJobStatus.COMPLETED,
            DockingJobStatus.FAILED,
            DockingJobStatus.CANCELED,
        }
    ),
    DockingJobStatus.CANCEL_REQUESTED: frozenset(
        {
            DockingJobStatus.CANCEL_REQUESTED,
            DockingJobStatus.CANCELED,
            DockingJobStatus.FAILED,
        }
    ),
}

# Scientific identifiers of a selected molecule. An unresolved one may be filled
# in once, because resolution legitimately precedes execution; a recorded one is
# frozen, because changing it would silently restate which molecule this entry
# is. `ligand_id` is not listed: it addresses the row, so a changed `ligand_id`
# is simply a different entry.
_ENTRY_IDENTITY_FIELDS = (
    "chemical_state_id",
    "source_index",
    "name",
    "ligand_preparation_id",
    "ligand_sha256",
    "conformer_id",
    "conformer_sha256",
)

_STATE_LOCKS: dict[str, threading.RLock] = {}
_STATE_LOCKS_GUARD = threading.Lock()


def _state_lock(directory: Path) -> threading.RLock:
    """One lock per campaign directory, shared by every store instance here.

    Cross-process writers are serialized by `BEGIN IMMEDIATE`; this keeps
    threads in one process from colliding on the same campaign.
    """
    key = str(directory)
    with _STATE_LOCKS_GUARD:
        lock = _STATE_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _STATE_LOCKS[key] = lock
        return lock


class GninaScreeningStore:
    """Create, read and incrementally update one project's screening campaigns."""

    def __init__(self, root: Path, project_id: str | None = None) -> None:
        self._project_root = resolve_project_root(root, project_id)
        # The job store is built for this same project rather than injected:
        # a campaign may only ever verify jobs belonging to its own project.
        self._jobs = GninaJobStore(root, project_id)
        self._ligands = LigandArtifactStore(root, project_id)

    @classmethod
    def from_environment(cls, project_id: str | None = None) -> GninaScreeningStore:
        configured = os.getenv("ANKORA_DATA_DIR")
        return cls(Path(configured) if configured else Path.cwd() / ".ankora-data", project_id)

    @property
    def jobs(self) -> GninaJobStore:
        """The single-job store this campaign store verifies against."""
        return self._jobs

    def new_campaign_id(self) -> str:
        return str(uuid4())

    # --- paths --------------------------------------------------------------

    def campaign_directory(self, campaign_id: str) -> Path:
        """A UUID-normalized directory that cannot escape this project."""
        try:
            normalized = str(UUID(campaign_id))
        except (ValueError, AttributeError, TypeError) as error:
            raise self._campaign_not_found(campaign_id) from error
        directory = (self._project_root / "results" / _CAMPAIGNS_DIRECTORY / normalized).resolve()
        if self._project_root not in directory.parents:
            raise self._campaign_not_found(campaign_id)
        return directory

    # --- creation -----------------------------------------------------------

    def create_campaign(self, record: GninaScreeningCampaignRecord) -> Path:
        """Write the immutable selection snapshot, then build its live sidecar.

        Create-only: an existing campaign is never reopened or overwritten.
        """
        record = GninaScreeningCampaignRecord.model_validate(record.model_dump())
        if (
            record.status is not DockingJobStatus.QUEUED
            or record.phase is not DockingJobPhase.QUEUED
            or record.revision != 0
            or any(
                entry.status not in {DockingJobStatus.QUEUED, DockingJobStatus.FAILED}
                or entry.gnina_job_id is not None
                or entry.revision != 0
                for entry in record.entries
            )
        ):
            raise self._invalid_campaign(
                record.campaign_id,
                "a new campaign must start queued with only queued or preflight-failed entries",
            )
        selection = verified_screening_selection(
            store=self._ligands,
            library_id=record.request.library_id,
            filter_run_id=record.request.filter_run_id,
        )
        selected_states = {item.ligand_id: item.state_id for item in selection.evaluations}
        selected_indices = {item.ligand_id: item.record_index for item in selection.evaluations}
        if (
            selection.artifact.sha256 != record.selection.manifest_sha256
            or selection.artifact.filter_run_id != record.selection.manifest_artifact_id
            or list(record.selected_ligand_ids) != selection.selected_ligand_ids
            or any(
                entry.chemical_state_id != selected_states.get(entry.ligand_id)
                for entry in record.entries
            )
            or any(
                entry.source_index is not None
                and entry.source_index != selected_indices.get(entry.ligand_id)
                for entry in record.entries
            )
        ):
            raise self._invalid_campaign(
                record.campaign_id, "campaign entries differ from the applied selection"
            )
        for entry in record.entries:
            if entry.revision > record.revision:
                # The campaign revision is the cursor every entry revision is
                # stamped from, so it cannot start out behind one of them.
                raise self._invalid_campaign(
                    record.campaign_id,
                    "an entry revision cannot exceed the campaign revision",
                )
        directory = self.campaign_directory(record.campaign_id)
        with _state_lock(directory):
            try:
                directory.mkdir(parents=True, exist_ok=False)
            except FileExistsError as error:
                raise self._campaign_exists(record.campaign_id) from error
            payload = record.model_dump(mode="json")
            with (directory / _RECORD_NAME).open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
            self._build_database(directory, record)
        return directory

    # --- reads --------------------------------------------------------------

    def original_selection(self, campaign_id: str) -> GninaScreeningCampaignRecord:
        """The creation snapshot, exactly as it was recorded and never rewritten."""
        directory = self.campaign_directory(campaign_id)
        try:
            raw = (directory / _RECORD_NAME).read_bytes()
        except OSError as error:
            raise self._campaign_not_found(campaign_id) from error
        return GninaScreeningCampaignRecord.model_validate_json(raw)

    def load_campaign(self, campaign_id: str) -> GninaScreeningCampaignRecord:
        """The live campaign: stored header plus every entry in selection order."""
        directory = self.campaign_directory(campaign_id)
        with _state_lock(directory), self._connect(campaign_id, directory) as database:
            summary = self._summary(campaign_id, database)
            entries = self._entry_payloads(database)
        return GninaScreeningCampaignRecord.model_validate({**summary, "entries": entries})

    def load_progress(self, campaign_id: str) -> GninaScreeningProgress:
        """The compact polling header, read without touching a single entry row.

        This is the whole point of the sidecar: polling a long campaign must
        stay cheap, so the counters come from the stored header and no entry is
        loaded, parsed or rewritten here.
        """
        directory = self.campaign_directory(campaign_id)
        with _state_lock(directory), self._connect(campaign_id, directory) as database:
            summary = self._summary(campaign_id, database)
        return GninaScreeningProgress.model_validate(
            {
                field: summary[field]
                for field in GninaScreeningProgress.model_fields
                if field in summary
            }
        )

    def load_entry(self, campaign_id: str, ligand_id: str) -> GninaScreeningEntry | None:
        directory = self.campaign_directory(campaign_id)
        with _state_lock(directory), self._connect(campaign_id, directory) as database:
            row = database.execute(
                "SELECT payload_json FROM entries WHERE ligand_id = ?", (ligand_id,)
            ).fetchone()
        if row is None:
            return None
        return GninaScreeningEntry.model_validate_json(str(row[0]))

    def entries_after_revision(self, campaign_id: str, revision: int) -> list[GninaScreeningEntry]:
        """Only what changed since `revision`, in selection order.

        Every update stamps the campaign's next revision onto the one row it
        touched, so this is a correct delta cursor for an incremental reader.
        """
        directory = self.campaign_directory(campaign_id)
        with _state_lock(directory), self._connect(campaign_id, directory) as database:
            rows = database.execute(
                """
                SELECT payload_json FROM entries
                WHERE revision > ?
                ORDER BY selection_order
                """,
                (revision,),
            ).fetchall()
        return [GninaScreeningEntry.model_validate_json(str(row[0])) for row in rows]

    def list_campaign_ids(self) -> list[str]:
        directory = self._project_root / "results" / _CAMPAIGNS_DIRECTORY
        if not directory.is_dir():
            return []
        return sorted(
            candidate.name
            for candidate in directory.iterdir()
            if candidate.is_dir() and (candidate / _DATABASE_NAME).is_file()
        )

    # --- incremental update -------------------------------------------------

    def update_entry(self, campaign_id: str, entry: GninaScreeningEntry) -> GninaScreeningEntry:
        """Atomically advance one selected molecule, the revision and the counters.

        The caller's `entry.revision` must still be the stored one. A stale copy
        is refused rather than written, so two store instances holding the same
        entry cannot silently overwrite each other.
        """
        entry = GninaScreeningEntry.model_validate(entry.model_dump())
        directory = self.campaign_directory(campaign_id)
        with _state_lock(directory), self._connect(campaign_id, directory) as database:
            try:
                database.execute("BEGIN IMMEDIATE")
                summary = self._summary(campaign_id, database)
                if summary["status"] in {state.value for state in TERMINAL_CAMPAIGN_STATES}:
                    raise self._invalid_campaign(campaign_id, "a terminal campaign is immutable")
                located = self._stored_entry(database, entry.ligand_id)
                if located is None:
                    raise self._entry_not_found(campaign_id, entry.ligand_id)
                selection_order, stored = located
                self._guard_transition(campaign_id, stored, entry)
                self._guard_identity(campaign_id, stored, entry)
                self._guard_job_reference(campaign_id, summary, stored, entry)

                next_revision = int(summary["revision"]) + 1
                updated = entry.model_copy(update={"revision": next_revision})
                self._write_entry(database, selection_order=selection_order, entry=updated)
                summary["revision"] = next_revision
                self._adjust_counters(summary, stored.status, updated.status)
                self._observe_campaign_start(summary, updated)
                self._write_summary(database, summary)
                database.commit()
            except BaseException:
                database.rollback()
                raise
        return updated

    def finalize_campaign(self, campaign_id: str) -> GninaScreeningProgress:
        """Derive the campaign's terminal status from its entries.

        The status is computed, never supplied: a campaign whose jobs all failed
        or were canceled cannot be recorded as completed, and a campaign that
        still has pending work cannot be finalized at all.

        This runs once per campaign, so unlike polling it may read the entries.
        """
        directory = self.campaign_directory(campaign_id)
        with _state_lock(directory), self._connect(campaign_id, directory) as database:
            try:
                database.execute("BEGIN IMMEDIATE")
                summary = self._summary(campaign_id, database)
                if summary["status"] in {state.value for state in TERMINAL_CAMPAIGN_STATES}:
                    raise self._invalid_campaign(campaign_id, "a terminal campaign is immutable")
                entries = [
                    GninaScreeningEntry.model_validate(payload)
                    for payload in self._entry_payloads(database)
                ]
                pending = [entry.ligand_id for entry in entries if not entry.is_terminal]
                if pending:
                    raise AnkoraDomainError(
                        code="GNINA_SCREENING_CAMPAIGN_PENDING",
                        stage="gnina_screening_storage",
                        message="This screening campaign still has unfinished molecules.",
                        status_code=409,
                        details={
                            "campaign_id": campaign_id,
                            "pending_count": len(pending),
                            "pending_ligand_ids": pending[:10],
                        },
                    )
                succeeded = sum(
                    1 for entry in entries if entry.status is DockingJobStatus.COMPLETED
                )
                canceled = sum(1 for entry in entries if entry.status is DockingJobStatus.CANCELED)
                if canceled:
                    # A stopped run is a canceled run even when some molecules
                    # finished first; the successful jobs keep their own records.
                    status = DockingJobStatus.CANCELED
                elif succeeded:
                    status = DockingJobStatus.COMPLETED
                else:
                    status = DockingJobStatus.FAILED

                summary["status"] = status.value
                summary["phase"] = DockingJobPhase.COMPLETE.value
                summary["revision"] = int(summary["revision"]) + 1
                summary["completed_at"] = self._latest_completion(entries)
                self._apply_exact_counters(database, summary)
                self._write_summary(database, summary)
                database.commit()
            except BaseException:
                database.rollback()
                raise
        return self.load_progress(campaign_id)

    def recover_interrupted_campaign(
        self, campaign_id: str, *, interrupted_at: datetime
    ) -> GninaScreeningProgress:
        """Mark an abandoned campaign interrupted without retrying or hiding work.

        Call only after the runtime has established that the prior owner is no
        longer active. Existing terminal entries remain untouched. Job IDs are
        retained even when the corresponding job is missing; this operation does
        not claim those jobs were verified or change their scientific artifacts.
        The complete transition is one SQLite transaction and can be retried
        after a crash. A terminal campaign is returned unchanged.
        """
        if interrupted_at.utcoffset() is None:
            raise ValueError("interrupted_at must include a timezone")
        directory = self.campaign_directory(campaign_id)
        with _state_lock(directory), self._connect(campaign_id, directory) as database:
            try:
                database.execute("BEGIN IMMEDIATE")
                summary = self._summary(campaign_id, database)
                if summary["status"] not in {state.value for state in TERMINAL_CAMPAIGN_STATES}:
                    rows = database.execute(
                        "SELECT selection_order, payload_json FROM entries ORDER BY selection_order"
                    ).fetchall()
                    revision = int(summary["revision"])
                    interrupted = 0
                    for order, payload in rows:
                        entry = GninaScreeningEntry.model_validate_json(str(payload))
                        if entry.status in TERMINAL_ENTRY_STATES:
                            continue
                        interrupted += 1
                        revision += 1
                        updated = self._interrupted_entry(
                            campaign_id, summary, entry, interrupted_at, revision
                        )
                        self._write_entry(database, selection_order=int(order), entry=updated)
                    summary["status"] = DockingJobStatus.FAILED.value
                    summary["phase"] = DockingJobPhase.COMPLETE.value
                    summary["completed_at"] = interrupted_at.isoformat()
                    summary["revision"] = revision + 1
                    summary["failure"] = DockingFailure(
                        code="GNINA_SCREENING_CAMPAIGN_INTERRUPTED",
                        message="The campaign was interrupted; no automatic retry was started.",
                        details={"interrupted_entry_count": interrupted},
                    ).model_dump(mode="json")
                    self._apply_exact_counters(database, summary)
                    self._write_summary(database, summary)
                database.commit()
            except BaseException:
                database.rollback()
                raise
        return self.load_progress(campaign_id)

    def _interrupted_entry(
        self,
        campaign_id: str,
        summary: dict[str, Any],
        entry: GninaScreeningEntry,
        interrupted_at: datetime,
        revision: int,
    ) -> GninaScreeningEntry:
        """Keep a verified terminal job or preserve an explicitly interrupted link."""
        updates: dict[str, Any] = {
            "status": DockingJobStatus.FAILED,
            "phase": DockingJobPhase.COMPLETE,
            "completed_at": interrupted_at,
            "failure": DockingFailure(
                code="GNINA_SCREENING_ENTRY_INTERRUPTED",
                message="The campaign was interrupted; no automatic retry was started.",
                details={"previous_status": entry.status.value, "gnina_job_id": entry.gnina_job_id},
            ),
            "revision": revision,
        }
        if entry.gnina_job_id is not None:
            try:
                job = self._matching_job(campaign_id, summary, entry)
                if job.status is DockingJobStatus.COMPLETED and job.completed_at is not None:
                    self._verify_completed_job(campaign_id, summary, entry)
                    updates.update(
                        {
                            "status": DockingJobStatus.COMPLETED,
                            "started_at": entry.started_at or job.started_at,
                            "completed_at": job.completed_at,
                            "failure": None,
                        }
                    )
                elif job.status is DockingJobStatus.FAILED:
                    updates.update(
                        {
                            "started_at": entry.started_at or job.started_at,
                            "completed_at": job.completed_at or interrupted_at,
                            "failure": job.failure or updates["failure"],
                        }
                    )
                elif job.status is DockingJobStatus.CANCELED:
                    updates.update(
                        {
                            "status": DockingJobStatus.CANCELED,
                            "started_at": entry.started_at or job.started_at,
                            "completed_at": job.completed_at or interrupted_at,
                            "failure": None,
                        }
                    )
                elif job.status is DockingJobStatus.COMPLETED:
                    raise ValueError("completed job has no recorded completion time")
            except (AnkoraDomainError, OSError, ValueError) as error:
                # Preserve the claimed ID and show why it was not published.
                reason = (
                    error.code if isinstance(error, AnkoraDomainError) else type(error).__name__
                )
                updates["failure"] = DockingFailure(
                    code="GNINA_SCREENING_RECOVERY_UNVERIFIED",
                    message="The linked job could not be verified; no pose was published.",
                    details={"gnina_job_id": entry.gnina_job_id, "reason_code": reason},
                )
        return GninaScreeningEntry.model_validate(entry.model_copy(update=updates).model_dump())

    # --- guards -------------------------------------------------------------

    def _guard_transition(
        self, campaign_id: str, stored: GninaScreeningEntry, entry: GninaScreeningEntry
    ) -> None:
        if stored.revision != entry.revision:
            raise AnkoraDomainError(
                code="GNINA_SCREENING_ENTRY_STALE",
                stage="gnina_screening_storage",
                message="This screening entry changed since it was read; reload it and retry.",
                status_code=409,
                details={
                    "campaign_id": campaign_id,
                    "ligand_id": entry.ligand_id,
                    "stored_revision": stored.revision,
                    "supplied_revision": entry.revision,
                },
            )
        if stored.status in TERMINAL_ENTRY_STATES:
            raise AnkoraDomainError(
                code="GNINA_SCREENING_ENTRY_TERMINAL",
                stage="gnina_screening_storage",
                message="A completed, failed or canceled screening entry is never rewritten.",
                status_code=409,
                details={
                    "campaign_id": campaign_id,
                    "ligand_id": entry.ligand_id,
                    "status": stored.status.value,
                },
            )
        allowed = _ALLOWED_ENTRY_TRANSITIONS.get(stored.status, frozenset())
        if entry.status not in allowed:
            raise AnkoraDomainError(
                code="GNINA_SCREENING_TRANSITION_REFUSED",
                stage="gnina_screening_storage",
                message="That screening-entry lifecycle transition is not possible.",
                status_code=409,
                details={
                    "campaign_id": campaign_id,
                    "ligand_id": entry.ligand_id,
                    "from": stored.status.value,
                    "to": entry.status.value,
                },
            )

    def _guard_identity(
        self, campaign_id: str, stored: GninaScreeningEntry, entry: GninaScreeningEntry
    ) -> None:
        for field in _ENTRY_IDENTITY_FIELDS:
            recorded = getattr(stored, field)
            supplied = getattr(entry, field)
            if supplied != recorded and (recorded is not None or field == "source_index"):
                raise AnkoraDomainError(
                    code="GNINA_SCREENING_ENTRY_IDENTITY_CHANGED",
                    stage="gnina_screening_storage",
                    message="A recorded screening-entry identifier cannot be changed.",
                    status_code=409,
                    details={
                        "campaign_id": campaign_id,
                        "ligand_id": entry.ligand_id,
                        "field": field,
                    },
                )
        if stored.gnina_job_id is not None and entry.gnina_job_id != stored.gnina_job_id:
            raise AnkoraDomainError(
                code="GNINA_SCREENING_ENTRY_IDENTITY_CHANGED",
                stage="gnina_screening_storage",
                message="A screening entry cannot be reassigned to a different GNINA job.",
                status_code=409,
                details={
                    "campaign_id": campaign_id,
                    "ligand_id": entry.ligand_id,
                    "field": "gnina_job_id",
                },
            )

    def _guard_job_reference(
        self,
        campaign_id: str,
        summary: dict[str, Any],
        stored: GninaScreeningEntry,
        entry: GninaScreeningEntry,
    ) -> None:
        """Check the claimed single job before the campaign believes the entry."""
        if entry.gnina_job_id is None:
            # A preflight refusal or a cancellation before submission. Honest and
            # verifiable on its own: there is no job to check.
            return
        if entry.status is DockingJobStatus.COMPLETED:
            self._verify_completed_job(campaign_id, summary, entry)
        else:
            job = self._matching_job(campaign_id, summary, entry)
            if (
                entry.status in {DockingJobStatus.FAILED, DockingJobStatus.CANCELED}
                and job.status is not entry.status
            ):
                raise self._job_mismatch(campaign_id, entry, "job status differs from entry")

    def _matching_job(
        self, campaign_id: str, summary: dict[str, Any], entry: GninaScreeningEntry
    ) -> GninaJobRecord:
        job_id = entry.gnina_job_id
        if (
            job_id is None
            or entry.ligand_preparation_id is None
            or entry.ligand_sha256 is None
            or entry.conformer_sha256 is None
            or entry.conformer_id is None
            or entry.chemical_state_id is None
        ):
            raise self._job_mismatch(campaign_id, entry, "missing prepared-input identity")
        request = GninaScreeningRequest.model_validate(summary["request"])
        expected = GninaDockingRequest(
            receptor_id=request.receptor_id,
            binding_site_id=request.binding_site_id,
            ligand_id=entry.ligand_id,
            ligand_preparation_id=entry.ligand_preparation_id,
            parameters=request.parameters,
            acknowledge_inputs_and_scoring=True,
        )
        job = self._jobs.load_job(job_id)
        if (
            job.job_id != job_id
            or job.request != expected
            or job.box != BindingBox.model_validate(summary["box"])
            or job.receptor_output_artifact_id != str(summary["receptor_output_artifact_id"])
            or job.receptor_sha256 != str(summary["receptor_sha256"])
            or job.tool != GninaToolIdentity.model_validate(summary["tool"])
            or job.ligand_sha256 != entry.ligand_sha256
            or job.conformer_sha256 != entry.conformer_sha256
        ):
            raise self._job_mismatch(campaign_id, entry, "job inputs differ from the campaign")
        return job

    def _verify_completed_job(
        self, campaign_id: str, summary: dict[str, Any], entry: GninaScreeningEntry
    ) -> None:
        """Re-read the referenced job and refuse success unless it still matches.

        The verified pose is a gate, not a payload: it is discarded here, and no
        score, affinity or pose is written into campaign storage.
        """
        job = self._matching_job(campaign_id, summary, entry)
        job_id = job.job_id
        if (
            entry.ligand_preparation_id is None
            or entry.ligand_sha256 is None
            or entry.conformer_sha256 is None
            or entry.conformer_id is None
            or entry.chemical_state_id is None
        ):
            raise self._job_mismatch(campaign_id, entry, "missing prepared-input hashes")
        preparation = LigandPreparationEntry(
            ligand_id=entry.ligand_id,
            chemical_state_id=entry.chemical_state_id,
            status=LigandPreparationStatus.PREPARED,
            conformer_id=entry.conformer_id,
            pdbqt_preparation_id=entry.ligand_preparation_id,
            updated_at=summary["created_at"],
        )
        pdbqt, conformer = verified_screening_preparation(
            store=self._ligands,
            ligand_id=entry.ligand_id,
            expected_state_id=entry.chemical_state_id,
            preparation=preparation,
        )
        if (
            pdbqt.artifact.sha256 != entry.ligand_sha256
            or conformer.artifact.sha256 != entry.conformer_sha256
        ):
            raise self._job_mismatch(campaign_id, entry, "prepared-input hashes changed")
        # Only the header pieces this check needs; the stored counters describe
        # the whole selection, so the full record is not reassembled here.
        request = GninaScreeningRequest.model_validate(summary["request"])
        tool = GninaToolIdentity.model_validate(summary["tool"])
        box = BindingBox.model_validate(summary["box"])
        expected_request = GninaDockingRequest(
            receptor_id=request.receptor_id,
            binding_site_id=request.binding_site_id,
            ligand_id=entry.ligand_id,
            ligand_preparation_id=entry.ligand_preparation_id,
            parameters=request.parameters,
            acknowledge_inputs_and_scoring=True,
        )
        verified_screening_pose(
            store=self._jobs,
            job_id=job_id,
            expected_request=expected_request,
            expected_receptor_sha256=str(summary["receptor_sha256"]),
            expected_ligand_sha256=entry.ligand_sha256,
            expected_conformer_sha256=entry.conformer_sha256,
            expected_tool_sha256=tool.sha256,
        )
        # Beyond the single-job projection: the campaign's own inputs. The
        # verifier checks the request, receptor bytes, tool build and preserved
        # pose; these bind the job to this campaign's box and receptor artifact
        # and to this entry's prepared ligand.
        if (
            job.box != box
            or job.receptor_output_artifact_id != str(summary["receptor_output_artifact_id"])
            or job.tool != tool
            or job.ligand_sha256 != entry.ligand_sha256
        ):
            raise self._job_mismatch(campaign_id, entry, "job inputs differ from the campaign")

    # --- sqlite -------------------------------------------------------------

    def _build_database(self, directory: Path, record: GninaScreeningCampaignRecord) -> None:
        path = directory / _DATABASE_NAME
        temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        try:
            database = sqlite3.connect(temporary)
            try:
                database.execute("PRAGMA synchronous = FULL")
                database.executescript(
                    """
                    CREATE TABLE metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    CREATE TABLE entries (
                        selection_order INTEGER PRIMARY KEY,
                        ligand_id TEXT NOT NULL UNIQUE,
                        status TEXT NOT NULL,
                        revision INTEGER NOT NULL,
                        gnina_job_id TEXT,
                        payload_json TEXT NOT NULL
                    );
                    CREATE UNIQUE INDEX entries_job ON entries(gnina_job_id);
                    CREATE INDEX entries_status ON entries(status, selection_order);
                    CREATE INDEX entries_revision ON entries(revision, selection_order);
                    """
                )
                database.execute(
                    "INSERT INTO metadata(key, value) VALUES('schema_version', ?)",
                    (_SCHEMA_VERSION,),
                )
                for order, entry in enumerate(record.entries):
                    self._write_entry(database, selection_order=order, entry=entry)
                self._write_summary(database, record.model_dump(mode="json", exclude={"entries"}))
                database.commit()
            finally:
                database.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @contextmanager
    def _connect(self, campaign_id: str, directory: Path) -> Iterator[sqlite3.Connection]:
        path = directory / _DATABASE_NAME
        if not path.is_file():
            raise self._campaign_not_found(campaign_id)
        database = sqlite3.connect(path, timeout=30)
        try:
            database.execute("PRAGMA synchronous = FULL")
            yield database
        finally:
            database.close()

    def _summary(self, campaign_id: str, database: sqlite3.Connection) -> dict[str, Any]:
        version = database.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        if version is None or str(version[0]) != _SCHEMA_VERSION:
            # Fail closed: an unknown layout is never silently rebuilt over.
            found = "missing" if version is None else str(version[0])
            raise self._invalid_campaign(
                campaign_id, f"unsupported screening campaign state schema: {found}"
            )
        row = database.execute("SELECT value FROM metadata WHERE key = 'summary_json'").fetchone()
        if row is None:
            raise self._invalid_campaign(campaign_id, "screening campaign state has no header")
        return cast(dict[str, Any], json.loads(str(row[0])))

    @staticmethod
    def _write_summary(database: sqlite3.Connection, summary: dict[str, Any]) -> None:
        payload = json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        database.execute(
            """
            INSERT INTO metadata(key, value) VALUES('summary_json', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (payload,),
        )

    @staticmethod
    def _entry_payloads(database: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = database.execute(
            "SELECT payload_json FROM entries ORDER BY selection_order"
        ).fetchall()
        return [cast(dict[str, Any], json.loads(str(row[0]))) for row in rows]

    @staticmethod
    def _stored_entry(
        database: sqlite3.Connection, ligand_id: str
    ) -> tuple[int, GninaScreeningEntry] | None:
        """The stored entry with its selection position, which is not a model field."""
        row = database.execute(
            "SELECT selection_order, payload_json FROM entries WHERE ligand_id = ?",
            (ligand_id,),
        ).fetchone()
        if row is None:
            return None
        return int(row[0]), GninaScreeningEntry.model_validate_json(str(row[1]))

    def _write_entry(
        self, database: sqlite3.Connection, *, selection_order: int, entry: GninaScreeningEntry
    ) -> None:
        try:
            database.execute(
                """
                INSERT INTO entries(
                    selection_order, ligand_id, status, revision, gnina_job_id, payload_json
                ) VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(selection_order) DO UPDATE SET
                    status = excluded.status,
                    revision = excluded.revision,
                    gnina_job_id = excluded.gnina_job_id,
                    payload_json = excluded.payload_json
                """,
                (
                    selection_order,
                    entry.ligand_id,
                    entry.status.value,
                    entry.revision,
                    entry.gnina_job_id,
                    entry.model_dump_json(),
                ),
            )
        except sqlite3.IntegrityError as error:
            raise AnkoraDomainError(
                code="GNINA_SCREENING_JOB_ALREADY_CLAIMED",
                stage="gnina_screening_storage",
                message="One GNINA single job cannot be the attempt for two molecules.",
                status_code=409,
                details={"ligand_id": entry.ligand_id, "gnina_job_id": entry.gnina_job_id},
            ) from error

    @staticmethod
    def _adjust_counters(
        summary: dict[str, Any], previous: DockingJobStatus, current: DockingJobStatus
    ) -> None:
        """Update one row's counters in constant work inside its transaction."""
        fields = {
            DockingJobStatus.COMPLETED: "succeeded_count",
            DockingJobStatus.FAILED: "failed_count",
            DockingJobStatus.CANCELED: "canceled_count",
        }
        for state, direction in ((previous, -1), (current, 1)):
            field = fields.get(state)
            if field is not None:
                summary[field] = int(summary[field]) + direction
                summary["completed_count"] = int(summary["completed_count"]) + direction

    @staticmethod
    def _apply_exact_counters(database: sqlite3.Connection, summary: dict[str, Any]) -> None:
        """Count the stored statuses in the same transaction as the write.

        Derived rather than incremented, so the header cannot drift from the
        rows it summarizes. This reads the status index only: no entry payload
        is parsed and no entry row is rewritten.
        """
        counts = {
            str(status): int(count)
            for status, count in database.execute(
                "SELECT status, COUNT(*) FROM entries GROUP BY status"
            ).fetchall()
        }
        succeeded = counts.get(DockingJobStatus.COMPLETED.value, 0)
        failed = counts.get(DockingJobStatus.FAILED.value, 0)
        canceled = counts.get(DockingJobStatus.CANCELED.value, 0)
        summary["selected_count"] = sum(counts.values())
        summary["succeeded_count"] = succeeded
        summary["failed_count"] = failed
        summary["canceled_count"] = canceled
        summary["completed_count"] = succeeded + failed + canceled

    @staticmethod
    def _observe_campaign_start(summary: dict[str, Any], entry: GninaScreeningEntry) -> None:
        """Record that work began, from the entry that reports having begun it.

        The time is the entry's own `started_at`; the store invents no clock
        reading of its own.
        """
        if summary.get("status") != DockingJobStatus.QUEUED.value:
            return
        if entry.status is DockingJobStatus.QUEUED or entry.started_at is None:
            return
        summary["status"] = DockingJobStatus.RUNNING.value
        summary["phase"] = DockingJobPhase.DOCKING.value
        summary["started_at"] = entry.started_at.isoformat()

    @staticmethod
    def _latest_completion(entries: list[GninaScreeningEntry]) -> str:
        completions = [entry.completed_at for entry in entries if entry.completed_at is not None]
        if not completions:  # pragma: no cover - every terminal entry records one
            raise ValueError("a finished screening campaign has no recorded completion time")
        return max(completions).isoformat()

    # --- errors -------------------------------------------------------------

    @staticmethod
    def _campaign_not_found(campaign_id: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="GNINA_SCREENING_CAMPAIGN_NOT_FOUND",
            stage="gnina_screening_storage",
            message="No GNINA screening campaign exists for this identifier in this project.",
            status_code=404,
            details={"campaign_id": campaign_id},
        )

    @staticmethod
    def _campaign_exists(campaign_id: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="GNINA_SCREENING_CAMPAIGN_EXISTS",
            stage="gnina_screening_storage",
            message="A GNINA screening campaign with this identifier already exists.",
            status_code=409,
            details={"campaign_id": campaign_id},
        )

    @staticmethod
    def _invalid_campaign(campaign_id: str, reason: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="GNINA_SCREENING_CAMPAIGN_INVALID",
            stage="gnina_screening_storage",
            message="This GNINA screening campaign's stored state cannot be used.",
            status_code=409,
            details={"campaign_id": campaign_id, "reason": reason},
            recoverable=False,
        )

    @staticmethod
    def _entry_not_found(campaign_id: str, ligand_id: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="GNINA_SCREENING_ENTRY_NOT_FOUND",
            stage="gnina_screening_storage",
            message="This molecule is not part of this screening campaign's selection.",
            status_code=404,
            details={"campaign_id": campaign_id, "ligand_id": ligand_id},
        )

    @staticmethod
    def _job_mismatch(
        campaign_id: str, entry: GninaScreeningEntry, reason: str
    ) -> AnkoraDomainError:
        return AnkoraDomainError(
            code="GNINA_SCREENING_JOB_MISMATCH",
            stage="gnina_screening_storage",
            message="The recorded GNINA job or its preserved inputs do not match this entry.",
            status_code=409,
            details={
                "campaign_id": campaign_id,
                "ligand_id": entry.ligand_id,
                "job_id": entry.gnina_job_id,
                "reason": reason,
            },
        )
