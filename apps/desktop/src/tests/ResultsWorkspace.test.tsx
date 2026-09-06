import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { ResultsWorkspace } from "../features/results/ResultsWorkspace";
import type {
  CatalogEntry,
  CatalogPage,
  CompoundPage,
  InteractionAnalysisRecord,
  PoseInventory,
} from "../types/api";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const baseEntry: CatalogEntry = {
  catalog_id: "vina_batch:vina-1",
  engine_key: "vina_batch",
  record_id: "vina-1",
  mode: "screening",
  scoring_family: "vina",
  backend: null,
  engine_label: "AutoDock Vina 1.2.7",
  engine_version: "1.2.7",
  executable_sha256: null,
  device_name: null,
  reproducibility: {
    status: "measured_reproducible",
    protocol: "ankora-reproducibility-v1",
    scope: "parsed scientific outputs and retained pose-artifact bytes",
    input_fingerprint_sha256: "a".repeat(64),
    executions: [
      { catalog_id: "vina_batch:vina-1", output_fingerprint_sha256: "b".repeat(64) },
      { catalog_id: "vina_batch:vina-2", output_fingerprint_sha256: "b".repeat(64) },
    ],
  },
  status: "completed",
  created_at: "2026-08-24T02:00:00Z",
  completed_at: "2026-08-24T02:30:00Z",
  receptor_id: "receptor-1abcdef0",
  binding_site_id: "site-1abcdef0",
  box: {
    center_x: 35.4, center_y: -2.9, center_z: -0.7,
    size_x: 21.6, size_y: 19.8, size_z: 19.3,
  },
  map_set_id: null,
  map_set_identity_key: null,
  library_id: "library-1",
  filter_run_id: "filter-1",
  selection_manifest_sha256: "c".repeat(64),
  ligand_id: null,
  selected_count: 283,
  succeeded_count: 282,
  failed_count: 1,
  canceled_count: 0,
  best_result_kcal_mol: -7.51,
  best_molecule: "Compound 288",
};

const gpuEntry: CatalogEntry = {
  ...baseEntry,
  catalog_id: "autodock_gpu_batch:gpu-1",
  engine_key: "autodock_gpu_batch",
  record_id: "gpu-1",
  scoring_family: "autodock4",
  backend: "autodock_gpu",
  engine_label: "AutoDock4 · AutoDock-GPU 1.6",
  engine_version: "1.6",
  executable_sha256: "2".repeat(64),
  device_name: "NVIDIA GeForce RTX 5050",
  reproducibility: {
    status: "measured_variable",
    protocol: "ankora-reproducibility-v1",
    scope: "parsed scientific outputs and retained pose-artifact bytes",
    input_fingerprint_sha256: "c".repeat(64),
    executions: [
      { catalog_id: "autodock_gpu_batch:gpu-1", output_fingerprint_sha256: "d".repeat(64) },
      { catalog_id: "autodock_gpu_batch:gpu-2", output_fingerprint_sha256: "e".repeat(64) },
    ],
  },
  created_at: "2026-08-26T15:47:00Z",
  map_set_id: "map-set-1",
  map_set_identity_key: "f".repeat(64),
  best_result_kcal_mol: -5.75,
  best_molecule: "Compound 100",
};

const page: CatalogPage = { entries: [gpuEntry, baseEntry], total: 2, offset: 0, limit: 25 };

const vinaCompounds: CompoundPage = {
  catalog_id: "vina_batch:vina-1",
  engine_label: "AutoDock Vina 1.2.7",
  value_label: "Vina score (kcal/mol)",
  rows: [
    {
      ligand_id: "ligand-287", source_index: 287, name: "Compound 288",
      canonical_smiles: "CCO", molecular_weight_g_mol: 46.1, status: "completed",
      failure_code: null, best_result_kcal_mol: -7.51,
      pose_count: 9, cluster_count: null, top_cluster_runs: null,
    },
    {
      ligand_id: "ligand-142", source_index: 142, name: "Compound 143",
      canonical_smiles: null, molecular_weight_g_mol: null, status: "failed",
      failure_code: "DOCKING_LIGAND_NOT_PREPARED", best_result_kcal_mol: null,
      pose_count: 0, cluster_count: null, top_cluster_runs: null,
    },
  ],
  total: 2,
  offset: 0,
  limit: 100,
};

