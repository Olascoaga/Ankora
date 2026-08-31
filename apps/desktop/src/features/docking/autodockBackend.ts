import { ankoraApi } from "../../api/client";
import type {
  AutoDock4BatchParameters,
  AutoDock4BatchRecord,
  AutoDock4ClusterResult,
  AutoDock4DockingJobRecord,
  AutoDock4DockingParameters,
  AutoDock4JobPhase,
  AutoDock4JobStatus,
  AutoDock4RunResult,
  AutoDockBackend,
  AutoDockGpuBatchParameters,
  AutoDockGpuBatchRecord,
  AutoDockGpuDockingJobRecord,
  AutoDockGpuDockingParameters,
  AutoDockGpuLocalSearch,
  StructuredWarning,
} from "../../types/api";

/**
 * AutoDock4's two execution backends behind one interface.
 *
 * They are one engine, not two. Both run AutoDock4's semi-empirical force
 * field against the same AutoGrid maps and both produce the same cluster-native
 * result, so the screening workspace, its results table and its history are
 * shared. What genuinely differs is the search protocol and what has to be
 * recorded about the run, and only that is expressed per backend here.
 *
 * Measured differences that this file encodes rather than assumes:
 *
 * - The GPU is roughly twenty times faster on a real campaign, and its own
 *   adaptive defaults are faster again.
 * - The GPU is **not reproducible from its seed**. Repeating one seed six times
 *   gave six different rankings. The CPU repeated one seed and was
 *   bit-identical. So a GPU campaign always carries that statement.
 * - A GPU campaign is one process over a file list. Two concurrent processes on
 *   one device measured slower than one, so there is no parallelism setting.
 */

export interface CampaignEntryView {
  ligand_id: string;
  source_index: number;
  name: string;
  canonical_smiles: string | null;
  molecular_weight_g_mol: number | null;
  status: AutoDock4JobStatus;
  clusters: AutoDock4ClusterResult[];
  runs: AutoDock4RunResult[];
  failure: { code: string; message: string } | null;
}

export interface CampaignView {
  batch_id: string;
  backend: AutoDockBackend;
  status: AutoDock4JobStatus;
  revision: number;
  map_set_id: string;
  map_set_identity_key: string;
  engine: { name: string; version: string };
  /** Null on the CPU, where there is no device to name. */
  device_name: string | null;
  bitwise_reproducible: boolean;
  worker_count: number;
  selected_count: number;
  completed_count: number;
  succeeded_count: number;
  failed_count: number;
  canceled_count: number;
  entries: CampaignEntryView[];
  warnings: StructuredWarning[];
}

export interface CampaignInputs {
  receptorId: string;
  bindingSiteId: string;
  mapSetId: string;
  libraryId: string;
  filterRunId: string;
}

/** What a backend needs to be driven by the shared workspace. */
export interface AutoDockBackendBinding {
  backend: AutoDockBackend;
  label: string;
  /** One line stating what choosing this backend actually means. */
  summary: string;
  defaultParameters: () => BackendParameters;
  startBatch: (
    inputs: CampaignInputs,
    parameters: BackendParameters,
    acknowledged: boolean,
  ) => Promise<CampaignView>;
  getBatch: (batchId: string) => Promise<CampaignView>;
  /** Returns null when nothing changed since `afterRevision`. */
  getProgressRevision: (batchId: string, afterRevision: number) => Promise<number | null>;
  cancelBatch: (batchId: string) => Promise<void>;
  latestBatch: (inputs: CampaignInputs) => Promise<CampaignView>;
}

export type BackendParameters = AutoDock4BatchParameters | AutoDockGpuBatchParameters;

export function isGpuParameters(
  parameters: BackendParameters,
): parameters is AutoDockGpuBatchParameters {
  return "local_search_method" in parameters;
}

export function isCpuParameters(
  parameters: BackendParameters,
): parameters is AutoDock4BatchParameters {
  return "ga_generations" in parameters;
}

// --- CPU -------------------------------------------------------------------

function cpuDefaults(): AutoDock4BatchParameters {
  return {
    parallel_ligands: 15,
    ga_runs: 10,
    ga_population_size: 150,
    ga_energy_evaluations: 2_500_000,
    ga_generations: 27_000,
    cluster_rmsd_tolerance_angstrom: 2,
    seed_1: 20260824,
    seed_2: 20260824,
    timeout_minutes: 360,
  };
}

