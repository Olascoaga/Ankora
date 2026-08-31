"""Bootstrap API routes."""

import os
from typing import Annotated, cast

from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

from ankora_backend.adapters.tools.discovery import (
    discover_autodock4,
    discover_autodock_gpu,
    discover_autogrid4,
    discover_p2rank,
    discover_python_package,
    discover_tool,
    discover_vina,
)
from ankora_backend.persistence.artifact_store import StructureArtifactStore
from ankora_backend.persistence.binding_site_store import BindingSiteArtifactStore
from ankora_backend.persistence.ligand_store import LigandArtifactStore
from ankora_backend.persistence.pocket_detection_store import PocketDetectionArtifactStore
from ankora_backend.persistence.receptor_store import ReceptorArtifactStore
from ankora_backend.schemas.autodock4 import (
    AutoDock4BatchProgress,
    AutoDock4BatchRecord,
    AutoDock4BatchRequest,
    AutoDock4CancelResponse,
    AutoDock4DockingJobRecord,
    AutoDock4DockingRequest,
)
from ankora_backend.schemas.autodock_gpu import (
    AutoDockGpuBatchProgress,
    AutoDockGpuBatchRecord,
    AutoDockGpuBatchRequest,
    AutoDockGpuCancelResponse,
    AutoDockGpuDockingJobRecord,
    AutoDockGpuDockingRequest,
)
from ankora_backend.schemas.autogrid import (
    AutoGridJobCancelResponse,
    AutoGridMapJobRecord,
    AutoGridMapSetRecord,
    AutoGridMapSetRequest,
    AutoGridMapSetSummary,
)
from ankora_backend.schemas.binding_sites import (
    BindingSitePreview,
    BindingSiteRecord,
    BindingSiteRequest,
    PocketDetectionReport,
)
from ankora_backend.schemas.campaign_history import CampaignHistory
from ankora_backend.schemas.docking import (
    DockingBatchCancelResponse,
    DockingCancelResponse,
    VinaBatchDockingRecord,
    VinaBatchDockingRequest,
    VinaBatchProgress,
    VinaDockingJobRecord,
    VinaDockingRequest,
)
from ankora_backend.schemas.engine_comparison import EngineComparison
from ankora_backend.schemas.exports import ExportKind, ExportPage
from ankora_backend.schemas.figures import FigureExport, FigureExportRequest
from ankora_backend.schemas.ligand_library_preparation import LigandLibraryPreparationRecord
from ankora_backend.schemas.ligands import (
    ApplyLigandLibraryFilterRequest,
    ExtractLigandRequest,
    GenerateLigandConformerRequest,
    LigandChemicalStateRecord,
    LigandConformerRecord,
    LigandLibraryFilterPreview,
    LigandLibraryFilterRequest,
    LigandLibraryFilterRun,
    LigandLibraryPage,
    LigandLibraryRecord,
    LigandPdbqtRecord,
    LigandProtonationOptions,
    LigandProtonationRecord,
    LigandRecord,
    LigandStateResolutionOptions,
    MinimizeLigandRequest,
    PrepareLigandPdbqtRequest,
    ResolveLigandProtonationRequest,
    ResolveLigandStateRequest,
)
from ankora_backend.schemas.methods import MethodsReport
from ankora_backend.schemas.pose_complexes import (
    PoseComplexExport,
    PoseComplexExportRequest,
)
from ankora_backend.schemas.pose_interactions import (
    InteractionAnalysisRecord,
    InteractionAnalysisRequest,
    PoseInventory,
)
from ankora_backend.schemas.receptors import (
    ReceptorInspectionReport,
    ReceptorPreparationRecord,
    ReceptorPreparationRequest,
)
from ankora_backend.schemas.redocking import (
    RedockingRunRecord,
    RedockingValidationRequest,
)
from ankora_backend.schemas.results_catalog import (
    CatalogEntry,
    CatalogPage,
    CompoundPage,
    ResultMode,
    ScoringFamily,
    TrashResultCampaignsRequest,
    TrashResultCampaignsResponse,
)
from ankora_backend.schemas.structures import (
    FetchAlphaFoldStructureRequest,
    FetchStructureRequest,
    StructureRecord,
    StructureSource,
)
from ankora_backend.schemas.system import (
    HealthResponse,
    ResourceUsage,
    SystemResponse,
    ToolsResponse,
    ToolStatus,
)
from ankora_backend.services.autodock4_docking import AutoDock4DockingService
from ankora_backend.services.autodock_gpu_docking import AutoDockGpuDockingService
from ankora_backend.services.autogrid_maps import AutoGridMapService
from ankora_backend.services.binding_site_definition import (
    define_binding_site,
    preview_binding_site,
)
from ankora_backend.services.campaign_export import CampaignExportService
from ankora_backend.services.campaign_history import CampaignHistoryService
from ankora_backend.services.engine_comparison import EngineComparisonService
from ankora_backend.services.export_catalog import ExportCatalogService
from ankora_backend.services.figure_export import FigureExportService
from ankora_backend.services.ligand_extraction import extract_crystallographic_ligand
from ankora_backend.services.ligand_filtering import (
    apply_library_filters,
    preview_library_filters,
)
from ankora_backend.services.ligand_import import (
    MAX_LIGAND_BYTES,
    import_local_ligand,
    import_local_ligand_library,
)
from ankora_backend.services.ligand_minimization import (
    generate_ligand_conformer,
    minimize_ligand,
)
from ankora_backend.services.ligand_preparation import prepare_ligand_pdbqt
from ankora_backend.services.ligand_protonation import (
    protonation_options,
    resolve_ligand_protonation,
)
from ankora_backend.services.ligand_state_resolution import (
    resolve_ligand_state,
    state_resolution_options,
)
from ankora_backend.services.methods_report import MethodsReportService
from ankora_backend.services.pocket_detection import detect_pockets
from ankora_backend.services.pose_complex_export import PoseComplexExportService
from ankora_backend.services.pose_interactions import PoseInteractionService
from ankora_backend.services.receptor_inspection import inspect_receptor
from ankora_backend.services.receptor_preparation import prepare_receptor
from ankora_backend.services.redocking_validation import RedockingValidationService
from ankora_backend.services.result_catalog import ResultCatalogService
from ankora_backend.services.result_deletion import ResultDeletionService
from ankora_backend.services.structure_inspection import (
    MAX_STRUCTURE_BYTES,
    fetch_alphafold_cif,
    fetch_rcsb_mmcif,
    import_structure_bytes,
)
from ankora_backend.services.system_info import collect_system_info
from ankora_backend.services.system_resources import collect_resource_usage
from ankora_backend.services.vina_docking import VinaDockingService

