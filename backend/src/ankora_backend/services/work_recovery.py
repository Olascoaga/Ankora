"""Reconcile durable records left active by an exited Ankora backend."""

from collections.abc import Sequence
from datetime import UTC, datetime

from ankora_backend.persistence.autodock4_store import AutoDock4JobStore
from ankora_backend.persistence.autodock_gpu_store import AutoDockGpuJobStore
from ankora_backend.persistence.autogrid_store import AutoGridMapStore
from ankora_backend.persistence.docking_store import DockingArtifactStore
from ankora_backend.persistence.work_lease_store import WorkLeaseStore
from ankora_backend.schemas.autodock4 import (
    AutoDock4BatchLigandResult,
    AutoDock4Failure,
    AutoDock4JobPhase,
    AutoDock4JobStatus,
)
from ankora_backend.schemas.autodock_gpu import AutoDockGpuBatchLigandResult
from ankora_backend.schemas.autogrid import (
    AutoGridFailure,
    AutoGridJobPhase,
    AutoGridJobStatus,
)
from ankora_backend.schemas.docking import (
    DockingFailure,
    DockingJobPhase,
    DockingJobStatus,
    VinaBatchLigandResult,
)
from ankora_backend.schemas.work_recovery import (
    RecoveredWorkItem,
    WorkKind,
    WorkLeaseRecord,
    WorkLeaseState,
    WorkRecoverySummary,
)

_ACTIVE = {"queued", "running", "cancel_requested"}


