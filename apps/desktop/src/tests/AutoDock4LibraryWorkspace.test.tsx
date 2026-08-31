import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { AutoDock4LibraryWorkspace } from "../features/docking/AutoDock4LibraryWorkspace";
import type {
  AutoDock4BatchLigandResult,
  AutoDock4BatchRecord,
  AutoGridMapJobRecord,
  BindingSiteRecord,
  LigandLibraryDockingInput,
  ReceptorPreparationRecord,
  ToolsResponse,
} from "../types/api";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const receptor = {
  receptor_id: "receptor-synthetic", source_artifact_id: "source-synthetic",
  created_at: "2026-08-24T00:00:00Z", status: "docking_ready",
  decisions: {
    selected_chains: ["A"], water_action: "remove", component_decisions: [], issue_decisions: [],
    reference_component_id: null,
    relaxation: { enabled: false, restraint_force_constant_kcal_mol_a2: 50, max_iterations: 200 },
    protonation: { enabled: true, ph: 7.4, force_field: "AMBER" }, generate_pdbqt: true,
  },
  outputs: [
    { artifact_id: "display-pdb", stage: "protonated_pdb", filename: "receptor.pdb", format: "pdb", sha256: "a".repeat(64), size_bytes: 100, created_at: "2026-08-24T00:00:00Z", content_url: "/receptor.pdb" },
    { artifact_id: "receptor-pdbqt", stage: "pdbqt", filename: "receptor.pdbqt", format: "pdbqt", sha256: "b".repeat(64), size_bytes: 120, created_at: "2026-08-24T00:00:00Z", content_url: "/receptor.pdbqt" },
  ],
  warnings: [], provenance: [], display_output_artifact_id: "display-pdb",
} satisfies ReceptorPreparationRecord;

const bindingSite = {
  binding_site_id: "binding-synthetic", receptor_id: receptor.receptor_id,
  source_artifact_id: "display-pdb", created_at: "2026-08-24T00:00:00Z",
  decisions: { source: "manual", ligand_origin: null, residue_selection: null, manual_box: { center_x: 1, center_y: 2, center_z: 3, size_x: 20, size_y: 22, size_z: 24 }, blind_margin_angstrom: 6, pocket_selection: null, parent_binding_site_id: null },
  box: { center_x: 1, center_y: 2, center_z: 3, size_x: 20, size_y: 22, size_z: 24 },
  stale: false, warnings: [], provenance: [],
} satisfies BindingSiteRecord;

const libraryInput = {
  library_id: "library-1",
  filter_run_id: "filter-1",
  selected_count: 3,
  prepared_count: 3,
} as LigandLibraryDockingInput;

const tools = {
  vina: { available: true, path: "synthetic", version: "1.2.7" },
  gnina: { available: false, path: null, version: null },
  autogrid4: { available: true, path: "synthetic", version: "4.2.6" },
  autodock4: { available: true, path: "synthetic", version: "4.2.6" },
  autodock_gpu: { available: true, path: "synthetic", version: "1.6" },
  pdbfixer: { available: true, path: "synthetic", version: "1" },
  pdb2pqr: { available: true, path: "synthetic", version: "1" },
  propka: { available: true, path: "synthetic", version: "1" },
  meeko: { available: true, path: "synthetic", version: "1" },
  meeko_ligand: { available: true, path: "synthetic", version: "1" },
  p2rank: { available: true, path: "synthetic", version: "1" },
} satisfies ToolsResponse;

const autogrid = {
  tool: { name: "AutoGrid", version: "4.2.6" }, executable_path: "synthetic",
  sha256: "e".repeat(64), architecture: "x86",
  max_receptor_types: 20, max_ligand_types: 14, max_maps: 16, max_grid_points: 1025,
};