router = APIRouter(prefix="/api/v1")


def _vina_docking_service(request: Request) -> VinaDockingService:
    return cast(VinaDockingService, request.app.state.vina_docking)


def _autogrid_map_service(request: Request) -> AutoGridMapService:
    return cast(AutoGridMapService, request.app.state.autogrid_maps)


def _autodock4_service(request: Request) -> AutoDock4DockingService:
    return cast(AutoDock4DockingService, request.app.state.autodock4_docking)


def _autodock_gpu_service(request: Request) -> AutoDockGpuDockingService:
    return cast(AutoDockGpuDockingService, request.app.state.autodock_gpu_docking)


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", backend_version="0.1.0")


@router.get("/system", response_model=SystemResponse)
def system() -> SystemResponse:
    return collect_system_info()


@router.get("/system/resources", response_model=ResourceUsage)
def system_resources() -> ResourceUsage:
    """What the machine is doing right now.

    Sampled per request: the status bar asks periodically, so the cost of a
    running campaign is visible where the scientist already looks.
    """
    return collect_resource_usage()


@router.get("/tools", response_model=ToolsResponse)
def tools() -> ToolsResponse:
    vina = discover_vina(os.getenv("ANKORA_VINA_PATH"))
    gnina = discover_tool("gnina", os.getenv("ANKORA_GNINA_PATH"))
    autogrid4 = discover_autogrid4(os.getenv("ANKORA_AUTOGRID4_PATH"))
    autodock4 = discover_autodock4(os.getenv("ANKORA_AUTODOCK4_PATH"))
    autodock_gpu = discover_autodock_gpu(os.getenv("ANKORA_AUTODOCK_GPU_PATH"))
    pdbfixer = discover_python_package("pdbfixer", "pdbfixer")
    pdb2pqr = discover_tool("pdb2pqr", os.getenv("ANKORA_PDB2PQR_PATH"))
    pdb2pqr_package = discover_python_package("pdb2pqr", "pdb2pqr")
    propka = discover_tool("propka3", os.getenv("ANKORA_PROPKA_PATH"))
    propka_package = discover_python_package("propka", "propka")
    meeko = discover_tool("mk_prepare_receptor", os.getenv("ANKORA_MEEKO_PATH"))
    meeko_ligand = discover_tool(
        "mk_prepare_ligand", os.getenv("ANKORA_MEEKO_LIGAND_PATH")
    )
    meeko_package = discover_python_package("meeko", "meeko")
    p2rank = discover_p2rank(os.getenv("ANKORA_P2RANK_PATH"))
    return ToolsResponse(
        vina=ToolStatus(available=vina.available, path=vina.path, version=vina.version),
        gnina=ToolStatus(available=gnina.available, path=gnina.path, version=gnina.version),
        autogrid4=ToolStatus(
            available=autogrid4.available,
            path=autogrid4.path,
            version=autogrid4.version,
            architecture=autogrid4.architecture,
            sha256=autogrid4.sha256,
        ),
        autodock4=ToolStatus(
            available=autodock4.available,
            path=autodock4.path,
            version=autodock4.version,
            architecture=autodock4.architecture,
            sha256=autodock4.sha256,
        ),
        autodock_gpu=ToolStatus(
            available=autodock_gpu.available,
            path=autodock_gpu.path,
            version=autodock_gpu.version,
            architecture=autodock_gpu.architecture,
            sha256=autodock_gpu.sha256,
        ),
        pdbfixer=ToolStatus(
            available=pdbfixer.available, path=pdbfixer.path, version=pdbfixer.version
        ),
        pdb2pqr=ToolStatus(
            available=pdb2pqr.available,
            path=pdb2pqr.path,
            version=pdb2pqr_package.version,
        ),
        propka=ToolStatus(
            available=propka.available,
            path=propka.path,
            version=propka_package.version,
        ),
        meeko=ToolStatus(
            available=meeko.available,
            path=meeko.path,
            version=meeko_package.version,
        ),
        meeko_ligand=ToolStatus(
            available=meeko_ligand.available,
            path=meeko_ligand.path,
            version=meeko_package.version,
        ),
        p2rank=ToolStatus(available=p2rank.available, path=p2rank.path, version=p2rank.version),
    )


@router.post("/structures/import", response_model=StructureRecord, status_code=201)
async def import_local_structure(file: Annotated[UploadFile, File()]) -> StructureRecord:
    filename = file.filename or "structure.cif"
    content = await file.read(MAX_STRUCTURE_BYTES + 1)
    await file.close()
    return import_structure_bytes(
        content=content,
        filename=filename,
        source=StructureSource.LOCAL,
        source_uri=None,
        store=StructureArtifactStore.from_environment(),
    )


@router.post("/structures/fetch", response_model=StructureRecord, status_code=201)
async def fetch_structure(request: FetchStructureRequest) -> StructureRecord:
    content, source_uri = await fetch_rcsb_mmcif(request.pdb_id)
    return import_structure_bytes(
        content=content,
        filename=f"{request.pdb_id}.cif",
        source=StructureSource.RCSB,
        source_uri=source_uri,
        store=StructureArtifactStore.from_environment(),
    )


@router.post("/structures/fetch/alphafold", response_model=StructureRecord, status_code=201)
async def fetch_alphafold_structure(request: FetchAlphaFoldStructureRequest) -> StructureRecord:
    content, source_uri = await fetch_alphafold_cif(request.uniprot_id)
    return import_structure_bytes(
        content=content,
        filename=f"AF-{request.uniprot_id}-model.cif",
        source=StructureSource.ALPHAFOLD,
        source_uri=source_uri,
        store=StructureArtifactStore.from_environment(),
    )


@router.get("/structures/{artifact_id}", response_model=StructureRecord)
def get_structure(artifact_id: str) -> StructureRecord:
    return StructureArtifactStore.from_environment().load_record(artifact_id)


@router.get("/structures/{artifact_id}/content", response_class=FileResponse)
def get_structure_content(artifact_id: str) -> FileResponse:
    store = StructureArtifactStore.from_environment()
    record = store.load_record(artifact_id)
    return FileResponse(
        store.content_path(artifact_id),
        media_type="text/plain; charset=utf-8",
        filename=record.artifact.original_filename,
        content_disposition_type="inline",
    )


@router.post(
    "/structures/{artifact_id}/ligands/extract",
    response_model=LigandRecord,
    status_code=201,
)
def extract_ligand(artifact_id: str, request: ExtractLigandRequest) -> LigandRecord:
    return extract_crystallographic_ligand(
        source_artifact_id=artifact_id,
        request=request,
        structure_store=StructureArtifactStore.from_environment(),
        ligand_store=LigandArtifactStore.from_environment(),
    )


