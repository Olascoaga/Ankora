"""Explicit retry-as-new dispatch for startup-reconciled work."""

from datetime import datetime
from typing import Protocol, assert_never

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.autodock4_store import AutoDock4JobStore
from ankora_backend.persistence.autodock_gpu_store import AutoDockGpuJobStore
from ankora_backend.persistence.autogrid_store import AutoGridMapStore
from ankora_backend.persistence.docking_store import DockingArtifactStore
from ankora_backend.schemas.work_recovery import (
    WorkKind,
    WorkRetryRequest,
    WorkRetryResponse,
)
from ankora_backend.services.autodock4_docking import AutoDock4DockingService
from ankora_backend.services.autodock_gpu_docking import AutoDockGpuDockingService
from ankora_backend.services.autogrid_maps import AutoGridMapService
from ankora_backend.services.vina_docking import VinaDockingService

_INTERRUPTED_CODES = {
    WorkKind.VINA_JOB: "VINA_EXECUTION_INTERRUPTED",
    WorkKind.VINA_BATCH: "VINA_CAMPAIGN_INTERRUPTED",
    WorkKind.AUTOGRID_JOB: "AUTOGRID_EXECUTION_INTERRUPTED",
    WorkKind.AUTODOCK4_JOB: "AUTODOCK4_EXECUTION_INTERRUPTED",
    WorkKind.AUTODOCK4_BATCH: "AUTODOCK4_CAMPAIGN_INTERRUPTED",
    WorkKind.AUTODOCK_GPU_JOB: "AUTODOCK_GPU_EXECUTION_INTERRUPTED",
    WorkKind.AUTODOCK_GPU_BATCH: "AUTODOCK_GPU_CAMPAIGN_INTERRUPTED",
}


class _Failure(Protocol):
    code: str


