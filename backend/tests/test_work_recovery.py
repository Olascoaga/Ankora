"""Startup recovery preserves terminal evidence and closes abandoned work."""

from datetime import UTC, datetime
from uuid import uuid4

from ankora_backend.persistence.work_lease_store import WorkLeaseStore
from ankora_backend.schemas.autodock4 import (
    AutoDock4BatchLigandResult,
    AutoDock4BatchRecord,
    AutoDock4DockingJobRecord,
    AutoDock4JobPhase,
    AutoDock4JobStatus,
)
from ankora_backend.schemas.autodock_gpu import (
    AutoDockGpuBatchLigandResult,
    AutoDockGpuBatchRecord,
    AutoDockGpuDockingJobRecord,
)
from ankora_backend.schemas.autogrid import (
    AutoGridJobPhase,
    AutoGridJobStatus,
    AutoGridMapJobRecord,
)
from ankora_backend.schemas.docking import (
    DockingJobPhase,
    DockingJobStatus,
    VinaBatchDockingRecord,
    VinaBatchLigandResult,
    VinaDockingJobRecord,
)
from ankora_backend.schemas.work_recovery import WorkKind, WorkLeaseRecord
from ankora_backend.services.work_recovery import InterruptedWorkRecovery


class _DockingStore:
    def __init__(self, job, batch) -> None:
        self.jobs = [job]
        self.batches = [batch]

    def list_jobs(self):
        return self.jobs

    def list_batch_records(self):
        return self.batches

    def update_record(self, record) -> None:
        self.jobs = [record]

    def update_batch_record(self, record) -> None:
        self.batches = [record]


class _AutoGridStore:
    def __init__(self, job) -> None:
        self.jobs = [job]

    def list_jobs(self):
        return self.jobs

    def update_job(self, record) -> None:
        self.jobs = [record]


class _AutoDockStore:
    def __init__(self, job, batch) -> None:
        self.jobs = [job]
        self.batches = [batch]

    def list_jobs(self):
        return self.jobs

    def list_batches(self):
        return self.batches

    def update_job(self, record) -> None:
        self.jobs = [record]

    def update_batch(self, record) -> None:
        self.batches = [record]


def _id() -> str:
    return str(uuid4())


def _lease(kind: WorkKind, work_id: str) -> WorkLeaseRecord:
    now = datetime.now(UTC)
    return WorkLeaseRecord(
        lease_id=_id(),
        work_kind=kind,
        work_id=work_id,
        owner_instance_id=_id(),
        acquired_at=now,
        heartbeat_at=now,
    )