@router.post("/ligands/import", response_model=LigandRecord, status_code=201)
async def import_ligand(file: Annotated[UploadFile, File()]) -> LigandRecord:
    filename = file.filename or "ligand.sdf"
    content = await file.read(MAX_LIGAND_BYTES + 1)
    await file.close()
    return import_local_ligand(
        content=content,
        filename=filename,
        store=LigandArtifactStore.from_environment(),
    )


@router.post(
    "/ligand-libraries/import",
    response_model=LigandLibraryRecord,
    status_code=201,
)
async def import_ligand_library(
    file: Annotated[UploadFile, File()],
) -> LigandLibraryRecord:
    filename = file.filename or "ligand_library.sdf"
    content = await file.read(MAX_LIGAND_BYTES + 1)
    await file.close()
    return import_local_ligand_library(
        content=content,
        filename=filename,
        store=LigandArtifactStore.from_environment(),
    )


@router.get("/ligand-libraries", response_model=LigandLibraryPage)
def list_ligand_libraries(
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
) -> LigandLibraryPage:
    """Every library this project has imported, newest first.

    Without this, a library was reachable only while the session that imported
    it was still open: the records were on disk and addressable by id, but
    nothing could enumerate them, so reopening Ankora meant importing the same
    file again. A page carries identity and counts, never molecules.
    """
    libraries = LigandArtifactStore.from_environment().list_libraries()
    return LigandLibraryPage(
        libraries=libraries[offset : offset + limit],
        total=len(libraries),
        offset=offset,
        limit=limit,
    )


@router.get(
    "/ligand-libraries/{library_id}", response_model=LigandLibraryRecord
)
def get_ligand_library(library_id: str) -> LigandLibraryRecord:
    return LigandArtifactStore.from_environment().load_library_record(library_id)


@router.get(
    "/ligand-libraries/{library_id}/content",
    response_class=FileResponse,
)
def get_ligand_library_content(library_id: str) -> FileResponse:
    store = LigandArtifactStore.from_environment()
    record = store.load_library_record(library_id)
    return FileResponse(
        store.library_content_path(library_id),
        media_type="application/octet-stream",
        filename=record.artifact.filename,
        content_disposition_type="inline",
    )


@router.post(
    "/ligand-libraries/{library_id}/filter-preview",
    response_model=LigandLibraryFilterPreview,
)
def preview_ligand_library_filters(
    library_id: str, request: LigandLibraryFilterRequest
) -> LigandLibraryFilterPreview:
    return preview_library_filters(
        library_id=library_id,
        request=request,
        store=LigandArtifactStore.from_environment(),
    )


@router.post(
    "/ligand-libraries/{library_id}/filter-runs",
    response_model=LigandLibraryFilterRun,
    status_code=201,
)
def create_ligand_library_filter_run(
    library_id: str, request: ApplyLigandLibraryFilterRequest
) -> LigandLibraryFilterRun:
    return apply_library_filters(
        library_id=library_id,
        request=request,
        store=LigandArtifactStore.from_environment(),
    )


@router.get(
    "/ligand-libraries/{library_id}/filter-runs/latest",
    response_model=LigandLibraryFilterRun,
)
def get_latest_ligand_library_filter_run(
    library_id: str,
) -> LigandLibraryFilterRun:
    return LigandArtifactStore.from_environment().load_latest_filter_run(library_id)


@router.get(
    "/ligand-libraries/{library_id}/filter-runs/{filter_run_id}",
    response_model=LigandLibraryFilterRun,
)
def get_ligand_library_filter_run(
    library_id: str, filter_run_id: str
) -> LigandLibraryFilterRun:
    return LigandArtifactStore.from_environment().load_filter_run(
        library_id, filter_run_id
    )


@router.get(
    "/ligand-libraries/{library_id}/filter-runs/{filter_run_id}/content",
    response_class=FileResponse,
)
def get_ligand_library_filter_manifest(
    library_id: str, filter_run_id: str
) -> FileResponse:
    store = LigandArtifactStore.from_environment()
    record = store.load_filter_run(library_id, filter_run_id)
    return FileResponse(
        store.filter_run_content_path(library_id, filter_run_id),
        media_type="application/json",
        filename=record.artifact.filename,
        content_disposition_type="inline",
    )


@router.get(
    "/ligand-libraries/{library_id}/preparation",
    response_model=LigandLibraryPreparationRecord,
)
def get_ligand_library_preparation(library_id: str) -> LigandLibraryPreparationRecord:
    store = LigandArtifactStore.from_environment()
    store.load_library_record(library_id)
    return store.load_preparation_status(library_id)


@router.get("/ligands/{ligand_id}", response_model=LigandRecord)
def get_ligand(ligand_id: str) -> LigandRecord:
    return LigandArtifactStore.from_environment().load_record(ligand_id)


@router.get("/ligands/{ligand_id}/content", response_class=FileResponse)
def get_ligand_content(ligand_id: str) -> FileResponse:
    store = LigandArtifactStore.from_environment()
    record = store.load_record(ligand_id)
    return FileResponse(
        store.content_path(ligand_id),
        media_type={
            "sdf": "chemical/x-mdl-sdfile",
            "mol": "chemical/x-mdl-molfile",
            "smiles": "chemical/x-daylight-smiles",
        }[record.artifact.format.value],
        filename=record.artifact.filename,
        content_disposition_type="inline",
    )


@router.get(
    "/ligands/{ligand_id}/states/{state_id}/content",
    response_class=FileResponse,
)
def get_ligand_state_content(ligand_id: str, state_id: str) -> FileResponse:
    store = LigandArtifactStore.from_environment()
    record = store.load_record(ligand_id)
    filename = (
        record.state.filename
        if record.state is not None and record.state.state_id == state_id
        else store.load_state_artifact(ligand_id, state_id).filename
    )
    return FileResponse(
        store.state_content_path(ligand_id, state_id),
        media_type="chemical/x-mdl-sdfile",
        filename=filename,
        content_disposition_type="inline",
    )


@router.get(
    "/ligands/{ligand_id}/states/{parent_state_id}/resolution-options",
    response_model=LigandStateResolutionOptions,
)
def get_ligand_state_resolution_options(
    ligand_id: str,
    parent_state_id: str,
    component_index: int | None = Query(default=None, ge=0),
) -> LigandStateResolutionOptions:
    return state_resolution_options(
        ligand_id=ligand_id,
        parent_state_id=parent_state_id,
        component_index=component_index,
        store=LigandArtifactStore.from_environment(),
    )


