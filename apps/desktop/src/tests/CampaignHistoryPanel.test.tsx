import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { AutoDock4LibraryWorkspace } from "../features/docking/AutoDock4LibraryWorkspace";
import { LibraryDockingWorkspace } from "../features/docking/LibraryDockingWorkspace";
import type {
  AutoDock4BatchRecord,
  BindingSiteRecord,
  CampaignSummary,
  LigandLibraryDockingInput,
  ReceptorPreparationRecord,
  ToolsResponse,
  VinaBatchDockingRecord,
} from "../types/api";

/**
 * Recovering earlier campaigns, for both engines.
 *
 * Reconnecting to the newest campaign is not enough: a project accumulates
 * campaigns, and the scientist has to be able to open an earlier one.
 */

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const receptor = {
  receptor_id: "receptor-1", source_artifact_id: "source-1",
  created_at: "2026-08-20T00:00:00Z", status: "docking_ready",
  decisions: {
    selected_chains: ["A"], water_action: "remove", component_decisions: [], issue_decisions: [],
    reference_component_id: null,
    relaxation: { enabled: false, restraint_force_constant_kcal_mol_a2: 50, max_iterations: 200 },
    protonation: { enabled: true, ph: 7.4, force_field: "AMBER" }, generate_pdbqt: true,
  },
  outputs: [
    { artifact_id: "display-pdb", stage: "protonated_pdb", filename: "receptor.pdb", format: "pdb", sha256: "a".repeat(64), size_bytes: 100, created_at: "2026-08-20T00:00:00Z", content_url: "/receptor.pdb" },
    { artifact_id: "receptor-pdbqt", stage: "pdbqt", filename: "receptor.pdbqt", format: "pdbqt", sha256: "b".repeat(64), size_bytes: 120, created_at: "2026-08-20T00:00:00Z", content_url: "/receptor.pdbqt" },
  ],
  warnings: [], provenance: [], display_output_artifact_id: "display-pdb",
} satisfies ReceptorPreparationRecord;

const bindingSite = {
  binding_site_id: "site-1", receptor_id: receptor.receptor_id,
  source_artifact_id: "display-pdb", created_at: "2026-08-20T00:00:00Z",
  decisions: { source: "manual", ligand_origin: null, residue_selection: null, manual_box: { center_x: 1, center_y: 2, center_z: 3, size_x: 20, size_y: 22, size_z: 24 }, blind_margin_angstrom: 6, pocket_selection: null, parent_binding_site_id: null },
  box: { center_x: 1, center_y: 2, center_z: 3, size_x: 20, size_y: 22, size_z: 24 },
  stale: false, warnings: [], provenance: [],
} satisfies BindingSiteRecord;

const libraryInput = {
  library_id: "library-1", library_name: "Library", filter_run_id: "filter-1",
  selection_manifest_sha256: "c".repeat(64), selected_count: 2, prepared_count: 2,
} satisfies LigandLibraryDockingInput;

const tools = {
  vina: { available: true, path: "synthetic", version: "1.2.7" },
  gnina: { available: false, path: null, version: null },
  autogrid4: { available: true, path: "synthetic", version: "4.2.6" },
  autodock4: { available: true, path: "synthetic", version: "4.2.6" },
  autodock_gpu: { available: false, path: null, version: null },
  pdbfixer: { available: true, path: "synthetic", version: "1" },
  pdb2pqr: { available: true, path: "synthetic", version: "1" },
  propka: { available: true, path: "synthetic", version: "1" },
  meeko: { available: true, path: "synthetic", version: "1" },
  meeko_ligand: { available: true, path: "synthetic", version: "1" },
  p2rank: { available: true, path: "synthetic", version: "1" },
} satisfies ToolsResponse;

function summary(overrides: Partial<CampaignSummary> = {}): CampaignSummary {
  return {
    batch_id: "campaign-old", engine: "autodock_vina", engine_version: "1.2.7",
    status: "completed", is_running: false,
    created_at: "2026-08-21T09:30:00Z", completed_at: "2026-08-21T10:00:00Z",
    receptor_id: receptor.receptor_id, binding_site_id: bindingSite.binding_site_id,
    same_site_record: true, library_id: "library-1", filter_run_id: "filter-1",
    selection_manifest_sha256: "c".repeat(64),
    selected_count: 2, succeeded_count: 2, failed_count: 0, canceled_count: 0,
    best_result_kcal_mol: -8.4, best_ligand_name: "Compound A",
    ...overrides,
  };
}

// --- Vina ---------------------------------------------------------------