class InterruptedWorkRecovery:
    def __init__(
        self,
        *,
        docking: DockingArtifactStore,
        autogrid: AutoGridMapStore,
        autodock4: AutoDock4JobStore,
        autodock_gpu: AutoDockGpuJobStore,
        leases: WorkLeaseStore,
    ) -> None:
        self._docking = docking
        self._autogrid = autogrid
        self._autodock4 = autodock4
        self._autodock_gpu = autodock_gpu
        self._leases = leases

    @classmethod
    def from_environment(
        cls, *, leases: WorkLeaseStore | None = None
    ) -> "InterruptedWorkRecovery":
        return cls(
            docking=DockingArtifactStore.from_environment(),
            autogrid=AutoGridMapStore.from_environment(),
            autodock4=AutoDock4JobStore.from_environment(),
            autodock_gpu=AutoDockGpuJobStore.from_environment(),
            leases=leases or WorkLeaseStore.from_environment(),
        )

    def reconcile(self) -> WorkRecoverySummary:
        reconciled_at = datetime.now(UTC)
        lease_index = {
            (lease.work_kind, lease.work_id): lease
            for lease in self._leases.list_active()
        }
        items = [
            *self._reconcile_vina(reconciled_at, lease_index),
            *self._reconcile_autogrid(reconciled_at, lease_index),
            *self._reconcile_autodock4(reconciled_at, lease_index),
            *self._reconcile_autodock_gpu(reconciled_at, lease_index),
        ]
        for item in items:
            lease = lease_index.get((item.work_kind, item.work_id))
            if lease is not None:
                self._leases.write(
                    lease.model_copy(
                        update={
                            "state": WorkLeaseState.RECONCILED,
                            "released_at": reconciled_at,
                        }
                    )
                )
        return WorkRecoverySummary(reconciled_at=reconciled_at, items=items)

    def _reconcile_vina(
        self,
        now: datetime,
        leases: dict[tuple[WorkKind, str], WorkLeaseRecord],
    ) -> list[RecoveredWorkItem]:
        items: list[RecoveredWorkItem] = []
        for record in self._docking.list_jobs():
            if record.status.value not in _ACTIVE:
                continue
            lease = leases.get((WorkKind.VINA_JOB, record.job_id))
            self._docking.update_record(
                record.model_copy(
                    update={
                        "status": DockingJobStatus.FAILED,
                        "phase": DockingJobPhase.COMPLETE,
                        "completed_at": now,
                        "failure": DockingFailure(
                            code="VINA_EXECUTION_INTERRUPTED",
                            message=_INTERRUPTED_MESSAGE,
                            details=_failure_details(record.status.value, lease, now),
                        ),
                    }
                )
            )
            items.append(_item(WorkKind.VINA_JOB, record.job_id, record.status.value, lease))
        for batch_record in self._docking.list_batch_records():
            if batch_record.status.value not in _ACTIVE:
                continue
            lease = leases.get((WorkKind.VINA_BATCH, batch_record.batch_id))
            entries, interrupted = _interrupt_vina_entries(
                batch_record.entries, now, batch_record.revision + 1
            )
            counts = _counts(entries)
            self._docking.update_batch_record(
                batch_record.model_copy(
                    update={
                        "status": DockingJobStatus.FAILED,
                        "phase": DockingJobPhase.COMPLETE,
                        "completed_at": now,
                        "entries": entries,
                        "revision": batch_record.revision + 1,
                        **counts,
                        "failure": DockingFailure(
                            code="VINA_CAMPAIGN_INTERRUPTED",
                            message=_INTERRUPTED_BATCH_MESSAGE,
                            details={
                                **_failure_details(
                                    batch_record.status.value, lease, now
                                ),
                                "interrupted_entry_count": interrupted,
                                "completed_entries_preserved": counts["succeeded_count"],
                            },
                        ),
                    }
                ),
                changed_entries=[
                    entry
                    for entry in entries
                    if entry.revision == batch_record.revision + 1
                ],
            )
            items.append(
                _item(
                    WorkKind.VINA_BATCH,
                    batch_record.batch_id,
                    batch_record.status.value,
                    lease,
                    interrupted,
                    counts["succeeded_count"],
                )
            )
        return items

    def _reconcile_autogrid(
        self,
        now: datetime,
        leases: dict[tuple[WorkKind, str], WorkLeaseRecord],
    ) -> list[RecoveredWorkItem]:
        items: list[RecoveredWorkItem] = []
        for record in self._autogrid.list_jobs():
            if record.status.value not in _ACTIVE:
                continue
            lease = leases.get((WorkKind.AUTOGRID_JOB, record.job_id))
            self._autogrid.update_job(
                record.model_copy(
                    update={
                        "status": AutoGridJobStatus.FAILED,
                        "phase": AutoGridJobPhase.COMPLETE,
                        "completed_at": now,
                        "failure": AutoGridFailure(
                            code="AUTOGRID_EXECUTION_INTERRUPTED",
                            message=_INTERRUPTED_MESSAGE,
                            details=_failure_details(record.status.value, lease, now),
                        ),
                    }
                )
            )
            items.append(
                _item(WorkKind.AUTOGRID_JOB, record.job_id, record.status.value, lease)
            )
        return items

    def _reconcile_autodock4(
        self,
        now: datetime,
        leases: dict[tuple[WorkKind, str], WorkLeaseRecord],
    ) -> list[RecoveredWorkItem]:
        items: list[RecoveredWorkItem] = []
        for record in self._autodock4.list_jobs():
            if record.status.value not in _ACTIVE:
                continue
            lease = leases.get((WorkKind.AUTODOCK4_JOB, record.job_id))
            self._autodock4.update_job(
                record.model_copy(
                    update={
                        "status": AutoDock4JobStatus.FAILED,
                        "phase": AutoDock4JobPhase.COMPLETE,
                        "completed_at": now,
                        "failure": AutoDock4Failure(
                            code="AUTODOCK4_EXECUTION_INTERRUPTED",
                            message=_INTERRUPTED_MESSAGE,
                            details=_failure_details(record.status.value, lease, now),
                        ),
                    }
                )
            )
            items.append(
                _item(WorkKind.AUTODOCK4_JOB, record.job_id, record.status.value, lease)
            )
        for batch_record in self._autodock4.list_batches():
            if batch_record.status.value not in _ACTIVE:
                continue
            lease = leases.get((WorkKind.AUTODOCK4_BATCH, batch_record.batch_id))
            entries, interrupted = _interrupt_autodock4_entries(
                batch_record.entries,
                now,
                batch_record.revision + 1,
                "AUTODOCK4_LIGAND_INTERRUPTED",
            )
            counts = _counts(entries)
            self._autodock4.update_batch(
                batch_record.model_copy(
                    update={
                        "status": AutoDock4JobStatus.FAILED,
                        "phase": AutoDock4JobPhase.COMPLETE,
                        "completed_at": now,
                        "entries": entries,
                        "revision": batch_record.revision + 1,
                        **counts,
                        "failure": AutoDock4Failure(
                            code="AUTODOCK4_CAMPAIGN_INTERRUPTED",
                            message=_INTERRUPTED_BATCH_MESSAGE,
                            details={
                                **_failure_details(
                                    batch_record.status.value, lease, now
                                ),
                                "interrupted_entry_count": interrupted,
                                "completed_entries_preserved": counts["succeeded_count"],
                            },
                        ),
                    }
                ),
                changed_entries=[
                    entry
                    for entry in entries
                    if entry.revision == batch_record.revision + 1
                ],
            )
            items.append(
                _item(
                    WorkKind.AUTODOCK4_BATCH,
                    batch_record.batch_id,
                    batch_record.status.value,
                    lease,
                    interrupted,
                    counts["succeeded_count"],
                )
            )
        return items

    def _reconcile_autodock_gpu(
        self,
        now: datetime,
        leases: dict[tuple[WorkKind, str], WorkLeaseRecord],
    ) -> list[RecoveredWorkItem]:
        items: list[RecoveredWorkItem] = []
        for record in self._autodock_gpu.list_jobs():
            if record.status.value not in _ACTIVE:
                continue
            lease = leases.get((WorkKind.AUTODOCK_GPU_JOB, record.job_id))
            self._autodock_gpu.update_job(
                record.model_copy(
                    update={
                        "status": AutoDock4JobStatus.FAILED,
                        "phase": AutoDock4JobPhase.COMPLETE,
                        "completed_at": now,
                        "failure": AutoDock4Failure(
                            code="AUTODOCK_GPU_EXECUTION_INTERRUPTED",
                            message=_INTERRUPTED_MESSAGE,
                            details=_failure_details(record.status.value, lease, now),
                        ),
                    }
                )
            )
            items.append(
                _item(
                    WorkKind.AUTODOCK_GPU_JOB,
                    record.job_id,
                    record.status.value,
                    lease,
                )
            )
        for batch_record in self._autodock_gpu.list_batches():
            if batch_record.status.value not in _ACTIVE:
                continue
            lease = leases.get((WorkKind.AUTODOCK_GPU_BATCH, batch_record.batch_id))
            entries, interrupted = _interrupt_autodock4_entries(
                batch_record.entries,
                now,
                batch_record.revision + 1,
                "AUTODOCK_GPU_LIGAND_INTERRUPTED",
            )
            counts = _counts(entries)
            self._autodock_gpu.update_batch(
                batch_record.model_copy(
                    update={
                        "status": AutoDock4JobStatus.FAILED,
                        "phase": AutoDock4JobPhase.COMPLETE,
                        "completed_at": now,
                        "entries": entries,
                        "revision": batch_record.revision + 1,
                        **counts,
                        "failure": AutoDock4Failure(
                            code="AUTODOCK_GPU_CAMPAIGN_INTERRUPTED",
                            message=_INTERRUPTED_BATCH_MESSAGE,
                            details={
                                **_failure_details(
                                    batch_record.status.value, lease, now
                                ),
                                "interrupted_entry_count": interrupted,
                                "completed_entries_preserved": counts["succeeded_count"],
                            },
                        ),
                    }
                ),
                changed_entries=[
                    entry
                    for entry in entries
                    if entry.revision == batch_record.revision + 1
                ],
            )
            items.append(
                _item(
                    WorkKind.AUTODOCK_GPU_BATCH,
                    batch_record.batch_id,
                    batch_record.status.value,
                    lease,
                    interrupted,
                    counts["succeeded_count"],
                )
            )
        return items


