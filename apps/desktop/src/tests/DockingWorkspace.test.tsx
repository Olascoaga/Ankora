import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { DockingWorkspace } from "../features/docking/DockingWorkspace";
import type {
  BindingSiteRecord,
  GninaDockingJobRecord,
  GninaScreeningCampaignRecord,
  GninaScreeningEntry,
  LigandDockingInput,
  LigandLibraryDockingInput,
  LigandRecord,
  ReceptorPreparationRecord,
  ToolsResponse,
  VinaBatchDockingRecord,
  VinaBatchProgress,
  VinaDockingJobRecord,
} from "../types/api";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const provenance = {
  event_id: "synthetic-event", event_type: "synthetic_fixture", timestamp: "2026-08-23T00:00:00Z",
  input_artifacts: [], output_artifacts: [], tool: { name: "synthetic", version: "1" },
  parameters: {}, warnings: [], command: null,
};

const receptor = {
  receptor_id: "receptor-synthetic", source_artifact_id: "source-synthetic", created_at: "2026-08-23T00:00:00Z", status: "docking_ready",
  decisions: {
    selected_chains: ["A"], water_action: "remove", component_decisions: [], issue_decisions: [], reference_component_id: null,
    relaxation: { enabled: false, restraint_force_constant_kcal_mol_a2: 50, max_iterations: 200 },
    protonation: { enabled: true, ph: 7.4, force_field: "AMBER" }, generate_pdbqt: true,
  },
  outputs: [
    { artifact_id: "display-pdb", stage: "protonated_pdb", filename: "receptor.pdb", format: "pdb", sha256: "a".repeat(64), size_bytes: 100, created_at: "2026-08-23T00:00:00Z", content_url: "/receptor.pdb" },
    { artifact_id: "receptor-pdbqt", stage: "pdbqt", filename: "receptor.pdbqt", format: "pdbqt", sha256: "b".repeat(64), size_bytes: 120, created_at: "2026-08-23T00:00:00Z", content_url: "/receptor.pdbqt" },
  ],
  warnings: [], provenance: [], display_output_artifact_id: "display-pdb",
} satisfies ReceptorPreparationRecord;

const bindingSite = {
  binding_site_id: "binding-synthetic", receptor_id: receptor.receptor_id, source_artifact_id: "display-pdb", created_at: "2026-08-23T00:00:00Z",
  decisions: { source: "manual", ligand_origin: null, residue_selection: null, manual_box: { center_x: 1, center_y: 2, center_z: 3, size_x: 20, size_y: 22, size_z: 24 }, blind_margin_angstrom: 6, pocket_selection: null, parent_binding_site_id: null },
  box: { center_x: 1, center_y: 2, center_z: 3, size_x: 20, size_y: 22, size_z: 24 }, stale: false, warnings: [], provenance: [],
} satisfies BindingSiteRecord;

const ligand = {
  artifact: { ligand_id: "ligand-synthetic", source: "local", source_structure_id: null, locator: null, filename: "ligand.sdf", format: "sdf", sha256: "c".repeat(64), size_bytes: 80, created_at: "2026-08-23T00:00:00Z", library_id: null, library_record_index: null },
  state: null,
  inspection: { name: "Synthetic ligand", formula: "C2H6", molecular_weight_g_mol: 30.07, exact_mass_da: 30.047, formal_charge: 0, atom_count: 8, heavy_atom_count: 2, rotatable_bond_count: 0, aromatic_ring_count: 0, stereocenter_count: 0, undefined_stereocenter_count: 0, fragment_count: 1, conformer_count: 1, has_3d_coordinates: true, canonical_smiles: "CC" },
  warnings: [], provenance, content_url: "/ligand.sdf", original_content_url: null,
} satisfies LigandRecord;

const ligandInput = {
  ligand_id: ligand.artifact.ligand_id,
  conformer: null,
  pdbqt: {
    artifact: { preparation_id: "preparation-synthetic", ligand_id: ligand.artifact.ligand_id, conformer_id: "conformer-synthetic", filename: "ligand.pdbqt", format: "pdbqt", sha256: "d".repeat(64), size_bytes: 90, created_at: "2026-08-23T00:00:00Z" },
    charge_model: "gasteiger", tool: { name: "Meeko", version: "0.7.1" }, command: ["synthetic"], stdout: "", stderr: "", provenance, content_url: "/ligand.pdbqt",
  },
} satisfies LigandDockingInput;

const libraryInput = {
  library_id: "library-synthetic",
  library_name: "synthetic-library.sdf",
  filter_run_id: "filter-synthetic",
  selection_manifest_sha256: "f".repeat(64),
  selected_count: 2,
  prepared_count: 2,
} satisfies LigandLibraryDockingInput;

const tools = {
  vina: { available: true, path: "tools/vina_1.2.7_win.exe", version: "1.2.7" }, gnina: { available: false, path: null, version: null },
  autogrid4: { available: false, path: null, version: null }, autodock4: { available: false, path: null, version: null },
  autodock_gpu: { available: false, path: null, version: null },
  pdbfixer: { available: true, path: "synthetic", version: "1" }, pdb2pqr: { available: true, path: "synthetic", version: "1" },
  propka: { available: true, path: "synthetic", version: "1" }, meeko: { available: true, path: "synthetic", version: "1" },
  meeko_ligand: { available: true, path: "synthetic", version: "1" }, p2rank: { available: true, path: "synthetic", version: "1" },
} satisfies ToolsResponse;

const gninaTools: ToolsResponse = { ...tools, gnina: { available: true, path: "synthetic-gnina", version: null } };
const gninaParameters = { compute: "cuda", device_index: 0, cpu_threads: 2, seed: 20261029, exhaustiveness: 8, num_modes: 9, min_rmsd_filter_angstrom: 1, timeout_minutes: 360, cnn_scoring: "rescore", cnn_model: "dense_1_3", hydrogen_handling: "prepared_pdbqt_no_add_no_strip", pose_sort_order: "cnn_score_descending" } as const;

function screeningEntry(id: string, index: number): GninaScreeningEntry {
  return { ligand_id: id, chemical_state_id: `state-${id}`, source_index: index, name: `Molecule ${index + 1}`,
    ligand_preparation_id: `prep-${id}`, ligand_sha256: "d".repeat(64), conformer_id: `conformer-${id}`,
    conformer_sha256: "c".repeat(64), status: "queued", phase: "queued", gnina_job_id: null,
    started_at: null, completed_at: null, failure: null, revision: 0 };
}