const mapJob = {
  job_id: "grid-job", status: "completed", phase: "complete",
  created_at: "2026-08-24T00:00:00Z", started_at: null, completed_at: null,
  request: { receptor_id: receptor.receptor_id, binding_site_id: bindingSite.binding_site_id, source: "filter_run" },
  identity_key: "f".repeat(64),
  geometry: { spacing_angstrom: 0.375, npts: [54, 60, 64], requested_size_angstrom: [20, 22, 24], realized_size_angstrom: [20.25, 22.5, 24] },
  preflight: {
    receptor_atom_types: ["A", "C"], ligand_atom_types: ["C", "OA"],
    selected_count: 3, prepared_count: 3, compatible_count: 2, incompatible_count: 1, ligands: [],
  },
  autogrid, map_set_id: "map-set-1", reused_existing_map_set: false,
  evidence_directory: null, execution: null, failure: null,
} as AutoGridMapJobRecord;

const autodock4 = {
  tool: { name: "AutoDock", version: "4.2.6" }, executable_path: "synthetic",
  sha256: "1".repeat(64), architecture: "x86",
  max_torsions: 32, max_atoms: 2048, max_maps: 16,
};

function entry(
  index: number, name: string, energy: number | null, status: string,
): AutoDock4BatchLigandResult {
  const clusters = energy === null ? [] : [
    { cluster_rank: 1, lowest_binding_energy_kcal_mol: energy, mean_binding_energy_kcal_mol: energy, run_count: 2, representative_run: 1, runs: [1, 2] },
  ];
  const runs = energy === null ? [] : [1, 2].map((run) => ({
    run, cluster_rank: 1, sub_rank: run, binding_energy_kcal_mol: energy,
    cluster_rmsd_angstrom: 0, reference_rmsd_angstrom: 10,
    artifact: {
      artifact_id: `pose-${index}-${run}`, run, filename: `run_${run}.pdbqt` as const,
      format: "pdbqt" as const, sha256: String(index).repeat(64).slice(0, 64),
      size_bytes: 2100, content_url: `/pose-${index}-${run}`,
    },
  }));
  return {
    ligand_id: `ligand-${index}`, source_index: index, name,
    canonical_smiles: "CC", molecular_weight_g_mol: 30,
    ligand_preparation_id: `prep-${index}`, ligand_sha256: "d".repeat(64),
    ligand_atom_types: ["C", "OA"],
    status: status as AutoDock4BatchLigandResult["status"],
    phase: "complete", started_at: null, completed_at: null,
    command: [], dpf_sha256: null, execution: null,
    clusters, runs,
    failure: status === "failed"
      ? { code: "AUTODOCK4_LIGAND_TYPES_NOT_IN_MAP_SET", message: "Uncovered atom types.", details: {} }
      : null,
    provenance: null, revision: 1,
  };
}

function batch(overrides: Partial<AutoDock4BatchRecord> = {}): AutoDock4BatchRecord {
  const entries = [
    entry(0, "Compound A", -4.1, "completed"),
    entry(1, "Compound B", -5.6, "completed"),
    entry(2, "Compound C", null, "failed"),
  ];
  return {
    batch_id: "batch-1", status: "completed", phase: "complete",
    created_at: "2026-08-24T00:00:00Z", started_at: null, completed_at: null,
    request: {
      receptor_id: receptor.receptor_id, binding_site_id: bindingSite.binding_site_id,
      map_set_id: "map-set-1", library_id: "library-1", filter_run_id: "filter-1",
      parameters: {
        parallel_ligands: 8, ga_runs: 10, ga_population_size: 150,
        ga_energy_evaluations: 2_500_000, ga_generations: 27_000,
        cluster_rmsd_tolerance_angstrom: 2, seed_1: 1, seed_2: 2, timeout_minutes: 360,
      },
      acknowledge_inputs_and_scoring: true,
    },
    autodock4, receptor_id: receptor.receptor_id, binding_site_id: bindingSite.binding_site_id,
    map_set_id: "map-set-1", map_set_identity_key: "f".repeat(64),
    selection_manifest_sha256: "c".repeat(64),
    selected_count: 3, worker_count: 8,
    completed_count: 3, succeeded_count: 2, failed_count: 1, canceled_count: 0,
    entries, warnings: [], failure: null, provenance: null, revision: 5,
    ...overrides,
  };
}

