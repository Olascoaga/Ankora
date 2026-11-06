"""Project-bound asynchronous GNINA screening lifecycle."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.gnina_screening_store import GninaScreeningStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.docking import DockingJobStatus
from ankora_backend.schemas.gnina_screening import (
    GninaScreeningCampaignRecord,
    GninaScreeningEntry,
    GninaScreeningProgress,
    GninaScreeningRequest,
)
from ankora_backend.services.gnina_docking import GninaDockingService
from ankora_backend.services.gnina_screening_admission import admit_screening
from ankora_backend.services.gnina_screening_runner import GninaScreeningRunner
from ankora_backend.services.resource_arbiter import ResourceArbiter
from ankora_backend.services.work_leases import WorkLeaseManager

_LOG = logging.getLogger(__name__)
_TERMINAL = {DockingJobStatus.COMPLETED, DockingJobStatus.FAILED, DockingJobStatus.CANCELED}


class GninaScreeningService:
    def __init__(
        self,
        *,
        store: GninaScreeningStore,
        runner: GninaScreeningRunner,
        receptors: ReceptorArtifactStore,
        sites: BindingSiteArtifactStore,
        ligands: LigandArtifactStore,
        resources: ResourceArbiter,
        enable_experimental_cuda: bool,
    ) -> None:
        self._store = store
        self._runner = runner
        self._receptors = receptors
        self._sites = sites
        self._ligands = ligands
        self._resources = resources
        self._enable_experimental_cuda = enable_experimental_cuda
        self._lock = threading.RLock()
        self._scheduled: set[str] = set()
        self._closed = False
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="ankora-gnina-screening"
        )

    @classmethod
    def from_environment(
        cls,
        *,
        docking: GninaDockingService,
        leases: WorkLeaseManager,
        resources: ResourceArbiter,
        enable_experimental_cuda: bool,
    ) -> GninaScreeningService:
        store = GninaScreeningStore.from_environment()
        return cls(
            store=store,
            runner=GninaScreeningRunner(store=store, docking=docking, leases=leases),
            receptors=ReceptorArtifactStore.from_environment(),
            sites=BindingSiteArtifactStore.from_environment(),
            ligands=LigandArtifactStore.from_environment(),
            resources=resources,
            enable_experimental_cuda=enable_experimental_cuda,
        )

    def start(self, request: GninaScreeningRequest) -> GninaScreeningCampaignRecord:
        with self._lock:
            if self._closed:
                raise _error("GNINA_SCREENING_SERVICE_CLOSED", "The screening service is closed.")
            record = admit_screening(
                request=request,
                store=self._store,
                receptors=self._receptors,
                sites=self._sites,
                ligands=self._ligands,
                resources=self._resources,
                enable_experimental_cuda=self._enable_experimental_cuda,
            )
            self._scheduled.add(record.campaign_id)
            try:
                self._executor.submit(self._run, record.campaign_id)
            except Exception:
                self._scheduled.discard(record.campaign_id)
                from datetime import UTC, datetime

                self._store.recover_interrupted_campaign(
                    record.campaign_id, interrupted_at=datetime.now(UTC)
                )
                raise
            return record

    def _run(self, campaign_id: str) -> None:
        try:
            self._runner.run(campaign_id)
        except Exception:
            _LOG.exception("GNINA screening worker failed for campaign %s", campaign_id)
        finally:
            with self._lock:
                self._scheduled.discard(campaign_id)

    def list_progress(self) -> list[GninaScreeningProgress]:
        return [self._store.load_progress(item) for item in self._store.list_campaign_ids()]

    def get(self, campaign_id: str) -> GninaScreeningCampaignRecord:
        return self._store.load_campaign(campaign_id)

    def progress(self, campaign_id: str) -> GninaScreeningProgress:
        return self._store.load_progress(campaign_id)

    def entries(self, campaign_id: str, after_revision: int) -> list[GninaScreeningEntry]:
        return self._store.entries_after_revision(campaign_id, after_revision)

    def cancel(self, campaign_id: str) -> GninaScreeningProgress:
        with self._lock:
            if campaign_id not in self._scheduled:
                progress = self._store.load_progress(campaign_id)
                if progress.status in _TERMINAL:
                    return progress
                raise _error("GNINA_SCREENING_NOT_ACTIVE", "This campaign is not active.")
            return self._runner.cancel_scheduled(campaign_id)

    def has_active_work(self) -> bool:
        with self._lock:
            return bool(self._scheduled)

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            for campaign_id in list(self._scheduled):
                try:
                    self._runner.cancel_scheduled(campaign_id)
                except Exception:
                    _LOG.exception(
                        "Could not cancel GNINA screening %s during shutdown", campaign_id
                    )
        self._executor.shutdown(wait=True)


def _error(code: str, message: str) -> AnkoraDomainError:
    return AnkoraDomainError(code=code, stage="gnina_screening", message=message, status_code=409)