@router.post(
    "/ligands/{ligand_id}/states/resolve",
    response_model=LigandChemicalStateRecord,
    status_code=201,
)
def create_resolved_ligand_state(
    ligand_id: str, request: ResolveLigandStateRequest
) -> LigandChemicalStateRecord:
    return resolve_ligand_state(
        ligand_id=ligand_id,
        request=request,
        store=LigandArtifactStore.from_environment(),
    )


@router.get(
    "/ligands/{ligand_id}/states/{parent_state_id}/protonation-options",
    response_model=LigandProtonationOptions,
)
def get_ligand_protonation_options(
    ligand_id: str,
    parent_state_id: str,
    ph_min: float = Query(default=7.4, ge=0, le=14),
    ph_max: float = Query(default=7.4, ge=0, le=14),
    precision: float = Query(default=1.0, gt=0, le=5),
) -> LigandProtonationOptions:
    return protonation_options(
        ligand_id=ligand_id,
        parent_state_id=parent_state_id,
        ph_min=ph_min,
        ph_max=ph_max,
        precision=precision,
        store=LigandArtifactStore.from_environment(),
    )


@router.post(
    "/ligands/{ligand_id}/states/protonate",
    response_model=LigandProtonationRecord,
    status_code=201,
)
def create_resolved_ligand_protonation(
    ligand_id: str, request: ResolveLigandProtonationRequest
) -> LigandProtonationRecord:
    return resolve_ligand_protonation(
        ligand_id=ligand_id,
        request=request,
        store=LigandArtifactStore.from_environment(),
    )


@router.post(
    "/ligands/{ligand_id}/conformers/minimize",
    response_model=LigandConformerRecord,
    status_code=201,
)
def minimize_ligand_conformer(
    ligand_id: str, request: MinimizeLigandRequest
) -> LigandConformerRecord:
    return minimize_ligand(
        ligand_id=ligand_id,
        request=request,
        store=LigandArtifactStore.from_environment(),
    )


@router.post(
    "/ligands/{ligand_id}/conformers/generate",
    response_model=LigandConformerRecord,
    status_code=201,
)
def generate_independent_ligand_conformer(
    ligand_id: str, request: GenerateLigandConformerRequest
) -> LigandConformerRecord:
    return generate_ligand_conformer(
        ligand_id=ligand_id,
        request=request,
        store=LigandArtifactStore.from_environment(),
    )


@router.get(
    "/ligands/{ligand_id}/conformers/{conformer_id}",
    response_model=LigandConformerRecord,
)
def get_ligand_conformer(ligand_id: str, conformer_id: str) -> LigandConformerRecord:
    return LigandArtifactStore.from_environment().load_conformer_record(
        ligand_id, conformer_id
    )


@router.get(
    "/ligands/{ligand_id}/conformers/{conformer_id}/content",
    response_class=FileResponse,
)
def get_ligand_conformer_content(ligand_id: str, conformer_id: str) -> FileResponse:
    store = LigandArtifactStore.from_environment()
    record = store.load_conformer_record(ligand_id, conformer_id)
    return FileResponse(
        store.conformer_content_path(ligand_id, conformer_id),
        media_type="chemical/x-mdl-sdfile",
        filename=record.artifact.filename,
        content_disposition_type="inline",
    )


@router.post(
    "/ligands/{ligand_id}/conformers/{conformer_id}/pdbqt",
    response_model=LigandPdbqtRecord,
    status_code=201,
)
def create_ligand_pdbqt(
    ligand_id: str,
    conformer_id: str,
    request: PrepareLigandPdbqtRequest,
) -> LigandPdbqtRecord:
    return prepare_ligand_pdbqt(
        ligand_id=ligand_id,
        conformer_id=conformer_id,
        request=request,
        store=LigandArtifactStore.from_environment(),
    )


@router.get(
    "/ligands/{ligand_id}/preparations/{preparation_id}",
    response_model=LigandPdbqtRecord,
)
def get_ligand_pdbqt(ligand_id: str, preparation_id: str) -> LigandPdbqtRecord:
    return LigandArtifactStore.from_environment().load_pdbqt_record(
        ligand_id, preparation_id
    )


@router.get(
    "/ligands/{ligand_id}/preparations/{preparation_id}/content",
    response_class=FileResponse,
)
def get_ligand_pdbqt_content(ligand_id: str, preparation_id: str) -> FileResponse:
    store = LigandArtifactStore.from_environment()
    record = store.load_pdbqt_record(ligand_id, preparation_id)
    return FileResponse(
        store.pdbqt_content_path(ligand_id, preparation_id),
        media_type="text/plain; charset=utf-8",
        filename=record.artifact.filename,
        content_disposition_type="inline",
    )


@router.get(
    "/structures/{artifact_id}/receptor-inspection",
    response_model=ReceptorInspectionReport,
)
def get_receptor_inspection(
    artifact_id: str,
    reference_component_id: str | None = Query(default=None),
) -> ReceptorInspectionReport:
    return inspect_receptor(
        artifact_id=artifact_id,
        store=StructureArtifactStore.from_environment(),
        reference_component_id=reference_component_id,
    )


@router.post(
    "/structures/{artifact_id}/receptors",
    response_model=ReceptorPreparationRecord,
    status_code=201,
)
def create_receptor(
    artifact_id: str, request: ReceptorPreparationRequest
) -> ReceptorPreparationRecord:
    return prepare_receptor(
        source_artifact_id=artifact_id,
        request=request,
        structure_store=StructureArtifactStore.from_environment(),
        receptor_store=ReceptorArtifactStore.from_environment(),
    )


@router.get("/receptors/latest", response_model=ReceptorPreparationRecord)
def get_latest_receptor() -> ReceptorPreparationRecord:
    return ReceptorArtifactStore.from_environment().load_latest_record()


@router.get("/receptors/{receptor_id}", response_model=ReceptorPreparationRecord)
def get_receptor(receptor_id: str) -> ReceptorPreparationRecord:
    return ReceptorArtifactStore.from_environment().load_record(receptor_id)


@router.get(
    "/receptors/{receptor_id}/outputs/{output_artifact_id}/content",
    response_class=FileResponse,
)
def get_receptor_content(receptor_id: str, output_artifact_id: str) -> FileResponse:
    store = ReceptorArtifactStore.from_environment()
    # Validates existence and raises the store's own RECEPTOR_NOT_FOUND (404)
    # if `output_artifact_id` isn't one of this receptor's outputs — routes
    # in this project never raise domain errors themselves, only stores and
    # services do, so this is the real check, not a redundant one to race
    # against a second, route-local check for the same condition.
    path = store.content_path(receptor_id, output_artifact_id)
    record = store.load_record(receptor_id)
    output = next(item for item in record.outputs if item.artifact_id == output_artifact_id)
    media_type = "text/plain; charset=utf-8"
    return FileResponse(
        path,
        media_type=media_type,
        filename=output.filename,
        content_disposition_type="inline",
    )