function fromCpuRecord(record: AutoDock4BatchRecord): CampaignView {
  return {
    batch_id: record.batch_id,
    backend: "autodock4_cpu",
    status: record.status,
    revision: record.revision,
    map_set_id: record.map_set_id,
    map_set_identity_key: record.map_set_identity_key,
    engine: record.autodock4.tool,
    device_name: null,
    // AutoDock4 on the CPU repeated one seed and produced bit-identical output.
    bitwise_reproducible: true,
    worker_count: record.worker_count,
    selected_count: record.selected_count,
    completed_count: record.completed_count,
    succeeded_count: record.succeeded_count,
    failed_count: record.failed_count,
    canceled_count: record.canceled_count,
    warnings: record.warnings,
    entries: record.entries.map((entry) => ({
      ligand_id: entry.ligand_id,
      source_index: entry.source_index,
      name: entry.name,
      canonical_smiles: entry.canonical_smiles,
      molecular_weight_g_mol: entry.molecular_weight_g_mol,
      status: entry.status,
      clusters: entry.clusters,
      runs: entry.runs,
      failure: entry.failure,
    })),
  };
}

export const cpuBinding: AutoDockBackendBinding = {
  backend: "autodock4_cpu",
  label: "CPU · AutoDock4 4.2.6",
  summary:
    "Slower, and exactly reproducible: repeating a seed gives bit-identical results.",
  defaultParameters: cpuDefaults,
  startBatch: async (inputs, parameters, acknowledged) =>
    fromCpuRecord(
      await ankoraApi.startAutoDock4Batch({
        receptor_id: inputs.receptorId,
        binding_site_id: inputs.bindingSiteId,
        map_set_id: inputs.mapSetId,
        library_id: inputs.libraryId,
        filter_run_id: inputs.filterRunId,
        parameters: parameters as AutoDock4BatchParameters,
        acknowledge_inputs_and_scoring: acknowledged,
      }),
    ),
  getBatch: async (batchId) => fromCpuRecord(await ankoraApi.getAutoDock4Batch(batchId)),
  getProgressRevision: async (batchId, afterRevision) => {
    const progress = await ankoraApi.getAutoDock4BatchProgress(batchId, afterRevision);
    return progress.revision === afterRevision ? null : progress.revision;
  },
  cancelBatch: async (batchId) => {
    await ankoraApi.cancelAutoDock4Batch(batchId);
  },
  latestBatch: async (inputs) =>
    fromCpuRecord(
      await ankoraApi.latestAutoDock4Batch(
        inputs.receptorId,
        inputs.bindingSiteId,
        inputs.filterRunId,
      ),
    ),
};

// --- GPU -------------------------------------------------------------------

function gpuDefaults(): AutoDockGpuBatchParameters {
  return {
    runs: 10,
    population_size: 150,
    energy_evaluations: 2_500_000,
    // A stated protocol rather than the tool's adaptive one, so the two
    // backends are at least asked for comparable effort.
    heuristics: false,
    autostop: false,
    local_search_method: "ad",
    cluster_rmsd_tolerance_angstrom: 2,
    seed_1: 20260826,
    seed_2: 20260826,
    seed_3: 20260826,
    device_number: 1,
    timeout_minutes: 60,
  };
}

function fromGpuRecord(record: AutoDockGpuBatchRecord): CampaignView {
  return {
    batch_id: record.batch_id,
    backend: record.backend,
    status: record.status,
    revision: record.revision,
    map_set_id: record.map_set_id,
    map_set_identity_key: record.map_set_identity_key,
    engine: record.autodock_gpu.tool,
    device_name: record.autodock_gpu.device_name,
    bitwise_reproducible: record.bitwise_reproducible,
    worker_count: record.worker_count,
    selected_count: record.selected_count,
    completed_count: record.completed_count,
    succeeded_count: record.succeeded_count,
    failed_count: record.failed_count,
    canceled_count: record.canceled_count,
    warnings: record.warnings,
    entries: record.entries.map((entry) => ({
      ligand_id: entry.ligand_id,
      source_index: entry.source_index,
      name: entry.name,
      canonical_smiles: entry.canonical_smiles,
      molecular_weight_g_mol: entry.molecular_weight_g_mol,
      status: entry.status,
      clusters: entry.clusters,
      runs: entry.runs,
      failure: entry.failure,
    })),
  };
}

