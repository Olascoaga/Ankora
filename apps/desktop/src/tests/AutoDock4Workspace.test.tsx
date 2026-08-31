import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { AutoDock4Workspace } from "../features/docking/AutoDock4Workspace";
import type {
  AutoDock4DockingJobRecord,
  AutoGridMapJobRecord,
  BindingSiteRecord,
  LigandDockingInput,
  LigandRecord,
  ReceptorPreparationRecord,
  ToolsResponse,
} from "../types/api";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const provenance = {
  event_id: "synthetic-event",
  event_type: "synthetic_fixture",
  timestamp: "2026-08-24T00:00:00Z",
  input_artifacts: [],
  output_artifacts: [],
  tool: { name: "synthetic", version: "1" },
  parameters: {},
  warnings: [],
  command: null,
};

const receptor = {
  receptor_id: "receptor-synthetic",
  source_artifact_id: "source-synthetic",
  created_at: "2026-08-24T00:00:00Z",
  status: "docking_ready",
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

const ligand = {
  artifact: { ligand_id: "ligand-synthetic", source: "local", source_structure_id: null, locator: null, filename: "ligand.sdf", format: "sdf", sha256: "c".repeat(64), size_bytes: 80, created_at: "2026-08-24T00:00:00Z", library_id: null, library_record_index: null },
  state: null,
  inspection: { name: "Synthetic ligand", formula: "C2H6", molecular_weight_g_mol: 30.07, exact_mass_da: 30.047, formal_charge: 0, atom_count: 8, heavy_atom_count: 2, rotatable_bond_count: 0, aromatic_ring_count: 0, stereocenter_count: 0, undefined_stereocenter_count: 0, fragment_count: 1, conformer_count: 1, has_3d_coordinates: true, canonical_smiles: "CC" },
  warnings: [], provenance, content_url: "/ligand.sdf", original_content_url: null,
} satisfies LigandRecord;

const ligandInput = {
  ligand_id: ligand.artifact.ligand_id,
  conformer: null,
  pdbqt: {
    artifact: { preparation_id: "preparation-synthetic", ligand_id: ligand.artifact.ligand_id, conformer_id: "conformer-synthetic", filename: "ligand.pdbqt", format: "pdbqt", sha256: "d".repeat(64), size_bytes: 90, created_at: "2026-08-24T00:00:00Z" },
    charge_model: "gasteiger", tool: { name: "Meeko", version: "0.7.1" }, command: ["synthetic"],
    stdout: "", stderr: "", provenance, content_url: "/ligand.pdbqt",
  },
} satisfies LigandDockingInput;

const tools = {
  vina: { available: true, path: "synthetic", version: "1.2.7" },
  gnina: { available: false, path: null, version: null },
  autogrid4: { available: true, path: "tools/autogrid4.exe", version: "4.2.6" },
  autodock4: { available: true, path: "tools/autodock4.exe", version: "4.2.6" },
  autodock_gpu: { available: true, path: "synthetic", version: "1.6" },
  pdbfixer: { available: true, path: "synthetic", version: "1" },
  pdb2pqr: { available: true, path: "synthetic", version: "1" },
  propka: { available: true, path: "synthetic", version: "1" },
  meeko: { available: true, path: "synthetic", version: "1" },
  meeko_ligand: { available: true, path: "synthetic", version: "1" },
  p2rank: { available: true, path: "synthetic", version: "1" },
} satisfies ToolsResponse;

const geometry = {
  spacing_angstrom: 0.375,
  npts: [54, 60, 64] as [number, number, number],
  requested_size_angstrom: [20, 22, 24] as [number, number, number],
  realized_size_angstrom: [20.25, 22.5, 24] as [number, number, number],
};

const preflight = {
  receptor_atom_types: ["A", "C", "HD", "N", "OA"],
  ligand_atom_types: ["C", "OA"],
  selected_count: 1, prepared_count: 1, compatible_count: 1, incompatible_count: 0,
  ligands: [{ ligand_id: ligand.artifact.ligand_id, source_index: 0, name: "Synthetic ligand", compatible: true, atom_types: ["C", "OA"], reason: null }],
};

const autogridIdentity = {
  tool: { name: "AutoGrid", version: "4.2.6" },
  executable_path: "tools/autogrid4.exe", sha256: "e".repeat(64), architecture: "x86",
  max_receptor_types: 20, max_ligand_types: 14, max_maps: 16, max_grid_points: 1025,
};

function mapJob(overrides: Partial<AutoGridMapJobRecord> = {}): AutoGridMapJobRecord {
  return {
    job_id: "grid-job", status: "queued", phase: "queued",
    created_at: "2026-08-24T00:00:00Z", started_at: null, completed_at: null,
    request: { receptor_id: receptor.receptor_id, binding_site_id: bindingSite.binding_site_id, source: "ligand_preparation" },
    identity_key: "f".repeat(64), geometry, preflight, autogrid: autogridIdentity,
    map_set_id: null, reused_existing_map_set: false, evidence_directory: null,
    execution: null, failure: null,
    ...overrides,
  };
}

const autodock4Identity = {
  tool: { name: "AutoDock", version: "4.2.6" },
  executable_path: "tools/autodock4.exe", sha256: "1".repeat(64), architecture: "x86",
  max_torsions: 32, max_atoms: 2048, max_maps: 16,
};

/** Mirrors the shape of a real 4.2.6 result: two clusters over five runs. */
function dockingJob(overrides: Partial<AutoDock4DockingJobRecord> = {}): AutoDock4DockingJobRecord {
  return {
    job_id: "dock-job", status: "queued", phase: "queued",
    created_at: "2026-08-24T00:00:00Z", started_at: null, completed_at: null,
    request: {
      receptor_id: receptor.receptor_id, binding_site_id: bindingSite.binding_site_id,
      map_set_id: "map-set-1", ligand_id: ligand.artifact.ligand_id,
      ligand_preparation_id: "preparation-synthetic",
      parameters: {
        ga_runs: 10, ga_population_size: 150, ga_energy_evaluations: 2_500_000,
        ga_generations: 27_000, cluster_rmsd_tolerance_angstrom: 2,
        seed_1: 20260824, seed_2: 20260824, timeout_minutes: 360,
      },
      acknowledge_inputs_and_scoring: true,
    },
    autodock4: autodock4Identity,
    receptor_id: receptor.receptor_id, binding_site_id: bindingSite.binding_site_id,
    map_set_id: "map-set-1", map_set_identity_key: "f".repeat(64),
    ligand_sha256: "d".repeat(64), ligand_atom_types: ["C", "OA"],
    ligand_atom_count: 10, torsional_degrees_of_freedom: 0,
    dpf_sha256: null, command: [], execution: null,
    clusters: [], runs: [], warnings: [], failure: null, provenance: null,
    ...overrides,
  };
}

function completedDocking(): AutoDock4DockingJobRecord {
  const pose = (run: number) => ({
    artifact_id: `pose-${run}`, run, filename: `run_${run}.pdbqt` as const,
    format: "pdbqt" as const, sha256: String(run).repeat(64).slice(0, 64),
    size_bytes: 2100, content_url: `/docking/autodock4/jobs/dock-job/poses/pose-${run}/content`,
  });
  return dockingJob({
    status: "completed", phase: "complete", command: ["autodock4.exe", "-p", "ligand.dpf"],
    dpf_sha256: "2".repeat(64),
    execution: { command: ["autodock4.exe"], exit_code: 0, stdout: "", stderr: "", duration_seconds: 5.16, successful_completion_logged: true, canceled: false, timed_out: false },
    clusters: [
      { cluster_rank: 1, lowest_binding_energy_kcal_mol: -3.4, mean_binding_energy_kcal_mol: -3.4, run_count: 2, representative_run: 3, runs: [3, 2] },
      { cluster_rank: 2, lowest_binding_energy_kcal_mol: -3.17, mean_binding_energy_kcal_mol: -3.16, run_count: 3, representative_run: 4, runs: [4, 1, 5] },
    ],
    runs: [
      { run: 1, cluster_rank: 2, sub_rank: 2, binding_energy_kcal_mol: -3.16, cluster_rmsd_angstrom: 0.34, reference_rmsd_angstrom: 31.68, artifact: pose(1) },
      { run: 2, cluster_rank: 1, sub_rank: 2, binding_energy_kcal_mol: -3.4, cluster_rmsd_angstrom: 0.11, reference_rmsd_angstrom: 39.35, artifact: pose(2) },
      { run: 3, cluster_rank: 1, sub_rank: 1, binding_energy_kcal_mol: -3.4, cluster_rmsd_angstrom: 0, reference_rmsd_angstrom: 39.29, artifact: pose(3) },
      { run: 4, cluster_rank: 2, sub_rank: 1, binding_energy_kcal_mol: -3.17, cluster_rmsd_angstrom: 0, reference_rmsd_angstrom: 31.7, artifact: pose(4) },
      { run: 5, cluster_rank: 2, sub_rank: 3, binding_energy_kcal_mol: -3.16, cluster_rmsd_angstrom: 0.16, reference_rmsd_angstrom: 31.9, artifact: pose(5) },
    ],
    provenance,
  });
}

function renderWorkspace() {
  return render(
    <AutoDock4Workspace
      receptor={receptor}
      bindingSite={bindingSite}
      ligand={ligand}
      ligandInput={ligandInput}
      tools={tools}
    />,
  );
}

it("requires affinity maps before AutoDock4 can be run", () => {
  renderWorkspace();

  const run = screen.getByRole("button", { name: "Run AutoDock4" });
  expect(run).toBeDisabled();
  expect(screen.getByText(/AutoDock4 cannot score without them/)).toBeInTheDocument();
});

it("generates maps, then docks, and presents AutoDock's own clusters", async () => {
  const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/autogrid/jobs") && init?.method === "POST") {
      return json(mapJob({ status: "completed", phase: "complete", map_set_id: "map-set-1" }), 202);
    }
    if (url.endsWith("/docking/autodock4/jobs") && init?.method === "POST") {
      return json(completedDocking(), 202);
    }
    return new Response(null, { status: 404 });
  });

  renderWorkspace();
  fireEvent.click(screen.getByRole("button", { name: "Generate affinity maps" }));

  expect(await screen.findByText("Map set generated")).toBeInTheDocument();
  expect(screen.getByText(/54 × 60 × 64 intervals/)).toBeInTheDocument();

  fireEvent.click(screen.getByRole("checkbox", { name: /Use these exact inputs/ }));
  fireEvent.click(screen.getByRole("button", { name: "Run AutoDock4" }));

  const results = await screen.findByRole("region", { name: "AutoDock4 clusters" });
  // The heading names the top cluster and how much of the search agreed with it.
  expect(within(results).getByText(/holds/)).toHaveTextContent("2 of 5 runs");

  const clusterRows = within(results).getAllByRole("row").filter(
    (row) => row.querySelector(".compound-expand"),
  );
  expect(clusterRows).toHaveLength(2);
  expect(within(clusterRows[0]).getByText("Best cluster")).toBeInTheDocument();

  // Rank 1 expands by default into its constituent runs, with the artifact hash.
  const expansion = within(results)
    .getByText(/Click a run to display/)
    .closest(".compound-poses") as HTMLElement;
  expect(expansion).not.toBeNull();
  const runRows = within(expansion).getAllByRole("row").slice(1);
  expect(runRows.map((row) => row.querySelector("code")?.textContent)).toEqual([
    "3333333333333333…",
    "2222222222222222…",
  ]);

  const generation = fetchSpy.mock.calls.find(([url]) => String(url).endsWith("/docking/autodock4/jobs"));
  expect(JSON.parse(String(generation?.[1]?.body)).map_set_id).toBe("map-set-1");
});