const gpuStarts: Record<string, unknown>[] = [];

function gpuBatch() {
  const source = batch();
  return {
    batch_id: "gpu-batch-1",
    backend: "autodock_gpu",
    status: "completed",
    phase: "complete",
    created_at: source.created_at,
    started_at: null,
    completed_at: null,
    request: {
      receptor_id: receptor.receptor_id,
      binding_site_id: bindingSite.binding_site_id,
      map_set_id: "map-set-1",
      library_id: "library-1",
      filter_run_id: "filter-1",
      parameters: {
        runs: 10, population_size: 150, energy_evaluations: 2_500_000,
        heuristics: false, autostop: false, local_search_method: "ad",
        cluster_rmsd_tolerance_angstrom: 2,
        seed_1: 1, seed_2: 1, seed_3: 1, device_number: 1, timeout_minutes: 60,
      },
      acknowledge_inputs_and_scoring: true,
    },
    autodock_gpu: {
      tool: { name: "AutoDock-GPU", version: "1.6" },
      executable_path: "synthetic", sha256: "1".repeat(64), architecture: "x86_64",
      build: "Release", device_number: 1, device_name: "Synthetic RTX",
    },
    receptor_id: receptor.receptor_id,
    binding_site_id: bindingSite.binding_site_id,
    map_set_id: "map-set-1", map_set_identity_key: "f".repeat(64),
    selection_manifest_sha256: "c".repeat(64),
    worker_count: 1, bitwise_reproducible: false,
    selected_count: 3, completed_count: 3, succeeded_count: 2,
    failed_count: 1, canceled_count: 0,
    command: ["synthetic", "--filelist", "campaign.lst"], execution: null,
    entries: source.entries.map((entry) => ({
      ligand_id: entry.ligand_id, source_index: entry.source_index, name: entry.name,
      canonical_smiles: entry.canonical_smiles,
      molecular_weight_g_mol: entry.molecular_weight_g_mol,
      ligand_preparation_id: entry.ligand_preparation_id,
      ligand_sha256: entry.ligand_sha256, ligand_atom_types: entry.ligand_atom_types,
      status: entry.status, phase: entry.phase, completed_at: null,
      clusters: entry.clusters, runs: entry.runs, failure: entry.failure, revision: 1,
    })),
    warnings: [], failure: null, provenance: null, revision: 3,
  };
}

function chooseGpu() {
  fireEvent.click(screen.getByRole("radio", { name: /AutoDock-GPU/ }));
}

function mockBackend(history: unknown = null) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.includes("/docking/autodock4/batches/latest")) {
      // No campaign for these inputs is the normal first-run state.
      return history === null ? new Response(null, { status: 404 }) : json(history);
    }
    if (url.endsWith("/autogrid/jobs") && init?.method === "POST") return json(mapJob, 202);
    if (url.endsWith("/docking/autodock4/batches") && init?.method === "POST") {
      return json(batch(), 202);
    }
    if (url.includes("/docking/autodock-gpu/batches/latest")) {
      return new Response(null, { status: 404 });
    }
    if (url.endsWith("/docking/autodock-gpu/batches") && init?.method === "POST") {
      gpuStarts.push(JSON.parse(String(init?.body)));
      return json(gpuBatch(), 202);
    }
    return new Response(null, { status: 404 });
  });
}

function renderWorkspace() {
  return render(
    <AutoDock4LibraryWorkspace
      receptor={receptor}
      bindingSite={bindingSite}
      libraryInput={libraryInput}
      tools={tools}
    />,
  );
}

async function runCampaign() {
  renderWorkspace();
  await screen.findByRole("button", { name: "Dock the applied selection" });
  fireEvent.click(screen.getByRole("button", { name: "Generate affinity maps" }));
  await screen.findByText("Map set generated");
  fireEvent.click(screen.getByRole("checkbox", { name: /Use these exact inputs/ }));
  fireEvent.click(screen.getByRole("button", { name: "Dock the applied selection" }));
  return screen.findByRole("region", { name: "AutoDock4 campaign results" });
}