export const gpuBinding: AutoDockBackendBinding = {
  backend: "autodock_gpu",
  label: "GPU · AutoDock-GPU 1.6",
  summary:
    "About twenty times faster, and not reproducible: repeating a seed gives "
    + "slightly different energies.",
  defaultParameters: gpuDefaults,
  startBatch: async (inputs, parameters, acknowledged) =>
    fromGpuRecord(
      await ankoraApi.startAutoDockGpuBatch({
        receptor_id: inputs.receptorId,
        binding_site_id: inputs.bindingSiteId,
        map_set_id: inputs.mapSetId,
        library_id: inputs.libraryId,
        filter_run_id: inputs.filterRunId,
        parameters: parameters as AutoDockGpuBatchParameters,
        acknowledge_inputs_and_scoring: acknowledged,
      }),
    ),
  getBatch: async (batchId) =>
    fromGpuRecord(await ankoraApi.getAutoDockGpuBatch(batchId)),
  getProgressRevision: async (batchId, afterRevision) => {
    const progress = await ankoraApi.getAutoDockGpuBatchProgress(batchId);
    return progress.revision === afterRevision ? null : progress.revision;
  },
  cancelBatch: async (batchId) => {
    await ankoraApi.cancelAutoDockGpuBatch(batchId);
  },
  latestBatch: async (inputs) =>
    fromGpuRecord(
      await ankoraApi.latestAutoDockGpuBatch(
        inputs.receptorId,
        inputs.bindingSiteId,
        inputs.filterRunId,
      ),
    ),
};

export const AUTODOCK_BACKENDS: AutoDockBackendBinding[] = [cpuBinding, gpuBinding];

export function bindingFor(backend: AutoDockBackend): AutoDockBackendBinding {
  return backend === "autodock_gpu" ? gpuBinding : cpuBinding;
}

// --- single-ligand jobs ----------------------------------------------------

/**
 * One molecule's job, normalised across backends.
 *
 * `protocol_summary` exists because the two backends state their search in
 * different words - independent runs and seeds on both, but ADADELTA against
 * Solis-Wets, and a heuristic the CPU does not have. The evidence panel shows
 * what was actually asked for rather than a shape that fits only one of them.
 */
export interface JobView {
  job_id: string;
  backend: AutoDockBackend;
  status: AutoDock4JobStatus;
  phase: AutoDock4JobPhase;
  map_set_identity_key: string;
  engine: { name: string; version: string };
  device_name: string | null;
  bitwise_reproducible: boolean;
  protocol_summary: string;
  command: string[];
  stdout: string;
  stderr: string;
  clusters: AutoDock4ClusterResult[];
  runs: AutoDock4RunResult[];
  warnings: StructuredWarning[];
  failure: { code: string; message: string } | null;
}

export interface JobInputs {
  receptorId: string;
  bindingSiteId: string;
  mapSetId: string;
  ligandId: string;
  ligandPreparationId: string;
}

export interface AutoDockJobBinding {
  backend: AutoDockBackend;
  defaultParameters: () => JobParameters;
  startJob: (
    inputs: JobInputs,
    parameters: JobParameters,
    acknowledged: boolean,
  ) => Promise<JobView>;
  getJob: (jobId: string) => Promise<JobView>;
  cancelJob: (jobId: string) => Promise<void>;
}

export type JobParameters = AutoDock4DockingParameters | AutoDockGpuDockingParameters;

export function isGpuJobParameters(
  parameters: JobParameters,
): parameters is AutoDockGpuDockingParameters {
  return "local_search_method" in parameters;
}

function fromCpuJob(record: AutoDock4DockingJobRecord): JobView {
  const p = record.request.parameters;
  return {
    job_id: record.job_id,
    backend: "autodock4_cpu",
    status: record.status,
    phase: record.phase,
    map_set_identity_key: record.map_set_identity_key,
    engine: record.autodock4.tool,
    device_name: null,
    bitwise_reproducible: true,
    protocol_summary:
      `${p.ga_runs} runs · ${p.ga_energy_evaluations.toLocaleString()} evals · `
      + `Solis-Wets · seeds ${p.seed_1}/${p.seed_2}`,
    command: record.command,
    stdout: record.execution?.stdout ?? "",
    stderr: record.execution?.stderr ?? "",
    clusters: record.clusters,
    runs: record.runs,
    warnings: record.warnings,
    failure: record.failure,
  };
}

