import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { AutoDock4LibraryWorkspace } from "../features/docking/AutoDock4LibraryWorkspace";
import { AutoDock4Workspace } from "../features/docking/AutoDock4Workspace";
import { CampaignExportPanel } from "../features/docking/CampaignExportPanel";
import { DockingWorkspace } from "../features/docking/DockingWorkspace";
import { cpuBinding, gpuBinding } from "../features/docking/autodockBackend";
import { ConsensusWorkspace } from "../features/results/ConsensusWorkspace";
import { ResultsWorkspace } from "../features/results/ResultsWorkspace";
import type {
  AutoDockGpuBatchRecord,
  BindingSiteRecord,
  CatalogEntry,
  LigandDockingInput,
  LigandLibraryDockingInput,
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

const receptor = {
  receptor_id: "receptor-synthetic",
  source_artifact_id: "source-synthetic",
  created_at: "2026-08-24T00:00:00Z",
  status: "docking_ready",
  decisions: {
    selected_chains: ["A"],
    water_action: "remove",
    component_decisions: [],
    issue_decisions: [],
    reference_component_id: null,
    relaxation: { enabled: false, restraint_force_constant_kcal_mol_a2: 50, max_iterations: 200 },
    protonation: { enabled: true, ph: 7.4, force_field: "AMBER" },
    generate_pdbqt: true,
  },
  outputs: [
    {
      artifact_id: "display-pdb",
      stage: "protonated_pdb",
      filename: "receptor.pdb",
      format: "pdb",
      sha256: "a".repeat(64),
      size_bytes: 100,
      created_at: "2026-08-24T00:00:00Z",
      content_url: "/receptor.pdb",
    },
    {
      artifact_id: "receptor-pdbqt",
      stage: "pdbqt",
      filename: "receptor.pdbqt",
      format: "pdbqt",
      sha256: "b".repeat(64),
      size_bytes: 120,
      created_at: "2026-08-24T00:00:00Z",
      content_url: "/receptor.pdbqt",
    },
  ],
  warnings: [],
  provenance: [],
  display_output_artifact_id: "display-pdb",
} satisfies ReceptorPreparationRecord;

const baseSite = {
  binding_site_id: "binding-synthetic",
  receptor_id: receptor.receptor_id,
  source_artifact_id: "display-pdb",
  created_at: "2026-08-24T00:00:00Z",
  decisions: {
    source: "manual",
    ligand_origin: null,
    residue_selection: null,
    manual_box: { center_x: 1, center_y: 2, center_z: 3, size_x: 20, size_y: 22, size_z: 24 },
    blind_margin_angstrom: 6,
    pocket_selection: null,
    parent_binding_site_id: null,
  },
  box: { center_x: 1, center_y: 2, center_z: 3, size_x: 20, size_y: 22, size_z: 24 },
  stale: false,
  warnings: [],
  provenance: [],
} satisfies BindingSiteRecord;

const ligand = {
  artifact: {
    ligand_id: "lig-1",
    filename: "lig.smi",
    format: "smi",
    sha256: "c".repeat(64),
    size_bytes: 12,
    created_at: "2026-08-24T00:00:00Z",
  },
  inspection: {
    name: "Synthetic Ligand",
    canonical_smiles: "CCO",
    molecular_formula: "C2H6O",
    molecular_weight_g_mol: 46.07,
    heavy_atom_count: 3,
    formal_charge: 0,
    rotatable_bonds: 0,
    hbd_count: 1,
    hba_count: 1,
    tpsa_angstrom2: 20.23,
    crippen_clogp: -0.001,
    lipinski_violations: 0,
    has_3d_coordinates: false,
    atom_count: 3,
    bond_count: 2,
    warnings: [],
  },
  warnings: [],
  provenance: [],
} as unknown as LigandRecord;

const ligandInput = {
  ligand_id: "lig-1",
  conformer: null,
  pdbqt: {
    artifact: {
      preparation_id: "prep-1",
      ligand_id: "lig-1",
      conformer_id: "conf-1",
      filename: "lig.pdbqt",
      format: "pdbqt",
      sha256: "d".repeat(64),
      size_bytes: 200,
      created_at: "2026-08-24T00:00:00Z",
    },
  },
} as unknown as LigandDockingInput;

const libraryInput = {
  library_id: "library-1",
  library_name: "Synthetic Library",
  filter_run_id: "filter-1",
  selection_manifest_sha256: "e".repeat(64),
  selected_count: 2,
  prepared_count: 2,
} as LigandLibraryDockingInput;

const gpuOnlyTools = {
  vina: { available: true, path: "synthetic", version: "1.2.7" },
  gnina: { available: false, path: null, version: null },
  autogrid4: { available: true, path: "synthetic", version: "4.2.6" },
  autodock4: { available: false, path: null, version: null },
  autodock_gpu: { available: true, path: "synthetic-gpu", version: "1.6" },
  pdbfixer: { available: true, path: "synthetic", version: "1" },
  pdb2pqr: { available: true, path: "synthetic", version: "1" },
  propka: { available: true, path: "synthetic", version: "1" },
  meeko: { available: true, path: "synthetic", version: "1" },
  meeko_ligand: { available: true, path: "synthetic", version: "1" },
  p2rank: { available: true, path: "synthetic", version: "1" },
} satisfies ToolsResponse;

const staleEntry: CatalogEntry = {
  catalog_id: "vina_batch:vina-stale",
  engine_key: "vina_batch",
  record_id: "vina-stale",
  mode: "screening",
  scoring_family: "vina",
  backend: null,
  engine_label: "AutoDock Vina 1.2.7",
  engine_version: "1.2.7",
  executable_sha256: null,
  device_name: null,
  reproducibility: {
    status: "not_assessed",
    protocol: "ankora-reproducibility-v1",
    scope: "parsed scientific outputs",
    input_fingerprint_sha256: "a".repeat(64),
    executions: [],
  },
  status: "completed",
  created_at: "2026-08-24T02:00:00Z",
  completed_at: "2026-08-24T02:30:00Z",
  receptor_id: receptor.receptor_id,
  binding_site_id: baseSite.binding_site_id,
  box: baseSite.box,
  map_set_id: null,
  map_set_identity_key: null,
  library_id: "library-1",
  filter_run_id: "filter-1",
  selection_manifest_sha256: "c".repeat(64),
  ligand_id: null,
  selected_count: 10,
  succeeded_count: 10,
  failed_count: 0,
  canceled_count: 0,
  best_result_kcal_mol: -7.5,
  best_molecule: "Compound 1",
  stale: true,
  stale_reasons: ["Upstream receptor preparation changed"],
};

describe("Wave 3 D8 Desktop UI parity regressions", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("D8-018: resets CampaignExportPanel bundle and error when sourceId changes", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      json({
        exported_at: "2026-11-26T12:00:00Z",
        source_kind: "vina_batch",
        source_id: "batch-alpha",
        export_id: "export-alpha",
        catalog_id: "vina_batch:batch-alpha",
        display_name: "Alpha Bundle",
        input_identity_sha256: "a".repeat(64),
        bundle_identity_sha256: "b".repeat(64),
        archive_filename: "alpha.zip",
        engine: "AutoDock Vina",
        engine_version: "1.2.7",
        reproducibility: staleEntry.reproducibility,
        row_count: 2,
        interaction_analysis_count: 0,
        figure_count: 0,
        directory: "/tmp/alpha",
        outside_project: false,
        record_directory: "/tmp/alpha",
        files: ["alpha.zip", "results.csv"],
      }),
    );

    const { rerender } = render(
      <CampaignExportPanel sourceKind="vina_batch" sourceId="batch-alpha" ready />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Export this campaign" }));
    await screen.findByText("Alpha Bundle");
    expect(screen.getByRole("link", { name: "alpha.zip" })).toBeInTheDocument();

    rerender(<CampaignExportPanel sourceKind="vina_batch" sourceId="batch-beta" ready />);
    expect(screen.queryByText("Alpha Bundle")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "alpha.zip" })).not.toBeInTheDocument();
  });

  it("D8-016: surfaces stale lineage on ResultsWorkspace cards, Evidence, and ConsensusWorkspace picker", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("/results/campaigns?")) {
        return Promise.resolve(json({ entries: [staleEntry], total: 1, offset: 0, limit: 25 }));
      }
      if (url.includes("/compounds?")) {
        return Promise.resolve(json({ entries: [], total: 0, offset: 0, limit: 50 }));
      }
      if (url.includes("/exports?")) {
        return Promise.resolve(json({ entries: [], total: 0, offset: 0, limit: 25 }));
      }
      if (url.includes("/consensus/runs")) {
        return Promise.resolve(json({ runs: [] }));
      }
      if (url.includes("/calibrations")) {
        return Promise.resolve(json({ runs: [] }));
      }
      return Promise.resolve(json({}));
    });

    const { unmount } = render(<ResultsWorkspace />);
    await screen.findByText(/Stale lineage · Upstream receptor preparation changed/);
    fireEvent.click(screen.getByRole("listitem"));
    expect(await screen.findByText("STALE_SOURCE_ARTIFACT")).toBeInTheDocument();
    unmount();

    render(<ConsensusWorkspace campaigns={[staleEntry]} />);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /New consensus run/i })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /New consensus run/i }));
    await screen.findByText(/stale lineage/i);
    const checkbox = screen.getByRole("checkbox", { name: /AutoDock Vina 1\.2\.7/i });
    fireEvent.click(checkbox);
    expect(
      await screen.findByText(/One or more selected source campaigns have stale upstream lineage/i),
    ).toBeInTheDocument();
  });

  it("D8-017: queries AutoDock-GPU campaign history and renders batch-level failure banner", async () => {
    const requestedUrls: string[] = [];
    const failedGpuBatch: AutoDockGpuBatchRecord = {
      batch_id: "gpu-batch-fail",
      backend: "autodock_gpu",
      status: "failed",
      phase: "complete",
      created_at: "2026-08-26T15:47:00Z",
      started_at: null,
      completed_at: "2026-08-26T15:48:00Z",
      request: {
        receptor_id: receptor.receptor_id,
        binding_site_id: baseSite.binding_site_id,
        map_set_id: "map-set-1",
        library_id: libraryInput.library_id,
        filter_run_id: libraryInput.filter_run_id,
        parameters: {
          runs: 10,
          population_size: 150,
          energy_evaluations: 2_500_000,
          heuristics: false,
          autostop: false,
          local_search_method: "ad",
          cluster_rmsd_tolerance_angstrom: 2,
          seed_1: 1,
          seed_2: 2,
          seed_3: 3,
          device_number: 1,
          timeout_minutes: 60,
        },
        acknowledge_inputs_and_scoring: true,
      },
      autodock_gpu: {
        tool: { name: "AutoDock-GPU", version: "1.6" },
        executable_path: "synthetic-gpu",
        sha256: "1".repeat(64),
        architecture: "x86_64",
        build: "Release",
        device_number: 1,
        device_name: "Synthetic GPU",
      },
      receptor_id: receptor.receptor_id,
      binding_site_id: baseSite.binding_site_id,
      map_set_id: "map-set-1",
      map_set_identity_key: "f".repeat(64),
      selection_manifest_sha256: libraryInput.selection_manifest_sha256,
      selected_count: 2,
      worker_count: 1,
      bitwise_reproducible: false,
      completed_count: 2,
      succeeded_count: 0,
      failed_count: 2,
      canceled_count: 0,
      command: [],
      execution: null,
      entries: [],
      warnings: [],
      failure: {
        code: "AUTODOCK_GPU_CAMPAIGN_FAILED",
        message: "Synthetic GPU batch failure banner.",
        details: {},
      },
      provenance: null,
      revision: 2,
    };

    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      requestedUrls.push(url);
      if (url.includes("/docking/autodock-gpu/batches/history")) {
        return Promise.resolve(
          json({
            engine: "autodock_gpu",
            receptor_id: receptor.receptor_id,
            binding_site_id: baseSite.binding_site_id,
            campaigns: [],
          }),
        );
      }
      if (url.includes("/docking/autodock4/batches/history")) {
        return Promise.resolve(
          json({
            engine: "autodock4",
            receptor_id: receptor.receptor_id,
            binding_site_id: baseSite.binding_site_id,
            campaigns: [],
          }),
        );
      }
      if (url.includes("/docking/autodock-gpu/batches/latest")) {
        return Promise.resolve(json(failedGpuBatch));
      }
      return Promise.resolve(json({ detail: "not found" }, 404));
    });

    render(
      <AutoDock4LibraryWorkspace
        receptor={receptor}
        bindingSite={baseSite}
        libraryInput={libraryInput}
        tools={{ ...gpuOnlyTools, autodock4: { available: true, path: "cpu", version: "4.2.6" } }}
      />,
    );
    fireEvent.click(screen.getByRole("radio", { name: /GPU · AutoDock-GPU 1\.6/i }));
    await screen.findByText("Synthetic GPU batch failure banner.");
    expect(screen.getByText("AUTODOCK_GPU_CAMPAIGN_FAILED")).toBeInTheDocument();
    expect(
      requestedUrls.some((url) => url.includes("/docking/autodock-gpu/batches/history")),
    ).toBe(true);
  });

  it("D8-019: rejects regressive revisions in cpuBinding and gpuBinding progress polling", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json({ batch_id: "b1", status: "running", revision: 4 }))
      .mockResolvedValueOnce(json({ batch_id: "b1", status: "running", revision: 6 }))
      .mockResolvedValueOnce(json({ batch_id: "b2", status: "running", revision: 4 }))
      .mockResolvedValueOnce(json({ batch_id: "b2", status: "running", revision: 6 }));

    expect(await cpuBinding.getProgressRevision("b1", 5)).toBeNull();
    expect(await cpuBinding.getProgressRevision("b1", 5)).toBe(6);
    expect(await gpuBinding.getProgressRevision("b2", 5)).toBeNull();
    expect(await gpuBinding.getProgressRevision("b2", 5)).toBe(6);
  });

  it("D8-020: blocks stale binding sites in Vina and enables GPU-only systems & resets acknowledgement in AD4", () => {
    const staleSite: BindingSiteRecord = { ...baseSite, stale: true };
    const { unmount } = render(
      <DockingWorkspace
        receptor={receptor}
        bindingSite={staleSite}
        ligand={ligand}
        ligandInput={ligandInput}
        libraryInput={null}
        tools={gpuOnlyTools}
      />,
    );
    expect(
      screen.getByText("Stale — confirm a current binding site before docking."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByRole("button", { name: /Run AutoDock Vina/i })).toBeDisabled();
    unmount();

    render(
      <AutoDock4Workspace
        receptor={receptor}
        bindingSite={baseSite}
        ligand={ligand}
        ligandInput={ligandInput}
        tools={gpuOnlyTools}
      />,
    );
    // Switch to available GPU backend on a GPU-only machine (autodock4 unavailable)
    fireEvent.click(screen.getByRole("radio", { name: /GPU · AutoDock-GPU 1\.6/i }));
    expect(
      screen.getByRole("button", { name: "Generate affinity maps" }),
    ).not.toBeDisabled();
    expect(screen.getByText("1.6")).toBeInTheDocument();

    const ackCheckbox = screen.getByRole("checkbox", {
      name: /Use these exact inputs and parameters/i,
    });
    fireEvent.click(ackCheckbox);
    expect(ackCheckbox).toBeChecked();

    // Changing a parameter resets acknowledgement
    const runsInput = screen.getByLabelText("Independent runs");
    fireEvent.change(runsInput, { target: { value: "20" } });
    expect(ackCheckbox).not.toBeChecked();
  });
});