@router.post(
    "/receptors/{receptor_id}/binding-site-preview",
    response_model=BindingSitePreview,
)
def create_binding_site_preview(
    receptor_id: str,
    request: BindingSiteRequest,
) -> BindingSitePreview:
    return preview_binding_site(
        receptor_id=receptor_id,
        request=request,
        structure_store=StructureArtifactStore.from_environment(),
        receptor_store=ReceptorArtifactStore.from_environment(),
        pocket_detection_store=PocketDetectionArtifactStore.from_environment(),
    )


@router.post(
    "/receptors/{receptor_id}/binding-sites",
    response_model=BindingSiteRecord,
    status_code=201,
)
def create_binding_site(receptor_id: str, request: BindingSiteRequest) -> BindingSiteRecord:
    return define_binding_site(
        receptor_id=receptor_id,
        request=request,
        structure_store=StructureArtifactStore.from_environment(),
        receptor_store=ReceptorArtifactStore.from_environment(),
        binding_site_store=BindingSiteArtifactStore.from_environment(),
        pocket_detection_store=PocketDetectionArtifactStore.from_environment(),
    )


@router.get("/binding-sites/{binding_site_id}", response_model=BindingSiteRecord)
def get_binding_site(binding_site_id: str) -> BindingSiteRecord:
    return BindingSiteArtifactStore.from_environment().load_record(binding_site_id)


@router.post(
    "/receptors/{receptor_id}/pocket-detection",
    response_model=PocketDetectionReport,
    status_code=201,
)
def create_pocket_detection(receptor_id: str) -> PocketDetectionReport:
    return detect_pockets(
        receptor_id=receptor_id,
        receptor_store=ReceptorArtifactStore.from_environment(),
        pocket_detection_store=PocketDetectionArtifactStore.from_environment(),
    )


@router.get("/pocket-detection/{report_id}", response_model=PocketDetectionReport)
def get_pocket_detection(report_id: str) -> PocketDetectionReport:
    return PocketDetectionArtifactStore.from_environment().load_record(report_id)


@router.post(
    "/docking/vina/jobs",
    response_model=VinaDockingJobRecord,
    status_code=202,
)
def create_vina_docking_job(
    request: VinaDockingRequest,
    http_request: Request,
) -> VinaDockingJobRecord:
    return _vina_docking_service(http_request).start(request)


@router.get("/docking/jobs/{job_id}", response_model=VinaDockingJobRecord)
def get_docking_job(job_id: str, request: Request) -> VinaDockingJobRecord:
    return _vina_docking_service(request).get(job_id)


@router.post(
    "/docking/jobs/{job_id}/cancel",
    response_model=DockingCancelResponse,
)
def cancel_docking_job(job_id: str, request: Request) -> DockingCancelResponse:
    return _vina_docking_service(request).cancel(job_id)


@router.get(
    "/docking/jobs/{job_id}/poses/{artifact_id}/content",
    response_class=FileResponse,
)
def get_docking_pose_content(
    job_id: str,
    artifact_id: str,
    request: Request,
) -> FileResponse:
    path = _vina_docking_service(request).pose_content_path(job_id, artifact_id)
    return FileResponse(
        path,
        media_type="text/plain; charset=utf-8",
        filename=path.name,
        content_disposition_type="inline",
    )


@router.post(
    "/docking/vina/batches",
    response_model=VinaBatchDockingRecord,
    status_code=202,
)
def create_vina_docking_batch(
    batch_request: VinaBatchDockingRequest,
    request: Request,
) -> VinaBatchDockingRecord:
    return _vina_docking_service(request).start_batch(batch_request)


@router.get(
    "/docking/batches/latest", response_model=VinaBatchDockingRecord
)
def get_latest_docking_batch(
    request: Request,
    library_id: Annotated[str, Query(min_length=1)],
    receptor_id: Annotated[str, Query(min_length=1)],
    binding_site_id: Annotated[str, Query(min_length=1)],
) -> VinaBatchDockingRecord:
    return _vina_docking_service(request).latest_batch(
        library_id=library_id,
        receptor_id=receptor_id,
        binding_site_id=binding_site_id,
    )


@router.get("/docking/batches/history", response_model=CampaignHistory)
def get_vina_campaign_history(
    receptor_id: Annotated[str, Query(min_length=1)],
    binding_site_id: Annotated[str, Query(min_length=1)],
) -> CampaignHistory:
    return CampaignHistoryService.from_environment().vina_history(
        receptor_id=receptor_id,
        binding_site_id=binding_site_id,
    )


@router.get(
    "/docking/batches/{batch_id}", response_model=VinaBatchDockingRecord
)
def get_docking_batch(batch_id: str, request: Request) -> VinaBatchDockingRecord:
    return _vina_docking_service(request).get_batch(batch_id)


@router.get(
    "/docking/batches/{batch_id}/progress", response_model=VinaBatchProgress
)
def get_docking_batch_progress(
    batch_id: str,
    request: Request,
    after_revision: Annotated[int, Query(ge=0)] = 0,
) -> VinaBatchProgress:
    return _vina_docking_service(request).get_batch_progress(
        batch_id, after_revision=after_revision
    )


@router.post(
    "/docking/batches/{batch_id}/cancel",
    response_model=DockingBatchCancelResponse,
)
def cancel_docking_batch(
    batch_id: str, request: Request
) -> DockingBatchCancelResponse:
    return _vina_docking_service(request).cancel_batch(batch_id)


@router.get(
    "/docking/batches/{batch_id}/ligands/{ligand_id}/poses/"
    "{artifact_id}/content",
    response_class=FileResponse,
)
def get_batch_docking_pose_content(
    batch_id: str,
    ligand_id: str,
    artifact_id: str,
    request: Request,
) -> FileResponse:
    path = _vina_docking_service(request).batch_pose_content_path(
        batch_id, ligand_id, artifact_id
    )
    return FileResponse(
        path,
        media_type="text/plain; charset=utf-8",
        filename=path.name,
        content_disposition_type="inline",
    )


@router.post("/autogrid/map-sets", response_model=AutoGridMapSetSummary)
def ensure_autogrid_map_set(
    request: AutoGridMapSetRequest,
    http_request: Request,
) -> AutoGridMapSetSummary:
    return _autogrid_map_service(http_request).ensure_map_set(request)