it("sorts clusters by any column and reverses on a second click", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/autogrid/jobs") && init?.method === "POST") {
      return json(mapJob({ status: "completed", phase: "complete", map_set_id: "map-set-1" }), 202);
    }
    if (url.endsWith("/docking/autodock4/jobs") && init?.method === "POST") {
      return json(completedDocking(), 202);
    }
    return new Response(null, { status: 404 });
  });

  renderWorkspace();
  fireEvent.click(screen.getByRole("button", { name: "Generate affinity maps" }));
  await screen.findByText("Map set generated");
  fireEvent.click(screen.getByRole("checkbox", { name: /Use these exact inputs/ }));
  fireEvent.click(screen.getByRole("button", { name: "Run AutoDock4" }));
  const results = await screen.findByRole("region", { name: "AutoDock4 clusters" });

  const ranks = () => within(results)
    .getAllByRole("row")
    .filter((row) => row.querySelector(".compound-expand"))
    .map((row) => row.querySelector(".compound-expand")?.textContent);

  expect(ranks()?.[0]).toContain("Rank 1");

  // Rank 2 holds more runs, so sorting by cluster size ascending puts rank 1 last.
  fireEvent.click(within(results).getByRole("button", { name: /Runs in cluster/ }));
  expect(ranks()?.[0]).toContain("Rank 1");
  fireEvent.click(within(results).getByRole("button", { name: /Runs in cluster/ }));
  expect(ranks()?.[0]).toContain("Rank 2");

  const header = within(results).getByRole("button", { name: /Runs in cluster/ }).closest("th");
  expect(header).toHaveAttribute("aria-sort", "descending");
});

