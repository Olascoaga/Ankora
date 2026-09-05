"""FastAPI application factory for the local Ankora API."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ankora_backend import __version__
from ankora_backend.api.routes import router
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.work_lease_store import WorkLeaseStore
from ankora_backend.schemas.errors import ErrorResponse
from ankora_backend.services.autodock4_docking import AutoDock4DockingService
from ankora_backend.services.autodock_gpu_docking import AutoDockGpuDockingService
from ankora_backend.services.autogrid_maps import AutoGridMapService
from ankora_backend.services.vina_docking import VinaDockingService
from ankora_backend.services.work_leases import WorkLeaseManager
from ankora_backend.services.work_recovery import InterruptedWorkRecovery

_ALLOWED_ORIGINS = [
    "http://127.0.0.1:1420",
    "http://localhost:1420",
    "http://tauri.localhost",
    "tauri://localhost",
]

# multipart/form-data is a CORS-safelisted content type, so the browser sends
# these three upload requests as "simple requests" with no preflight — CORS
# headers only stop a malicious page's script from reading the *response*,
# not from triggering the upload's side effects (disk writes, RDKit parsing)
# in the first place. Any page open in a browser on this machine could POST
# to 127.0.0.1:8765 directly. Requiring a known Origin closes that gap
# without touching the JSON endpoints, which already require preflight.
_ORIGIN_GUARDED_PATHS = {
    "/api/v1/structures/import",
    "/api/v1/ligands/import",
    "/api/v1/ligand-libraries/import",
    # Not an upload, but the one endpoint that writes outside Ankora's own data
    # directory, to a folder the request names. A JSON body already forces a
    # preflight that a foreign origin fails, so this is the belt to that
    # brace - the consequence of getting it wrong is a file somewhere else on
    # the scientist's disk.
    "/api/v1/results/figures",
}


def _requires_known_origin(path: str) -> bool:
    return path in _ORIGIN_GUARDED_PATHS or (
        path.startswith("/api/v1/results/campaigns/")
        and path.endswith("/complex/export")
    )


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        cast(VinaDockingService, app.state.vina_docking).shutdown()
        cast(AutoGridMapService, app.state.autogrid_maps).shutdown()
        cast(AutoDock4DockingService, app.state.autodock4_docking).shutdown()
        cast(
            AutoDockGpuDockingService, app.state.autodock_gpu_docking
        ).shutdown()
        cast(WorkLeaseManager, app.state.work_leases).shutdown()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Ankora local API",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=_lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    lease_store = WorkLeaseStore.from_environment()
    app.state.work_recovery = InterruptedWorkRecovery.from_environment(
        leases=lease_store
    ).reconcile()
    lease_manager = WorkLeaseManager(lease_store)
    app.state.work_leases = lease_manager
    app.state.vina_docking = VinaDockingService.from_environment(
        lease_manager=lease_manager
    )
    app.state.autogrid_maps = AutoGridMapService.from_environment(
        lease_manager=lease_manager
    )
    app.state.autodock4_docking = AutoDock4DockingService.from_environment(
        lease_manager=lease_manager
    )
    app.state.autodock_gpu_docking = AutoDockGpuDockingService.from_environment(
        lease_manager=lease_manager
    )

    @app.middleware("http")
    async def require_known_origin_for_uploads(request: Request, call_next):  # type: ignore[no-untyped-def]
        if _requires_known_origin(request.url.path) and request.method == "POST":
            origin = request.headers.get("origin")
            if origin not in _ALLOWED_ORIGINS:
                body = ErrorResponse(
                    code="UPLOAD_ORIGIN_NOT_ALLOWED",
                    stage="request_validation",
                    message=(
                        "This endpoint only accepts requests from the Ankora "
                        "desktop app."
                    ),
                    details={"origin": origin},
                    recoverable=False,
                )
                return JSONResponse(status_code=403, content=body.model_dump(mode="json"))
        return await call_next(request)

    app.include_router(router)

    @app.exception_handler(AnkoraDomainError)
    async def handle_domain_error(
        _request: Request, error: AnkoraDomainError
    ) -> JSONResponse:
        body = ErrorResponse(
            code=error.code,
            stage=error.stage,
            message=error.message,
            details=error.details,
            recoverable=error.recoverable,
        )
        return JSONResponse(status_code=error.status_code, content=body.model_dump(mode="json"))

    return app