@router.post(
    "/autogrid/jobs",
    response_model=AutoGridMapJobRecord,
    status_code=202,
)
def start_autogrid_job(
    request: AutoGridMapSetRequest,
    http_request: Request,
) -> AutoGridMapJobRecord:
    return _autogrid_map_service(http_request).start_map_set(request)


@router.get("/autogrid/jobs/{job_id}", response_model=AutoGridMapJobRecord)
def get_autogrid_job(job_id: str, request: Request) -> AutoGridMapJobRecord:
    return _autogrid_map_service(request).get_job(job_id)


@router.post(
    "/autogrid/jobs/{job_id}/cancel",
    response_model=AutoGridJobCancelResponse,
)
def cancel_autogrid_job(job_id: str, request: Request) -> AutoGridJobCancelResponse:
    return _autogrid_map_service(request).cancel_job(job_id)


@router.get(
    "/autogrid/map-sets/{map_set_id}",
    response_model=AutoGridMapSetRecord,
)
def get_autogrid_map_set(map_set_id: str, request: Request) -> AutoGridMapSetRecord:
    return _autogrid_map_service(request).get(map_set_id)


@router.get(
    "/autogrid/map-sets/{map_set_id}/artifacts/{artifact_id}/content",
    response_class=FileResponse,
)
def get_autogrid_map_content(
    map_set_id: str,
    artifact_id: str,
    request: Request,
) -> FileResponse:
    path = _autogrid_map_service(request).content_path(map_set_id, artifact_id)
    return FileResponse(
        path,
        media_type="text/plain; charset=utf-8",
        filename=path.name,
        content_disposition_type="inline",
    )


@router.post(
    "/docking/autodock4/jobs",
    response_model=AutoDock4DockingJobRecord,
    status_code=202,
)
def create_autodock4_job(
    request: AutoDock4DockingRequest,
    http_request: Request,
) -> AutoDock4DockingJobRecord:
    return _autodock4_service(http_request).start(request)


@router.get(
    "/docking/autodock4/jobs/{job_id}",
    response_model=AutoDock4DockingJobRecord,
)
def get_autodock4_job(job_id: str, request: Request) -> AutoDock4DockingJobRecord:
    return _autodock4_service(request).get(job_id)


@router.post(
    "/docking/autodock4/jobs/{job_id}/cancel",
    response_model=AutoDock4CancelResponse,
)
def cancel_autodock4_job(job_id: str, request: Request) -> AutoDock4CancelResponse:
    return _autodock4_service(request).cancel(job_id)


@router.get(
    "/docking/autodock4/jobs/{job_id}/poses/{artifact_id}/content",
    response_class=FileResponse,
)
def get_autodock4_pose_content(
    job_id: str,
    artifact_id: str,
    request: Request,
) -> FileResponse:
    path = _autodock4_service(request).pose_content_path(job_id, artifact_id)
    return FileResponse(
        path,
        media_type="text/plain; charset=utf-8",
        filename=path.name,
        content_disposition_type="inline",
    )


@router.post(
    "/docking/autodock-gpu/jobs",
    response_model=AutoDockGpuDockingJobRecord,
    status_code=202,
)
def create_autodock_gpu_job(
    request: AutoDockGpuDockingRequest,
    http_request: Request,
) -> AutoDockGpuDockingJobRecord:
    return _autodock_gpu_service(http_request).start(request)


@router.get(
    "/docking/autodock-gpu/jobs/{job_id}",
    response_model=AutoDockGpuDockingJobRecord,
)
def get_autodock_gpu_job(
    job_id: str, request: Request
) -> AutoDockGpuDockingJobRecord:
    return _autodock_gpu_service(request).get(job_id)


@router.post(
    "/docking/autodock-gpu/jobs/{job_id}/cancel",
    response_model=AutoDockGpuCancelResponse,
)
def cancel_autodock_gpu_job(
    job_id: str, request: Request
) -> AutoDockGpuCancelResponse:
    return _autodock_gpu_service(request).cancel(job_id)


@router.get(
    "/docking/autodock-gpu/jobs/{job_id}/poses/{artifact_id}/content",
    response_class=FileResponse,
)
def get_autodock_gpu_pose_content(
    job_id: str,
    artifact_id: str,
    request: Request,
) -> FileResponse:
    path = _autodock_gpu_service(request).pose_content_path(job_id, artifact_id)
    return FileResponse(
        path,
        media_type="text/plain; charset=utf-8",
        filename=path.name,
        content_disposition_type="inline",
    )


@router.post(
    "/docking/autodock-gpu/batches",
    response_model=AutoDockGpuBatchRecord,
    status_code=202,
)
def create_autodock_gpu_batch(
    request: AutoDockGpuBatchRequest,
    http_request: Request,
) -> AutoDockGpuBatchRecord:
    return _autodock_gpu_service(http_request).start_batch(request)


@router.get(
    "/docking/autodock-gpu/batches/latest",
    response_model=AutoDockGpuBatchRecord,
)
def get_latest_autodock_gpu_batch(
    receptor_id: Annotated[str, Query(min_length=1)],
    binding_site_id: Annotated[str, Query(min_length=1)],
    filter_run_id: Annotated[str, Query(min_length=1)],
    request: Request,
) -> AutoDockGpuBatchRecord:
    return _autodock_gpu_service(request).latest_batch(
        receptor_id=receptor_id,
        binding_site_id=binding_site_id,
        filter_run_id=filter_run_id,
    )


@router.get(
    "/docking/autodock-gpu/batches/{batch_id}",
    response_model=AutoDockGpuBatchRecord,
)
def get_autodock_gpu_batch(
    batch_id: str, request: Request
) -> AutoDockGpuBatchRecord:
    return _autodock_gpu_service(request).get_batch(batch_id)


@router.get(
    "/docking/autodock-gpu/batches/{batch_id}/progress",
    response_model=AutoDockGpuBatchProgress,
)
def get_autodock_gpu_batch_progress(
    batch_id: str, request: Request
) -> AutoDockGpuBatchProgress:
    return _autodock_gpu_service(request).get_batch_progress(batch_id)


@router.post(
    "/docking/autodock-gpu/batches/{batch_id}/cancel",
    response_model=AutoDockGpuCancelResponse,
)
def cancel_autodock_gpu_batch(
    batch_id: str, request: Request
) -> AutoDockGpuCancelResponse:
    return _autodock_gpu_service(request).cancel_batch(batch_id)