def test_startup_recovery_preserves_completed_entries_and_interrupts_active_work(
    tmp_path,
) -> None:
    vina_job = VinaDockingJobRecord.model_construct(
        job_id=_id(),
        status=DockingJobStatus.RUNNING,
        phase=DockingJobPhase.DOCKING,
    )
    completed_vina_entry = VinaBatchLigandResult.model_construct(
        ligand_id=_id(),
        source_index=0,
        name="synthetic completed ligand",
        status=DockingJobStatus.COMPLETED,
        phase=DockingJobPhase.COMPLETE,
        revision=2,
    )
    running_vina_entry = VinaBatchLigandResult.model_construct(
        ligand_id=_id(),
        source_index=1,
        name="synthetic interrupted ligand",
        status=DockingJobStatus.RUNNING,
        phase=DockingJobPhase.DOCKING,
        revision=2,
    )
    vina_batch = VinaBatchDockingRecord.model_construct(
        batch_id=_id(),
        status=DockingJobStatus.RUNNING,
        phase=DockingJobPhase.DOCKING,
        entries=[completed_vina_entry, running_vina_entry],
        revision=2,
    )
    autogrid_job = AutoGridMapJobRecord.model_construct(
        job_id=_id(),
        status=AutoGridJobStatus.CANCEL_REQUESTED,
        phase=AutoGridJobPhase.GENERATING_MAPS,
    )
    ad4_job = AutoDock4DockingJobRecord.model_construct(
        job_id=_id(),
        status=AutoDock4JobStatus.QUEUED,
        phase=AutoDock4JobPhase.QUEUED,
    )
    ad4_batch = AutoDock4BatchRecord.model_construct(
        batch_id=_id(),
        status=AutoDock4JobStatus.RUNNING,
        phase=AutoDock4JobPhase.DOCKING,
        entries=[
            AutoDock4BatchLigandResult.model_construct(
                ligand_id=_id(),
                source_index=0,
                name="synthetic CPU ligand",
                status=AutoDock4JobStatus.RUNNING,
                phase=AutoDock4JobPhase.DOCKING,
                revision=1,
            )
        ],
        revision=1,
    )
    gpu_job = AutoDockGpuDockingJobRecord.model_construct(
        job_id=_id(),
        status=AutoDock4JobStatus.RUNNING,
        phase=AutoDock4JobPhase.DOCKING,
    )
    gpu_batch = AutoDockGpuBatchRecord.model_construct(
        batch_id=_id(),
        status=AutoDock4JobStatus.RUNNING,
        phase=AutoDock4JobPhase.DOCKING,
        entries=[
            AutoDockGpuBatchLigandResult.model_construct(
                ligand_id=_id(),
                source_index=0,
                name="synthetic GPU ligand",
                status=AutoDock4JobStatus.RUNNING,
                phase=AutoDock4JobPhase.DOCKING,
                revision=1,
            )
        ],
        revision=1,
    )

    docking = _DockingStore(vina_job, vina_batch)
    autogrid = _AutoGridStore(autogrid_job)
    autodock4 = _AutoDockStore(ad4_job, ad4_batch)
    autodock_gpu = _AutoDockStore(gpu_job, gpu_batch)
    leases = WorkLeaseStore(tmp_path)
    for kind, work_id in (
        (WorkKind.VINA_JOB, vina_job.job_id),
        (WorkKind.VINA_BATCH, vina_batch.batch_id),
        (WorkKind.AUTOGRID_JOB, autogrid_job.job_id),
        (WorkKind.AUTODOCK4_JOB, ad4_job.job_id),
        (WorkKind.AUTODOCK4_BATCH, ad4_batch.batch_id),
        (WorkKind.AUTODOCK_GPU_JOB, gpu_job.job_id),
        (WorkKind.AUTODOCK_GPU_BATCH, gpu_batch.batch_id),
    ):
        leases.write(_lease(kind, work_id))

    summary = InterruptedWorkRecovery(
        docking=docking,
        autogrid=autogrid,
        autodock4=autodock4,
        autodock_gpu=autodock_gpu,
        leases=leases,
    ).reconcile()

    assert len(summary.items) == 7
    assert docking.jobs[0].status is DockingJobStatus.FAILED
    assert docking.jobs[0].failure.code == "VINA_EXECUTION_INTERRUPTED"
    recovered_vina_batch = docking.batches[0]
    assert recovered_vina_batch.status is DockingJobStatus.FAILED
    assert recovered_vina_batch.succeeded_count == 1
    assert recovered_vina_batch.failed_count == 1
    assert recovered_vina_batch.entries[0] == completed_vina_entry
    assert recovered_vina_batch.entries[1].failure.code == "VINA_LIGAND_INTERRUPTED"
    assert autogrid.jobs[0].failure.code == "AUTOGRID_EXECUTION_INTERRUPTED"
    assert autodock4.jobs[0].failure.code == "AUTODOCK4_EXECUTION_INTERRUPTED"
    assert autodock4.batches[0].entries[0].failure.code == (
        "AUTODOCK4_LIGAND_INTERRUPTED"
    )
    assert autodock_gpu.jobs[0].failure.code == "AUTODOCK_GPU_EXECUTION_INTERRUPTED"
    assert autodock_gpu.batches[0].entries[0].failure.code == (
        "AUTODOCK_GPU_LIGAND_INTERRUPTED"
    )
    assert leases.list_active() == []