function screeningCampaign(): GninaScreeningCampaignRecord {
  return { campaign_id: "campaign-synthetic", engine: "gnina", status: "queued", phase: "queued",
    created_at: "2026-11-06T00:00:00Z", started_at: null, completed_at: null,
    request: { receptor_id: receptor.receptor_id, binding_site_id: bindingSite.binding_site_id,
      library_id: libraryInput.library_id, filter_run_id: libraryInput.filter_run_id,
      parameters: { ...gninaParameters, compute: "cpu" }, acknowledge_inputs_and_scoring: true },
    tool: { version: "1.3.3", sha256: "a".repeat(64), architecture: "x86_64" },
    selection: { library_id: libraryInput.library_id, filter_run_id: libraryInput.filter_run_id,
      manifest_artifact_id: libraryInput.filter_run_id, manifest_sha256: libraryInput.selection_manifest_sha256 },
    receptor_output_artifact_id: "receptor-pdbqt", receptor_sha256: "b".repeat(64), box: bindingSite.box,
    worker_count: 1, selected_count: 2, completed_count: 0, succeeded_count: 0, failed_count: 0, canceled_count: 0,
    entries: [screeningEntry(ligand.artifact.ligand_id, 0), screeningEntry("ligand-second", 1)],
    warnings: [], failure: null, provenance: null, revision: 0 };
}
function gninaJob(status: GninaDockingJobRecord["status"]): GninaDockingJobRecord {
  const completed = status === "completed";
  return {
    job_id: "gnina-synthetic", engine: "gnina", status, phase: completed ? "complete" : "docking", created_at: "2026-08-23T00:00:00Z", started_at: null, completed_at: null,
    request: { receptor_id: receptor.receptor_id, binding_site_id: bindingSite.binding_site_id, ligand_id: ligand.artifact.ligand_id, ligand_preparation_id: "preparation-synthetic", parameters: gninaParameters, acknowledge_inputs_and_scoring: true },
    tool: { version: "1.3.3", sha256: "a".repeat(64), architecture: "x86_64" }, box: bindingSite.box,
    receptor_output_artifact_id: "receptor-pdbqt", receptor_sha256: "b".repeat(64), ligand_sha256: "d".repeat(64), conformer_sha256: "c".repeat(64), command: ["gnina", "--cnn", "dense_1_3"],
    execution: completed ? { command: ["gnina"], exit_code: 0, stdout: "synthetic", stderr: "", timed_out: false, canceled: false, gpu_process_observed: true, gpu_observation: "synthetic", requested_gpu_uuid: "GPU-synthetic", observed_gpu_uuid: "GPU-synthetic" } : null,
    poses: completed ? [
      { mode: 1, cnn_score: 0.9, cnn_affinity: 6, minimized_affinity_kcal_mol: -4, artifact: { artifact_id: "pose-1", mode: 1, filename: "pose_1.pdbqt", sha256: "e".repeat(64), size_bytes: 100 } },
      { mode: 2, cnn_score: 0.7, cnn_affinity: 7, minimized_affinity_kcal_mol: -9, artifact: { artifact_id: "pose-2", mode: 2, filename: "pose_2.pdbqt", sha256: "f".repeat(64), size_bytes: 100 } },
    ] : [], failure: null,
  };
}

it("offers GNINA only on Linux", () => {
  const { rerender } = render(<DockingWorkspace receptor={receptor} bindingSite={bindingSite} ligand={ligand} ligandInput={ligandInput} tools={gninaTools} platform="windows" />);
  expect(screen.queryByRole("button", { name: "GNINA · single" })).not.toBeInTheDocument();
  rerender(<DockingWorkspace receptor={receptor} bindingSite={bindingSite} ligand={ligand} ligandInput={ligandInput} tools={gninaTools} platform="linux" />);
  expect(screen.getByRole("button", { name: "GNINA · single" })).toBeInTheDocument();
});

it("updates GNINA screening progress and automatically reads each completed job", async () => {
  window.localStorage.clear();
  const initial = screeningCampaign();
  const first = { ...initial.entries[0], status: "completed", phase: "complete", gnina_job_id: "gnina-synthetic", revision: 2 };
  const second = { ...initial.entries[1], status: "failed", phase: "complete", revision: 3,
    failure: { code: "SYNTHETIC_FAILURE", message: "synthetic preflight failure", details: {} } };
  const progress = { campaign_id: initial.campaign_id, engine: "gnina", status: "completed", phase: "complete", revision: 4,
    started_at: "2026-11-06T00:00:01Z", completed_at: "2026-11-06T00:01:00Z", selected_count: 2,
    completed_count: 2, succeeded_count: 1, failed_count: 1, canceled_count: 0 };
  let submitted: Record<string, unknown> | null = null;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (path.endsWith("/docking/gnina/screenings") && init?.method === "POST") { submitted = JSON.parse(String(init.body)); return json(initial, 202); }
    if (path.endsWith("/docking/gnina/screenings")) return json([]);
    if (path.endsWith("/progress")) return json(progress);
    if (path.includes("/entries?after_revision=")) return json([first, second]);
    if (path.endsWith("/docking/gnina/jobs/gnina-synthetic")) return json({ ...gninaJob("completed"), screening_campaign_id: initial.campaign_id });
    return new Response("", { status: 200 });
  });
  render(<DockingWorkspace receptor={receptor} bindingSite={bindingSite} ligand={ligand} ligandInput={ligandInput} libraryInput={libraryInput} tools={gninaTools} platform="linux" />);
  fireEvent.click(screen.getByRole("button", { name: "GNINA · screening" }));
  fireEvent.click(screen.getByText("Dock this exact applied selection with GNINA"));
  await waitFor(() => expect(screen.getByRole("button", { name: "Dock 2 prepared molecules" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Dock 2 prepared molecules" }));
  expect(await screen.findByText("0.9000", {}, { timeout: 4000 })).toBeInTheDocument();
  expect(submitted).toMatchObject({ library_id: libraryInput.library_id, filter_run_id: libraryInput.filter_run_id,
    acknowledge_inputs_and_scoring: true, parameters: { pose_sort_order: "cnn_score_descending" } });
  expect(screen.getByText("SYNTHETIC_FAILURE")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Molecule 1/ }));
  expect(await screen.findByRole("button", { name: "Pose 1" })).toBeInTheDocument();
  window.localStorage.clear();
});