const gpuCompounds: CompoundPage = {
  catalog_id: "autodock_gpu_batch:gpu-1",
  engine_label: "AutoDock4 · AutoDock-GPU 1.6",
  value_label: "Binding energy (kcal/mol)",
  rows: [
    {
      ligand_id: "ligand-99", source_index: 99, name: "Compound 100",
      canonical_smiles: "CCN", molecular_weight_g_mol: 45.0, status: "completed",
      failure_code: null, best_result_kcal_mol: -5.75,
      pose_count: null, cluster_count: 2, top_cluster_runs: 8,
    },
  ],
  total: 1,
  offset: 0,
  limit: 100,
};

function mock(compounds: CompoundPage = vinaCompounds, catalog: CatalogPage = page) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/compounds")) return json(compounds);
    return json(catalog);
  });
}

it("orders the catalog by time, never by result", async () => {
  // A Vina score sits several kcal/mol below an AutoDock4 binding energy for
  // the same molecule, so "best first" would put every Vina campaign on top
  // and read as a verdict about the engines.
  mock();
  render(<ResultsWorkspace />);

  const browser = await screen.findByRole("list", { name: "Recorded results" });
  const cards = within(browser).getAllByRole("listitem");

  expect(cards[0]).toHaveTextContent("AutoDock-GPU 1.6");
  expect(cards[0]).toHaveTextContent("-5.75");
  expect(cards[1]).toHaveTextContent("AutoDock Vina 1.2.7");
  expect(cards[1]).toHaveTextContent("-7.51");
  expect(
    screen.getByText(/not on a\s+shared scale/),
  ).toBeInTheDocument();
});

it("never shows a result without the engine that produced it", async () => {
  mock();
  render(<ResultsWorkspace />);

  const browser = await screen.findByRole("list", { name: "Recorded results" });
  const cards = within(browser).getAllByRole("listitem");

  expect(cards[0]).toHaveTextContent("best binding energy");
  expect(cards[1]).toHaveTextContent("best Vina score");
});

it("distinguishes measured variability from measured reproducibility", async () => {
  mock();
  render(<ResultsWorkspace />);

  const browser = await screen.findByRole("list", { name: "Recorded results" });
  const cards = within(browser).getAllByRole("listitem");

  expect(cards[0]).toHaveTextContent("Exact repeats produced different outputs");
  expect(cards[1]).not.toHaveTextContent("Repeat reproducibility not assessed");
});

it("loads a campaign's molecules only when it is opened", async () => {
  const fetcher = mock();
  render(<ResultsWorkspace />);

  const browser = await screen.findByRole("list", { name: "Recorded results" });
  expect(fetcher.mock.calls.every(([url]) => !String(url).includes("/compounds"))).toBe(true);

  fireEvent.click(within(browser).getAllByRole("listitem")[1]);

  await screen.findByRole("region", { name: "Molecules in this result" });
  expect(fetcher.mock.calls.some(([url]) => String(url).includes("/compounds"))).toBe(true);
});

