"""Serial execution of one already-created GNINA screening campaign.

Internal building block: callers must own project runtime lifecycle and run
this blocking worker off the request thread. It does not expose an API.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from time import monotonic

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.gnina_screening_store import GninaScreeningStore
from ankora_backend.schemas.docking import DockingFailure, DockingJobPhase, DockingJobStatus
from ankora_backend.schemas.gnina import GninaDockingRequest
from ankora_backend.schemas.gnina_screening import GninaScreeningProgress
from ankora_backend.schemas.work_recovery import WorkKind
from ankora_backend.services.gnina_docking import GninaDockingService
from ankora_backend.services.work_leases import WorkLeaseManager

_TERMINAL = frozenset(
    {DockingJobStatus.COMPLETED, DockingJobStatus.FAILED, DockingJobStatus.CANCELED}
)
_RUNNING_LOCK = threading.Lock()
_RUNNING_CAMPAIGNS: set[str] = set()


class GninaScreeningRunner:
    """Run at most one selected molecule at a time using the single-job service."""

    def __init__(
        self,
        *,
        store: GninaScreeningStore,
        docking: GninaDockingService,
        leases: WorkLeaseManager,
        poll_seconds: float = 0.25,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self._store = store
        self._docking = docking
        self._leases = leases
        self._poll_seconds = poll_seconds
        self._lock = threading.RLock()
        self._active: dict[str, str | None] = {}

    def has_active_work(self) -> bool:
        with self._lock:
            return bool(self._active)

    def cancel(self, campaign_id: str) -> GninaScreeningProgress:
        """Record intent and signal the active child under the launch lock."""
        with self._lock:
            if campaign_id not in self._active:
                raise self._error("GNINA_SCREENING_NOT_ACTIVE", "This campaign is not active.")
            progress = self._store.request_cancel(campaign_id)
            job_id = self._active[campaign_id]
            if job_id is not None:
                self._docking.cancel(job_id)
            return progress

    def cancel_scheduled(self, campaign_id: str) -> GninaScreeningProgress:
        """Cancel an owned campaign, including one still awaiting its worker."""
        with self._lock:
            if campaign_id in self._active:
                return self.cancel(campaign_id)
            progress = self._store.load_progress(campaign_id)
            if progress.status in _TERMINAL:
                return progress
            if progress.status not in {DockingJobStatus.QUEUED, DockingJobStatus.CANCEL_REQUESTED}:
                raise self._error(
                    "GNINA_SCREENING_NOT_ACTIVE", "This campaign is not owned by this runner."
                )
            return self._store.request_cancel(campaign_id)

    def run(self, campaign_id: str) -> GninaScreeningProgress:
        """Run a fresh campaign once; existing attempts are never retried."""
        with self._lock:
            if campaign_id in self._active:
                raise self._error(
                    "GNINA_SCREENING_ALREADY_ACTIVE", "This campaign is already active."
                )
            campaign = self._store.load_campaign(campaign_id)
            if campaign.status not in {
                DockingJobStatus.QUEUED,
                DockingJobStatus.CANCEL_REQUESTED,
            } or any(
                not entry.is_terminal
                and (entry.status is not DockingJobStatus.QUEUED or entry.gnina_job_id)
                for entry in campaign.entries
            ):
                raise self._error(
                    "GNINA_SCREENING_NOT_FRESH", "Only a fresh campaign can be started."
                )
            if any(
                job.screening_campaign_id == campaign_id for job in self._store.jobs.list_jobs()
            ):
                raise self._error(
                    "GNINA_SCREENING_NOT_FRESH", "A previous campaign attempt already exists."
                )
            key = str(self._store.campaign_directory(campaign_id))
            with _RUNNING_LOCK:
                if key in _RUNNING_CAMPAIGNS:
                    raise self._error(
                        "GNINA_SCREENING_ALREADY_ACTIVE", "This campaign is already active."
                    )
                _RUNNING_CAMPAIGNS.add(key)
            self._active[campaign_id] = None
        acquired = False
        try:
            self._leases.acquire(WorkKind.GNINA_SCREENING, campaign_id)
            acquired = True
            for original in campaign.entries:
                if original.is_terminal:
                    continue
                with self._lock:
                    entry = self._store.load_entry(campaign_id, original.ligand_id)
                    if entry is None:
                        raise self._error(
                            "GNINA_SCREENING_ENTRY_MISSING", "A selected molecule is missing."
                        )
                    if (
                        self._store.load_progress(campaign_id).status
                        is DockingJobStatus.CANCEL_REQUESTED
                    ):
                        self._store.update_entry(
                            campaign_id,
                            entry.model_copy(
                                update={
                                    "status": DockingJobStatus.CANCELED,
                                    "phase": DockingJobPhase.COMPLETE,
                                    "completed_at": datetime.now(UTC),
                                }
                            ),
                        )
                        continue
                    if entry.ligand_preparation_id is None:
                        raise self._error(
                            "GNINA_SCREENING_PREPARATION_MISSING",
                            "The prepared molecule is missing.",
                        )
                    request = GninaDockingRequest(
                        receptor_id=campaign.request.receptor_id,
                        binding_site_id=campaign.request.binding_site_id,
                        ligand_id=entry.ligand_id,
                        ligand_preparation_id=entry.ligand_preparation_id,
                        parameters=campaign.request.parameters,
                        acknowledge_inputs_and_scoring=True,
                    )
                    try:
                        job = self._docking.start(request, screening_campaign_id=campaign_id)
                    except AnkoraDomainError as error:
                        # An admission failure before a job exists is local to
                        # this molecule. If a job was written, let the outer
                        # recovery path stop and reconcile it rather than guess.
                        if any(
                            candidate.screening_campaign_id == campaign_id
                            and candidate.request.ligand_id == entry.ligand_id
                            for candidate in self._store.jobs.list_jobs()
                        ):
                            raise
                        self._store.update_entry(
                            campaign_id,
                            entry.model_copy(
                                update={
                                    "status": DockingJobStatus.FAILED,
                                    "phase": DockingJobPhase.COMPLETE,
                                    "completed_at": datetime.now(UTC),
                                    "failure": DockingFailure(
                                        code=error.code,
                                        message=error.message,
                                        details=error.details,
                                    ),
                                }
                            ),
                        )
                        continue
                    self._active[campaign_id] = job.job_id
                    entry = self._store.update_entry(
                        campaign_id,
                        entry.model_copy(
                            update={
                                "status": DockingJobStatus.RUNNING,
                                "phase": DockingJobPhase.DOCKING,
                                "gnina_job_id": job.job_id,
                                "started_at": datetime.now(UTC),
                            }
                        ),
                    )
                while True:
                    job = self._docking.get(job.job_id)
                    if job.status in _TERMINAL:
                        break
                    threading.Event().wait(self._poll_seconds)
                if job.completed_at is None:
                    raise self._error(
                        "GNINA_SCREENING_JOB_INCOMPLETE",
                        "The terminal GNINA job has no recorded completion time.",
                    )
                self._store.update_entry(
                    campaign_id,
                    entry.model_copy(
                        update={
                            "status": job.status,
                            "phase": DockingJobPhase.COMPLETE,
                            "completed_at": job.completed_at,
                            "failure": job.failure,
                        }
                    ),
                )
                with self._lock:
                    self._active[campaign_id] = None
            return self._store.finalize_campaign(campaign_id)
        except Exception:
            # A failure after start can leave a correlated job whose ID was not
            # yet attached to its entry. Stop every still-active child first;
            # reconciliation is safe only after each has actually terminated.
            if acquired:
                self._stop_and_reconcile(campaign_id)
            else:
                # Admission checked there was no prior attempt and this worker
                # has not launched one before acquiring its campaign lease.
                self._store.recover_interrupted_campaign(
                    campaign_id, interrupted_at=datetime.now(UTC)
                )
            raise
        finally:
            # Unexpected errors are not silently converted into successful work.
            # Runtime startup reconciliation is responsible for abandoned state.
            try:
                if acquired:
                    self._leases.release(WorkKind.GNINA_SCREENING, campaign_id)
            finally:
                with self._lock:
                    self._active.pop(campaign_id, None)
                with _RUNNING_LOCK:
                    _RUNNING_CAMPAIGNS.discard(key)

    def _stop_and_reconcile(self, campaign_id: str) -> None:
        jobs = [
            job
            for job in self._store.jobs.list_jobs()
            if job.screening_campaign_id == campaign_id and job.status not in _TERMINAL
        ]
        # list_jobs deliberately skips unreadable records. Never conclude that
        # a known child has stopped just because it was omitted from the list.
        with self._lock:
            active_id = self._active.get(campaign_id)
        if active_id is not None and not any(job.job_id == active_id for job in jobs):
            active_job = self._store.jobs.load_job(active_id)
            if active_job.screening_campaign_id != campaign_id:
                raise self._error(
                    "GNINA_SCREENING_CHILD_MISMATCH",
                    "The active job no longer matches its campaign.",
                )
            if active_job.status not in _TERMINAL:
                jobs.append(active_job)
        for job in jobs:
            self._docking.cancel(job.job_id)
        deadline = monotonic() + 30
        for job in jobs:
            while self._docking.get(job.job_id).status not in _TERMINAL:
                if monotonic() >= deadline:
                    raise self._error(
                        "GNINA_SCREENING_CHILD_STILL_ACTIVE", "A screening job did not stop."
                    )
                threading.Event().wait(self._poll_seconds)
        self._store.recover_interrupted_campaign(campaign_id, interrupted_at=datetime.now(UTC))

    @staticmethod
    def _error(code: str, message: str) -> AnkoraDomainError:
        return AnkoraDomainError(
            code=code, stage="gnina_screening", message=message, status_code=409
        )