it("loads terminal entry changes returned with screening cancellation", async () => {
  window.localStorage.clear();
  const initial = screeningCampaign();
  const canceled = initial.entries.map((entry, index) => ({ ...entry, status: "canceled", phase: "complete", revision: index + 2 }));
  const progress = { campaign_id: initial.campaign_id, engine: "gnina", status: "canceled", phase: "complete", revision: 4,
    started_at: null, completed_at: "2026-11-06T00:01:00Z", selected_count: 2,
    completed_count: 2, succeeded_count: 0, failed_count: 0, canceled_count: 2 };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (path.endsWith("/docking/gnina/screenings") && init?.method === "POST") return json(initial, 202);
    if (path.endsWith("/docking/gnina/screenings")) return json([]);
    if (path.endsWith("/cancel")) return json(progress);
    if (path.includes("/entries?after_revision=")) return json(canceled);
    return new Response("", { status: 200 });
  });
  render(<DockingWorkspace receptor={receptor} bindingSite={bindingSite} ligand={ligand} ligandInput={ligandInput} libraryInput={libraryInput} tools={gninaTools} platform="linux" />);
  fireEvent.click(screen.getByRole("button", { name: "GNINA · screening" }));
  fireEvent.click(screen.getByText("Dock this exact applied selection with GNINA"));
  await waitFor(() => expect(screen.getByRole("button", { name: "Dock 2 prepared molecules" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Dock 2 prepared molecules" }));
  fireEvent.click(await screen.findByRole("button", { name: "Cancel campaign" }));
  await waitFor(() => expect(screen.getByLabelText("GNINA campaign progress")).toHaveAttribute("aria-valuenow", "2"));
  expect(screen.getAllByText("canceled").length).toBeGreaterThanOrEqual(2);
  window.localStorage.clear();
});

it("refreshes a job opened while running when its molecule completes", async () => {
  window.localStorage.clear();
  const initial = screeningCampaign();
  initial.entries[0] = { ...initial.entries[0], status: "running", phase: "docking", gnina_job_id: "gnina-synthetic" };
  initial.status = "running"; initial.phase = "docking";
  let finished = false;
  let jobReads = 0;
  const progress = { campaign_id: initial.campaign_id, engine: "gnina", status: "completed", phase: "complete", revision: 3,
    started_at: "2026-11-06T00:00:01Z", completed_at: "2026-11-06T00:01:00Z", selected_count: 2,
    completed_count: 2, succeeded_count: 1, failed_count: 1, canceled_count: 0 };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (path.endsWith("/docking/gnina/screenings") && init?.method === "POST") return json(initial, 202);
    if (path.endsWith("/docking/gnina/screenings")) return json([]);
    if (path.endsWith("/progress")) return json(finished ? progress : { ...progress, status: "running", phase: "docking", revision: 0, completed_count: 0, succeeded_count: 0, failed_count: 0, completed_at: null });
    if (path.includes("/entries?after_revision=")) return json([
      { ...initial.entries[0], status: "completed", phase: "complete", revision: 1 },
      { ...initial.entries[1], status: "failed", phase: "complete", revision: 2, failure: { code: "FAIL", message: "synthetic", details: {} } },
    ]);
    if (path.endsWith("/docking/gnina/jobs/gnina-synthetic")) {
      jobReads += 1;
      return json({ ...gninaJob(finished ? "completed" : "running"), screening_campaign_id: initial.campaign_id });
    }
    return new Response("", { status: 200 });
  });
  render(<DockingWorkspace receptor={receptor} bindingSite={bindingSite} ligand={ligand} ligandInput={ligandInput} libraryInput={libraryInput} tools={gninaTools} platform="linux" />);
  fireEvent.click(screen.getByRole("button", { name: "GNINA · screening" }));
  fireEvent.click(screen.getByText("Dock this exact applied selection with GNINA"));
  await waitFor(() => expect(screen.getByRole("button", { name: "Dock 2 prepared molecules" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Dock 2 prepared molecules" }));
  fireEvent.click(await screen.findByRole("button", { name: /Molecule 1/ }));
  await waitFor(() => expect(jobReads).toBe(1));
  finished = true;
  expect((await screen.findAllByText("0.9000", {}, { timeout: 4000 })).length).toBeGreaterThan(0);
  expect(jobReads).toBeGreaterThanOrEqual(2);
  window.localStorage.clear();
});

it("reopens a recorded GNINA screening from the active project", async () => {
  window.localStorage.clear();
  const saved = screeningCampaign();
  const summary = { campaign_id: saved.campaign_id, engine: "gnina", status: "failed", phase: "complete", revision: 1,
    started_at: null, completed_at: "2026-11-06T00:01:00Z", selected_count: 2,
    completed_count: 2, succeeded_count: 0, failed_count: 2, canceled_count: 0 };
  saved.status = "failed"; saved.phase = "complete"; saved.revision = 1;
  saved.completed_count = 2; saved.failed_count = 2; saved.completed_at = summary.completed_at;
  saved.entries = saved.entries.map((entry) => ({ ...entry, status: "failed", phase: "complete", failure: { code: "SYNTHETIC", message: "synthetic", details: {} } }));
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = String(input);
    if (path.endsWith("/docking/gnina/screenings")) return json([summary]);
    if (path.endsWith(`/docking/gnina/screenings/${saved.campaign_id}`)) return json(saved);
    return new Response("", { status: 200 });
  });
  render(<DockingWorkspace receptor={receptor} bindingSite={bindingSite} ligand={ligand} ligandInput={ligandInput} libraryInput={libraryInput} tools={gninaTools} platform="linux" />);
  fireEvent.click(screen.getByRole("button", { name: "GNINA · screening" }));
  fireEvent.click(await screen.findByRole("button", { name: /campaign · failed · 2\/2/i }));
  expect(await screen.findByRole("region", { name: "GNINA campaign results" })).toBeInTheDocument();
  expect(screen.getByLabelText("GNINA campaign progress")).toHaveAttribute("aria-valuenow", "2");
  window.localStorage.clear();
});

it("rejects a progress update that invents a molecule outside the selection", async () => {
  window.localStorage.clear();
  const initial = screeningCampaign();
  const progress = { campaign_id: initial.campaign_id, engine: "gnina", status: "running", phase: "docking", revision: 1,
    started_at: "2026-11-06T00:00:01Z", completed_at: null, selected_count: 2,
    completed_count: 0, succeeded_count: 0, failed_count: 0, canceled_count: 0 };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (path.endsWith("/docking/gnina/screenings") && init?.method === "POST") return json(initial, 202);
    if (path.endsWith("/docking/gnina/screenings")) return json([]);
    if (path.endsWith("/progress")) return json(progress);
    if (path.includes("/entries?after_revision=")) return json([screeningEntry("unexpected", 5)]);
    return new Response("", { status: 200 });
  });
  render(<DockingWorkspace receptor={receptor} bindingSite={bindingSite} ligand={ligand} ligandInput={ligandInput} libraryInput={libraryInput} tools={gninaTools} platform="linux" />);
  fireEvent.click(screen.getByRole("button", { name: "GNINA · screening" }));
  fireEvent.click(screen.getByText("Dock this exact applied selection with GNINA"));
  await waitFor(() => expect(screen.getByRole("button", { name: "Dock 2 prepared molecules" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Dock 2 prepared molecules" }));
  expect(await screen.findByText("The GNINA campaign returned an inconsistent selection update.", {}, { timeout: 4000 })).toBeInTheDocument();
  expect(screen.queryByText("Molecule 6")).not.toBeInTheDocument();
  window.localStorage.clear();
});

it("does not roll completed progress back when a delayed cancel response arrives", async () => {
  window.localStorage.clear();
  const initial = screeningCampaign();
  let finishCancel!: (response: Response) => void;
  const pendingCancel = new Promise<Response>((resolve) => { finishCancel = resolve; });
  const progress = { campaign_id: initial.campaign_id, engine: "gnina", status: "completed", phase: "complete", revision: 4,
    started_at: "2026-11-06T00:00:01Z", completed_at: "2026-11-06T00:01:00Z", selected_count: 2,
    completed_count: 2, succeeded_count: 1, failed_count: 1, canceled_count: 0 };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (path.endsWith("/docking/gnina/screenings") && init?.method === "POST") return json(initial, 202);
    if (path.endsWith("/docking/gnina/screenings")) return json([]);
    if (path.endsWith("/cancel")) return pendingCancel;
    if (path.endsWith("/progress")) return json(progress);
    if (path.includes("/entries?after_revision=")) return json([
      { ...initial.entries[0], status: "completed", phase: "complete", gnina_job_id: "gnina-synthetic", revision: 2 },
      { ...initial.entries[1], status: "failed", phase: "complete", revision: 3, failure: { code: "FAIL", message: "synthetic", details: {} } },
    ]);
    if (path.endsWith("/docking/gnina/jobs/gnina-synthetic")) return json({ ...gninaJob("completed"), screening_campaign_id: initial.campaign_id });
    return new Response("", { status: 200 });
  });
  render(<DockingWorkspace receptor={receptor} bindingSite={bindingSite} ligand={ligand} ligandInput={ligandInput} libraryInput={libraryInput} tools={gninaTools} platform="linux" />);
  fireEvent.click(screen.getByRole("button", { name: "GNINA · screening" }));
  fireEvent.click(screen.getByText("Dock this exact applied selection with GNINA"));
  await waitFor(() => expect(screen.getByRole("button", { name: "Dock 2 prepared molecules" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Dock 2 prepared molecules" }));
  fireEvent.click(await screen.findByRole("button", { name: "Cancel campaign" }));
  await waitFor(() => expect(screen.getByLabelText("GNINA campaign progress")).toHaveAttribute("aria-valuenow", "2"), { timeout: 4000 });
  await act(async () => { finishCancel(json({ ...progress, status: "cancel_requested", phase: "docking", revision: 1, completed_count: 0, succeeded_count: 0, failed_count: 0, completed_at: null })); });
  expect(screen.getByLabelText("GNINA campaign progress")).toHaveAttribute("aria-valuenow", "2");
  expect(screen.queryByRole("button", { name: "Cancel campaign" })).not.toBeInTheDocument();
  window.localStorage.clear();
});

it("runs CUDA GNINA with explicit settings and preserves CNN pose order", async () => {
  window.localStorage.clear();
  let submitted: Record<string, unknown> | null = null;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (path.endsWith("/docking/gnina/jobs")) { submitted = JSON.parse(String(init?.body)); return json(gninaJob("running"), 202); }
    if (path.endsWith("/docking/gnina/jobs/gnina-synthetic")) return json(gninaJob("completed"));
    return new Response("", { status: 200 });
  });
  render(<DockingWorkspace receptor={receptor} bindingSite={bindingSite} ligand={ligand} ligandInput={ligandInput} tools={gninaTools} platform="linux" />);
  fireEvent.click(screen.getByRole("button", { name: "GNINA · single" }));
  fireEvent.change(screen.getByLabelText("Compute"), { target: { value: "cuda" } });
  expect(screen.getByText(/requires one identifiable NVIDIA GPU/)).toBeInTheDocument();
  fireEvent.click(screen.getByText("Use these exact inputs and parameters"));
  await waitFor(() => expect(screen.getByRole("button", { name: "Run GNINA" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Run GNINA" }));
  const pose2 = await screen.findByRole("button", { name: "Pose 2" }, { timeout: 3000 });
  expect(submitted).toMatchObject({ parameters: { compute: "cuda", cnn_model: "dense_1_3", cnn_scoring: "rescore", pose_sort_order: "cnn_score_descending" }, acknowledge_inputs_and_scoring: true });
  const rows = within(screen.getByRole("table")).getAllByRole("row");
  expect(within(rows[1]).getByText("-4.000")).toBeInTheDocument();
  expect(within(rows[2]).getByText("-9.000")).toBeInTheDocument();
  fireEvent.click(pose2);
  expect(pose2).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText(/Neither is measured affinity/)).toBeInTheDocument();
  expect(screen.getByText("CNN affinity (pK)")).toBeInTheDocument();
  window.localStorage.clear();
});

it("restores the last matching GNINA job when returning to the workspace", async () => {
  window.localStorage.clear();
  const key = `ankora:gnina:${receptor.receptor_id}:${bindingSite.binding_site_id}:${ligand.artifact.ligand_id}:preparation-synthetic`;
  window.localStorage.setItem(key, "gnina-synthetic");
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => String(input).endsWith("/docking/gnina/jobs/gnina-synthetic") ? json(gninaJob("completed")) : new Response("", { status: 200 }));
  render(<DockingWorkspace receptor={receptor} bindingSite={bindingSite} ligand={ligand} ligandInput={ligandInput} tools={gninaTools} platform="linux" />);
  fireEvent.click(screen.getByRole("button", { name: "GNINA · single" }));
  expect(await screen.findByRole("button", { name: "Pose 1" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByLabelText("Compute")).toHaveValue("cuda");
  window.localStorage.clear();
});

it("blocks unavailable GNINA and invalid parameters, and requests cancellation", async () => {
  window.localStorage.clear();
  const paths: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input); paths.push(`${init?.method ?? "GET"} ${path}`);
    if (path.endsWith("/docking/gnina/jobs")) return json(gninaJob("running"), 202);
    if (path.endsWith("/cancel")) return json({ job_id: "gnina-synthetic", status: "cancel_requested" });
    if (path.endsWith("/docking/gnina/jobs/gnina-synthetic")) return json(gninaJob("running"));
    return new Response("", { status: 200 });
  });
  const view = render(<DockingWorkspace receptor={receptor} bindingSite={bindingSite} ligand={ligand} ligandInput={ligandInput} tools={tools} platform="linux" />);
  fireEvent.click(screen.getByRole("button", { name: "GNINA · single" }));
  fireEvent.click(screen.getByText("Use these exact inputs and parameters"));
  expect(screen.getByRole("button", { name: "Run GNINA" })).toBeDisabled();
  view.rerender(<DockingWorkspace receptor={receptor} bindingSite={bindingSite} ligand={ligand} ligandInput={ligandInput} tools={gninaTools} platform="linux" />);
  fireEvent.change(screen.getByLabelText("Exhaustiveness"), { target: { value: "" } });
  expect(screen.getByLabelText("Exhaustiveness")).toHaveValue(null);
  fireEvent.change(screen.getByLabelText("Exhaustiveness"), { target: { value: "0" } });
  fireEvent.click(screen.getByText("Use these exact inputs and parameters"));
  expect(screen.getByRole("button", { name: "Run GNINA" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Exhaustiveness"), { target: { value: "8" } });
  fireEvent.click(screen.getByText("Use these exact inputs and parameters"));
  await waitFor(() => expect(screen.getByRole("button", { name: "Run GNINA" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Run GNINA" }));
  fireEvent.click(await screen.findByRole("button", { name: "Cancel docking" }));
  await waitFor(() => expect(paths).toContain("POST http://127.0.0.1:8765/api/v1/docking/gnina/jobs/gnina-synthetic/cancel"));
  window.localStorage.clear();
});

it("does not cancel the previous result while a new GNINA launch is pending", async () => {
  window.localStorage.clear();
  const key = `ankora:gnina:${receptor.receptor_id}:${bindingSite.binding_site_id}:${ligand.artifact.ligand_id}:preparation-synthetic`;
  window.localStorage.setItem(key, "gnina-synthetic");
  let failLaunch: (reason: Error) => void = () => {};
  const pending = new Promise<Response>((_resolve, reject) => { failLaunch = reject; });
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (path.endsWith("/docking/gnina/jobs") && init?.method === "POST") return pending;
    if (path.endsWith("/docking/gnina/jobs/gnina-synthetic")) return json(gninaJob("completed"));
    return new Response("", { status: 200 });
  });
  render(<DockingWorkspace receptor={receptor} bindingSite={bindingSite} ligand={ligand} ligandInput={ligandInput} tools={gninaTools} platform="linux" />);
  fireEvent.click(screen.getByRole("button", { name: "GNINA · single" }));
  await screen.findByRole("button", { name: "Pose 1" });
  fireEvent.click(screen.getByText("Use these exact inputs and parameters"));
  fireEvent.click(screen.getByRole("button", { name: "Run GNINA" }));
  expect(screen.getByRole("button", { name: "Cancel docking" })).toBeDisabled();
  failLaunch(new Error("synthetic launch failure"));
  expect(await screen.findByText(/Could not start a new GNINA job/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Pose 1" })).toHaveAttribute("aria-pressed", "true");
  window.localStorage.clear();
});

function job(status: VinaDockingJobRecord["status"]): VinaDockingJobRecord {
  return {
    job_id: "job-synthetic", engine: "autodock_vina", status, phase: status === "completed" ? "complete" : "docking",
    created_at: "2026-08-23T00:00:00Z", started_at: "2026-08-23T00:00:01Z", completed_at: status === "completed" ? "2026-08-23T00:00:02Z" : null,
    request: { receptor_id: receptor.receptor_id, binding_site_id: bindingSite.binding_site_id, ligand_id: ligand.artifact.ligand_id, ligand_preparation_id: "preparation-synthetic", parameters: { cpu_threads: 4, seed: 12345, exhaustiveness: 8, num_modes: 9, min_rmsd_angstrom: 1, energy_range_kcal_mol: 3, timeout_minutes: 360 }, acknowledge_inputs_and_scoring: true },
    tool: { name: "AutoDock Vina", version: "1.2.7" }, receptor_output_artifact_id: "receptor-pdbqt", receptor_sha256: "b".repeat(64), ligand_sha256: "d".repeat(64),
    command: ["vina_1.2.7_win.exe", "--seed", "12345"],
    execution: status === "completed" ? { command: ["vina_1.2.7_win.exe"], exit_code: 0, stdout: "synthetic Vina output", stderr: "", timed_out: false, canceled: false } : null,
    poses: status === "completed" ? [{ mode: 1, affinity_kcal_mol: -7.2, rmsd_lower_bound_angstrom: 0, rmsd_upper_bound_angstrom: 0, artifact: { artifact_id: "pose-synthetic", mode: 1, filename: "pose_1.pdbqt", format: "pdbqt", sha256: "e".repeat(64), size_bytes: 130, content_url: "/pose_1.pdbqt" } }] : [],
    warnings: [], failure: null, provenance: null,
  };
}

function batch(status: VinaBatchDockingRecord["status"]): VinaBatchDockingRecord {
  const completed = status === "completed";
  const entries = [
    { ligand_id: "ligand-alpha", source_index: 0, name: "Synthetic alpha", canonical_smiles: "CCO", molecular_weight_g_mol: 46.07, preparation_initial_energy_kcal_mol: 22.345, preparation_energy_kcal_mol: 12.345 },
    { ligand_id: "ligand-beta", source_index: 1, name: "Synthetic beta", canonical_smiles: "CCN", molecular_weight_g_mol: 45.08, preparation_initial_energy_kcal_mol: 15.111, preparation_energy_kcal_mol: 10.111 },
  ].map((entry, index) => ({
    ...entry,
    ligand_preparation_id: `preparation-${index}`,
    ligand_sha256: String(index + 1).repeat(64),
    status: completed ? "completed" as const : "running" as const,
    phase: completed ? "complete" as const : "docking" as const,
    started_at: "2026-08-23T00:00:01Z",
    completed_at: completed ? "2026-08-23T00:00:02Z" : null,
    command: ["vina_1.2.7_win.exe", "--cpu", "3"],
    execution: completed ? { command: ["vina_1.2.7_win.exe"], exit_code: 0, stdout: "synthetic", stderr: "", timed_out: false, canceled: false } : null,
    poses: completed ? [
      { mode: 1, affinity_kcal_mol: index ? -6.8 : -7.2, rmsd_lower_bound_angstrom: 0, rmsd_upper_bound_angstrom: 0, artifact: { artifact_id: `batch-pose-${index}`, mode: 1, filename: "pose_1.pdbqt", format: "pdbqt" as const, sha256: "e".repeat(64), size_bytes: 130, content_url: `/batch-pose-${index}.pdbqt` } },
      ...(index === 0 ? [{ mode: 2, affinity_kcal_mol: -6.9, rmsd_lower_bound_angstrom: 1.2, rmsd_upper_bound_angstrom: 1.8, artifact: { artifact_id: "batch-pose-alpha-2", mode: 2, filename: "pose_2.pdbqt", format: "pdbqt" as const, sha256: "a".repeat(64), size_bytes: 132, content_url: "/batch-pose-alpha-2.pdbqt" } }] : []),
    ] : [],
    failure: null,
    provenance: null,
    revision: completed ? 3 : 1,
  }));
  return {
    batch_id: "batch-synthetic", engine: "autodock_vina", status, phase: completed ? "complete" : "docking",
    created_at: "2026-08-23T00:00:00Z", started_at: "2026-08-23T00:00:01Z", completed_at: completed ? "2026-08-23T00:00:02Z" : null,
    request: { receptor_id: receptor.receptor_id, binding_site_id: bindingSite.binding_site_id, library_id: libraryInput.library_id, filter_run_id: libraryInput.filter_run_id, parameters: { total_cpu_threads: 6, parallel_ligands: 2, seed: 45678, exhaustiveness: 8, num_modes: 9, min_rmsd_angstrom: 1, energy_range_kcal_mol: 3, timeout_minutes_per_ligand: 360 }, acknowledge_inputs_and_scoring: true },
    tool: { name: "AutoDock Vina", version: "1.2.7" }, receptor_output_artifact_id: "receptor-pdbqt", receptor_sha256: "b".repeat(64),
    selection_manifest_artifact_id: libraryInput.filter_run_id, selection_manifest_sha256: libraryInput.selection_manifest_sha256,
    selected_count: 2, worker_count: 2, threads_per_ligand: 3, completed_count: completed ? 2 : 0, succeeded_count: completed ? 2 : 0, failed_count: 0, canceled_count: 0,
    entries, warnings: [], failure: null, provenance: null, revision: completed ? 3 : 1,
  };
}

function batchProgress(): VinaBatchProgress {
  const completed = batch("completed");
  return {
    batch_id: completed.batch_id,
    status: completed.status,
    phase: completed.phase,
    revision: completed.revision,
    started_at: completed.started_at,
    completed_at: completed.completed_at,
    selected_count: completed.selected_count,
    worker_count: completed.worker_count,
    threads_per_ligand: completed.threads_per_ligand,
    completed_count: completed.completed_count,
    succeeded_count: completed.succeeded_count,
    failed_count: completed.failed_count,
    canceled_count: completed.canceled_count,
    entries: completed.entries,
    failure: completed.failure,
    provenance: completed.provenance,
  };
}

it("submits explicit Vina parameters and displays the completed pose table", async () => {
  let submitted: Record<string, unknown> | null = null;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (path.endsWith("/docking/vina/jobs")) {
      submitted = JSON.parse(String(init?.body)) as Record<string, unknown>;
      return json(job("running"), 202);
    }
    if (path.endsWith("/docking/jobs/job-synthetic")) return json(job("completed"));
    return new Response("", { status: 200 });
  });
  render(<DockingWorkspace receptor={receptor} bindingSite={bindingSite} ligand={ligand} ligandInput={ligandInput} tools={tools} />);
  fireEvent.change(screen.getByLabelText("CPU threads"), { target: { value: "4" } });
  fireEvent.change(screen.getByLabelText("Seed"), { target: { value: "12345" } });
  fireEvent.click(screen.getByText("Use these exact inputs and parameters"));
  fireEvent.click(screen.getByRole("button", { name: "Run AutoDock Vina" }));

  await screen.findAllByText("-7.200", {}, { timeout: 2000 });
  expect(submitted).toMatchObject({
    receptor_id: receptor.receptor_id,
    binding_site_id: bindingSite.binding_site_id,
    ligand_id: ligand.artifact.ligand_id,
    ligand_preparation_id: "preparation-synthetic",
    parameters: { sampling_protocol: "screening", cpu_threads: 4, seed: 12345 },
    acknowledge_inputs_and_scoring: true,
  });
  expect(screen.getByText(/not experimental affinities/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Pose 1" })).toHaveAttribute("aria-pressed", "true");
});

it("blocks docking instead of substituting an unprepared ligand state", () => {
  render(<DockingWorkspace receptor={receptor} bindingSite={bindingSite} ligand={ligand} ligandInput={null} tools={tools} />);
  expect(screen.getByText(/Return to Ligand, minimize it, and generate PDBQT/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Run AutoDock Vina" })).toBeDisabled();
});

it("requests cancellation for an active native job", async () => {
  const requestedPaths: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    requestedPaths.push(`${init?.method ?? "GET"} ${path}`);
    if (path.endsWith("/docking/vina/jobs")) return json(job("running"), 202);
    if (path.endsWith("/cancel")) return json({ job_id: "job-synthetic", status: "cancel_requested" });
    if (path.endsWith("/docking/jobs/job-synthetic")) return json(job("running"));
    return new Response("", { status: 200 });
  });
  render(<DockingWorkspace receptor={receptor} bindingSite={bindingSite} ligand={ligand} ligandInput={ligandInput} tools={tools} />);
  fireEvent.click(screen.getByText("Use these exact inputs and parameters"));
  fireEvent.click(screen.getByRole("button", { name: "Run AutoDock Vina" }));
  fireEvent.click(await screen.findByRole("button", { name: "Cancel docking" }));
  await waitFor(() => expect(requestedPaths.some((path) => path.includes("/cancel"))).toBe(true));
});

it("docks the complete applied library and renders compound-level results", async () => {
  let submitted: Record<string, unknown> | null = null;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (path.includes("/docking/batches/latest?")) return json({ code: "DOCKING_BATCH_HISTORY_EMPTY", stage: "docking_storage", message: "No history", details: {}, recoverable: true }, 404);
    if (path.endsWith("/docking/vina/batches")) {
      submitted = JSON.parse(String(init?.body)) as Record<string, unknown>;
      return json(batch("running"), 202);
    }
    if (path.includes("/docking/batches/batch-synthetic/progress?")) return json(batchProgress());
    return new Response("", { status: 200 });
  });
  render(<DockingWorkspace receptor={receptor} bindingSite={bindingSite} ligand={ligand} ligandInput={ligandInput} libraryInput={libraryInput} tools={tools} />);
  fireEvent.change(screen.getByLabelText("Total CPU threads"), { target: { value: "6" } });
  fireEvent.change(screen.getByLabelText("Concurrent ligands"), { target: { value: "2" } });
  fireEvent.change(screen.getByLabelText("Seed"), { target: { value: "45678" } });
  const acknowledgement = screen.getByRole("checkbox");
  await waitFor(() => expect(acknowledgement).toBeEnabled());
  fireEvent.click(acknowledgement);
  const startButton = await screen.findByRole("button", { name: "Dock 2 prepared ligands" });
  fireEvent.click(startButton);

  await screen.findAllByText("-7.200", {}, { timeout: 2000 });
  expect(submitted).toMatchObject({
    library_id: libraryInput.library_id,
    filter_run_id: libraryInput.filter_run_id,
    parameters: { sampling_protocol: "screening", total_cpu_threads: 6, parallel_ligands: 2, seed: 45678 },
    acknowledge_inputs_and_scoring: true,
  });
  expect(screen.getByText("CCO")).toBeInTheDocument();
  expect(screen.getByText("46.07")).toBeInTheDocument();
  expect(screen.getByText("-10.000")).toBeInTheDocument();
  expect(screen.getByText("2 / 2")).toBeInTheDocument();
});

it("applies a refinement protocol and relabels scientist edits as custom", () => {
  render(<DockingWorkspace receptor={receptor} bindingSite={bindingSite} ligand={ligand} ligandInput={ligandInput} tools={tools} />);

  fireEvent.click(screen.getByRole("button", { name: "Pose refinement" }));
  expect(screen.getByLabelText("Exhaustiveness")).toHaveValue(32);
  expect(screen.getByLabelText("Maximum poses")).toHaveValue(20);
  expect(screen.getByLabelText("Energy range (kcal/mol)")).toHaveValue(5);

  const acknowledgement = screen.getByRole("checkbox");
  fireEvent.click(acknowledgement);
  expect(acknowledgement).toBeChecked();
  fireEvent.change(screen.getByLabelText("Exhaustiveness"), { target: { value: "16" } });

  expect(screen.getByRole("button", { name: "Custom" })).toHaveAttribute("aria-pressed", "true");
  expect(acknowledgement).not.toBeChecked();
});

it("updates the best result live, sorts columns, and expands every pose for a compound", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = String(input);
    if (path.includes("/docking/batches/latest?")) return json({ code: "DOCKING_BATCH_HISTORY_EMPTY", stage: "docking_storage", message: "No history", details: {}, recoverable: true }, 404);
    if (path.endsWith("/docking/vina/batches")) return json(batch("running"), 202);
    if (path.includes("/docking/batches/batch-synthetic/progress?")) return json(batchProgress());
    return new Response("", { status: 200 });
  });
  render(<DockingWorkspace receptor={receptor} bindingSite={bindingSite} ligand={ligand} ligandInput={ligandInput} libraryInput={libraryInput} tools={tools} />);
  const acknowledgement = screen.getByRole("checkbox");
  await waitFor(() => expect(acknowledgement).toBeEnabled());
  fireEvent.click(acknowledgement);
  fireEvent.click(await screen.findByRole("button", { name: "Dock 2 prepared ligands" }));

  const bestResult = await screen.findByRole("button", { name: /Most favorable current Vina score.*Synthetic alpha.*-7.200/i }, { timeout: 2000 });
  expect(bestResult).toBeInTheDocument();
  const results = screen.getByRole("region", { name: "Virtual-screening docking results" });
  const scrollRegion = within(results).getByLabelText("Scrollable compound results table");
  const horizontalScroll = within(results).getByLabelText("Horizontal compound results scroll");
  expect(scrollRegion).toHaveAttribute("tabindex", "0");
  expect(horizontalScroll).toHaveAttribute("tabindex", "0");
  expect(within(results).getByText("MMFF ΔE (kcal/mol) · QC")).toBeInTheDocument();
  expect(within(results).queryByRole("button", { name: /MMFF ΔE/ })).not.toBeInTheDocument();
  expect(within(results).getByText(/MMFF ΔE is geometry QC and is not used for ranking/)).toBeInTheDocument();
  expect(within(results).getByText("-10.000")).toBeInTheDocument();
  expect(within(results).getByText("-5.000")).toBeInTheDocument();
  horizontalScroll.scrollLeft = 280;
  fireEvent.scroll(horizontalScroll);
  expect(scrollRegion.scrollLeft).toBe(280);

  fireEvent.click(within(results).getByRole("button", { name: /Synthetic alpha.*Current best/i }));
  expect(within(results).getByRole("button", { name: "Pose 2" })).toBeInTheDocument();
  fireEvent.click(within(results).getByRole("button", { name: "Pose 2" }));
  expect(within(results).getByRole("button", { name: "Pose 2" })).toHaveAttribute("aria-pressed", "true");

  const nameSort = within(results).getByRole("button", { name: /^Name/ });
  fireEvent.click(nameSort);
  fireEvent.click(nameSort);
  const compoundButtons = within(results).getAllByRole("button", { name: /Synthetic (alpha|beta)/i });
  expect(compoundButtons[0]).toHaveTextContent("Synthetic beta");
});

it("defaults library screening to one concurrent Vina process per available CPU thread", async () => {
  const hardwareDescriptor = Object.getOwnPropertyDescriptor(navigator, "hardwareConcurrency");
  Object.defineProperty(navigator, "hardwareConcurrency", { configurable: true, value: 16 });
  vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ code: "DOCKING_BATCH_HISTORY_EMPTY", stage: "docking_storage", message: "No history", details: {}, recoverable: true }, 404));
  render(<DockingWorkspace receptor={receptor} bindingSite={bindingSite} ligand={ligand} ligandInput={ligandInput} libraryInput={{ ...libraryInput, selected_count: 20, prepared_count: 20 }} tools={tools} />);

  await waitFor(() => expect(screen.getByLabelText("Total CPU threads")).toHaveValue(15));
  expect(screen.getByLabelText("Concurrent ligands")).toHaveValue(15);
  expect(screen.getByText(/15 concurrent Vina processes × 1 thread/i)).toBeInTheDocument();
  if (hardwareDescriptor) Object.defineProperty(navigator, "hardwareConcurrency", hardwareDescriptor);
});

it("runs every prepared row and explicitly accounts for an unavailable manifest entry", async () => {
  let submitted = false;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = String(input);
    if (path.includes("/docking/batches/latest?")) return json({ code: "DOCKING_BATCH_HISTORY_EMPTY", stage: "docking_storage", message: "No history", details: {}, recoverable: true }, 404);
    if (path.endsWith("/docking/vina/batches")) {
      submitted = true;
      return json(batch("running"), 202);
    }
    if (path.includes("/docking/batches/batch-synthetic/progress?")) return json(batchProgress());
    return new Response("", { status: 200 });
  });
  render(<DockingWorkspace receptor={receptor} bindingSite={bindingSite} ligand={ligand} ligandInput={ligandInput} libraryInput={{ ...libraryInput, prepared_count: 1 }} tools={tools} />);
  expect(screen.getByText(/1 selected molecule is not docking-ready/i)).toBeInTheDocument();
  expect(screen.getByText(/1 Vina executions and 1 explicit preflight failure/i)).toBeInTheDocument();
  const acknowledgement = screen.getByRole("checkbox");
  await waitFor(() => expect(acknowledgement).toBeEnabled());
  fireEvent.click(acknowledgement);
  const startButton = await screen.findByRole("button", { name: "Dock 1 prepared ligands" });
  fireEvent.click(startButton);
  await waitFor(() => expect(submitted).toBe(true));
});

it("restores the latest matching campaign and exposes recent finished molecules", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = String(input);
    if (path.includes("/docking/batches/latest?")) return json(batch("completed"));
    return new Response("", { status: 200 });
  });

  render(<DockingWorkspace receptor={receptor} bindingSite={bindingSite} ligand={ligand} ligandInput={ligandInput} libraryInput={libraryInput} tools={tools} />);

  expect(await screen.findByText("Most recently finished")).toBeInTheDocument();
  expect(screen.getByText("2/2")).toBeInTheDocument();
  expect(screen.getByText("100%")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /#2 Synthetic beta/i })).toBeInTheDocument();
});