it("keeps a campaign open when its card receives a double click", async () => {
  mock();
  render(<ResultsWorkspace />);

  const browser = await screen.findByRole("list", { name: "Recorded results" });
  const card = within(browser).getAllByRole("listitem")[1];

  // Native double-clicks dispatch two click events. The second one must not
  // toggle the selected campaign closed.
  fireEvent.click(card);
  await screen.findByRole("region", { name: "Molecules in this result" });
  fireEvent.click(card);

  expect(screen.getByRole("region", { name: "Molecules in this result" })).toBeInTheDocument();
  expect(card).toHaveAttribute("aria-pressed", "true");
  expect(screen.queryByRole("list", { name: "Recorded results" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Delete this result" })).toBeEnabled();

  fireEvent.click(screen.getByRole("button", { name: "All results" }));
  expect(screen.getByRole("list", { name: "Recorded results" })).toBeInTheDocument();
});

it("labels the value column with the engine's own quantity", async () => {
  mock();
  render(<ResultsWorkspace />);

  const browser = await screen.findByRole("list", { name: "Recorded results" });
  fireEvent.click(within(browser).getAllByRole("listitem")[1]);

  const table = await screen.findByRole("region", { name: "Molecules in this result" });
  const headers = within(table).getAllByRole("columnheader").map((cell) => cell.textContent);
  expect(headers).toContain("Vina score (kcal/mol)");
  expect(headers.some((header) => header === "Score")).toBe(false);
});

it("counts poses for Vina and clusters for AutoDock", async () => {
  mock(gpuCompounds);
  render(<ResultsWorkspace />);

  const browser = await screen.findByRole("list", { name: "Recorded results" });
  fireEvent.click(within(browser).getAllByRole("listitem")[0]);

  const table = await screen.findByRole("region", { name: "Molecules in this result" });
  const headers = within(table).getAllByRole("columnheader").map((cell) => cell.textContent);
  expect(headers).toContain("Clusters");
  expect(headers).toContain("Top cluster runs");
  expect(headers).not.toContain("Poses");
});

it("keeps a molecule that was never docked, unranked", async () => {
  mock();
  render(<ResultsWorkspace />);

  const browser = await screen.findByRole("list", { name: "Recorded results" });
  fireEvent.click(within(browser).getAllByRole("listitem")[1]);

  const table = await screen.findByRole("region", { name: "Molecules in this result" });
  const rows = within(table).getAllByRole("row").slice(1);
  const failed = within(rows[1]).getAllByRole("cell").map((cell) => cell.textContent);

  expect(failed[0]).toBe("—");            // no rank without a result
  expect(failed[2]).toBe("Compound 143"); // still a row
  expect(rows[1]).toHaveTextContent("DOCKING_LIGAND_NOT_PREPARED");
});

it("keeps manifest order beside the ranking that reordered it", async () => {
  mock();
  render(<ResultsWorkspace />);

  const browser = await screen.findByRole("list", { name: "Recorded results" });
  fireEvent.click(within(browser).getAllByRole("listitem")[1]);

  const table = await screen.findByRole("region", { name: "Molecules in this result" });
  const first = within(within(table).getAllByRole("row")[1]).getAllByRole("cell");

  expect(first[0]).toHaveTextContent("1");   // rank
  expect(first[1]).toHaveTextContent("288"); // which molecule this was
});

it("keeps the sideways scrollbar above the table in step with it", async () => {
  // The table is wider than the column, and a scrollbar only at the bottom of
  // a long table is one the reader has to go looking for.
  mock();
  render(<ResultsWorkspace />);

  const browser = await screen.findByRole("list", { name: "Recorded results" });
  fireEvent.click(within(browser).getAllByRole("listitem")[1]);
  await screen.findByRole("region", { name: "Molecules in this result" });

  const bar = screen.getByLabelText("Horizontal molecule table scroll");
  const table = screen.getByLabelText("Scrollable molecule table");

  bar.scrollLeft = 420;
  fireEvent.scroll(bar);
  expect(table.scrollLeft).toBe(420);

  table.scrollLeft = 130;
  fireEvent.scroll(table);
  expect(bar.scrollLeft).toBe(130);
});

it("shows the box rather than only the binding site identifier", async () => {
  // Confirming one pocket twice writes two records carrying the same box, so
  // the box is the part a reader can actually compare.
  mock();
  render(<ResultsWorkspace />);

  const browser = await screen.findByRole("list", { name: "Recorded results" });
  fireEvent.click(within(browser).getAllByRole("listitem")[1]);

  const inspector = await screen.findByRole("complementary", { name: "Results inspector" });
  expect(inspector).toHaveTextContent("35.4, -2.9, -0.7 Å");
  expect(inspector).toHaveTextContent("22×20×19 Å");
});

it("offers an export for a campaign and not for a single job", async () => {
  const singleJob: CatalogEntry = {
    ...baseEntry,
    catalog_id: "vina_job:job-1",
    engine_key: "vina_job",
    record_id: "job-1",
    mode: "single_ligand",
    ligand_id: "ligand-solo",
    selected_count: 1,
    succeeded_count: 1,
    failed_count: 0,
  };
  mock(vinaCompounds, { entries: [singleJob, baseEntry], total: 2, offset: 0, limit: 25 });
  render(<ResultsWorkspace />);

  const browser = await screen.findByRole("list", { name: "Recorded results" });
  fireEvent.click(within(browser).getAllByRole("listitem")[1]);
  await waitFor(() =>
    expect(screen.getByRole("region", { name: "Campaign export" })).toBeInTheDocument(),
  );

  fireEvent.click(screen.getByRole("button", { name: "All results" }));
  const reopenedBrowser = screen.getByRole("list", { name: "Recorded results" });
  fireEvent.click(within(reopenedBrowser).getAllByRole("listitem")[0]);
  await waitFor(() =>
    expect(screen.queryByRole("region", { name: "Campaign export" })).not.toBeInTheDocument(),
  );
});

it("survives a project with nothing recorded in it", async () => {
  mock(vinaCompounds, { entries: [], total: 0, offset: 0, limit: 25 });
  render(<ResultsWorkspace />);

  expect(await screen.findByText("No results recorded yet")).toBeInTheDocument();
});

it("deletes one result or a multiple selection as one acknowledged Trash operation", async () => {
  let activeEntries = [...page.entries];
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/results/campaigns/trash") && init?.method === "POST") {
      const request = JSON.parse(String(init.body)) as {
        catalog_ids: string[];
        acknowledge_removal: boolean;
      };
      activeEntries = activeEntries.filter(
        (entry) => !request.catalog_ids.includes(entry.catalog_id),
      );
      return json({
        operation_id: "trash-operation-1",
        trashed_at: "2026-08-27T20:00:00Z",
        campaigns: request.catalog_ids.map((catalogId) => {
          const entry = page.entries.find((item) => item.catalog_id === catalogId)!;
          return {
            catalog_id: catalogId,
            engine_label: entry.engine_label,
            status: entry.status,
          };
        }),
        interaction_analysis_count: 1,
        redocking_validation_count: 0,
        exports_preserved: true,
        recoverable: true,
      });
    }
    if (url.includes("/compounds")) return json(vinaCompounds);
    return json({ ...page, entries: activeEntries, total: activeEntries.length });
  });
  render(<ResultsWorkspace />);

  fireEvent.click(await screen.findByRole("button", { name: "Select multiple" }));
  const browser = screen.getByRole("list", { name: "Recorded results" });
  const cards = within(browser).getAllByRole("listitem");

  fireEvent.click(cards[0]);
  expect(screen.getByRole("button", { name: "Delete 1" })).toBeEnabled();
  fireEvent.click(cards[1]);
  fireEvent.click(screen.getByRole("button", { name: "Delete 2" }));

  const dialog = screen.getByRole("dialog", { name: "Delete 2 results?" });
  expect(dialog).toHaveTextContent("dependent pose analyses or redocking validations");
  expect(dialog).toHaveTextContent("export bundles are not deleted");
  expect(within(dialog).getByRole("button", { name: "Keep results" })).toHaveFocus();
  const confirm = within(dialog).getByRole("button", { name: "Delete 2" });
  expect(confirm).toBeDisabled();
  fireEvent.click(within(dialog).getByRole("checkbox", {
    name: /Remove this exact selection from active Results/,
  }));
  fireEvent.click(confirm);

  expect(await screen.findByText("No results recorded yet")).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("2 results moved to Trash");
  expect(screen.getByRole("status")).toHaveTextContent("1 pose analysis moved with them");
  expect(screen.getByRole("status")).toHaveTextContent("Export bundles remain");
  await waitFor(() => expect(screen.getByLabelText("Results workspace")).toHaveFocus());
  const removal = fetcher.mock.calls.find(([url]) =>
    String(url).endsWith("/results/campaigns/trash")
  );
  expect(JSON.parse(String(removal?.[1]?.body))).toEqual({
    catalog_ids: [gpuEntry.catalog_id, baseEntry.catalog_id],
    acknowledge_removal: true,
  });
});

