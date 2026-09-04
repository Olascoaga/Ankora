import type {
  ApplyLigandLibraryFilterRequest,
  BindingSitePreview,
  CatalogEntry,
  CatalogPage,
  CompoundPage,
  FigureExport,
  FigureExportRequest,
  PoseComplexExport,
  PoseComplexExportRequest,
  BindingSiteRecord,
  BindingSiteRequest,
  DockingBatchCancelResponse,
  EngineComparison,
  DockingCancelResponse,
  ErrorResponse,
  ExportPage,
  PocketDetectionReport,
  GenerateLigandConformerRequest,
  HealthResponse,
  LigandConformerRecord,
  LigandChemicalStateRecord,
  LigandLocator,
  LigandLibraryFilterPreview,
  LigandLibraryFilterRequest,
  LigandLibraryFilterRun,
  LigandLibraryPage,
  LigandLibraryPreparationRecord,
  LigandLibraryRecord,
  LigandMicrostateOptions,
  LigandMicrostatePlan,
  LigandMicrostateRecord,
  LigandPdbqtRecord,
  LigandProtonationOptions,
  LigandProtonationRecord,
  LigandRecord,
  LigandStateResolutionOptions,
  MethodsReport,
  MinimizeLigandRequest,
  PrepareLigandPdbqtRequest,
  ReceptorInspectionReport,
  ReceptorPreparationRecord,
  ReceptorPreparationRequest,
  ResolveLigandProtonationRequest,
  ResolveLigandMicrostateRequest,
  ResolveLigandStateRequest,
  ResourceUsage,
  StructureRecord,
  SystemResponse,
  ToolsResponse,
  AutoDock4BatchProgress,
  AutoDock4BatchRecord,
  AutoDockGpuBatchProgress,
  AutoDockGpuBatchRecord,
  AutoDockGpuBatchRequest,
  AutoDockGpuDockingJobRecord,
  AutoDockGpuDockingRequest,
  CampaignExport,
  CampaignHistory,
  RedockingRunRecord,
  RedockingValidationRequest,
  AutoDock4BatchRequest,
  AutoDock4CancelResponse,
  AutoDock4DockingJobRecord,
  AutoDock4DockingRequest,
  AutoGridJobCancelResponse,
  AutoGridMapJobRecord,
  AutoGridMapSetRecord,
  AutoGridMapSetRequest,
  VinaBatchDockingRecord,
  VinaBatchDockingRequest,
  VinaBatchProgress,
  VinaDockingJobRecord,
  VinaDockingRequest,
  InteractionAnalysisRecord,
  PoseInventory,
  TrashResultCampaignsResponse,
} from "../types/api";

const API_BASE_URL = import.meta.env.VITE_ANKORA_API_URL ?? "http://127.0.0.1:8765/api/v1";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly stage: string | null;
  readonly details: Record<string, unknown>;

  constructor(message: string, status: number, error?: ErrorResponse) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = error?.code ?? null;
    this.stage = error?.stage ?? null;
    this.details = error?.details ?? {};
  }
}

async function requestJson<T>(path: string, init: RequestInit): Promise<T> {
  // `fetch` labels a string body `text/plain`, which FastAPI rejects with its
  // own 422 before any handler runs - and that response carries no `message`,
  // so the caller only ever sees "returned 422". Declare JSON here rather than
  // relying on every call site to remember. A FormData body is left alone so
  // the browser can set its own multipart boundary.
  const declaresJsonBody = typeof init.body === "string";
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(declaresJsonBody ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });

  if (!response.ok) {
    let error: ErrorResponse | undefined;
    try {
      error = (await response.json()) as ErrorResponse;
    } catch {
      error = undefined;
    }
    throw new ApiError(error?.message ?? `Ankora backend returned ${response.status}`, response.status, error);
  }

  return (await response.json()) as T;
}

function getJson<T>(path: string): Promise<T> {
  return requestJson<T>(path, { method: "GET" });
}

/** `engine:record` is one identifier, and the route spends it as two segments. */
function catalogPath(catalogId: string): string {
  const separator = catalogId.indexOf(":");
  if (separator < 0) throw new Error("A catalog identifier names its engine and its record.");
  return `${encodeURIComponent(catalogId.slice(0, separator))}`
    + `/${encodeURIComponent(catalogId.slice(separator + 1))}`;
}