function vinaRecord(overrides: Partial<VinaBatchDockingRecord> = {}): VinaBatchDockingRecord {
  return {
    batch_id: "campaign-old", engine: "autodock_vina", status: "completed", phase: "complete",
    created_at: "2026-08-21T09:30:00Z", started_at: null, completed_at: null,
    request: {
      receptor_id: receptor.receptor_id, binding_site_id: bindingSite.binding_site_id,
      library_id: "library-1", filter_run_id: "filter-1",
      parameters: {
        total_cpu_threads: 8, parallel_ligands: 4, seed: 1, exhaustiveness: 8,
        num_modes: 9, min_rmsd_angstrom: 1, energy_range_kcal_mol: 3,
        timeout_minutes_per_ligand: 30,
      },
      acknowledge_inputs_and_scoring: true,
    },
    tool: { name: "AutoDock Vina", version: "1.2.7" },
    receptor_output_artifact_id: "receptor-pdbqt", receptor_sha256: "b".repeat(64),
    selection_manifest_artifact_id: "manifest", selection_manifest_sha256: "c".repeat(64),
    selected_count: 2, worker_count: 4, threads_per_ligand: 2,
    completed_count: 2, succeeded_count: 2, failed_count: 0, canceled_count: 0,
    warnings: [],
    entries: [
      {
        ligand_id: "ligand-0", source_index: 0, name: "Restored Compound",
        canonical_smiles: "CC", molecular_weight_g_mol: 30,
        preparation_initial_energy_kcal_mol: null, preparation_energy_kcal_mol: null,
        ligand_preparation_id: "prep-0",
        ligand_sha256: "d".repeat(64), status: "completed", phase: "complete",
        started_at: null, completed_at: null, command: [], execution: null,
        poses: [{
          mode: 1, affinity_kcal_mol: -8.4,
          rmsd_lower_bound_angstrom: 0, rmsd_upper_bound_angstrom: 0,
          artifact: {
            artifact_id: "pose-0", mode: 1, filename: "pose_1.pdbqt", format: "pdbqt",
            sha256: "e".repeat(64), size_bytes: 100, content_url: "/pose-0",
          },
        }],
        failure: null, provenance: null, revision: 1,
      },
    ],
    failure: null, provenance: null, revision: 3,
    ...overrides,
  };
}

function mockVina(campaigns: CampaignSummary[], record = vinaRecord()) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("/docking/batches/history")) {
      return json({
        engine: "autodock_vina", receptor_id: receptor.receptor_id,
        binding_site_id: bindingSite.binding_site_id, campaigns,
      });
    }
    // Nothing is auto-restored, so the history is the only way in.
    if (url.includes("/docking/batches/latest")) return new Response(null, { status: 404 });
    if (url.includes(`/docking/batches/${record.batch_id}`)) return json(record);
    return new Response(null, { status: 404 });
  });
}

function renderVina() {
  return render(
    <LibraryDockingWorkspace
      receptor={receptor}
      bindingSite={bindingSite}
      libraryInput={libraryInput}
      tools={tools}
    />,
  );
}

// --- AutoDock4 ----------------------------------------------------------

function autodock4Record(): AutoDock4BatchRecord {
  return {
    batch_id: "ad4-old", status: "completed", phase: "complete",
    created_at: "2026-08-21T09:30:00Z", started_at: null, completed_at: null,
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
    autodock4: {
      tool: { name: "AutoDock", version: "4.2.6" }, executable_path: "synthetic",
      sha256: "1".repeat(64), architecture: "x86",
      max_torsions: 32, max_atoms: 2048, max_maps: 16,
    },
    receptor_id: receptor.receptor_id, binding_site_id: bindingSite.binding_site_id,
    map_set_id: "map-set-1", map_set_identity_key: "f".repeat(64),
    selection_manifest_sha256: "c".repeat(64),
    selected_count: 1, worker_count: 8,
    completed_count: 1, succeeded_count: 1, failed_count: 0, canceled_count: 0,
    entries: [{
      ligand_id: "ligand-0", source_index: 0, name: "Restored Compound",
      canonical_smiles: "CC", molecular_weight_g_mol: 30,
      ligand_preparation_id: "prep-0", ligand_sha256: "d".repeat(64),
      ligand_atom_types: ["C", "OA"], status: "completed", phase: "complete",
      started_at: null, completed_at: null, command: [], dpf_sha256: null, execution: null,
      clusters: [{
        cluster_rank: 1, lowest_binding_energy_kcal_mol: -6.3,
        mean_binding_energy_kcal_mol: -6.3, run_count: 2, representative_run: 1, runs: [1, 2],
      }],
      runs: [{
        run: 1, cluster_rank: 1, sub_rank: 1, binding_energy_kcal_mol: -6.3,
        cluster_rmsd_angstrom: 0, reference_rmsd_angstrom: 10,
        artifact: {
          artifact_id: "ad4-pose-1", run: 1, filename: "run_1.pdbqt", format: "pdbqt",
          sha256: "e".repeat(64), size_bytes: 2100, content_url: "/ad4-pose-1",
        },
      }],
      failure: null, provenance: null, revision: 1,
    }],
    warnings: [], failure: null, provenance: null, revision: 4,
  };
}