it("explains when a stale backend does not yet expose direct result deletion", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/results/campaigns/trash") && init?.method === "POST") {
      return json({ detail: "Not Found" }, 404);
    }
    return json(page);
  });
  render(<ResultsWorkspace />);

  const catalogDelete = await screen.findByRole("button", { name: "Delete open result" });
  expect(catalogDelete).toBeDisabled();
  const browser = screen.getByRole("list", { name: "Recorded results" });
  fireEvent.click(within(browser).getAllByRole("listitem")[0]);
  const directDelete = screen.getByRole("button", { name: "Delete this result" });
  expect(directDelete).toBeEnabled();
  fireEvent.click(directDelete);

  const dialog = screen.getByRole("dialog", { name: "Delete 1 result?" });
  fireEvent.click(within(dialog).getByRole("checkbox", {
    name: /Remove this exact selection from active Results/,
  }));
  fireEvent.click(within(dialog).getByRole("button", { name: "Delete 1" }));

  await waitFor(() => expect(fetcher).toHaveBeenCalledWith(
    expect.stringContaining("/results/campaigns/trash"),
    expect.objectContaining({ method: "POST" }),
  ));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Close and restart Ankora to load the updated backend",
  );
  expect(screen.getByRole("alert")).toHaveTextContent("No result was removed");
});