function fromGpuJob(record: AutoDockGpuDockingJobRecord): JobView {
  const p = record.request.parameters;
  const budget = p.heuristics
    ? "heuristic evaluation count"
    : `${p.energy_evaluations.toLocaleString()} evals`;
  return {
    job_id: record.job_id,
    backend: record.backend,
    status: record.status,
    phase: record.phase,
    map_set_identity_key: record.map_set_identity_key,
    engine: record.autodock_gpu.tool,
    device_name: record.autodock_gpu.device_name,
    bitwise_reproducible: record.bitwise_reproducible,
    protocol_summary:
      `${p.runs} runs · ${budget} · ${LOCAL_SEARCH_LABEL[p.local_search_method]}`
      + `${p.autostop ? " · auto-stop" : ""} · seeds `
      + `${p.seed_1}/${p.seed_2}/${p.seed_3}`,
    command: record.command,
    stdout: record.execution?.stdout ?? "",
    stderr: record.execution?.stderr ?? "",
    clusters: record.clusters,
    runs: record.runs,
    warnings: record.warnings,
    failure: record.failure,
  };
}

export const LOCAL_SEARCH_LABEL: Record<AutoDockGpuLocalSearch, string> = {
  ad: "ADADELTA",
  sw: "Solis-Wets",
  fire: "FIRE",
};

export const cpuJobBinding: AutoDockJobBinding = {
  backend: "autodock4_cpu",
  defaultParameters: () => ({
    ga_runs: 10,
    ga_population_size: 150,
    ga_energy_evaluations: 2_500_000,
    ga_generations: 27_000,
    cluster_rmsd_tolerance_angstrom: 2,
    seed_1: 20260824,
    seed_2: 20260824,
    timeout_minutes: 360,
  }),
  startJob: async (inputs, parameters, acknowledged) =>
    fromCpuJob(
      await ankoraApi.startAutoDock4Docking({
        receptor_id: inputs.receptorId,
        binding_site_id: inputs.bindingSiteId,
        map_set_id: inputs.mapSetId,
        ligand_id: inputs.ligandId,
        ligand_preparation_id: inputs.ligandPreparationId,
        parameters: parameters as AutoDock4DockingParameters,
        acknowledge_inputs_and_scoring: acknowledged,
      }),
    ),
  getJob: async (jobId) => fromCpuJob(await ankoraApi.getAutoDock4Job(jobId)),
  cancelJob: async (jobId) => {
    await ankoraApi.cancelAutoDock4Job(jobId);
  },
};

export const gpuJobBinding: AutoDockJobBinding = {
  backend: "autodock_gpu",
  defaultParameters: () => ({
    runs: 10,
    population_size: 150,
    energy_evaluations: 2_500_000,
    heuristics: false,
    autostop: false,
    local_search_method: "ad",
    cluster_rmsd_tolerance_angstrom: 2,
    seed_1: 20260826,
    seed_2: 20260826,
    seed_3: 20260826,
    device_number: 1,
    timeout_minutes: 60,
  }),
  startJob: async (inputs, parameters, acknowledged) =>
    fromGpuJob(
      await ankoraApi.startAutoDockGpuJob({
        receptor_id: inputs.receptorId,
        binding_site_id: inputs.bindingSiteId,
        map_set_id: inputs.mapSetId,
        ligand_id: inputs.ligandId,
        ligand_preparation_id: inputs.ligandPreparationId,
        parameters: parameters as AutoDockGpuDockingParameters,
        acknowledge_inputs_and_scoring: acknowledged,
      }),
    ),
  getJob: async (jobId) => fromGpuJob(await ankoraApi.getAutoDockGpuJob(jobId)),
  cancelJob: async (jobId) => {
    await ankoraApi.cancelAutoDockGpuJob(jobId);
  },
};

export function jobBindingFor(backend: AutoDockBackend): AutoDockJobBinding {
  return backend === "autodock_gpu" ? gpuJobBinding : cpuJobBinding;
}