function campaignHistoryQuery(receptorId: string, bindingSiteId: string): string {
  return new URLSearchParams({
    receptor_id: receptorId,
    binding_site_id: bindingSiteId,
  }).toString();
}

export const ankoraApi = {
  health: (): Promise<HealthResponse> => getJson<HealthResponse>("/health"),
  system: (): Promise<SystemResponse> => getJson<SystemResponse>("/system"),
  tools: (): Promise<ToolsResponse> => getJson<ToolsResponse>("/tools"),
  importLigand: (file: File): Promise<LigandRecord> => {
    const form = new FormData();
    form.append("file", file);
    return requestJson<LigandRecord>("/ligands/import", { method: "POST", body: form });
  },
  importLigandLibrary: (file: File): Promise<LigandLibraryRecord> => {
    const form = new FormData();
    form.append("file", file);
    return requestJson<LigandLibraryRecord>("/ligand-libraries/import", {
      method: "POST",
      body: form,
    });
  },
  getLigandLibrary: (libraryId: string): Promise<LigandLibraryRecord> =>
    getJson<LigandLibraryRecord>(`/ligand-libraries/${libraryId}`),
  previewLigandLibraryFilters: (
    libraryId: string,
    request: LigandLibraryFilterRequest,
  ): Promise<LigandLibraryFilterPreview> =>
    requestJson<LigandLibraryFilterPreview>(`/ligand-libraries/${libraryId}/filter-preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request),
    }),
  getLigandLibraryPreparation: (libraryId: string): Promise<LigandLibraryPreparationRecord> =>
    getJson<LigandLibraryPreparationRecord>(`/ligand-libraries/${libraryId}/preparation`),
  /**
   * Every library already imported into this project, newest first.
   *
   * Without it a library was reachable only while the session that imported it
   * stayed open, which is why one file ended up imported 33 times.
   */
  listLigandLibraries: (
    query: { offset?: number; limit?: number } = {},
  ): Promise<LigandLibraryPage> => {
    const parameters = new URLSearchParams();
    if (query.offset !== undefined) parameters.set("offset", String(query.offset));
    if (query.limit !== undefined) parameters.set("limit", String(query.limit));
    return getJson<LigandLibraryPage>(`/ligand-libraries?${parameters.toString()}`);
  },

  latestLigandLibraryFilterRun: (libraryId: string): Promise<LigandLibraryFilterRun> =>
    getJson<LigandLibraryFilterRun>(`/ligand-libraries/${libraryId}/filter-runs/latest`),
  applyLigandLibraryFilters: (
    libraryId: string,
    request: ApplyLigandLibraryFilterRequest,
  ): Promise<LigandLibraryFilterRun> =>
    requestJson<LigandLibraryFilterRun>(`/ligand-libraries/${libraryId}/filter-runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request),
    }),
  importStructure: (file: File): Promise<StructureRecord> => {
    const form = new FormData();
    form.append("file", file);
    return requestJson<StructureRecord>("/structures/import", { method: "POST", body: form });
  },
  fetchStructure: (pdbId: string): Promise<StructureRecord> =>
    requestJson<StructureRecord>("/structures/fetch", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ pdb_id: pdbId }),
    }),
  fetchAlphafoldStructure: (uniprotId: string): Promise<StructureRecord> =>
  requestJson<StructureRecord>("/structures/fetch/alphafold", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ uniprot_id: uniprotId }),
  }),