@router.get(
    "/docking/autodock-gpu/batches/{batch_id}/ligands/{ligand_id}"
    "/poses/{artifact_id}/content",
    response_class=FileResponse,
)
def get_autodock_gpu_batch_pose_content(
    batch_id: str,
    ligand_id: str,
    artifact_id: str,
    request: Request,
) -> FileResponse:
    path = _autodock_gpu_service(request).batch_pose_content_path(
        batch_id, ligand_id, artifact_id
    )
    return FileResponse(
        path,
        media_type="text/plain; charset=utf-8",
        filename=path.name,
        content_disposition_type="inline",
    )


@router.post(
    "/docking/autodock4/batches",
    response_model=AutoDock4BatchRecord,
    status_code=202,
)
def create_autodock4_batch(
    request: AutoDock4BatchRequest,
    http_request: Request,
) -> AutoDock4BatchRecord:
    return _autodock4_service(http_request).start_batch(request)


@router.get(
    "/docking/autodock4/batches/latest",
    response_model=AutoDock4BatchRecord,
)
def get_latest_autodock4_batch(
    receptor_id: Annotated[str, Query(min_length=1)],
    binding_site_id: Annotated[str, Query(min_length=1)],
    filter_run_id: Annotated[str, Query(min_length=1)],
    request: Request,
) -> AutoDock4BatchRecord:
    return _autodock4_service(request).latest_batch(
        receptor_id=receptor_id,
        binding_site_id=binding_site_id,
        filter_run_id=filter_run_id,
    )


@router.get(
    "/docking/autodock4/batches/history",
    response_model=CampaignHistory,
)
def get_autodock4_campaign_history(
    receptor_id: Annotated[str, Query(min_length=1)],
    binding_site_id: Annotated[str, Query(min_length=1)],
) -> CampaignHistory:
    return CampaignHistoryService.from_environment().autodock4_history(
        receptor_id=receptor_id,
        binding_site_id=binding_site_id,
    )


@router.get(
    "/docking/autodock4/batches/{batch_id}",
    response_model=AutoDock4BatchRecord,
)
def get_autodock4_batch(batch_id: str, request: Request) -> AutoDock4BatchRecord:
    return _autodock4_service(request).get_batch(batch_id)


@router.get(
    "/docking/autodock4/batches/{batch_id}/progress",
    response_model=AutoDock4BatchProgress,
)
def get_autodock4_batch_progress(
    batch_id: str,
    request: Request,
    after_revision: Annotated[int, Query(ge=0)] = 0,
) -> AutoDock4BatchProgress:
    return _autodock4_service(request).get_batch_progress(batch_id, after_revision)


@router.post(
    "/docking/autodock4/batches/{batch_id}/cancel",
    response_model=AutoDock4CancelResponse,
)
def cancel_autodock4_batch(batch_id: str, request: Request) -> AutoDock4CancelResponse:
    return _autodock4_service(request).cancel_batch(batch_id)


@router.get(
    "/docking/autodock4/batches/{batch_id}/ligands/{ligand_id}/poses/"
    "{artifact_id}/content",
    response_class=FileResponse,
)
def get_autodock4_batch_pose_content(
    batch_id: str,
    ligand_id: str,
    artifact_id: str,
    request: Request,
) -> FileResponse:
    path = _autodock4_service(request).batch_pose_content_path(
        batch_id, ligand_id, artifact_id
    )
    return FileResponse(
        path,
        media_type="text/plain; charset=utf-8",
        filename=path.name,
        content_disposition_type="inline",
    )


@router.get(
    "/docking/comparison",
    response_model=EngineComparison,
)
def compare_docking_engines(
    vina_batch_id: Annotated[str, Query(min_length=1)],
    autodock4_batch_id: Annotated[str, Query(min_length=1)],
    top_n: Annotated[int, Query(ge=1, le=1000)] = 20,
) -> EngineComparison:
    return EngineComparisonService.from_environment().compare(
        vina_batch_id=vina_batch_id,
        autodock4_batch_id=autodock4_batch_id,
        top_n=top_n,
    )


@router.get(
    "/docking/comparison/latest",
    response_model=EngineComparison,
)
def compare_latest_docking_campaigns(
    receptor_id: Annotated[str, Query(min_length=1)],
    binding_site_id: Annotated[str, Query(min_length=1)],
    filter_run_id: Annotated[str, Query(min_length=1)],
    top_n: Annotated[int, Query(ge=1, le=1000)] = 20,
) -> EngineComparison:
    return EngineComparisonService.from_environment().compare_latest(
        receptor_id=receptor_id,
        binding_site_id=binding_site_id,
        filter_run_id=filter_run_id,
        top_n=top_n,
    )


@router.post(
    "/validation/redocking",
    response_model=RedockingRunRecord,
    status_code=201,
)
def validate_redocking(request: RedockingValidationRequest) -> RedockingRunRecord:
    """Measure a docking result that already exists against a preserved pose."""
    return RedockingValidationService.from_environment().validate(request)


@router.get("/validation/redocking", response_model=list[RedockingRunRecord])
def list_redocking_validations() -> list[RedockingRunRecord]:
    return RedockingValidationService.from_environment().list_runs()


@router.get(
    "/validation/redocking/{validation_id}",
    response_model=RedockingRunRecord,
)
def get_redocking_validation(validation_id: str) -> RedockingRunRecord:
    return RedockingValidationService.from_environment().get(validation_id)


@router.get("/exports", response_model=ExportPage)
def list_exports(
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    kind: ExportKind | None = None,
) -> ExportPage:
    """Everything this project has sent out of Ankora, newest first.

    Each export already recorded what it was and where it came from; until now
    none of them could be listed, so a bundle written last week was findable
    only by remembering its identifier.
    """
    return ExportCatalogService.from_environment().list_exports(
        offset=offset, limit=limit, kind=kind
    )


@router.post("/exports/campaigns", status_code=201)
def export_campaign(
    source_kind: Annotated[str, Query(min_length=1)],
    source_id: Annotated[str, Query(min_length=1)],
    destination: Annotated[str | None, Query(min_length=1)] = None,
) -> dict[str, object]:
    """Write a reproducible bundle for a campaign that already ran.

    The bundle is preserved in the project rather than streamed away, so an
    export is itself something that happened and can be found again.
    """
    return CampaignExportService.from_environment().export_campaign(
        source_kind=source_kind, batch_id=source_id, destination=destination
    )