_INTERRUPTED_MESSAGE = (
    "The owning Ankora backend stopped before this execution reached a terminal state. "
    "Its partial evidence remains preserved; retry must create a new immutable attempt."
)
_INTERRUPTED_BATCH_MESSAGE = (
    "The owning Ankora backend stopped before this campaign reached a terminal state. "
    "Completed molecule results remain preserved; retry must create a new campaign."
)


def _failure_details(
    previous_status: str,
    lease: WorkLeaseRecord | None,
    reconciled_at: datetime,
) -> dict[str, object]:
    details: dict[str, object] = {
        "previous_status": previous_status,
        "reconciled_at": reconciled_at.isoformat(),
    }
    if lease is not None:
        details.update(
            {
                "lease_id": lease.lease_id,
                "previous_owner_instance_id": lease.owner_instance_id,
                "last_heartbeat_at": lease.heartbeat_at.isoformat(),
            }
        )
    return details


def _item(
    work_kind: WorkKind,
    work_id: str,
    previous_status: str,
    lease: WorkLeaseRecord | None,
    interrupted_entry_count: int = 0,
    completed_entry_count: int = 0,
) -> RecoveredWorkItem:
    return RecoveredWorkItem(
        work_kind=work_kind,
        work_id=work_id,
        previous_status=previous_status,
        interrupted_entry_count=interrupted_entry_count,
        completed_entry_count=completed_entry_count,
        last_heartbeat_at=lease.heartbeat_at if lease is not None else None,
        previous_owner_instance_id=(
            lease.owner_instance_id if lease is not None else None
        ),
    )