it("computes the maps once for the whole selection before docking", async () => {
  const fetchSpy = mockBackend();
  renderWorkspace();

  // The workspace first checks for an existing campaign; only then can it run.
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Dock the applied selection" })).toBeDisabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Generate affinity maps" }));

  expect(await screen.findByText("Map set generated")).toBeInTheDocument();
  // The map request covers the whole applied selection, not one molecule.
  const call = fetchSpy.mock.calls.find(([url]) => String(url).endsWith("/autogrid/jobs"));
  const body = JSON.parse(String(call?.[1]?.body));
  expect(body.source).toBe("filter_run");
  expect(body.filter_run_id).toBe("filter-1");
  // Maps alone are not enough: the acknowledgement is still required.
  expect(screen.getByRole("button", { name: "Dock the applied selection" })).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox", { name: /Use these exact inputs/ }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Dock the applied selection" })).toBeEnabled(),
  );
});

it("ranks compounds by their best AutoDock energy and names the current best", async () => {
  mockBackend();
  const results = await runCampaign();

  expect(within(results).getByText(/currently ranks first/)).toHaveTextContent(
    "Compound B currently ranks first at -5.60 kcal/mol",
  );
  const rows = within(results).getAllByRole("row").slice(1);
  const names = rows.map((row) => row.querySelector(".compound-expand")?.textContent);
  // Sorted by best energy ascending, so the most favourable is first.
  expect(names[0]).toContain("Compound B");
  expect(names[0]).toContain("Current best");
  expect(names[1]).toContain("Compound A");
});

it("keeps an incompatible molecule as a visible failed row", async () => {
  mockBackend();
  const results = await runCampaign();

  const rows = within(results).getAllByRole("row").slice(1);
  const failedRow = rows.find((row) => row.textContent?.includes("Compound C"));
  expect(failedRow).toBeDefined();
  expect(within(failedRow as HTMLElement).getByText("failed")).toBeInTheDocument();
  expect(
    within(failedRow as HTMLElement).getByText("AUTODOCK4_LIGAND_TYPES_NOT_IN_MAP_SET"),
  ).toBeInTheDocument();
});

it("expands a compound into the clusters AutoDock produced for it", async () => {
  mockBackend();
  const results = await runCampaign();

  fireEvent.click(within(results).getByRole("button", { name: /Compound A/ }));

  expect(within(results).getByText(/1 clusters over 2 runs/)).toBeInTheDocument();
  expect(within(results).getByRole("button", { name: "Run 1" })).toBeInTheDocument();
  expect(within(results).getByRole("button", { name: "Run 2" })).toBeInTheDocument();
});

it("states that the pool is the whole CPU budget because the build is single-threaded", () => {
  mockBackend();
  renderWorkspace();

  expect(screen.getByText(/no OpenMP support/)).toBeInTheDocument();
  expect(screen.getByLabelText("Parallel molecules")).toBeInTheDocument();
});

it("reconnects to a campaign that already exists on disk", async () => {
  // A campaign outlives the session that ran it; reopening the workspace must
  // show it rather than an empty page over completed work.
  mockBackend(batch());
  renderWorkspace();

  const results = await screen.findByRole("region", { name: "AutoDock4 campaign results" });
  expect(within(results).getByText(/currently ranks first/)).toBeInTheDocument();
  // Its map set is already known, so docking is not gated behind regenerating.
  await waitFor(() =>
    expect(screen.queryByText(/AutoDock4 cannot score without them/)).not.toBeInTheDocument(),
  );
});

it("does not report an error when no campaign has been run yet", async () => {
  mockBackend();
  renderWorkspace();

  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Dock the applied selection" })).toBeInTheDocument(),
  );
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});


// --- execution backend -----------------------------------------------------