it("opens an exact pose and records its structured ProLIF contacts", async () => {
  const poses: PoseInventory = {
    catalog_id: baseEntry.catalog_id,
    ligand_id: "ligand-287",
    engine_label: baseEntry.engine_label,
    receptor_artifact_id: "receptor-pdb",
    receptor_content_url: "/receptors/receptor-1/outputs/receptor-pdb/content",
    poses: [{
      artifact_id: "pose-1", kind: "vina_mode", ordinal: 1, label: "Mode 1",
      result_kcal_mol: -7.51, value_label: "Vina score", cluster_rank: null,
      sub_rank: null, rmsd_lower_bound_angstrom: 0, rmsd_upper_bound_angstrom: 0,
      cluster_rmsd_angstrom: null, reference_rmsd_angstrom: null,
      sha256: "a".repeat(64), content_url: "/docking/pose-1/content",
    }],
  };
  const analysis: InteractionAnalysisRecord = {
    analysis_id: "analysis-1", created_at: "2026-08-26T20:00:00Z",
    catalog_id: baseEntry.catalog_id, engine_key: baseEntry.engine_key,
    record_id: baseEntry.record_id, engine_label: baseEntry.engine_label,
    ligand_id: "ligand-287", ligand_preparation_id: "prep-1",
    conformer_id: "conformer-1", conformer_sha256: "b".repeat(64),
    pose: poses.poses[0], receptor_id: baseEntry.receptor_id,
    docking_receptor_artifact_id: "receptor-pdbqt",
    docking_receptor_sha256: "c".repeat(64),
    analysis_receptor_artifact_id: "receptor-pdb",
    analysis_receptor_sha256: "d".repeat(64),
    analysis_receptor_content_url: poses.receptor_content_url!,
    detector: { name: "ProLIF", version: "2.2.1" },
    profile: { profile_id: "ankora-default-v1", vicinity_cutoff_angstrom: 6, interactions: ["Hydrophobic"] },
    contacts: [{
      contact_id: "contact-1", detector_type: "Hydrophobic", display_type: "Hydrophobic",
      residue: { chain_id: "A", residue_name: "TRP", sequence_number: 139, insertion_code: "" },
      ligand_atom_indices: [0], protein_atom_indices: [2191],
      ligand_atom_labels: ["C1"], protein_atom_labels: ["CZ2"],
      distance_angstrom: 3.7, geometry: { distance: 3.7 },
      ligand_point: { x: 1, y: 2, z: 3 }, protein_point: { x: 4, y: 5, z: 6 },
    }, {
      contact_id: "contact-2", detector_type: "HBAcceptor", display_type: "H-bond · ligand acceptor",
      residue: { chain_id: "A", residue_name: "HIS", sequence_number: 143, insertion_code: "" },
      ligand_atom_indices: [1], protein_atom_indices: [2240],
      ligand_atom_labels: ["N2"], protein_atom_labels: ["NE2"],
      distance_angstrom: 2.9, geometry: { distance: 2.9, DHA_angle: 151.2 },
      // An analysis recorded before Ankora drew contacts in 3D.
      ligand_point: null, protein_point: null,
    }],
    ligand_diagram: {
      atoms: [
        { atom_index: 0, element: "C", label: "C1", x: 0, y: 0 },
        { atom_index: 1, element: "N", label: "N2", x: 1.2, y: 0 },
        { atom_index: 2, element: "H", label: "H3", x: 1.8, y: 0.6 },
        { atom_index: 3, element: "O", label: "O4", x: -1.2, y: 0 },
      ],
      bonds: [
        { begin_atom_index: 0, end_atom_index: 1, order: 1 },
        { begin_atom_index: 1, end_atom_index: 2, order: 1 },
        { begin_atom_index: 0, end_atom_index: 3, order: 2 },
      ],
    },
    warnings: [],
    provenance: {
      event_id: "event-1", event_type: "pose_interactions_analyzed",
      timestamp: "2026-08-26T20:00:00Z", input_artifacts: [], output_artifacts: ["analysis-1"],
      tool: { name: "ProLIF", version: "2.2.1" }, parameters: {}, warnings: [], command: null,
    },
  };
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/poses")) return json(poses);
    if (url.endsWith("/interactions") && init?.method === "POST") return json(analysis, 201);
    if (url.endsWith("/interactions")) return json([]);
    if (url.includes("/compounds?")) return json(vinaCompounds);
    return json(page);
  });
  render(<ResultsWorkspace />);

  const browser = await screen.findByRole("list", { name: "Recorded results" });
  fireEvent.click(within(browser).getAllByRole("listitem")[1]);
  const molecules = await screen.findByRole("region", { name: "Molecules in this result" });
  fireEvent.click(within(molecules).getByText("Compound 288"));

  const panel = await screen.findByRole("region", { name: "Pose interactions for Compound 288" });
  expect(screen.getByRole("heading", { name: "Pose interactions · Compound 288" })).toBeInTheDocument();
  expect(screen.getByText("M9 · pose interactions")).toBeInTheDocument();
  expect(screen.queryByRole("list", { name: "Recorded results" })).not.toBeInTheDocument();
  expect(within(panel).getByRole("combobox", { name: "Exact pose / run" })).toHaveTextContent("Mode 1");
  fireEvent.click(within(panel).getByRole("button", { name: "Analyze this pose with ProLIF" }));

  await waitFor(() => expect(fetcher.mock.calls.some(([, init]) => init?.method === "POST")).toBe(true));
  const diagram = await within(panel).findByRole("img", { name: "2D pose interaction diagram" });
  expect(diagram).toBeInTheDocument();
  expect(diagram.querySelector(".ligand-diagram-atoms .element-c")).toBeNull();
  expect(diagram.querySelector(".ligand-diagram-atoms .element-h")).toBeNull();
  expect(diagram.querySelector(".ligand-diagram-atoms .element-n text")).toHaveTextContent("N");
  expect(diagram.querySelector(".ligand-diagram-atoms .element-o text")).toHaveTextContent("O");
  expect(diagram.querySelectorAll(".ligand-diagram-bonds .bond-order-2 line")).toHaveLength(2);
  expect(within(panel).getAllByText("TRP A:139")).toHaveLength(2);
  expect(within(panel).getByText("ProLIF 2.2.1")).toBeInTheDocument();
  expect(within(panel).getByRole("combobox", { name: "Recorded analysis" })).toHaveValue("analysis-1");
  expect(within(panel).getByText("DHA angle 151.2°")).toBeInTheDocument();
  expect(within(panel).getByText("b".repeat(64))).toBeInTheDocument();
  expect(within(panel).getByText("1 recorded contact · receptor shown as context")).toBeInTheDocument();
  expect(within(panel).getByRole("button", { name: "Center on interaction site" })).toBeEnabled();

  const evidence = within(panel).getByRole("region", { name: "Pose interaction evidence" });
  expect(within(evidence).getAllByRole("row")[1]).toHaveTextContent("HIS A:143");
  fireEvent.click(within(evidence).getByRole("button", { name: "Residue ↑" }));
  expect(within(evidence).getAllByRole("row")[1]).toHaveTextContent("TRP A:139");

  // Every plane says where it is and offers the way back. Reaching an analysis
  // used to leave no visible route to the catalog at all: the only way out was
  // to leave Results entirely and come back through another step.
  const trail = screen.getByRole("navigation", { name: "Results navigation" });
  expect(within(trail).getByRole("button", { name: "All results" })).toBeInTheDocument();
  expect(within(trail).getByRole("button", { name: "AutoDock Vina 1.2.7" })).toBeInTheDocument();
  expect(within(trail).getByText("Compound 288")).toHaveAttribute("aria-current", "page");

  // One step back is the molecules of this result...
  fireEvent.click(within(trail).getByRole("button", { name: "AutoDock Vina 1.2.7" }));
  expect(screen.getByRole("region", { name: "Molecules in this result" })).toBeInTheDocument();
  expect(screen.queryByRole("list", { name: "Recorded results" })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "All results" }));
  expect(await screen.findByRole("list", { name: "Recorded results" })).toBeInTheDocument();
});

