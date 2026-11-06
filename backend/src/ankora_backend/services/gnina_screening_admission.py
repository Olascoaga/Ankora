"""Admit an explicitly selected GNINA screening into project storage."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from ankora_backend.adapters.engines.gnina import _linux_host, probe_gnina
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.gnina_screening_store import GninaScreeningStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.docking import DockingJobPhase, DockingJobStatus
from ankora_backend.schemas.gnina import GninaToolIdentity
from ankora_backend.schemas.gnina_screening import (
    GninaScreeningCampaignRecord,
    GninaScreeningRequest,
    GninaScreeningSelection,
)
from ankora_backend.schemas.receptors import ReceptorOutputStage, ReceptorPreparationStatus
from ankora_backend.services.gnina_screening_preflight import prepare_screening_entries
from ankora_backend.services.project_dependencies import ProjectDependencyService
from ankora_backend.services.resource_arbiter import ResourceArbiter, ResourceClaim


def admit_screening(
    *,
    request: GninaScreeningRequest,
    store: GninaScreeningStore,
    receptors: ReceptorArtifactStore,
    sites: BindingSiteArtifactStore,
    ligands: LigandArtifactStore,
    resources: ResourceArbiter,
    enable_experimental_cuda: bool,
) -> GninaScreeningCampaignRecord:
    """Verify common inputs and persist every selected entry; launch nothing."""
    if not _linux_host():
        raise _error("GNINA_LINUX_ONLY", "GNINA is available only in the Linux edition.")
    if request.parameters.compute == "cuda" and not enable_experimental_cuda:
        raise _error("GNINA_CUDA_VERIFICATION_UNAVAILABLE", "GNINA CUDA execution is not enabled.")
    ProjectDependencyService.for_project_root(sites.project_root).require_current(
        {
            request.receptor_id,
            request.binding_site_id,
            request.library_id,
            request.filter_run_id,
        }
    )
    receptor = receptors.load_record(request.receptor_id)
    if receptor.status is not ReceptorPreparationStatus.DOCKING_READY:
        raise _error("GNINA_RECEPTOR_NOT_READY", "The receptor is not docking ready.")
    output = next(
        (item for item in receptor.outputs if item.stage is ReceptorOutputStage.PDBQT), None
    )
    if output is None:
        raise _error("GNINA_RECEPTOR_PDBQT_MISSING", "The receptor has no PDBQT output.")
    site = sites.load_record(request.binding_site_id)
    if site.receptor_id != request.receptor_id or site.stale:
        raise _error("GNINA_BINDING_SITE_INVALID", "The binding site is stale or mismatched.")
    try:
        receptor_bytes = receptors.content_path(
            request.receptor_id, output.artifact_id
        ).read_bytes()
    except OSError as error:
        raise _error(
            "GNINA_INPUT_UNREADABLE", "The prepared receptor could not be read."
        ) from error
    if sha256(receptor_bytes).hexdigest() != output.sha256:
        raise _error("GNINA_INPUT_CHANGED", "The prepared receptor no longer matches its record.")
    now = datetime.now(UTC)
    preflight = prepare_screening_entries(
        store=ligands, library_id=request.library_id, filter_run_id=request.filter_run_id, now=now
    )
    installation = probe_gnina()
    if installation.architecture != "x86_64":
        raise _error("GNINA_EXECUTABLE_INVALID", "GNINA requires a Linux x86-64 executable.")
    campaign_id = store.new_campaign_id()
    resources.validate(
        ResourceClaim(
            workload="gnina_job",
            owner_id=campaign_id,
            cpu_threads=request.parameters.cpu_threads,
            gpu_slots=1 if request.parameters.compute == "cuda" else 0,
            memory_bytes=2 * 1024**3,
            disk_bytes=64 * 1024**2,
        )
    )
    entries = list(preflight.entries)
    failures = sum(entry.status is DockingJobStatus.FAILED for entry in entries)
    record = GninaScreeningCampaignRecord(
        campaign_id=campaign_id,
        status=DockingJobStatus.QUEUED,
        phase=DockingJobPhase.QUEUED,
        created_at=now,
        request=request,
        tool=GninaToolIdentity(
            version=installation.version, sha256=installation.sha256, architecture="x86_64"
        ),
        selection=GninaScreeningSelection(
            library_id=request.library_id,
            filter_run_id=request.filter_run_id,
            manifest_artifact_id=preflight.selection.artifact.filter_run_id,
            manifest_sha256=preflight.selection.artifact.sha256,
        ),
        receptor_output_artifact_id=output.artifact_id,
        receptor_sha256=output.sha256,
        box=site.box,
        selected_count=len(entries),
        completed_count=failures,
        failed_count=failures,
        entries=entries,
    )
    store.create_campaign(record)
    return record


def _error(code: str, message: str) -> AnkoraDomainError:
    return AnkoraDomainError(code=code, stage="gnina_screening", message=message, status_code=422)
