"""Safely rebind application-scoped scientific services to one project."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.project_context import project_scope
from ankora_backend.persistence.project_store import ProjectStore
from ankora_backend.persistence.work_lease_store import WorkLeaseStore
from ankora_backend.schemas.projects import ProjectRecord
from ankora_backend.schemas.work_recovery import WorkRecoverySummary
from ankora_backend.services.autodock4_docking import AutoDock4DockingService
from ankora_backend.services.autodock_gpu_docking import AutoDockGpuDockingService
from ankora_backend.services.autogrid_maps import AutoGridMapService
from ankora_backend.services.resource_arbiter import ResourceArbiter
from ankora_backend.services.vina_docking import VinaDockingService
from ankora_backend.services.work_leases import WorkLeaseManager
from ankora_backend.services.work_recovery import InterruptedWorkRecovery
from ankora_backend.services.work_retry import WorkRetryService


@dataclass(slots=True)
class ProjectServiceBundle:
    project_id: str
    recovery: WorkRecoverySummary
    work_leases: WorkLeaseManager
    vina: VinaDockingService
    autogrid: AutoGridMapService
    autodock4: AutoDock4DockingService
    autodock_gpu: AutoDockGpuDockingService
    work_retry: WorkRetryService

    def has_active_work(self) -> bool:
        return any(
            service.has_active_work()
            for service in (self.vina, self.autogrid, self.autodock4, self.autodock_gpu)
        )

    def shutdown(self) -> None:
        self.vina.shutdown()
        self.autogrid.shutdown()
        self.autodock4.shutdown()
        self.autodock_gpu.shutdown()
        self.work_leases.shutdown()


class ProjectRuntime:
    """Own the active project and its long-lived execution services."""

    def __init__(self, *, projects: ProjectStore, resources: ResourceArbiter) -> None:
        self.projects = projects
        self.resources = resources
        self._lock = threading.RLock()
        self._bundle = self._build(projects.active_project_id())

    @property
    def active_project_id(self) -> str:
        with self._lock:
            return self._bundle.project_id

    def publish(self, state: Any) -> None:
        """Publish compatibility aliases consumed by existing route helpers."""
        with self._lock:
            bundle = self._bundle
            state.work_recovery = bundle.recovery
            state.work_leases = bundle.work_leases
            state.vina_docking = bundle.vina
            state.autogrid_maps = bundle.autogrid
            state.autodock4_docking = bundle.autodock4
            state.autodock_gpu_docking = bundle.autodock_gpu
            state.work_retry = bundle.work_retry

    def activate(self, project_id: str, state: Any) -> ProjectRecord:
        with self._lock:
            if project_id == self._bundle.project_id:
                return self.projects.activate(project_id)
            # Validate catalog membership before constructing any project-bound
            # service. Constructors may create runtime directories, so doing
            # this after `_build` would turn a failed lookup into a new project.
            self.projects.get(project_id)
            snapshot = self.resources.snapshot()
            if (
                self._bundle.has_active_work()
                or snapshot.queued_requests
                or snapshot.active_allocations
            ):
                raise AnkoraDomainError(
                    code="PROJECT_SWITCH_BLOCKED_BY_ACTIVE_WORK",
                    stage="project_workspace",
                    message=("Finish or cancel active scientific work before switching projects."),
                    status_code=409,
                    details={
                        "active_project_id": self._bundle.project_id,
                        "requested_project_id": project_id,
                        "queued_requests": snapshot.queued_requests,
                        "active_allocations": len(snapshot.active_allocations),
                    },
                )
            replacement = self._build(project_id)
            try:
                project = self.projects.activate(project_id)
            except Exception:
                replacement.shutdown()
                raise
            previous = self._bundle
            self._bundle = replacement
            self.publish(state)
            previous.shutdown()
            return project

    def shutdown(self) -> None:
        with self._lock:
            self._bundle.shutdown()

    def _build(self, project_id: str) -> ProjectServiceBundle:
        with project_scope(project_id):
            lease_store = WorkLeaseStore.from_environment()
            recovery = InterruptedWorkRecovery.from_environment(leases=lease_store).reconcile()
            lease_manager = WorkLeaseManager(lease_store)
            vina = VinaDockingService.from_environment(
                lease_manager=lease_manager,
                resource_arbiter=self.resources,
            )
            autogrid = AutoGridMapService.from_environment(
                lease_manager=lease_manager,
                resource_arbiter=self.resources,
            )
            autodock4 = AutoDock4DockingService.from_environment(
                lease_manager=lease_manager,
                resource_arbiter=self.resources,
            )
            autodock_gpu = AutoDockGpuDockingService.from_environment(
                lease_manager=lease_manager,
                resource_arbiter=self.resources,
            )
            retry = WorkRetryService.from_environment(
                vina=vina,
                autogrid=autogrid,
                autodock4=autodock4,
                autodock_gpu=autodock_gpu,
            )
        return ProjectServiceBundle(
            project_id=project_id,
            recovery=recovery,
            work_leases=lease_manager,
            vina=vina,
            autogrid=autogrid,
            autodock4=autodock4,
            autodock_gpu=autodock_gpu,
            work_retry=retry,
        )