getStructure: (structureId: string): Promise<StructureRecord> =>
    getJson<StructureRecord>(`/structures/${structureId}`),
  latestReceptor: (): Promise<ReceptorPreparationRecord> =>
    getJson<ReceptorPreparationRecord>("/receptors/latest"),
  inspectReceptor: (structureId: string, referenceComponentId: string | null): Promise<ReceptorInspectionReport> => {
    const query = referenceComponentId ? `?reference_component_id=${encodeURIComponent(referenceComponentId)}` : "";
    return getJson<ReceptorInspectionReport>(`/structures/${structureId}/receptor-inspection${query}`);
  },
  prepareReceptor: (structureId: string, request: ReceptorPreparationRequest): Promise<ReceptorPreparationRecord> =>
    requestJson<ReceptorPreparationRecord>(`/structures/${structureId}/receptors`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request),
    }),
  previewBindingSite: (receptorId: string, request: BindingSiteRequest): Promise<BindingSitePreview> =>
    requestJson<BindingSitePreview>(`/receptors/${receptorId}/binding-site-preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request),
    }),
  createBindingSite: (receptorId: string, request: BindingSiteRequest): Promise<BindingSiteRecord> =>
    requestJson<BindingSiteRecord>(`/receptors/${receptorId}/binding-sites`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request),
    }),
  getBindingSite: (bindingSiteId: string): Promise<BindingSiteRecord> =>
    getJson<BindingSiteRecord>(`/binding-sites/${bindingSiteId}`),
  detectPockets: (receptorId: string): Promise<PocketDetectionReport> =>
    requestJson<PocketDetectionReport>(`/receptors/${receptorId}/pocket-detection`, {
      method: "POST",
      headers: { Accept: "application/json" },
    }),
  getPocketDetectionReport: (reportId: string): Promise<PocketDetectionReport> =>
    getJson<PocketDetectionReport>(`/pocket-detection/${reportId}`),
  extractLigand: (structureId: string, locator: LigandLocator): Promise<LigandRecord> =>
    requestJson<LigandRecord>(`/structures/${structureId}/ligands/extract`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ locator }),
    }),
  ligandStateResolutionOptions: (
    ligandId: string,
    parentStateId: string,
    componentIndex: number | null,
  ): Promise<LigandStateResolutionOptions> => {
    const query = componentIndex === null ? "" : `?component_index=${componentIndex}`;
    return getJson<LigandStateResolutionOptions>(
      `/ligands/${ligandId}/states/${parentStateId}/resolution-options${query}`,
    );
  },
  resolveLigandState: (
    ligandId: string,
    request: ResolveLigandStateRequest,
  ): Promise<LigandChemicalStateRecord> =>
    requestJson<LigandChemicalStateRecord>(`/ligands/${ligandId}/states/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request),
    }),
  ligandProtonationOptions: (
    ligandId: string,
    parentStateId: string,
    phMin: number,
    phMax: number,
    precision: number,
  ): Promise<LigandProtonationOptions> =>
    getJson<LigandProtonationOptions>(
      `/ligands/${ligandId}/states/${parentStateId}/protonation-options`
      + `?ph_min=${phMin}&ph_max=${phMax}&precision=${precision}`,
    ),
  resolveLigandProtonation: (
    ligandId: string,
    request: ResolveLigandProtonationRequest,
  ): Promise<LigandProtonationRecord> =>
    requestJson<LigandProtonationRecord>(`/ligands/${ligandId}/states/protonate`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request),
    }),
  ligandMicrostateOptions: (
    ligandId: string,
    parentStateId: string,
    plan: LigandMicrostatePlan,
  ): Promise<LigandMicrostateOptions> =>
    requestJson<LigandMicrostateOptions>(
      `/ligands/${ligandId}/states/${parentStateId}/microstate-options`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(plan),
      },
    ),
  resolveLigandMicrostate: (
    ligandId: string,
    request: ResolveLigandMicrostateRequest,
  ): Promise<LigandMicrostateRecord> =>
    requestJson<LigandMicrostateRecord>(`/ligands/${ligandId}/states/select-microstate`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request),
    }),
  minimizeLigand: (ligandId: string, request: MinimizeLigandRequest): Promise<LigandConformerRecord> =>
    requestJson<LigandConformerRecord>(`/ligands/${ligandId}/conformers/minimize`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request),
    }),
  generateLigandConformer: (ligandId: string, request: GenerateLigandConformerRequest): Promise<LigandConformerRecord> =>
    requestJson<LigandConformerRecord>(`/ligands/${ligandId}/conformers/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request),
    }),
  prepareLigandPdbqt: (
    ligandId: string,
    conformerId: string,
    request: PrepareLigandPdbqtRequest,
  ): Promise<LigandPdbqtRecord> =>
    requestJson<LigandPdbqtRecord>(`/ligands/${ligandId}/conformers/${conformerId}/pdbqt`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request),
    }),
  getLigandConformer: (ligandId: string, conformerId: string): Promise<LigandConformerRecord> =>
    getJson<LigandConformerRecord>(`/ligands/${ligandId}/conformers/${conformerId}`),
  getLigandPdbqt: (ligandId: string, preparationId: string): Promise<LigandPdbqtRecord> =>
    getJson<LigandPdbqtRecord>(`/ligands/${ligandId}/preparations/${preparationId}`),
  startVinaDocking: (request: VinaDockingRequest): Promise<VinaDockingJobRecord> =>
    requestJson<VinaDockingJobRecord>("/docking/vina/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request),
    }),
  getDockingJob: (jobId: string): Promise<VinaDockingJobRecord> =>
    getJson<VinaDockingJobRecord>(`/docking/jobs/${jobId}`),
  cancelDockingJob: (jobId: string): Promise<DockingCancelResponse> =>
    requestJson<DockingCancelResponse>(`/docking/jobs/${jobId}/cancel`, {
      method: "POST",
      headers: { Accept: "application/json" },
    }),
  startVinaDockingBatch: (request: VinaBatchDockingRequest): Promise<VinaBatchDockingRecord> =>
    requestJson<VinaBatchDockingRecord>("/docking/vina/batches", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request),
    }),
  getDockingBatch: (batchId: string): Promise<VinaBatchDockingRecord> =>
    getJson<VinaBatchDockingRecord>(`/docking/batches/${batchId}`),
  getDockingBatchProgress: (
    batchId: string,
    afterRevision: number,
  ): Promise<VinaBatchProgress> =>
    getJson<VinaBatchProgress>(
      `/docking/batches/${batchId}/progress?after_revision=${afterRevision}`,
    ),
  latestDockingBatch: (
    libraryId: string,
    receptorId: string,
    bindingSiteId: string,
  ): Promise<VinaBatchDockingRecord> => {
    const query = new URLSearchParams({
      library_id: libraryId,
      receptor_id: receptorId,
      binding_site_id: bindingSiteId,
    });
    return getJson<VinaBatchDockingRecord>(`/docking/batches/latest?${query}`);
  },
  cancelDockingBatch: (batchId: string): Promise<DockingBatchCancelResponse> =>
    requestJson<DockingBatchCancelResponse>(`/docking/batches/${batchId}/cancel`, {
      method: "POST",
      headers: { Accept: "application/json" },
    }),
  dockingPoseUrl: (contentUrl: string): string => `${API_BASE_URL}${contentUrl}`,

  latestAutoDock4Batch: (
    receptorId: string,
    bindingSiteId: string,
    filterRunId: string,
  ): Promise<AutoDock4BatchRecord> =>
    getJson<AutoDock4BatchRecord>(
      `/docking/autodock4/batches/latest?receptor_id=${encodeURIComponent(receptorId)}`
      + `&binding_site_id=${encodeURIComponent(bindingSiteId)}`
      + `&filter_run_id=${encodeURIComponent(filterRunId)}`,
    ),

  compareLatestDockingCampaigns: (
    receptorId: string,
    bindingSiteId: string,
    filterRunId: string,
    topN = 20,
  ): Promise<EngineComparison> =>
    getJson<EngineComparison>(
      `/docking/comparison/latest?receptor_id=${encodeURIComponent(receptorId)}`
      + `&binding_site_id=${encodeURIComponent(bindingSiteId)}`
      + `&filter_run_id=${encodeURIComponent(filterRunId)}`
      + `&top_n=${topN}`,
    ),

  compareDockingEngines: (
    vinaBatchId: string,
    autodock4BatchId: string,
    topN = 20,
  ): Promise<EngineComparison> =>
    getJson<EngineComparison>(
      `/docking/comparison?vina_batch_id=${encodeURIComponent(vinaBatchId)}`
      + `&autodock4_batch_id=${encodeURIComponent(autodock4BatchId)}`
      + `&top_n=${topN}`,
    ),

  startAutoGridJob: (request: AutoGridMapSetRequest): Promise<AutoGridMapJobRecord> =>
    requestJson<AutoGridMapJobRecord>("/autogrid/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request),
    }),

  getAutoGridJob: (jobId: string): Promise<AutoGridMapJobRecord> =>
    getJson<AutoGridMapJobRecord>(`/autogrid/jobs/${jobId}`),

  cancelAutoGridJob: (jobId: string): Promise<AutoGridJobCancelResponse> =>
    requestJson<AutoGridJobCancelResponse>(`/autogrid/jobs/${jobId}/cancel`, {
      method: "POST",
      headers: { Accept: "application/json" },
    }),

  getAutoGridMapSet: (mapSetId: string): Promise<AutoGridMapSetRecord> =>
    getJson<AutoGridMapSetRecord>(`/autogrid/map-sets/${mapSetId}`),

  startAutoDock4Docking: (
    request: AutoDock4DockingRequest,
  ): Promise<AutoDock4DockingJobRecord> =>
    requestJson<AutoDock4DockingJobRecord>("/docking/autodock4/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request),
    }),

  getAutoDock4Job: (jobId: string): Promise<AutoDock4DockingJobRecord> =>
    getJson<AutoDock4DockingJobRecord>(`/docking/autodock4/jobs/${jobId}`),

  cancelAutoDock4Job: (jobId: string): Promise<AutoDock4CancelResponse> =>
    requestJson<AutoDock4CancelResponse>(`/docking/autodock4/jobs/${jobId}/cancel`, {
      method: "POST",
      headers: { Accept: "application/json" },
    }),

  startAutoDock4Batch: (request: AutoDock4BatchRequest): Promise<AutoDock4BatchRecord> =>
    requestJson<AutoDock4BatchRecord>("/docking/autodock4/batches", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request),
    }),

  startAutoDockGpuJob: (
    request: AutoDockGpuDockingRequest,
  ): Promise<AutoDockGpuDockingJobRecord> =>
    requestJson<AutoDockGpuDockingJobRecord>("/docking/autodock-gpu/jobs", {
      method: "POST",
      body: JSON.stringify(request),
    }),

  getAutoDockGpuJob: (jobId: string): Promise<AutoDockGpuDockingJobRecord> =>
    getJson<AutoDockGpuDockingJobRecord>(`/docking/autodock-gpu/jobs/${jobId}`),

  cancelAutoDockGpuJob: (jobId: string): Promise<{ job_id: string; status: string }> =>
    requestJson(`/docking/autodock-gpu/jobs/${jobId}/cancel`, { method: "POST" }),

  startAutoDockGpuBatch: (
    request: AutoDockGpuBatchRequest,
  ): Promise<AutoDockGpuBatchRecord> =>
    requestJson<AutoDockGpuBatchRecord>("/docking/autodock-gpu/batches", {
      method: "POST",
      body: JSON.stringify(request),
    }),

  getAutoDockGpuBatch: (batchId: string): Promise<AutoDockGpuBatchRecord> =>
    getJson<AutoDockGpuBatchRecord>(`/docking/autodock-gpu/batches/${batchId}`),

  getAutoDockGpuBatchProgress: (
    batchId: string,
  ): Promise<AutoDockGpuBatchProgress> =>
    getJson<AutoDockGpuBatchProgress>(
      `/docking/autodock-gpu/batches/${batchId}/progress`,
    ),

  cancelAutoDockGpuBatch: (
    batchId: string,
  ): Promise<{ job_id: string; status: string }> =>
    requestJson(`/docking/autodock-gpu/batches/${batchId}/cancel`, { method: "POST" }),

  latestAutoDockGpuBatch: (
    receptorId: string,
    bindingSiteId: string,
    filterRunId: string,
  ): Promise<AutoDockGpuBatchRecord> =>
    getJson<AutoDockGpuBatchRecord>(
      `/docking/autodock-gpu/batches/latest?receptor_id=${encodeURIComponent(receptorId)}`
      + `&binding_site_id=${encodeURIComponent(bindingSiteId)}`
      + `&filter_run_id=${encodeURIComponent(filterRunId)}`,
    ),

  autoDockGpuBatchPoseUrl: (contentUrl: string): string =>
    `${API_BASE_URL}${contentUrl}`,

  validateRedocking: (
    request: RedockingValidationRequest,
  ): Promise<RedockingRunRecord> =>
    requestJson<RedockingRunRecord>("/validation/redocking", {
      method: "POST",
      body: JSON.stringify(request),
    }),

  listRedockingValidations: (): Promise<RedockingRunRecord[]> =>
    getJson<RedockingRunRecord[]>("/validation/redocking"),

  getRedockingValidation: (validationId: string): Promise<RedockingRunRecord> =>
    getJson<RedockingRunRecord>(`/validation/redocking/${validationId}`),

  /**
   * Everything already exported, newest first.
   *
   * Every export recorded where it came from; until this existed none of them
   * could be listed, so a bundle was findable only by its identifier.
   */
  listExports: (
    query: { offset?: number; limit?: number; kind?: string } = {},
  ): Promise<ExportPage> => {
    const parameters = new URLSearchParams();
    if (query.offset !== undefined) parameters.set("offset", String(query.offset));
    if (query.limit !== undefined) parameters.set("limit", String(query.limit));
    if (query.kind) parameters.set("kind", query.kind);
    return getJson<ExportPage>(`/exports?${parameters.toString()}`);
  },

  /** An export file the project can serve; relative paths come from the API. */
  exportContentUrl: (contentUrl: string): string => `${API_BASE_URL}${contentUrl}`,

  exportCampaign: (
    sourceKind: string,
    sourceId: string,
    destination?: string | null,
  ): Promise<CampaignExport> => {
    const parameters = new URLSearchParams({
      source_kind: sourceKind,
      source_id: sourceId,
    });
    if (destination) parameters.set("destination", destination);
    return requestJson<CampaignExport>(
      `/exports/campaigns?${parameters.toString()}`,
      { method: "POST" },
    );
  },

  exportFileUrl: (exportId: string, filename: string): string =>
    `${API_BASE_URL}/exports/${exportId}/${filename}`,

  vinaCampaignHistory: (
    receptorId: string,
    bindingSiteId: string,
  ): Promise<CampaignHistory> =>
    getJson<CampaignHistory>(
      `/docking/batches/history?${campaignHistoryQuery(receptorId, bindingSiteId)}`,
    ),

  autoDock4CampaignHistory: (
    receptorId: string,
    bindingSiteId: string,
  ): Promise<CampaignHistory> =>
    getJson<CampaignHistory>(
      `/docking/autodock4/batches/history?${campaignHistoryQuery(receptorId, bindingSiteId)}`,
    ),

  getAutoDock4Batch: (batchId: string): Promise<AutoDock4BatchRecord> =>
    getJson<AutoDock4BatchRecord>(`/docking/autodock4/batches/${batchId}`),

  getAutoDock4BatchProgress: (
    batchId: string,
    afterRevision: number,
  ): Promise<AutoDock4BatchProgress> =>
    getJson<AutoDock4BatchProgress>(
      `/docking/autodock4/batches/${batchId}/progress?after_revision=${afterRevision}`,
    ),

  cancelAutoDock4Batch: (batchId: string): Promise<AutoDock4CancelResponse> =>
    requestJson<AutoDock4CancelResponse>(
      `/docking/autodock4/batches/${batchId}/cancel`,
      { method: "POST", headers: { Accept: "application/json" } },
    ),
  /**
   * Every durable result in the project, newest first and without any of them.
   *
   * Nothing here is ordered across engines: a Vina score and an AutoDock4
   * binding energy are different scales, so time is the only shared axis.
   */
  listResultCampaigns: (query: {
    offset?: number;
    limit?: number;
    mode?: string;
    scoringFamily?: string;
    receptorId?: string;
    bindingSiteId?: string;
    status?: string;
  } = {}): Promise<CatalogPage> => {
    const parameters = new URLSearchParams();
    if (query.offset !== undefined) parameters.set("offset", String(query.offset));
    if (query.limit !== undefined) parameters.set("limit", String(query.limit));
    if (query.mode) parameters.set("mode", query.mode);
    if (query.scoringFamily) parameters.set("scoring_family", query.scoringFamily);
    if (query.receptorId) parameters.set("receptor_id", query.receptorId);
    if (query.bindingSiteId) parameters.set("binding_site_id", query.bindingSiteId);
    if (query.status) parameters.set("status", query.status);
    return getJson<CatalogPage>(`/results/campaigns?${parameters.toString()}`);
  },

  getResultCampaign: (catalogId: string): Promise<CatalogEntry> =>
    getJson<CatalogEntry>(`/results/campaigns/${catalogPath(catalogId)}`),

  campaignMethods: (catalogId: string): Promise<MethodsReport> =>
    getJson<MethodsReport>(`/results/campaigns/${catalogPath(catalogId)}/methods`),

  trashResultCampaigns: (catalogIds: string[]): Promise<TrashResultCampaignsResponse> =>
    requestJson<TrashResultCampaignsResponse>("/results/campaigns/trash", {
      method: "POST",
      body: JSON.stringify({
        catalog_ids: catalogIds,
        acknowledge_removal: true,
      }),
    }),

  listResultCompounds: (
    catalogId: string,
    query: { offset?: number; limit?: number; status?: string; search?: string } = {},
  ): Promise<CompoundPage> => {
    const parameters = new URLSearchParams();
    if (query.offset !== undefined) parameters.set("offset", String(query.offset));
    if (query.limit !== undefined) parameters.set("limit", String(query.limit));
    if (query.status) parameters.set("status", query.status);
    if (query.search) parameters.set("search", query.search);
    return getJson<CompoundPage>(
      `/results/campaigns/${catalogPath(catalogId)}/compounds?${parameters.toString()}`,
    );
  },

  listResultPoses: (catalogId: string, ligandId: string): Promise<PoseInventory> =>
    getJson<PoseInventory>(
      `/results/campaigns/${catalogPath(catalogId)}/compounds/`
      + `${encodeURIComponent(ligandId)}/poses`,
    ),

  listPoseInteractionAnalyses: (
    catalogId: string,
    ligandId: string,
    poseArtifactId: string,
  ): Promise<InteractionAnalysisRecord[]> =>
    getJson<InteractionAnalysisRecord[]>(
      `/results/campaigns/${catalogPath(catalogId)}/compounds/`
      + `${encodeURIComponent(ligandId)}/poses/${encodeURIComponent(poseArtifactId)}/interactions`,
    ),

  analyzePoseInteractions: (
    catalogId: string,
    ligandId: string,
    poseArtifactId: string,
  ): Promise<InteractionAnalysisRecord> => requestJson<InteractionAnalysisRecord>(
    `/results/campaigns/${catalogPath(catalogId)}/compounds/`
    + `${encodeURIComponent(ligandId)}/poses/${encodeURIComponent(poseArtifactId)}/interactions`,
    { method: "POST", body: JSON.stringify({}) },
  ),

  exportPoseComplex: (
    catalogId: string,
    ligandId: string,
    poseArtifactId: string,
    request: PoseComplexExportRequest,
  ): Promise<PoseComplexExport> => requestJson<PoseComplexExport>(
    `/results/campaigns/${catalogPath(catalogId)}/compounds/`
    + `${encodeURIComponent(ligandId)}/poses/${encodeURIComponent(poseArtifactId)}`
    + "/complex/export",
    { method: "POST", body: JSON.stringify(request) },
  ),

  exportFigure: (request: FigureExportRequest): Promise<FigureExport> =>
    requestJson<FigureExport>("/results/figures", {
      method: "POST",
      body: JSON.stringify(request),
    }),

  figureFileUrl: (figureId: string, filename: string): string =>
    `${API_BASE_URL}/results/figures/${figureId}/${filename}`,

  resourceUsage: (): Promise<ResourceUsage> =>
    getJson<ResourceUsage>("/system/resources"),

  structureContentUrl: (record: StructureRecord): string => `${API_BASE_URL}${record.content_url}`,
  receptorOutputUrl: (contentUrl: string): string => `${API_BASE_URL}${contentUrl}`,
  ligandContentUrl: (contentUrl: string): string => `${API_BASE_URL}${contentUrl}`,
};