def _interrupt_vina_entries(
    entries: list[VinaBatchLigandResult], now: datetime, revision: int
) -> tuple[list[VinaBatchLigandResult], int]:
    interrupted = 0
    updated: list[VinaBatchLigandResult] = []
    for entry in entries:
        if entry.status.value not in _ACTIVE:
            updated.append(entry)
            continue
        interrupted += 1
        updated.append(
            entry.model_copy(
                update={
                    "status": DockingJobStatus.FAILED,
                    "phase": DockingJobPhase.COMPLETE,
                    "completed_at": now,
                    "failure": DockingFailure(
                        code="VINA_LIGAND_INTERRUPTED",
                        message=_INTERRUPTED_MESSAGE,
                    ),
                    "revision": revision,
                }
            )
        )
    return updated, interrupted


def _interrupt_autodock4_entries[
    BatchEntry: (AutoDock4BatchLigandResult, AutoDockGpuBatchLigandResult)
](
    entries: list[BatchEntry],
    now: datetime,
    revision: int,
    code: str,
) -> tuple[list[BatchEntry], int]:
    interrupted = 0
    updated: list[BatchEntry] = []
    for entry in entries:
        if entry.status.value not in _ACTIVE:
            updated.append(entry)
            continue
        interrupted += 1
        updated.append(
            entry.model_copy(
                update={
                    "status": AutoDock4JobStatus.FAILED,
                    "phase": AutoDock4JobPhase.COMPLETE,
                    "completed_at": now,
                    "failure": AutoDock4Failure(
                        code=code,
                        message=_INTERRUPTED_MESSAGE,
                    ),
                    "revision": revision,
                }
            )
        )
    return updated, interrupted


def _counts(
    entries: Sequence[
        VinaBatchLigandResult
        | AutoDock4BatchLigandResult
        | AutoDockGpuBatchLigandResult
    ],
) -> dict[str, int]:
    statuses = [entry.status.value for entry in entries]
    succeeded = statuses.count("completed")
    failed = statuses.count("failed")
    canceled = statuses.count("canceled")
    return {
        "completed_count": succeeded + failed + canceled,
        "succeeded_count": succeeded,
        "failed_count": failed,
        "canceled_count": canceled,
    }