it("returns to the catalog in one step from an open analysis", async () => {
  // The reported dead end: from an analysis the reader had to go to Structure
  // and back into Results to reach another result.
  const poses = {
    catalog_id: baseEntry.catalog_id, ligand_id: "ligand-287",
    engine_label: "AutoDock Vina 1.2.7",
    receptor_artifact_id: "receptor-pdb", receptor_content_url: "/receptor",
    poses: [{
      artifact_id: "pose-1", kind: "vina_mode", ordinal: 1, label: "Mode 1",
      result_kcal_mol: -7.51, value_label: "Vina score", cluster_rank: null,
      sub_rank: null, rmsd_lower_bound_angstrom: null, rmsd_upper_bound_angstrom: null,
      cluster_rmsd_angstrom: null, reference_rmsd_angstrom: null,
      sha256: "a".repeat(64), content_url: "/docking/pose-1/content",
    }],
  };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith("/poses")) return json(poses);
    if (url.endsWith("/interactions")) return json([]);
    if (url.includes("/compounds?")) return json(vinaCompounds);
    return json(page);
  });
  render(<ResultsWorkspace />);

  const browser = await screen.findByRole("list", { name: "Recorded results" });
  fireEvent.click(within(browser).getAllByRole("listitem")[1]);
  const molecules = await screen.findByRole("region", { name: "Molecules in this result" });
  fireEvent.click(within(molecules).getByText("Compound 288"));
  await screen.findByRole("region", { name: "Pose interactions for Compound 288" });

  fireEvent.click(screen.getByRole("button", { name: "All results" }));

  expect(await screen.findByRole("list", { name: "Recorded results" })).toBeInTheDocument();
  expect(
    screen.queryByRole("region", { name: "Pose interactions for Compound 288" }),
  ).not.toBeInTheDocument();
});