it("collapses and expands a cluster to reveal its runs", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/autogrid/jobs") && init?.method === "POST") {
      return json(mapJob({ status: "completed", phase: "complete", map_set_id: "map-set-1" }), 202);
    }
    if (url.endsWith("/docking/autodock4/jobs") && init?.method === "POST") {
      return json(completedDocking(), 202);
    }
    return new Response(null, { status: 404 });
  });

  renderWorkspace();
  fireEvent.click(screen.getByRole("button", { name: "Generate affinity maps" }));
  await screen.findByText("Map set generated");
  fireEvent.click(screen.getByRole("checkbox", { name: /Use these exact inputs/ }));
  fireEvent.click(screen.getByRole("button", { name: "Run AutoDock4" }));
  const results = await screen.findByRole("region", { name: "AutoDock4 clusters" });

  const rankTwo = within(results)
    .getAllByRole("button", { name: /Rank 2/ })[0];
  expect(within(results).queryByRole("button", { name: "Run 4" })).not.toBeInTheDocument();

  fireEvent.click(rankTwo);

  expect(within(results).getByRole("button", { name: "Run 4" })).toBeInTheDocument();
  // Only one cluster stays expanded at a time.
  expect(within(results).queryByRole("button", { name: "Run 3" })).not.toBeInTheDocument();
});

