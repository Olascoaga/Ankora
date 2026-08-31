import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { DockingWorkspace } from "../features/docking/DockingWorkspace";
import type {
  BindingSiteRecord,
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
    { ligand_id: "ligand-alpha", source_index: 0, name: "Synthetic alpha", canonical_smiles: "CCO", molecular_weight_g_mol: 46.07, preparation_energy_kcal_mol: 12.345 },
    { ligand_id: "ligand-beta", source_index: 1, name: "Synthetic beta", canonical_smiles: "CCN", molecular_weight_g_mol: 45.08, preparation_energy_kcal_mol: 10.111 },
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
    entries, failure: null, provenance: null, revision: completed ? 3 : 1,
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
    parameters: { cpu_threads: 4, seed: 12345 },
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
    parameters: { total_cpu_threads: 6, parallel_ligands: 2, seed: 45678 },
    acknowledge_inputs_and_scoring: true,
  });
  expect(screen.getByText("CCO")).toBeInTheDocument();
  expect(screen.getByText("46.07")).toBeInTheDocument();
  expect(screen.getByText("12.345")).toBeInTheDocument();
  expect(screen.getByText("2 / 2")).toBeInTheDocument();
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