@router.get("/exports/{export_id}/{filename}", response_class=FileResponse)
def get_export_file(export_id: str, filename: str) -> FileResponse:
    path = CampaignExportService.from_environment().file_path(export_id, filename)
    return FileResponse(
        path,
        media_type=(
            "application/zip"
            if path.suffix == ".zip"
            else "text/csv; charset=utf-8"
            if path.suffix == ".csv"
            else "application/json"
            if path.suffix == ".json"
            else "text/plain; charset=utf-8"
        ),
        filename=path.name,
        content_disposition_type="attachment",
    )


@router.get("/results/campaigns", response_model=CatalogPage)
def list_result_campaigns(
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    mode: ResultMode | None = None,
    scoring_family: ScoringFamily | None = None,
    receptor_id: Annotated[str | None, Query(min_length=1)] = None,
    binding_site_id: Annotated[str | None, Query(min_length=1)] = None,
    status: Annotated[str | None, Query(min_length=1)] = None,
) -> CatalogPage:
    """Every durable result in this project, newest first, without any of them.

    A page is identity and counts. The results themselves are a separate
    request, because a completed campaign is megabytes of poses and a listing
    that carried them would be unusable at the size a real project reaches.
    """
    return ResultCatalogService.from_environment().list_campaigns(
        offset=offset,
        limit=limit,
        mode=mode,
        scoring_family=scoring_family,
        receptor_id=receptor_id,
        binding_site_id=binding_site_id,
        status=status,
    )


@router.post(
    "/results/campaigns/trash",
    response_model=TrashResultCampaignsResponse,
)
def trash_result_campaigns(
    payload: TrashResultCampaignsRequest,
) -> TrashResultCampaignsResponse:
    """Remove one or many complete terminal results as one recoverable action."""
    return ResultDeletionService.from_environment().trash(payload)


@router.get(
    "/results/campaigns/{engine}/{record_id}/methods",
    response_model=MethodsReport,
)
def get_campaign_methods(engine: str, record_id: str) -> MethodsReport:
    """The Methods section this campaign's own records support.

    Rendered from the stored provenance chain rather than a template: every
    number is one a record holds, and anything a record does not hold appears
    as a visible gap instead of a plausible sentence.
    """
    return MethodsReportService.from_environment().render(f"{engine}:{record_id}")


@router.get("/results/campaigns/{engine}/{record_id}", response_model=CatalogEntry)
def get_result_campaign(engine: str, record_id: str) -> CatalogEntry:
    return ResultCatalogService.from_environment().get_campaign(f"{engine}:{record_id}")


@router.get(
    "/results/campaigns/{engine}/{record_id}/compounds",
    response_model=CompoundPage,
)
def list_result_compounds(
    engine: str,
    record_id: str,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    status: Annotated[str | None, Query(min_length=1)] = None,
    search: Annotated[str | None, Query(min_length=1)] = None,
) -> CompoundPage:
    """One page of molecules, labelled with the engine that produced them."""
    return ResultCatalogService.from_environment().list_compounds(
        f"{engine}:{record_id}",
        offset=offset,
        limit=limit,
        status=status,
        search=search,
    )


@router.get(
    "/results/campaigns/{engine}/{record_id}/compounds/{ligand_id}/poses",
    response_model=PoseInventory,
)
def list_result_poses(engine: str, record_id: str, ligand_id: str) -> PoseInventory:
    """Engine-native modes or runs for exactly one recorded molecule."""
    return PoseInteractionService.from_environment().list_poses(
        f"{engine}:{record_id}", ligand_id
    )


@router.get(
    "/results/campaigns/{engine}/{record_id}/compounds/{ligand_id}/poses/"
    "{pose_artifact_id}/interactions",
    response_model=list[InteractionAnalysisRecord],
)
def list_pose_interactions(
    engine: str, record_id: str, ligand_id: str, pose_artifact_id: str
) -> list[InteractionAnalysisRecord]:
    return PoseInteractionService.from_environment().list_analyses(
        f"{engine}:{record_id}", ligand_id, pose_artifact_id
    )


@router.post(
    "/results/campaigns/{engine}/{record_id}/compounds/{ligand_id}/poses/"
    "{pose_artifact_id}/interactions",
    response_model=InteractionAnalysisRecord,
    status_code=201,
)
def analyze_pose_interactions(
    engine: str,
    record_id: str,
    ligand_id: str,
    pose_artifact_id: str,
    payload: InteractionAnalysisRequest,
) -> InteractionAnalysisRecord:
    return PoseInteractionService.from_environment().analyze(
        f"{engine}:{record_id}", ligand_id, pose_artifact_id, payload
    )


@router.get(
    "/results/campaigns/{engine}/{record_id}/compounds/{ligand_id}/poses/"
    "{pose_artifact_id}/complex",
    response_class=PlainTextResponse,
)
def get_pose_complex(
    engine: str, record_id: str, ligand_id: str, pose_artifact_id: str
) -> PlainTextResponse:
    """The receptor and this exact pose in one PDB, for any other viewer.

    Offered because a scientist's next step is often PyMOL or Chimera, and the
    only honest way to get there is the same coordinates Ankora analyzed rather
    than a re-export that quietly moved something.
    """
    document, filename = PoseInteractionService.from_environment().complex_pdb(
        f"{engine}:{record_id}", ligand_id, pose_artifact_id
    )
    return PlainTextResponse(
        document,
        media_type="chemical/x-pdb",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/results/campaigns/{engine}/{record_id}/compounds/{ligand_id}/poses/"
    "{pose_artifact_id}/complex/export",
    response_model=PoseComplexExport,
    status_code=201,
)
def export_pose_complex(
    engine: str,
    record_id: str,
    ligand_id: str,
    pose_artifact_id: str,
    payload: PoseComplexExportRequest,
) -> PoseComplexExport:
    """Write the exact combined PDB into a visible, explicit folder."""
    return PoseComplexExportService.from_environment().export(
        f"{engine}:{record_id}", ligand_id, pose_artifact_id, payload
    )


@router.post("/results/figures", response_model=FigureExport, status_code=201)
def export_figure(payload: FigureExportRequest) -> FigureExport:
    """Write one recorded view out as a publication figure.

    The picture is the one the page was already showing; nothing is recomputed
    for export, so the figure and the screen cannot disagree.
    """
    return FigureExportService.from_environment().export_figure(payload)


@router.get("/results/figures/{figure_id}/{filename}", response_class=FileResponse)
def get_figure_file(figure_id: str, filename: str) -> FileResponse:
    path = FigureExportService.from_environment().file_path(figure_id, filename)
    media_types = {
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".tiff": "image/tiff",
        ".pdf": "application/pdf",
        ".json": "application/json",
    }
    return FileResponse(
        path,
        media_type=media_types.get(path.suffix, "application/octet-stream"),
        filename=path.name,
        content_disposition_type="attachment",
    )