it("states that an AutoDock4 energy is not comparable to a Vina score", () => {
  renderWorkspace();

  expect(
    screen.getByText(/not an experimental affinity, and that it is not comparable to a Vina score/),
  ).toBeInTheDocument();
});

it("reports a reused map set instead of implying it recomputed one", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/autogrid/jobs") && init?.method === "POST") {
      return json(
        mapJob({ status: "completed", phase: "complete", map_set_id: "map-set-1", reused_existing_map_set: true }),
        202,
      );
    }
    return new Response(null, { status: 404 });
  });

  renderWorkspace();
  fireEvent.click(screen.getByRole("button", { name: "Generate affinity maps" }));

  expect(await screen.findByText("Reused existing map set")).toBeInTheDocument();
});

it("surfaces a failed grid job rather than silently offering to dock", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/autogrid/jobs") && init?.method === "POST") {
      return json(
        mapJob({
          status: "failed", phase: "complete",
          failure: { code: "AUTOGRID_EXECUTION_FAILED", message: "AutoGrid did not complete successfully.", details: {} },
        }),
        202,
      );
    }
    return new Response(null, { status: 404 });
  });

  renderWorkspace();
  fireEvent.click(screen.getByRole("button", { name: "Generate affinity maps" }));

  expect(await screen.findByText("AutoGrid did not complete successfully.")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole("button", { name: "Run AutoDock4" })).toBeDisabled());
});


// --- execution backend -----------------------------------------------------

function chooseGpuBackend() {
  fireEvent.click(screen.getByRole("radio", { name: /AutoDock-GPU/ }));
}

it("offers both backends and defaults to the one that reproduces", () => {
  renderWorkspace();

  const group = screen.getByRole("radiogroup", { name: "Execution backend" });
  const options = within(group).getAllByRole("radio");

  expect(options).toHaveLength(2);
  expect(options[0]).toHaveAttribute("aria-checked", "true");
  expect(options[0]).toHaveTextContent(/CPU · AutoDock4/);
  expect(options[1]).toHaveTextContent(/GPU · AutoDock-GPU/);
});

it("states the GPU's irreproducibility before anything is run", () => {
  renderWorkspace();

  chooseGpuBackend();

  expect(screen.getByText(/does not reproduce a run from its seed/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Run AutoDock-GPU" })).toBeInTheDocument();
});

it("shows each backend only the settings it has", () => {
  renderWorkspace();

  // Generations is a CPU-only Lamarckian-GA setting; the GPU has none.
  expect(screen.getByLabelText("Generations")).toBeInTheDocument();
  expect(screen.queryByLabelText("Seed 3")).not.toBeInTheDocument();

  chooseGpuBackend();

  expect(screen.queryByLabelText("Generations")).not.toBeInTheDocument();
  // AutoDock-GPU takes three seeds where AutoDock4 takes two.
  expect(screen.getByLabelText("Seed 3")).toBeInTheDocument();
  expect(screen.getByLabelText("Local search")).toBeInTheDocument();
});

it("disables the evaluation budget when the tool is asked to choose it", () => {
  renderWorkspace();
  chooseGpuBackend();

  const budget = screen.getByLabelText("Energy evaluations");
  expect(budget).not.toBeDisabled();

  fireEvent.click(
    screen.getByRole("checkbox", { name: /Let the tool choose the evaluation count/ }),
  );

  // The tool ignores the budget under its heuristic, so offering it would lie.
  expect(budget).toBeDisabled();
});

it("names the backend it is actually on, everywhere it names one", () => {
  renderWorkspace();

  expect(screen.getByText(/M5 · AutoDock4 4\.2\.6 CPU/)).toBeInTheDocument();

  chooseGpuBackend();

  expect(screen.getByText(/M5 · AutoDock-GPU 1\.6/)).toBeInTheDocument();
  expect(screen.queryByText(/AutoDock4 4\.2\.6 CPU/)).not.toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: /^AutoDock-GPU on one ligand$/ }),
  ).toBeInTheDocument();
});