it("offers both backends of the one engine, saying how they differ", async () => {
  mockBackend();
  renderWorkspace();

  const group = await screen.findByRole("radiogroup", { name: "Execution backend" });
  const options = within(group).getAllByRole("radio");
  expect(options).toHaveLength(2);
  expect(options[0]).toHaveTextContent(/CPU · AutoDock4/);
  expect(options[0]).toHaveTextContent(/exactly reproducible/);
  expect(options[1]).toHaveTextContent(/GPU · AutoDock-GPU/);
  expect(options[1]).toHaveTextContent(/not reproducible/);
  // The CPU is the default, because it is the one that reproduces.
  expect(options[0]).toHaveAttribute("aria-checked", "true");
});

it("warns about irreproducibility as soon as the GPU is chosen, not after", async () => {
  mockBackend();
  renderWorkspace();
  await screen.findByRole("radiogroup", { name: "Execution backend" });

  chooseGpu();

  expect(
    screen.getByText(/does not reproduce a run from its seed/),
  ).toBeInTheDocument();
  expect(screen.getByText(/Use the CPU backend when an exactly repeatable/))
    .toBeInTheDocument();
});

it("shows each backend only the settings it actually has", async () => {
  mockBackend();
  renderWorkspace();
  await screen.findByRole("radiogroup", { name: "Execution backend" });

  // The CPU pool is the whole CPU budget; the GPU has one device.
  expect(screen.getByLabelText("Parallel molecules")).toBeInTheDocument();
  expect(screen.queryByLabelText("Local search")).not.toBeInTheDocument();

  chooseGpu();

  expect(screen.queryByLabelText("Parallel molecules")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Local search")).toBeInTheDocument();
  expect(screen.getByText(/Two processes on one device measured slower/))
    .toBeInTheDocument();
  // The tool's adaptive settings are offered, and named for what they cost.
  expect(
    screen.getByRole("checkbox", { name: /Let the tool choose the evaluation count/ }),
  ).toBeInTheDocument();
});

it("sends the campaign to the backend the scientist chose", async () => {
  const fetchSpy = mockBackend();
  renderWorkspace();
  await screen.findByRole("radiogroup", { name: "Execution backend" });
  chooseGpu();

  fireEvent.click(screen.getByRole("button", { name: "Generate affinity maps" }));
  await screen.findByText(/Map set generated|Reused existing map set/);
  fireEvent.click(screen.getByRole("checkbox", { name: /Use these exact inputs/ }));
  fireEvent.click(screen.getByRole("button", { name: "Dock the applied selection" }));

  await waitFor(() => expect(gpuStarts).toHaveLength(1));
  // The GPU request carries its own protocol, not the CPU's.
  expect(gpuStarts[0].parameters).toEqual(
    expect.objectContaining({ local_search_method: "ad", heuristics: false }),
  );
  const posted = fetchSpy.mock.calls.filter(([, init]) => init?.method === "POST");
  expect(posted.some(([url]) => String(url).endsWith("/docking/autodock4/batches")))
    .toBe(false);
});

it("names the backend it is actually on, everywhere it names one", async () => {
  // A badge hardcoded to CPU is worse than none: it contradicts the panel
  // beside it and misattributes the result a scientist is looking at.
  mockBackend();
  renderWorkspace();
  await screen.findByRole("radiogroup", { name: "Execution backend" });

  expect(screen.getByText(/M5 · AutoDock4 4\.2\.6 CPU/)).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /^AutoDock4 over the applied selection$/ })).toBeInTheDocument();

  chooseGpu();

  expect(screen.getByText(/M5 · AutoDock-GPU 1\.6/)).toBeInTheDocument();
  expect(screen.queryByText(/AutoDock4 4\.2\.6 CPU/)).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /^AutoDock-GPU over the applied selection$/ })).toBeInTheDocument();
});

it("keeps the results table scrollable sideways without hunting for a bar", async () => {
  // The table is forced wider than the panel, and its own scrollbar sits at the
  // bottom of a box that is often taller than the viewport.
  mockBackend(batch());
  renderWorkspace();

  const results = await screen.findByRole("region", { name: "AutoDock4 campaign results" });

  expect(
    within(results).getByLabelText("Horizontal campaign results scroll"),
  ).toBeInTheDocument();
  expect(
    within(results).getByLabelText("Scrollable campaign results table"),
  ).toBeInTheDocument();
});