it("prevents a rapid double click from creating duplicate campaigns", async () => {
  let starts = 0;
  let resolveStart!: (response: Response) => void;
  const pendingStart = new Promise<Response>((resolve) => { resolveStart = resolve; });
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = String(input);
    if (path.includes("/docking/batches/latest?")) return json({ code: "DOCKING_BATCH_HISTORY_EMPTY", stage: "docking_storage", message: "No history", details: {}, recoverable: true }, 404);
    if (path.endsWith("/docking/vina/batches")) {
      starts += 1;
      return pendingStart;
    }
    if (path.includes("/progress?")) return json({ ...batchProgress(), status: "running", phase: "docking", completed_at: null, completed_count: 0, succeeded_count: 0, entries: [] });
    return new Response("", { status: 200 });
  });

  render(<DockingWorkspace receptor={receptor} bindingSite={bindingSite} ligand={ligand} ligandInput={ligandInput} libraryInput={libraryInput} tools={tools} />);
  const acknowledgement = screen.getByRole("checkbox");
  await waitFor(() => expect(acknowledgement).toBeEnabled());
  fireEvent.click(acknowledgement);
  const startButton = await screen.findByRole("button", { name: "Dock 2 prepared ligands" });
  fireEvent.click(startButton);
  fireEvent.click(startButton);
  expect(starts).toBe(1);

  resolveStart(json(batch("running"), 202));
  expect(await screen.findByRole("button", { name: "Cancel library docking" })).toBeInTheDocument();
});