function mockAutoDock4(campaigns: CampaignSummary[]) {
  const record = autodock4Record();
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("/docking/autodock4/batches/history")) {
      return json({
        engine: "autodock4", receptor_id: receptor.receptor_id,
        binding_site_id: bindingSite.binding_site_id, campaigns,
      });
    }
    if (url.includes("/docking/autodock4/batches/latest")) {
      return new Response(null, { status: 404 });
    }
    if (url.includes(`/docking/autodock4/batches/${record.batch_id}`)) return json(record);
    return new Response(null, { status: 404 });
  });
}

function renderAutoDock4() {
  return render(
    <AutoDock4LibraryWorkspace
      receptor={receptor}
      bindingSite={bindingSite}
      libraryInput={libraryInput}
      tools={tools}
    />,
  );
}

// --- tests --------------------------------------------------------------

it("offers every saved Vina campaign, not only the most recent one", async () => {
  mockVina([
    summary({ batch_id: "campaign-old", created_at: "2026-08-21T09:30:00Z", best_result_kcal_mol: -8.4 }),
    summary({ batch_id: "campaign-older", created_at: "2026-08-19T09:30:00Z", best_result_kcal_mol: -7.1 }),
  ]);
  renderVina();

  const list = await screen.findByRole("group", { name: "Saved campaigns" });
  const entries = within(list).getAllByRole("button");
  expect(entries).toHaveLength(2);
  expect(entries[0]).toHaveTextContent("-8.40");
  expect(entries[1]).toHaveTextContent("-7.10");
});

it("opens an earlier Vina campaign and shows its own results", async () => {
  mockVina([summary({ batch_id: "campaign-old" })]);
  renderVina();

  fireEvent.click(await screen.findByText("-8.40"));

  // The campaign's own molecule appears, from its own record.
  const results = await screen.findByRole("region", { name: "Virtual-screening docking results" });
  // The molecule and the score both come from the reopened record.
  expect(within(results).getByText(/currently ranks first/)).toHaveTextContent(
    "Restored Compound currently ranks first at -8.400 kcal/mol",
  );
});

it("opens an earlier AutoDock4 campaign and shows its own clusters", async () => {
  mockAutoDock4([
    summary({ batch_id: "ad4-old", engine: "autodock4", engine_version: "4.2.6", best_result_kcal_mol: -6.3, selected_count: 1, succeeded_count: 1 }),
  ]);
  renderAutoDock4();

  fireEvent.click(await screen.findByText("-6.30"));

  const results = await screen.findByRole("region", { name: "AutoDock4 campaign results" });
  expect(within(results).getByText(/currently ranks first/)).toHaveTextContent(
    "Restored Compound",
  );
});

it("says which engine's number each best result is", async () => {
  mockVina([summary()]);
  const view = renderVina();
  expect(await screen.findByText("best score kcal/mol")).toBeInTheDocument();
  view.unmount();
  vi.restoreAllMocks();

  mockAutoDock4([summary({ batch_id: "ad4-old", engine: "autodock4" })]);
  renderAutoDock4();
  expect(await screen.findByText("best energy kcal/mol")).toBeInTheDocument();
});

it("flags a campaign that docked a different selection", async () => {
  // Its results are real, but they are not the selection applied right now.
  mockVina([summary({ filter_run_id: "filter-earlier" })]);
  renderVina();

  expect(await screen.findByText("different selection")).toBeInTheDocument();
});

it("flags a campaign that used another site record for the same box", async () => {
  // Confirming one pocket twice writes two records; the reuse is stated.
  mockVina([summary({ same_site_record: false })]);
  renderVina();

  expect(await screen.findByText("same box, other site record")).toBeInTheDocument();
});

it("says plainly when a project has no saved campaign yet", async () => {
  mockVina([]);
  renderVina();

  expect(
    await screen.findByText(/No campaign has been saved for this receptor and search space yet/),
  ).toBeInTheDocument();
});

it("keeps a campaign that produced nothing visible rather than hiding it", async () => {
  mockVina([
    summary({
      batch_id: "canceled-one", status: "canceled",
      succeeded_count: 0, best_result_kcal_mol: null, best_ligand_name: null,
    }),
  ]);
  renderVina();

  const entry = await screen.findByRole("button", { name: /canceled/ });
  expect(entry).toHaveTextContent("0/2 docked");
  expect(entry).toHaveTextContent("—");
});

it("marks the open campaign and does not offer to reopen it", async () => {
  mockVina([summary({ batch_id: "campaign-old" })]);
  renderVina();

  fireEvent.click(await screen.findByText("-8.40"));

  await waitFor(() => {
    const entry = screen.getByText("-8.40").closest("button") as HTMLButtonElement;
    expect(entry).toHaveAttribute("aria-current", "true");
    expect(entry).toBeDisabled();
  });
});