class WorkRetryService:
    """Revalidate a recorded request and launch it under a new identity.

    The interrupted record is only read. Each execution service owns creation
    of the new UUID, directory, lease, raw evidence, and scientific provenance.
    """

    def __init__(
        self,
        *,
        docking_store: DockingArtifactStore,
        autogrid_store: AutoGridMapStore,
        autodock4_store: AutoDock4JobStore,
        autodock_gpu_store: AutoDockGpuJobStore,
        vina: VinaDockingService,
        autogrid: AutoGridMapService,
        autodock4: AutoDock4DockingService,
        autodock_gpu: AutoDockGpuDockingService,
    ) -> None:
        self._docking_store = docking_store
        self._autogrid_store = autogrid_store
        self._autodock4_store = autodock4_store
        self._autodock_gpu_store = autodock_gpu_store
        self._vina = vina
        self._autogrid = autogrid
        self._autodock4 = autodock4
        self._autodock_gpu = autodock_gpu

    @classmethod
    def from_environment(
        cls,
        *,
        vina: VinaDockingService,
        autogrid: AutoGridMapService,
        autodock4: AutoDock4DockingService,
        autodock_gpu: AutoDockGpuDockingService,
    ) -> "WorkRetryService":
        return cls(
            docking_store=DockingArtifactStore.from_environment(),
            autogrid_store=AutoGridMapStore.from_environment(),
            autodock4_store=AutoDock4JobStore.from_environment(),
            autodock_gpu_store=AutoDockGpuJobStore.from_environment(),
            vina=vina,
            autogrid=autogrid,
            autodock4=autodock4,
            autodock_gpu=autodock_gpu,
        )

    def retry(
        self,
        work_kind: WorkKind,
        work_id: str,
        request: WorkRetryRequest,
    ) -> WorkRetryResponse:
        if not request.acknowledge_new_immutable_attempt:
            raise AnkoraDomainError(
                code="WORK_RETRY_CONFIRMATION_REQUIRED",
                stage="work_recovery",
                message=(
                    "Confirm that retry creates a new immutable attempt and "
                    "does not resume or modify the interrupted one."
                ),
                status_code=409,
                details={"work_kind": work_kind.value, "work_id": work_id},
            )

        if work_kind is WorkKind.VINA_JOB:
            vina_job = self._docking_store.load_record(work_id)
            self._require_interrupted(work_kind, work_id, vina_job.failure)
            created_vina_job = self._vina.start(vina_job.request)
            return self._response(
                work_kind,
                work_id,
                created_vina_job.job_id,
                created_vina_job.status.value,
                created_vina_job.created_at,
            )
        if work_kind is WorkKind.VINA_BATCH:
            vina_batch = self._docking_store.load_batch_record(work_id)
            self._require_interrupted(work_kind, work_id, vina_batch.failure)
            created_vina_batch = self._vina.start_batch(vina_batch.request)
            return self._response(
                work_kind,
                work_id,
                created_vina_batch.batch_id,
                created_vina_batch.status.value,
                created_vina_batch.created_at,
            )
        if work_kind is WorkKind.AUTOGRID_JOB:
            autogrid_job = self._autogrid_store.load_job(work_id)
            self._require_interrupted(work_kind, work_id, autogrid_job.failure)
            created_autogrid_job = self._autogrid.start_map_set(autogrid_job.request)
            return self._response(
                work_kind,
                work_id,
                created_autogrid_job.job_id,
                created_autogrid_job.status.value,
                created_autogrid_job.created_at,
            )
        if work_kind is WorkKind.AUTODOCK4_JOB:
            autodock4_job = self._autodock4_store.load_job(work_id)
            self._require_interrupted(work_kind, work_id, autodock4_job.failure)
            created_autodock4_job = self._autodock4.start(autodock4_job.request)
            return self._response(
                work_kind,
                work_id,
                created_autodock4_job.job_id,
                created_autodock4_job.status.value,
                created_autodock4_job.created_at,
            )
        if work_kind is WorkKind.AUTODOCK4_BATCH:
            autodock4_batch = self._autodock4_store.load_batch(work_id)
            self._require_interrupted(work_kind, work_id, autodock4_batch.failure)
            created_autodock4_batch = self._autodock4.start_batch(autodock4_batch.request)
            return self._response(
                work_kind,
                work_id,
                created_autodock4_batch.batch_id,
                created_autodock4_batch.status.value,
                created_autodock4_batch.created_at,
            )
        if work_kind is WorkKind.AUTODOCK_GPU_JOB:
            autodock_gpu_job = self._autodock_gpu_store.load_job(work_id)
            self._require_interrupted(work_kind, work_id, autodock_gpu_job.failure)
            created_autodock_gpu_job = self._autodock_gpu.start(autodock_gpu_job.request)
            return self._response(
                work_kind,
                work_id,
                created_autodock_gpu_job.job_id,
                created_autodock_gpu_job.status.value,
                created_autodock_gpu_job.created_at,
            )

        if work_kind is WorkKind.AUTODOCK_GPU_BATCH:
            autodock_gpu_batch = self._autodock_gpu_store.load_batch(work_id)
            self._require_interrupted(work_kind, work_id, autodock_gpu_batch.failure)
            created_autodock_gpu_batch = self._autodock_gpu.start_batch(
                autodock_gpu_batch.request
            )
            return self._response(
                work_kind,
                work_id,
                created_autodock_gpu_batch.batch_id,
                created_autodock_gpu_batch.status.value,
                created_autodock_gpu_batch.created_at,
            )
        assert_never(work_kind)

    @staticmethod
    def _require_interrupted(
        work_kind: WorkKind,
        work_id: str,
        failure: _Failure | None,
    ) -> None:
        expected = _INTERRUPTED_CODES[work_kind]
        if failure is not None and failure.code == expected:
            return
        raise AnkoraDomainError(
            code="WORK_NOT_INTERRUPTED",
            stage="work_recovery",
            message="Only work reconciled as interrupted at startup can be retried here.",
            status_code=409,
            details={
                "work_kind": work_kind.value,
                "work_id": work_id,
                "expected_failure_code": expected,
                "recorded_failure_code": failure.code if failure is not None else None,
            },
        )

    @staticmethod
    def _response(
        work_kind: WorkKind,
        interrupted_work_id: str,
        new_work_id: str,
        status: str,
        created_at: datetime,
    ) -> WorkRetryResponse:
        if new_work_id == interrupted_work_id:
            raise RuntimeError("A retry service reused the interrupted work identity")
        return WorkRetryResponse(
            work_kind=work_kind,
            interrupted_work_id=interrupted_work_id,
            new_work_id=new_work_id,
            status=status,
            created_at=created_at,
        )