it("offers one docking experiment selector rather than separate engine and scope controls", () => {
  // Engine and scope are not independently selectable: Vina runs a single
  // ligand or a library, AutoDock4 runs a single ligand only. Two pill groups
  // would imply a 2x2 matrix that does not exist.
  render(
    <DockingWorkspace
      receptor={receptor}
      bindingSite={bindingSite}
      ligand={ligand}
      ligandInput={ligandInput}
      libraryInput={libraryInput}
      tools={tools}
    />,
  );

  const switches = screen.getAllByLabelText(/^Docking/);
  expect(switches).toHaveLength(1);
  const experiment = screen.getByLabelText("Docking experiment");
  expect(
    within(experiment).getAllByRole("button").map((button) => button.textContent),
  ).toEqual([
    "Vina · single",
    "Vina · screening",
    "AutoDock4 · single",
    "AutoDock4 · screening",
    "Compare engines",
  ]);
});

it("hides the screening option when no library is loaded, keeping both engines reachable", () => {
  render(
    <DockingWorkspace
      receptor={receptor}
      bindingSite={bindingSite}
      ligand={ligand}
      ligandInput={ligandInput}
      tools={tools}
    />,
  );

  const experiment = screen.getByLabelText("Docking experiment");
  expect(
    within(experiment).getAllByRole("button").map((button) => button.textContent),
  ).toEqual(["Vina · single", "AutoDock4 · single"]);
});

it("switches to the AutoDock4 experiment from the same selector", () => {
  render(
    <DockingWorkspace
      receptor={receptor}
      bindingSite={bindingSite}
      ligand={ligand}
      ligandInput={ligandInput}
      tools={tools}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "AutoDock4 · single" }));

  expect(screen.getByRole("region", { name: "AutoDock4 docking workspace" })).toBeInTheDocument();
  expect(screen.getAllByLabelText(/^Docking experiment$/)).toHaveLength(1);
});

it("routes the AutoDock4 screening option to the campaign workspace", () => {
  render(
    <DockingWorkspace
      receptor={receptor}
      bindingSite={bindingSite}
      ligand={ligand}
      ligandInput={ligandInput}
      libraryInput={libraryInput}
      tools={tools}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "AutoDock4 · screening" }));

  expect(
    screen.getByRole("region", { name: "AutoDock4 screening workspace" }),
  ).toBeInTheDocument();
  // Still exactly one selector, now carrying all four real combinations.
  expect(screen.getAllByLabelText(/^Docking experiment$/)).toHaveLength(1);
});

it("opens the side-by-side comparison, which resolves campaigns from disk", async () => {
  render(
    <DockingWorkspace
      receptor={receptor}
      bindingSite={bindingSite}
      ligand={ligand}
      ligandInput={ligandInput}
      libraryInput={libraryInput}
      tools={tools}
    />,
  );

  const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(null, { status: 404 }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Compare engines" }));

  expect(
    screen.getByRole("region", { name: "Engine comparison workspace" }),
  ).toBeInTheDocument();
  // It asks the backend for the persisted campaigns rather than relying on
  // anything this session happened to launch.
  await waitFor(() =>
    expect(
      fetchSpy.mock.calls.some(([url]) =>
        String(url).includes("/docking/comparison/latest"),
      ),
    ).toBe(true),
  );
});
