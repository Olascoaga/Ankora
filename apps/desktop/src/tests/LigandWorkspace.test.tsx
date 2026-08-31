import { useState } from "react";

import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { LigandWorkspace } from "../features/ligand/LigandWorkspace";
import type {
  LigandChemicalStateRecord,
  LigandConformerRecord,
  LigandFilterEvaluation,
  LigandLibraryFilterPreview,
  LigandLibraryFilterRun,
  LigandLibraryRecord,
  LigandRecord,
  LigandStateResolutionOptions,
  StructureRecord,
  ToolsResponse,
} from "../types/api";

function json(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

// LigandWorkspace treats `record` as a controlled prop; a real parent owns the
// state. This harness plays that role so selecting a ligand actually updates
// what's rendered, instead of silently no-op'ing against a static prop.
function LigandWorkspaceHarness(props: Omit<Parameters<typeof LigandWorkspace>[0], "record" | "onRecordChange">) {
  const [record, setRecord] = useState<LigandRecord | null>(null);
  return <LigandWorkspace {...props} record={record} onRecordChange={setRecord} />;
}

const structure = {
  artifact: { artifact_id: "source", original_filename: "source.cif", format: "mmcif", sha256: "a".repeat(64), size_bytes: 100, source: "local", source_uri: null, imported_at: "2026-08-19T00:00:00Z" },
  metadata: { entry_id: "SYN", title: "Synthetic test structure", experimental_method: "SYNTHETIC", resolution_angstrom: null, model_count: 1, atom_count: 1, residue_count: 1, chains: [], heterogens: [], alternate_location_atom_count: 0, missing_residue_count: 0, missing_atom_count: 0, nonstandard_polymer_residues: [] },
  warnings: [],
  provenance: { event_id: "source", event_type: "structure_imported", timestamp: "2026-08-19T00:00:00Z", input_artifacts: [], output_artifacts: ["source"], tool: { name: "synthetic", version: "1" }, parameters: {}, warnings: [], command: null },
  content_url: "/structures/source/content",
} satisfies StructureRecord;

const tools = {
  vina: { available: false, path: null, version: null },
  gnina: { available: false, path: null, version: null },
  autogrid4: { available: false, path: null, version: null },
  autodock4: { available: false, path: null, version: null },
  autodock_gpu: { available: false, path: null, version: null },
  pdbfixer: { available: false, path: null, version: null },
  pdb2pqr: { available: false, path: null, version: null },
  propka: { available: false, path: null, version: null },
  meeko: { available: false, path: null, version: null },
  meeko_ligand: { available: false, path: null, version: "0.7.1" },
  p2rank: { available: false, path: null, version: null },
} satisfies ToolsResponse;

function ligand(index: number, name: string, smiles: string, formula: string, mass: number): LigandRecord {
  const ligandId = `ligand-${index}`;
  const stateId = `state-${index}`;
  return {
    artifact: { ligand_id: ligandId, source: "local", source_structure_id: null, locator: null, filename: `${name}.sdf`, format: "sdf", sha256: String(index).repeat(64), size_bytes: 100, created_at: "2026-08-19T00:00:00Z", library_id: "library-1", library_record_index: index },
    state: { state_id: stateId, ligand_id: ligandId, filename: "inspected_state.sdf", format: "sdf", sha256: "b".repeat(64), size_bytes: 100, created_at: "2026-08-19T00:00:00Z" },
    inspection: { name, formula, molecular_weight_g_mol: mass, exact_mass_da: mass, formal_charge: 0, atom_count: 3, heavy_atom_count: 3, rotatable_bond_count: 1, aromatic_ring_count: 0, stereocenter_count: 0, undefined_stereocenter_count: 0, fragment_count: 1, conformer_count: 0, has_3d_coordinates: false, canonical_smiles: smiles },
    warnings: [],
    provenance: { event_id: ligandId, event_type: "local_ligand_imported", timestamp: "2026-08-19T00:00:00Z", input_artifacts: ["library-1"], output_artifacts: [ligandId], tool: { name: "synthetic", version: "1" }, parameters: {}, warnings: [], command: null },
    content_url: `/ligands/${ligandId}/states/${stateId}/content`,
    original_content_url: `/ligands/${ligandId}/content`,
  };
}

function conformer(source: LigandRecord, energy: number): LigandConformerRecord {
  return {
    artifact: { conformer_id: `conformer-${source.artifact.ligand_id}`, ligand_id: source.artifact.ligand_id, stage: "generated_minimized", filename: "prepared.sdf", format: "sdf", sha256: "c".repeat(64), size_bytes: 200, created_at: "2026-08-19T00:00:00Z" },
    inspection: { ...source.inspection, conformer_count: 1, has_3d_coordinates: true },
    minimization: { force_field: "MMFF94s", max_iterations: 500, converged: true, initial_energy_kcal_mol: energy + 10, final_energy_kcal_mol: energy, embedding_method: "ETKDGv3", random_seed: 20260819, independent_from_source_coordinates: true, conformer_pool_size: 20 },
    warnings: [],
    provenance: { event_id: `conformer-${source.artifact.ligand_id}`, event_type: "ligand_conformer_generated_and_minimized", timestamp: "2026-08-19T00:00:00Z", input_artifacts: [source.state?.state_id ?? ""], output_artifacts: [], tool: { name: "synthetic", version: "1" }, parameters: {}, warnings: [], command: null },
    content_url: `/ligands/${source.artifact.ligand_id}/conformers/content`,
  };
}

function filterEvaluation(
  source: LigandRecord,
  disposition: LigandFilterEvaluation["disposition"],
  overrides: Partial<LigandFilterEvaluation> = {},
): LigandFilterEvaluation {
  const passed = { passed: true, violations: [] };
  return {
    ligand_id: source.artifact.ligand_id,
    record_index: source.artifact.library_record_index ?? 0,
    state_id: source.state?.state_id ?? "missing",
    canonical_isomeric_smiles: source.inspection.canonical_smiles,
    descriptors: disposition === "needs_decision" ? null : {
      molecular_weight_g_mol: source.inspection.molecular_weight_g_mol ?? 1,
      clogp: source.inspection.name === "ethanol" ? -0.001 : 0.407,
      hydrogen_bond_donors: 0,
      hydrogen_bond_acceptors: 1,
      tpsa_angstrom2: 17.07,
      rotatable_bonds: 0,
      molar_refractivity: 15,
      total_atom_count_with_hydrogens: 10,
      carbon_atom_count: 3,
      hetero_atom_count: 1,
      ring_count: 0,
      qed: source.inspection.name === "ethanol" ? 0.407 : 0.385,
    },
    lipinski: disposition === "needs_decision" ? null : passed,
    veber: disposition === "needs_decision" ? null : passed,
    ghose: disposition === "needs_decision" ? null : passed,
    muegge: disposition === "needs_decision" ? null : passed,
    custom_rule_results: [],
    alerts: [],
    duplicate_of_ligand_id: null,
    disposition,
    reasons: [],
    ...overrides,
  };
}

it("imports and processes every eligible molecule while showing a screening table", async () => {
  const first = ligand(1, "ethanol", "CCO", "C2H6O", 46.069);
  const second = ligand(2, "acetone", "CC(C)=O", "C3H6O", 58.08);
  const unresolved = ligand(3, "salted", "CCO.[Na+]", "C2H6NaO+", 69.059);
  unresolved.inspection.fragment_count = 2;
  const excluded = ligand(4, "eicosane", "CCCCCCCCCCCCCCCCCCCC", "C20H42", 282.556);
  const library: LigandLibraryRecord = {
    artifact: { library_id: "library-1", filename: "synthetic_library.sdf", format: "sdf", sha256: "d".repeat(64), size_bytes: 500, record_count: 4, created_at: "2026-08-19T00:00:00Z" },
    entries: [
      { record_index: 0, status: "imported", ligand: first, failure: null },
      { record_index: 1, status: "imported", ligand: second, failure: null },
      { record_index: 2, status: "imported", ligand: unresolved, failure: null },
      { record_index: 3, status: "imported", ligand: excluded, failure: null },
    ],
    imported_count: 4,
    failed_count: 0,
    provenance: { event_id: "library-1", event_type: "local_ligand_library_imported", timestamp: "2026-08-19T00:00:00Z", input_artifacts: [], output_artifacts: ["library-1"], tool: { name: "synthetic", version: "1" }, parameters: {}, warnings: [], command: null },
    original_content_url: "/ligand-libraries/library-1/content",
  };
  const filterPlan = {
    preset: "general_oral" as const,
    require_lipinski: true,
    max_lipinski_violations: 1,
    require_veber: true,
    require_ghose: false,
    require_muegge: false,
    minimum_qed: null,
    pains_policy: "review" as const,
    brenk_policy: "review" as const,
    duplicate_policy: "exclude" as const,
    custom_rules: [],
  };
  const evaluations = [
    filterEvaluation(first, "eligible"),
    filterEvaluation(second, "eligible", { alerts: [{ catalog: "PAINS", description: "synthetic alert", atom_indices: [0, 1] }], reasons: ["PAINS_REVIEW"] }),
    filterEvaluation(unresolved, "needs_decision", { reasons: ["CHEMICAL_STATE_UNRESOLVED"] }),
    filterEvaluation(excluded, "excluded", { veber: { passed: false, violations: ["rotatable bonds > 10"] }, reasons: ["VEBER_REQUIRED"] }),
  ];
  const filterPreview: LigandLibraryFilterPreview = {
    library_id: "library-1",
    plan: filterPlan,
    evaluations,
    summary: { imported_count: 4, eligible_count: 2, excluded_count: 1, needs_decision_count: 1, duplicate_count: 0, pains_match_count: 1, brenk_match_count: 0 },
    rdkit_version: "2025.09.4",
    worker_count: 3,
  };
  const filterRun: LigandLibraryFilterRun = {
    artifact: { filter_run_id: "filter-1", library_id: "library-1", filename: "selection_manifest.json", sha256: "e".repeat(64), size_bytes: 1000, created_at: "2026-08-20T00:00:00Z" },
    plan: filterPlan,
    evaluations,
    summary: filterPreview.summary,
    rdkit_version: filterPreview.rdkit_version,
    worker_count: filterPreview.worker_count,
    selected_ligand_ids: [first.artifact.ligand_id, second.artifact.ligand_id],
    provenance: { event_id: "filter-1", event_type: "ligand_library_filtered", timestamp: "2026-08-20T00:00:00Z", input_artifacts: ["library-1"], output_artifacts: ["filter-1"], tool: { name: "RDKit", version: "2025.09.4" }, parameters: {}, warnings: [], command: null },
    manifest_content_url: "/ligand-libraries/library-1/filter-runs/filter-1/content",
  };
  let releaseFirst!: (response: Response) => void;
  let releaseSecond!: (response: Response) => void;
  const firstConformerResponse = new Promise<Response>((resolve) => { releaseFirst = resolve; });
  const secondConformerResponse = new Promise<Response>((resolve) => { releaseSecond = resolve; });
  const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/ligand-libraries/import") && init?.method === "POST") {
      return new Response(JSON.stringify(library), { status: 201, headers: { "Content-Type": "application/json" } });
    }
    if (url.endsWith("/ligand-libraries/library-1/filter-preview") && init?.method === "POST") {
      return new Response(JSON.stringify(filterPreview), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    if (url.endsWith("/ligand-libraries/library-1/filter-runs") && init?.method === "POST") {
      return new Response(JSON.stringify(filterRun), { status: 201, headers: { "Content-Type": "application/json" } });
    }
    if (url.includes("/ligand-1/conformers/generate")) {
      return firstConformerResponse;
    }
    if (url.includes("/ligand-2/conformers/generate")) {
      return secondConformerResponse;
    }
    return new Response(null, { status: 404 });
  });
  const onLibraryDockingInputChange = vi.fn();
  const onLibraryStatusChange = vi.fn();
  render(<LigandWorkspace structure={structure} record={null} tools={tools} onRecordChange={vi.fn()} onLibraryDockingInputChange={onLibraryDockingInputChange} onLibraryStatusChange={onLibraryStatusChange} />);

  fireEvent.click(screen.getByRole("button", { name: "Local file" }));
  const input = document.querySelector<HTMLInputElement>(".ligand-file-action input");
  fireEvent.change(input!, { target: { files: [new File(["synthetic"], "synthetic_library.sdf")] } });

  expect(await screen.findByRole("table")).toBeInTheDocument();
  expect(screen.getByText("CCO")).toBeInTheDocument();
  expect(screen.getByText("CC(C)=O")).toBeInTheDocument();
  expect(screen.getByText("46.07")).toBeInTheDocument();
  expect(screen.getByText("PAINS · review")).toBeInTheDocument();
  expect(screen.getByText("Excluded")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: /Apply this exact selection/ }));
  fireEvent.click(screen.getByRole("button", { name: "Apply filtered subset" }));
  expect(await screen.findByText("Selection manifest applied")).toBeInTheDocument();
  await waitFor(() => expect(onLibraryDockingInputChange).toHaveBeenLastCalledWith({
    library_id: "library-1",
    library_name: "synthetic_library.sdf",
    filter_run_id: "filter-1",
    selection_manifest_sha256: "e".repeat(64),
    selected_count: 2,
    prepared_count: 0,
  }));
  expect(screen.getByText(/does not run Dimorphite-DL/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: /Prepare the applied filtered subset/ }));
  fireEvent.click(screen.getByRole("button", { name: "Process 2 selected ligands" }));

  await waitFor(() => expect(
    fetchSpy.mock.calls.filter(([url]) => String(url).includes("/conformers/generate")),
  ).toHaveLength(2));
  const generationCalls = fetchSpy.mock.calls.filter(
    ([url]) => String(url).includes("/conformers/generate"),
  );
  expect(generationCalls.map(([, init]) => (
    JSON.parse(String(init?.body)).client_concurrency_hint
  ))).toEqual([2, 2]);
  expect(screen.getByText(/2 parallel workers/)).toBeInTheDocument();
  releaseFirst(new Response(JSON.stringify(conformer(first, -1.25)), { status: 201, headers: { "Content-Type": "application/json" } }));
  releaseSecond(new Response(JSON.stringify(conformer(second, -3.5)), { status: 201, headers: { "Content-Type": "application/json" } }));
  await waitFor(() => expect(screen.getByText("-1.250")).toBeInTheDocument());
  expect(screen.getByText("-3.500")).toBeInTheDocument();
  expect(screen.getAllByText("Minimized")).toHaveLength(2);
  await waitFor(() => expect(onLibraryStatusChange).toHaveBeenLastCalledWith({
    total: 2,
    terminal: 2,
    prepared: 0,
    notReady: 2,
  }));
  expect(screen.getByText("Needs decision")).toBeInTheDocument();
  expect(fetchSpy.mock.calls.filter(([url]) => String(url).includes("/conformers/generate"))).toHaveLength(2);
});

it("builds a custom descriptor rule, sends it in the preview request, and reflects the resulting exclusion", async () => {
  const first = ligand(1, "ethanol", "CCO", "C2H6O", 46.069);
  const second = ligand(2, "acetone", "CC(C)=O", "C3H6O", 58.08);
  const library: LigandLibraryRecord = {
    artifact: { library_id: "library-1", filename: "synthetic_library.sdf", format: "sdf", sha256: "d".repeat(64), size_bytes: 500, record_count: 2, created_at: "2026-08-19T00:00:00Z" },
    entries: [
      { record_index: 0, status: "imported", ligand: first, failure: null },
      { record_index: 1, status: "imported", ligand: second, failure: null },
    ],
    imported_count: 2,
    failed_count: 0,
    provenance: { event_id: "library-1", event_type: "local_ligand_library_imported", timestamp: "2026-08-19T00:00:00Z", input_artifacts: [], output_artifacts: ["library-1"], tool: { name: "synthetic", version: "1" }, parameters: {}, warnings: [], command: null },
    original_content_url: "/ligand-libraries/library-1/content",
  };
  const bothEligible: LigandLibraryFilterPreview = {
    library_id: "library-1",
    plan: { preset: "general_oral", require_lipinski: true, max_lipinski_violations: 1, require_veber: true, require_ghose: false, require_muegge: false, minimum_qed: null, pains_policy: "review", brenk_policy: "review", duplicate_policy: "exclude", custom_rules: [] },
    evaluations: [filterEvaluation(first, "eligible"), filterEvaluation(second, "eligible")],
    summary: { imported_count: 2, eligible_count: 2, excluded_count: 0, needs_decision_count: 0, duplicate_count: 0, pains_match_count: 0, brenk_match_count: 0 },
    rdkit_version: "2025.09.4",
    worker_count: 2,
  };
  const previewRequestBodies: Array<{ plan: { custom_rules: Array<Record<string, unknown>> } }> = [];
  const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/ligand-libraries/import") && init?.method === "POST") {
      return new Response(JSON.stringify(library), { status: 201, headers: { "Content-Type": "application/json" } });
    }
    if (url.endsWith("/ligand-libraries/library-1/filter-preview") && init?.method === "POST") {
      const body = JSON.parse(String(init?.body)) as { plan: { custom_rules: Array<Record<string, unknown>> } };
      previewRequestBodies.push(body);
      if (body.plan.custom_rules.length === 0) {
        return new Response(JSON.stringify(bothEligible), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      const rule = body.plan.custom_rules[0];
      const excluded: LigandLibraryFilterPreview = {
        ...bothEligible,
        plan: body.plan as unknown as LigandLibraryFilterPreview["plan"],
        evaluations: [
          filterEvaluation(first, "eligible"),
          filterEvaluation(second, "excluded", {
            reasons: [`CUSTOM_RULE_REQUIRED:${rule.rule_id as string}`],
            custom_rule_results: [{ rule_id: rule.rule_id as string, label: rule.label as string, required: true, passed: false, value: 58.08 }],
          }),
        ],
        summary: { ...bothEligible.summary, eligible_count: 1, excluded_count: 1 },
      };
      return new Response(JSON.stringify(excluded), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    return new Response(null, { status: 404 });
  });

  render(<LigandWorkspaceHarness structure={structure} tools={tools} />);

  fireEvent.click(screen.getByRole("button", { name: "Local file" }));
  const input = document.querySelector<HTMLInputElement>(".ligand-file-action input");
  fireEvent.change(input!, { target: { files: [new File(["synthetic"], "synthetic_library.sdf")] } });
  expect(await screen.findByRole("table")).toBeInTheDocument();
  expect(previewRequestBodies).toHaveLength(1);
  expect(previewRequestBodies[0].plan.custom_rules).toEqual([]);

  fireEvent.change(screen.getByLabelText("Custom rule label"), { target: { value: "MW ceiling" } });
  fireEvent.click(screen.getByRole("button", { name: "Add rule" }));

  expect(screen.getByText("MW ceiling")).toBeInTheDocument();
  expect(screen.getByText(/Molecular weight < 500 g\/mol · Required/)).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Preview filters" }));

  await waitFor(() => expect(previewRequestBodies).toHaveLength(2));
  expect(previewRequestBodies[1].plan.custom_rules).toEqual([
    {
      rule_id: expect.stringMatching(/^custom-/),
      label: "MW ceiling",
      descriptor: "molecular_weight_g_mol",
      operator: "lt",
      value: 500,
      value_upper: null,
      required: true,
    },
  ]);
  expect(await screen.findByText("Excluded")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  expect(screen.queryByText("MW ceiling")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Preview filters" }));
  await waitFor(() => expect(previewRequestBodies).toHaveLength(3));
  expect(previewRequestBodies[2].plan.custom_rules).toEqual([]);
});

it("does not reprocess an already-prepared ligand and shows a completion state instead", async () => {
  const only = ligand(1, "ethanol", "CCO", "C2H6O", 46.069);
  const library: LigandLibraryRecord = {
    artifact: { library_id: "library-1", filename: "synthetic_library.sdf", format: "sdf", sha256: "d".repeat(64), size_bytes: 500, record_count: 1, created_at: "2026-08-19T00:00:00Z" },
    entries: [{ record_index: 0, status: "imported", ligand: only, failure: null }],
    imported_count: 1,
    failed_count: 0,
    provenance: { event_id: "library-1", event_type: "local_ligand_library_imported", timestamp: "2026-08-19T00:00:00Z", input_artifacts: [], output_artifacts: ["library-1"], tool: { name: "synthetic", version: "1" }, parameters: {}, warnings: [], command: null },
    original_content_url: "/ligand-libraries/library-1/content",
  };
  const filterPlan = {
    preset: "general_oral" as const,
    require_lipinski: true,
    max_lipinski_violations: 1,
    require_veber: true,
    require_ghose: false,
    require_muegge: false,
    minimum_qed: null,
    pains_policy: "review" as const,
    brenk_policy: "review" as const,
    duplicate_policy: "exclude" as const,
    custom_rules: [],
  };
  const evaluations = [filterEvaluation(only, "eligible")];
  const filterPreview: LigandLibraryFilterPreview = {
    library_id: "library-1",
    plan: filterPlan,
    evaluations,
    summary: { imported_count: 1, eligible_count: 1, excluded_count: 0, needs_decision_count: 0, duplicate_count: 0, pains_match_count: 0, brenk_match_count: 0 },
    rdkit_version: "2025.09.4",
    worker_count: 1,
  };
  const filterRun: LigandLibraryFilterRun = {
    artifact: { filter_run_id: "filter-1", library_id: "library-1", filename: "selection_manifest.json", sha256: "e".repeat(64), size_bytes: 1000, created_at: "2026-08-20T00:00:00Z" },
    plan: filterPlan,
    evaluations,
    summary: filterPreview.summary,
    rdkit_version: filterPreview.rdkit_version,
    worker_count: filterPreview.worker_count,
    selected_ligand_ids: [only.artifact.ligand_id],
    provenance: { event_id: "filter-1", event_type: "ligand_library_filtered", timestamp: "2026-08-20T00:00:00Z", input_artifacts: ["library-1"], output_artifacts: ["filter-1"], tool: { name: "RDKit", version: "2025.09.4" }, parameters: {}, warnings: [], command: null },
    manifest_content_url: "/ligand-libraries/library-1/filter-runs/filter-1/content",
  };
  const preparedConformer = conformer(only, -2.5);
  const pdbqt = {
    artifact: { preparation_id: "pdbqt-1", ligand_id: only.artifact.ligand_id, conformer_id: preparedConformer.artifact.conformer_id, filename: "ethanol_prepared.pdbqt", format: "pdbqt", sha256: "f".repeat(64), size_bytes: 50, created_at: "2026-08-20T00:00:00Z" },
    charge_model: "gasteiger" as const,
    tool: { name: "Meeko", version: "0.7.1" },
    command: ["mk_prepare_ligand"],
    stdout: "",
    stderr: "",
    provenance: { event_id: "pdbqt-1", event_type: "ligand_pdbqt_prepared", timestamp: "2026-08-20T00:00:00Z", input_artifacts: [preparedConformer.artifact.conformer_id], output_artifacts: ["pdbqt-1"], tool: { name: "Meeko", version: "0.7.1" }, parameters: {}, warnings: [], command: ["mk_prepare_ligand"] },
    content_url: "/ligands/ligand-1/preparations/pdbqt-1/content",
  };
  const generateCalls: string[] = [];
  const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/ligand-libraries/import") && init?.method === "POST") {
      return new Response(JSON.stringify(library), { status: 201, headers: { "Content-Type": "application/json" } });
    }
    if (url.endsWith("/ligand-libraries/library-1/filter-preview") && init?.method === "POST") {
      return new Response(JSON.stringify(filterPreview), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    if (url.endsWith("/ligand-libraries/library-1/filter-runs") && init?.method === "POST") {
      return new Response(JSON.stringify(filterRun), { status: 201, headers: { "Content-Type": "application/json" } });
    }
    if (url.endsWith("/ligand-libraries/library-1/preparation")) {
      return new Response(JSON.stringify({ library_id: "library-1", updated_at: "2026-08-20T00:00:00Z", entries: {} }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    if (url.includes("/ligand-1/conformers/generate")) {
      generateCalls.push(url);
      return new Response(JSON.stringify(preparedConformer), { status: 201, headers: { "Content-Type": "application/json" } });
    }
    if (url.includes("/conformers/") && url.includes("/pdbqt")) {
      return new Response(JSON.stringify(pdbqt), { status: 201, headers: { "Content-Type": "application/json" } });
    }
    return new Response(null, { status: 404 });
  });
  render(<LigandWorkspace structure={structure} record={null} tools={{ ...tools, meeko_ligand: { available: true, path: "mk_prepare_ligand.exe", version: "0.7.1" } }} onRecordChange={vi.fn()} />);

  fireEvent.click(screen.getByRole("button", { name: "Local file" }));
  const input = document.querySelector<HTMLInputElement>(".ligand-file-action input");
  fireEvent.change(input!, { target: { files: [new File(["synthetic"], "synthetic_library.sdf")] } });
  expect(await screen.findByRole("table")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: /Apply this exact selection/ }));
  fireEvent.click(screen.getByRole("button", { name: "Apply filtered subset" }));
  expect(await screen.findByText("Selection manifest applied")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: /Prepare the applied filtered subset/ }));
  fireEvent.click(screen.getByRole("button", { name: "Process 1 selected ligands" }));

  await waitFor(() => expect(screen.getByText(/Batch complete/)).toBeInTheDocument());
  expect(screen.getByText(/1\/1 ligands are PDBQT-ready/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Process \d+ (selected|remaining) ligands/ })).not.toBeInTheDocument();
  expect(generateCalls).toHaveLength(1);
});

it("lets a needs-decision ligand be resolved from the always-visible notice, then included by re-applying filters", async () => {
  // A first, already-eligible ligand is imported at index 0 and gets
  // auto-selected on import - the "unresolved" ligand at index 1 is never
  // auto-selected, so acting on it can only happen through a real click.
  // A needs-decision ligand's descriptors can never be computed without an
  // explicit chemical state (see ligand_filtering.py), so the backend can
  // never place it in a filter run's selected_ligand_ids - only re-applying
  // after resolving it does that.
  const eligible = ligand(1, "ethanol", "CCO", "C2H6O", 46.069);
  const unresolved = ligand(2, "salted", "CCO.[Na+]", "C2H6NaO+", 69.059);
  unresolved.inspection.fragment_count = 2;
  const library: LigandLibraryRecord = {
    artifact: { library_id: "library-1", filename: "synthetic_library.sdf", format: "sdf", sha256: "d".repeat(64), size_bytes: 500, record_count: 2, created_at: "2026-08-19T00:00:00Z" },
    entries: [
      { record_index: 0, status: "imported", ligand: eligible, failure: null },
      { record_index: 1, status: "imported", ligand: unresolved, failure: null },
    ],
    imported_count: 2,
    failed_count: 0,
    provenance: { event_id: "library-1", event_type: "local_ligand_library_imported", timestamp: "2026-08-19T00:00:00Z", input_artifacts: [], output_artifacts: ["library-1"], tool: { name: "synthetic", version: "1" }, parameters: {}, warnings: [], command: null },
    original_content_url: "/ligand-libraries/library-1/content",
  };
  const filterPlan = {
    preset: "general_oral" as const,
    require_lipinski: true,
    max_lipinski_violations: 1,
    require_veber: true,
    require_ghose: false,
    require_muegge: false,
    minimum_qed: null,
    pains_policy: "review" as const,
    brenk_policy: "review" as const,
    duplicate_policy: "exclude" as const,
    custom_rules: [],
  };
  const beforeEvaluations = [
    filterEvaluation(eligible, "eligible"),
    filterEvaluation(unresolved, "needs_decision", { reasons: ["CHEMICAL_STATE_UNRESOLVED"] }),
  ];
  const filterPreviewBefore: LigandLibraryFilterPreview = {
    library_id: "library-1",
    plan: filterPlan,
    evaluations: beforeEvaluations,
    summary: { imported_count: 2, eligible_count: 1, excluded_count: 0, needs_decision_count: 1, duplicate_count: 0, pains_match_count: 0, brenk_match_count: 0 },
    rdkit_version: "2025.09.4",
    worker_count: 1,
  };
  const firstFilterRun: LigandLibraryFilterRun = {
    artifact: { filter_run_id: "filter-1", library_id: "library-1", filename: "selection_manifest.json", sha256: "e".repeat(64), size_bytes: 1000, created_at: "2026-08-20T00:00:00Z" },
    plan: filterPlan,
    evaluations: beforeEvaluations,
    summary: filterPreviewBefore.summary,
    rdkit_version: filterPreviewBefore.rdkit_version,
    worker_count: filterPreviewBefore.worker_count,
    selected_ligand_ids: [eligible.artifact.ligand_id],
    provenance: { event_id: "filter-1", event_type: "ligand_library_filtered", timestamp: "2026-08-20T00:00:00Z", input_artifacts: ["library-1"], output_artifacts: ["filter-1"], tool: { name: "RDKit", version: "2025.09.4" }, parameters: {}, warnings: [], command: null },
    manifest_content_url: "/ligand-libraries/library-1/filter-runs/filter-1/content",
  };
  const afterEvaluations = [
    filterEvaluation(eligible, "eligible"),
    filterEvaluation(unresolved, "eligible"),
  ];
  const filterPreviewAfter: LigandLibraryFilterPreview = {
    ...filterPreviewBefore,
    evaluations: afterEvaluations,
    summary: { ...filterPreviewBefore.summary, eligible_count: 2, needs_decision_count: 0 },
  };
  const secondFilterRun: LigandLibraryFilterRun = {
    ...firstFilterRun,
    artifact: { ...firstFilterRun.artifact, filter_run_id: "filter-2" },
    evaluations: afterEvaluations,
    summary: filterPreviewAfter.summary,
    selected_ligand_ids: [eligible.artifact.ligand_id, unresolved.artifact.ligand_id],
  };
  const resolutionOptions: LigandStateResolutionOptions = {
    parent_state_id: unresolved.state!.state_id,
    component_options: [
      { index: 0, formula: "C2H6O", formal_charge: 0, heavy_atom_count: 3, canonical_smiles: "CCO" },
      { index: 1, formula: "Na", formal_charge: 1, heavy_atom_count: 1, canonical_smiles: "[Na+]" },
    ],
    selected_component_index: null,
    stereoisomer_options: [],
    component_selection_required: true,
    stereoisomer_selection_required: false,
  };
  const resolvedState: LigandChemicalStateRecord = {
    artifact: { state_id: "state-resolved-1", ligand_id: unresolved.artifact.ligand_id, filename: "resolved.sdf", format: "sdf", sha256: "f".repeat(64), size_bytes: 80, created_at: "2026-08-20T00:00:00Z" },
    parent_state_id: unresolved.state!.state_id,
    inspection: { ...unresolved.inspection, fragment_count: 1, canonical_smiles: "CCO" },
    selection: { component_index: 0, source_fragment_count: 2, stereoisomer_index: null, stereoisomer_count: 1 },
    warnings: [],
    provenance: { event_id: "resolve-1", event_type: "ligand_state_resolved", timestamp: "2026-08-20T00:00:00Z", input_artifacts: [unresolved.state!.state_id], output_artifacts: ["state-resolved-1"], tool: { name: "RDKit", version: "2025.09.4" }, parameters: {}, warnings: [], command: null },
    content_url: `/ligands/${unresolved.artifact.ligand_id}/states/state-resolved-1/content`,
  };
  const eligibleConformer = conformer(eligible, -1.25);
  const resolvedConformer = conformer(unresolved, -0.9);
  const generateCalls: string[] = [];
  let filterRunCallCount = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/ligand-libraries/import") && init?.method === "POST") return json(library, 201);
    if (url.endsWith("/ligand-libraries/library-1/filter-preview") && init?.method === "POST") {
      return json(filterRunCallCount > 0 ? filterPreviewAfter : filterPreviewBefore, 200);
    }
    if (url.endsWith("/ligand-libraries/library-1/filter-runs") && init?.method === "POST") {
      filterRunCallCount += 1;
      return json(filterRunCallCount === 1 ? firstFilterRun : secondFilterRun, 201);
    }
    if (url.includes("/resolution-options")) return json(resolutionOptions, 200);
    if (url.endsWith(`/ligands/${unresolved.artifact.ligand_id}/states/resolve`) && init?.method === "POST") return json(resolvedState, 201);
    if (url.includes(`/${unresolved.artifact.ligand_id}/conformers/generate`)) {
      generateCalls.push(url);
      return json(resolvedConformer, 201);
    }
    if (url.includes(`/${eligible.artifact.ligand_id}/conformers/generate`)) {
      generateCalls.push(url);
      return json(eligibleConformer, 201);
    }
    return new Response(null, { status: 404 });
  });
  render(<LigandWorkspaceHarness structure={structure} tools={tools} />);

  fireEvent.click(screen.getByRole("button", { name: "Local file" }));
  const input = document.querySelector<HTMLInputElement>(".ligand-file-action input");
  fireEvent.change(input!, { target: { files: [new File(["synthetic"], "synthetic_library.sdf")] } });
  expect(await screen.findByRole("table")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: /Apply this exact selection/ }));
  fireEvent.click(screen.getByRole("button", { name: "Apply filtered subset" }));
  expect(await screen.findByText("Selection manifest applied")).toBeInTheDocument();

  // The needs-decision notice must be visible right away - "salted" was
  // never processed, its disposition alone already flags it - and the
  // applied batch only ever contains the one truly-eligible ligand.
  expect(await screen.findByText(/1 ligand needs a decision/)).toBeInTheDocument();
  expect(document.querySelector(".ligand-row-status.needs-decision")).not.toBeNull();
  fireEvent.click(screen.getByRole("checkbox", { name: /Prepare the applied filtered subset/ }));
  expect(screen.getByRole("button", { name: "Process 1 selected ligands" })).toBeInTheDocument();

  // Regression for the reported bug: clicking the status badge itself (not
  // just the name button) must select the row so a decision can be made.
  fireEvent.click(document.querySelector(".ligand-row-status.needs-decision")!);
  expect(await screen.findByText("Decision required")).toBeInTheDocument();
  const componentSelect = await screen.findByLabelText("Component to retain");
  fireEvent.change(componentSelect, { target: { value: "0" } });
  fireEvent.click(screen.getByRole("button", { name: "Create explicitly resolved state" }));
  expect(await screen.findByText("Explicit state created")).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByText(/needs a decision/)).not.toBeInTheDocument());

  // Re-applying is what actually folds the now-resolved ligand into a
  // processable selection - the first manifest never contained it. A fresh
  // manifest asks for a fresh confirmation, but must not forget anything
  // already prepared under the previous one.
  fireEvent.click(screen.getByRole("button", { name: "Apply filtered subset" }));
  expect(await screen.findByText(/^2 ligands ·/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: /Prepare the applied filtered subset/ }));
  const reprocessButton = await screen.findByRole("button", { name: "Process 2 selected ligands" });
  fireEvent.click(reprocessButton);

  await waitFor(() => expect(generateCalls).toHaveLength(2));
  expect(generateCalls.some((url) => url.includes(unresolved.artifact.ligand_id))).toBe(true);
});

it("bulk-resolves multi-fragment needs-decision ligands by keeping the largest fragment, and bulk-excludes the rest", async () => {
  const saltA = ligand(1, "saltA", "CCO.[Na+]", "C2H6NaO+", 69.059);
  saltA.inspection.fragment_count = 2;
  const saltB = ligand(2, "saltB", "CC(=O)O.[K+]", "C2H3KO2", 98.15);
  saltB.inspection.fragment_count = 2;
  const chiral = ligand(3, "chiral", "CC(N)C(=O)O", "C3H7NO2", 89.09);
  chiral.inspection.undefined_stereocenter_count = 1;
  const library: LigandLibraryRecord = {
    artifact: { library_id: "library-1", filename: "synthetic_library.sdf", format: "sdf", sha256: "d".repeat(64), size_bytes: 500, record_count: 3, created_at: "2026-08-19T00:00:00Z" },
    entries: [
      { record_index: 0, status: "imported", ligand: saltA, failure: null },
      { record_index: 1, status: "imported", ligand: saltB, failure: null },
      { record_index: 2, status: "imported", ligand: chiral, failure: null },
    ],
    imported_count: 3,
    failed_count: 0,
    provenance: { event_id: "library-1", event_type: "local_ligand_library_imported", timestamp: "2026-08-19T00:00:00Z", input_artifacts: [], output_artifacts: ["library-1"], tool: { name: "synthetic", version: "1" }, parameters: {}, warnings: [], command: null },
    original_content_url: "/ligand-libraries/library-1/content",
  };
  const filterPlan = {
    preset: "general_oral" as const,
    require_lipinski: true,
    max_lipinski_violations: 1,
    require_veber: true,
    require_ghose: false,
    require_muegge: false,
    minimum_qed: null,
    pains_policy: "review" as const,
    brenk_policy: "review" as const,
    duplicate_policy: "exclude" as const,
    custom_rules: [],
  };
  // Real backend semantics (ligand_filtering.py): a needs-decision ligand's
  // descriptors can't be computed without an explicit chemical state, so it
  // is never ELIGIBLE and therefore never lands in selected_ligand_ids. All
  // three start out needs-decision here, so the first filter run selects
  // none of them at all.
  const initialEvaluations = [
    filterEvaluation(saltA, "needs_decision", { reasons: ["CHEMICAL_STATE_UNRESOLVED"] }),
    filterEvaluation(saltB, "needs_decision", { reasons: ["CHEMICAL_STATE_UNRESOLVED"] }),
    filterEvaluation(chiral, "needs_decision", { reasons: ["CHEMICAL_STATE_UNRESOLVED"] }),
  ];
  const filterPreviewInitial: LigandLibraryFilterPreview = {
    library_id: "library-1",
    plan: filterPlan,
    evaluations: initialEvaluations,
    summary: { imported_count: 3, eligible_count: 0, excluded_count: 0, needs_decision_count: 3, duplicate_count: 0, pains_match_count: 0, brenk_match_count: 0 },
    rdkit_version: "2025.09.4",
    worker_count: 1,
  };
  const firstFilterRun: LigandLibraryFilterRun = {
    artifact: { filter_run_id: "filter-1", library_id: "library-1", filename: "selection_manifest.json", sha256: "e".repeat(64), size_bytes: 1000, created_at: "2026-08-20T00:00:00Z" },
    plan: filterPlan,
    evaluations: initialEvaluations,
    summary: filterPreviewInitial.summary,
    rdkit_version: filterPreviewInitial.rdkit_version,
    worker_count: filterPreviewInitial.worker_count,
    selected_ligand_ids: [],
    provenance: { event_id: "filter-1", event_type: "ligand_library_filtered", timestamp: "2026-08-20T00:00:00Z", input_artifacts: ["library-1"], output_artifacts: ["filter-1"], tool: { name: "RDKit", version: "2025.09.4" }, parameters: {}, warnings: [], command: null },
    manifest_content_url: "/ligand-libraries/library-1/filter-runs/filter-1/content",
  };
  // After bulk-resolving saltA/saltB, the refreshed preview shows them
  // eligible - chiral was never resolved, so it stays needs-decision.
  const afterBulkEvaluations = [
    filterEvaluation(saltA, "eligible"),
    filterEvaluation(saltB, "eligible"),
    filterEvaluation(chiral, "needs_decision", { reasons: ["CHEMICAL_STATE_UNRESOLVED"] }),
  ];
  const filterPreviewAfterBulk: LigandLibraryFilterPreview = {
    ...filterPreviewInitial,
    evaluations: afterBulkEvaluations,
    summary: { ...filterPreviewInitial.summary, eligible_count: 2, needs_decision_count: 1 },
  };
  const secondFilterRun: LigandLibraryFilterRun = {
    ...firstFilterRun,
    artifact: { ...firstFilterRun.artifact, filter_run_id: "filter-2" },
    evaluations: afterBulkEvaluations,
    summary: filterPreviewAfterBulk.summary,
    selected_ligand_ids: [saltA.artifact.ligand_id, saltB.artifact.ligand_id],
  };
  // The larger fragment sits at a different index for each salt (0 for A, 1
  // for B) so the test can tell "picks whichever has the most heavy atoms"
  // apart from a bug that would just always take component index 0.
  function componentOptions(largeFormula: string, largeAtoms: number, largeIndex: 0 | 1): LigandStateResolutionOptions {
    const large = { formula: largeFormula, formal_charge: 0, heavy_atom_count: largeAtoms, canonical_smiles: largeFormula };
    const counterion = { formula: "counterion", formal_charge: 1, heavy_atom_count: 1, canonical_smiles: "[X+]" };
    const ordered = largeIndex === 0 ? [large, counterion] : [counterion, large];
    return {
      parent_state_id: "irrelevant",
      component_options: ordered.map((option, index) => ({ index, ...option })),
      selected_component_index: null,
      stereoisomer_options: [],
      component_selection_required: true,
      stereoisomer_selection_required: false,
    };
  }
  function resolvedRecord(source: LigandRecord, resolvedStateId: string): LigandChemicalStateRecord {
    return {
      artifact: { state_id: resolvedStateId, ligand_id: source.artifact.ligand_id, filename: "resolved.sdf", format: "sdf", sha256: "f".repeat(64), size_bytes: 80, created_at: "2026-08-20T00:00:00Z" },
      parent_state_id: source.state!.state_id,
      inspection: { ...source.inspection, fragment_count: 1 },
      selection: { component_index: 0, source_fragment_count: 2, stereoisomer_index: null, stereoisomer_count: 1 },
      warnings: [],
      provenance: { event_id: `resolve-${resolvedStateId}`, event_type: "ligand_state_resolved", timestamp: "2026-08-20T00:00:00Z", input_artifacts: [source.state!.state_id], output_artifacts: [resolvedStateId], tool: { name: "RDKit", version: "2025.09.4" }, parameters: {}, warnings: [], command: null },
      content_url: `/ligands/${source.artifact.ligand_id}/states/${resolvedStateId}/content`,
    };
  }
  const resolveCalls: { ligandId: string; componentIndex: number }[] = [];
  const chiralResolutionOptionsCalls: string[] = [];
  const generateCalls: string[] = [];
  let filterRunCallCount = 0;
  let bulkResolved = false;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/ligand-libraries/import") && init?.method === "POST") return json(library, 201);
    if (url.endsWith("/ligand-libraries/library-1/filter-preview") && init?.method === "POST") {
      return json(bulkResolved ? filterPreviewAfterBulk : filterPreviewInitial, 200);
    }
    if (url.endsWith("/ligand-libraries/library-1/filter-runs") && init?.method === "POST") {
      filterRunCallCount += 1;
      return json(filterRunCallCount === 1 ? firstFilterRun : secondFilterRun, 201);
    }
    if (url.includes(`/ligands/${chiral.artifact.ligand_id}/states/`) && url.includes("/resolution-options")) {
      chiralResolutionOptionsCalls.push(url);
      return new Response(null, { status: 404 });
    }
    if (url.includes(`/ligands/${saltA.artifact.ligand_id}/states/`) && url.includes("/resolution-options")) {
      return json(componentOptions("C2H6O", 3, 0), 200);
    }
    if (url.includes(`/ligands/${saltB.artifact.ligand_id}/states/`) && url.includes("/resolution-options")) {
      return json(componentOptions("C2H3O2", 4, 1), 200);
    }
    if (url.endsWith(`/ligands/${saltA.artifact.ligand_id}/states/resolve`) && init?.method === "POST") {
      resolveCalls.push({ ligandId: saltA.artifact.ligand_id, componentIndex: JSON.parse(String(init?.body)).component_index });
      if (resolveCalls.length === 2) bulkResolved = true;
      return json(resolvedRecord(saltA, "state-resolved-a"), 201);
    }
    if (url.endsWith(`/ligands/${saltB.artifact.ligand_id}/states/resolve`) && init?.method === "POST") {
      resolveCalls.push({ ligandId: saltB.artifact.ligand_id, componentIndex: JSON.parse(String(init?.body)).component_index });
      if (resolveCalls.length === 2) bulkResolved = true;
      return json(resolvedRecord(saltB, "state-resolved-b"), 201);
    }
    if (url.includes("/conformers/generate")) {
      generateCalls.push(url);
      return json(conformer(saltA, -1.0), 201);
    }
    if (url.includes("/conformers/") && url.includes("/pdbqt")) {
      return json({
        artifact: { preparation_id: "pdbqt-1", ligand_id: "ligand", conformer_id: "conformer-ligand-1", filename: "prepared.pdbqt", format: "pdbqt", sha256: "f".repeat(64), size_bytes: 50, created_at: "2026-08-20T00:00:00Z" },
        charge_model: "gasteiger",
        tool: { name: "Meeko", version: "0.7.1" },
        command: ["mk_prepare_ligand"],
        stdout: "",
        stderr: "",
        provenance: { event_id: "pdbqt-1", event_type: "ligand_pdbqt_prepared", timestamp: "2026-08-20T00:00:00Z", input_artifacts: [], output_artifacts: ["pdbqt-1"], tool: { name: "Meeko", version: "0.7.1" }, parameters: {}, warnings: [], command: ["mk_prepare_ligand"] },
        content_url: "/ligands/ligand/preparations/pdbqt-1/content",
      }, 201);
    }
    return new Response(null, { status: 404 });
  });
  render(<LigandWorkspaceHarness structure={structure} tools={{ ...tools, meeko_ligand: { available: true, path: "mk_prepare_ligand.exe", version: "0.7.1" } }} />);

  fireEvent.click(screen.getByRole("button", { name: "Local file" }));
  const input = document.querySelector<HTMLInputElement>(".ligand-file-action input");
  fireEvent.change(input!, { target: { files: [new File(["synthetic"], "synthetic_library.sdf")] } });
  expect(await screen.findByRole("table")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: /Apply this exact selection/ }));
  fireEvent.click(screen.getByRole("button", { name: "Apply filtered subset" }));
  expect(await screen.findByText("Selection manifest applied")).toBeInTheDocument();
  // All three ligands are already known-blocked (multi-fragment or undefined
  // stereochemistry), so none of them were ever selected by the applied
  // filter run - the notice must appear regardless, straight from the
  // preview, with nothing else to show in its place.
  expect(await screen.findByText(/3 ligands need a decision/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Process \d+ (selected|remaining) ligands/ })).not.toBeInTheDocument();
  await waitFor(() => expect(document.querySelectorAll(".ligand-row-status.needs-decision")).toHaveLength(3));

  fireEvent.click(screen.getByRole("checkbox", { name: "Select saltA for a bulk action" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Select saltB for a bulk action" }));
  fireEvent.click(screen.getByRole("button", { name: "Keep largest fragment" }));

  await waitFor(() => expect(resolveCalls).toHaveLength(2));
  // saltA's larger fragment sits at component index 0, saltB's at index 1 -
  // asserting both proves this picks the largest fragment by heavy-atom
  // count, not just always the first component in the list.
  expect(resolveCalls).toContainEqual({ ligandId: saltA.artifact.ligand_id, componentIndex: 0 });
  expect(resolveCalls).toContainEqual({ ligandId: saltB.artifact.ligand_id, componentIndex: 1 });
  // The undefined-stereocenter-only ligand has no fragment ambiguity, so the
  // bulk fragment action must never even inspect it, let alone resolve it.
  expect(chiralResolutionOptionsCalls).toHaveLength(0);
  // Only chiral is left needing a decision now.
  expect(await screen.findByText(/1 ligand needs a decision/)).toBeInTheDocument();

  fireEvent.click(screen.getByRole("checkbox", { name: "Select chiral for a bulk action" }));
  fireEvent.click(screen.getByRole("button", { name: "Exclude selected" }));
  expect(await screen.findByText("Excluded")).toBeInTheDocument();
  expect(screen.queryByText(/needs a decision/)).not.toBeInTheDocument();

  // Resolving saltA/saltB does not retroactively add them to the already
  // applied (empty) selection - re-applying is what actually does that.
  fireEvent.click(screen.getByRole("button", { name: "Apply filtered subset" }));
  expect(await screen.findByText(/^2 ligands ·/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: /Prepare the applied filtered subset/ }));
  const reprocessButton = await screen.findByRole("button", { name: "Process 2 selected ligands" });
  fireEvent.click(reprocessButton);

  await waitFor(() => expect(generateCalls).toHaveLength(2));
  // The excluded ligand was never part of this selection and must never be
  // reprocessed.
  expect(generateCalls.some((url) => url.includes(chiral.artifact.ligand_id))).toBe(false);
  await waitFor(() => expect(screen.getByText(/Batch complete/)).toBeInTheDocument());
});

it("proactively surfaces a needs-decision notice with its own bulk actions, even while other ligands are still workable", async () => {
  // The notice must not wait until nothing else can be processed - a user
  // running a large screen could easily miss a handful of needs-decision
  // ligands buried among hundreds of workable ones otherwise. It must also
  // be actionable on its own, without requiring the table's checkboxes.
  const workable = ligand(1, "workable", "CCO", "C2H6O", 46.069);
  const saltX = ligand(2, "saltX", "CCO.[Na+]", "C2H6NaO+", 69.059);
  saltX.inspection.fragment_count = 2;
  const library: LigandLibraryRecord = {
    artifact: { library_id: "library-1", filename: "synthetic_library.sdf", format: "sdf", sha256: "d".repeat(64), size_bytes: 500, record_count: 2, created_at: "2026-08-19T00:00:00Z" },
    entries: [
      { record_index: 0, status: "imported", ligand: workable, failure: null },
      { record_index: 1, status: "imported", ligand: saltX, failure: null },
    ],
    imported_count: 2,
    failed_count: 0,
    provenance: { event_id: "library-1", event_type: "local_ligand_library_imported", timestamp: "2026-08-19T00:00:00Z", input_artifacts: [], output_artifacts: ["library-1"], tool: { name: "synthetic", version: "1" }, parameters: {}, warnings: [], command: null },
    original_content_url: "/ligand-libraries/library-1/content",
  };
  const filterPlan = {
    preset: "general_oral" as const,
    require_lipinski: true,
    max_lipinski_violations: 1,
    require_veber: true,
    require_ghose: false,
    require_muegge: false,
    minimum_qed: null,
    pains_policy: "review" as const,
    brenk_policy: "review" as const,
    duplicate_policy: "exclude" as const,
    custom_rules: [],
  };
  const evaluations = [
    filterEvaluation(workable, "eligible"),
    filterEvaluation(saltX, "needs_decision", { reasons: ["CHEMICAL_STATE_UNRESOLVED"] }),
  ];
  const filterPreview: LigandLibraryFilterPreview = {
    library_id: "library-1",
    plan: filterPlan,
    evaluations,
    summary: { imported_count: 2, eligible_count: 1, excluded_count: 0, needs_decision_count: 1, duplicate_count: 0, pains_match_count: 0, brenk_match_count: 0 },
    rdkit_version: "2025.09.4",
    worker_count: 1,
  };
  const filterRun: LigandLibraryFilterRun = {
    artifact: { filter_run_id: "filter-1", library_id: "library-1", filename: "selection_manifest.json", sha256: "e".repeat(64), size_bytes: 1000, created_at: "2026-08-20T00:00:00Z" },
    plan: filterPlan,
    evaluations,
    summary: filterPreview.summary,
    rdkit_version: filterPreview.rdkit_version,
    worker_count: filterPreview.worker_count,
    selected_ligand_ids: [workable.artifact.ligand_id],
    provenance: { event_id: "filter-1", event_type: "ligand_library_filtered", timestamp: "2026-08-20T00:00:00Z", input_artifacts: ["library-1"], output_artifacts: ["filter-1"], tool: { name: "RDKit", version: "2025.09.4" }, parameters: {}, warnings: [], command: null },
    manifest_content_url: "/ligand-libraries/library-1/filter-runs/filter-1/content",
  };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/ligand-libraries/import") && init?.method === "POST") return json(library, 201);
    if (url.endsWith("/ligand-libraries/library-1/filter-preview") && init?.method === "POST") return json(filterPreview, 200);
    if (url.endsWith("/ligand-libraries/library-1/filter-runs") && init?.method === "POST") return json(filterRun, 201);
    return new Response(null, { status: 404 });
  });
  render(<LigandWorkspaceHarness structure={structure} tools={tools} />);

  fireEvent.click(screen.getByRole("button", { name: "Local file" }));
  const input = document.querySelector<HTMLInputElement>(".ligand-file-action input");
  fireEvent.change(input!, { target: { files: [new File(["synthetic"], "synthetic_library.sdf")] } });
  expect(await screen.findByRole("table")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: /Apply this exact selection/ }));
  fireEvent.click(screen.getByRole("button", { name: "Apply filtered subset" }));
  expect(await screen.findByText("Selection manifest applied")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: /Prepare the applied filtered subset/ }));

  // Both must be visible together: there is still a workable ligand left,
  // but the notice does not wait for that to finish first.
  expect(await screen.findByText(/1 ligand needs a decision/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Process 1 selected ligands" })).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Exclude all 1" }));

  expect(await screen.findByText("Excluded")).toBeInTheDocument();
  expect(screen.queryByText(/needs a decision/)).not.toBeInTheDocument();
});

it("does not offer a guaranteed-no-op 'keep largest fragment' when every needs-decision ligand is only ambiguous by stereochemistry", async () => {
  // Reproduces the reported bug: clicking a bulk action that structurally
  // cannot apply to any of the selected ligands used to silently do
  // nothing, with no feedback at all. A single-fragment, undefined-stereo
  // ligand has no multi-fragment ambiguity for "keep largest fragment" to
  // resolve, so the button must not even be offered - only "Exclude" can
  // act on this group.
  const chiralA = ligand(1, "chiralA", "CC(N)C(=O)O", "C3H7NO2", 89.09);
  chiralA.inspection.undefined_stereocenter_count = 1;
  const chiralB = ligand(2, "chiralB", "CC(O)C(=O)O", "C3H6O3", 90.08);
  chiralB.inspection.undefined_stereocenter_count = 1;
  const library: LigandLibraryRecord = {
    artifact: { library_id: "library-1", filename: "synthetic_library.sdf", format: "sdf", sha256: "d".repeat(64), size_bytes: 500, record_count: 2, created_at: "2026-08-19T00:00:00Z" },
    entries: [
      { record_index: 0, status: "imported", ligand: chiralA, failure: null },
      { record_index: 1, status: "imported", ligand: chiralB, failure: null },
    ],
    imported_count: 2,
    failed_count: 0,
    provenance: { event_id: "library-1", event_type: "local_ligand_library_imported", timestamp: "2026-08-19T00:00:00Z", input_artifacts: [], output_artifacts: ["library-1"], tool: { name: "synthetic", version: "1" }, parameters: {}, warnings: [], command: null },
    original_content_url: "/ligand-libraries/library-1/content",
  };
  const filterPlan = {
    preset: "general_oral" as const,
    require_lipinski: true,
    max_lipinski_violations: 1,
    require_veber: true,
    require_ghose: false,
    require_muegge: false,
    minimum_qed: null,
    pains_policy: "review" as const,
    brenk_policy: "review" as const,
    duplicate_policy: "exclude" as const,
    custom_rules: [],
  };
  const evaluations = [
    filterEvaluation(chiralA, "needs_decision", { reasons: ["UNDEFINED_STEREOCENTER"] }),
    filterEvaluation(chiralB, "needs_decision", { reasons: ["UNDEFINED_STEREOCENTER"] }),
  ];
  const filterPreview: LigandLibraryFilterPreview = {
    library_id: "library-1",
    plan: filterPlan,
    evaluations,
    summary: { imported_count: 2, eligible_count: 0, excluded_count: 0, needs_decision_count: 2, duplicate_count: 0, pains_match_count: 0, brenk_match_count: 0 },
    rdkit_version: "2025.09.4",
    worker_count: 1,
  };
  const filterRun: LigandLibraryFilterRun = {
    artifact: { filter_run_id: "filter-1", library_id: "library-1", filename: "selection_manifest.json", sha256: "e".repeat(64), size_bytes: 1000, created_at: "2026-08-20T00:00:00Z" },
    plan: filterPlan,
    evaluations,
    summary: filterPreview.summary,
    rdkit_version: filterPreview.rdkit_version,
    worker_count: filterPreview.worker_count,
    selected_ligand_ids: [],
    provenance: { event_id: "filter-1", event_type: "ligand_library_filtered", timestamp: "2026-08-20T00:00:00Z", input_artifacts: ["library-1"], output_artifacts: ["filter-1"], tool: { name: "RDKit", version: "2025.09.4" }, parameters: {}, warnings: [], command: null },
    manifest_content_url: "/ligand-libraries/library-1/filter-runs/filter-1/content",
  };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/ligand-libraries/import") && init?.method === "POST") return json(library, 201);
    if (url.endsWith("/ligand-libraries/library-1/filter-preview") && init?.method === "POST") return json(filterPreview, 200);
    if (url.endsWith("/ligand-libraries/library-1/filter-runs") && init?.method === "POST") return json(filterRun, 201);
    // chiralA auto-selects on import and its own per-ligand chemical-state
    // panel legitimately probes resolution-options on its own - unrelated
    // to the bulk action under test here.
    if (url.includes("/resolution-options")) return new Response(null, { status: 404 });
    return new Response(null, { status: 404 });
  });
  render(<LigandWorkspaceHarness structure={structure} tools={tools} />);

  fireEvent.click(screen.getByRole("button", { name: "Local file" }));
  const input = document.querySelector<HTMLInputElement>(".ligand-file-action input");
  fireEvent.change(input!, { target: { files: [new File(["synthetic"], "synthetic_library.sdf")] } });
  expect(await screen.findByText(/2 ligands need a decision/)).toBeInTheDocument();

  // No safe bulk default exists for stereochemistry, so this must not be
  // offered at all - not shown-but-disabled, not shown-and-silently-broken.
  expect(screen.queryByRole("button", { name: /Keep largest fragment/ })).not.toBeInTheDocument();

  // "Exclude" has no such restriction and must still work for this group.
  fireEvent.click(screen.getByRole("button", { name: "Exclude all 2" }));
  expect(await screen.findAllByText("Excluded")).toHaveLength(2);
  expect(screen.queryByText(/needs a decision/)).not.toBeInTheDocument();
});

it("hydrates a fully-prepared ligand's conformer and PDBQT from persisted status so its inspector stages read as done, not pending", async () => {
  // Reproduces the reported bug: the library table correctly shows a ligand
  // as PDBQT-ready from persisted preparation status, but the individual
  // ligand inspector's own conformer/pdbqt objects were never fetched, so
  // its own stages (docking format, chemical state) stayed stuck on
  // "Pending"/"Review" even though the work was genuinely already done.
  const readyMol = ligand(1, "readyMol", "CCO", "C2H6O", 46.069);
  const library: LigandLibraryRecord = {
    artifact: { library_id: "library-1", filename: "synthetic_library.sdf", format: "sdf", sha256: "d".repeat(64), size_bytes: 500, record_count: 1, created_at: "2026-08-19T00:00:00Z" },
    entries: [{ record_index: 0, status: "imported", ligand: readyMol, failure: null }],
    imported_count: 1,
    failed_count: 0,
    provenance: { event_id: "library-1", event_type: "local_ligand_library_imported", timestamp: "2026-08-19T00:00:00Z", input_artifacts: [], output_artifacts: ["library-1"], tool: { name: "synthetic", version: "1" }, parameters: {}, warnings: [], command: null },
    original_content_url: "/ligand-libraries/library-1/content",
  };
  const persistedConformer = conformer(readyMol, -3.3);
  const persistedPdbqt = {
    artifact: { preparation_id: "pdbqt-x", ligand_id: readyMol.artifact.ligand_id, conformer_id: persistedConformer.artifact.conformer_id, filename: "readyMol_prepared.pdbqt", format: "pdbqt", sha256: "f".repeat(64), size_bytes: 50, created_at: "2026-08-20T00:00:00Z" },
    charge_model: "gasteiger" as const,
    tool: { name: "Meeko", version: "0.7.1" },
    command: ["mk_prepare_ligand"],
    stdout: "",
    stderr: "",
    provenance: { event_id: "pdbqt-x", event_type: "ligand_pdbqt_prepared", timestamp: "2026-08-20T00:00:00Z", input_artifacts: [persistedConformer.artifact.conformer_id], output_artifacts: ["pdbqt-x"], tool: { name: "Meeko", version: "0.7.1" }, parameters: {}, warnings: [], command: ["mk_prepare_ligand"] },
    content_url: `/ligands/${readyMol.artifact.ligand_id}/preparations/pdbqt-x/content`,
  };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/ligand-libraries/import") && init?.method === "POST") return json(library, 201);
    if (url.endsWith("/ligand-libraries/library-1/preparation")) {
      return json({
        library_id: "library-1",
        updated_at: "2026-08-20T00:00:00Z",
        entries: {
          [readyMol.artifact.ligand_id]: {
            ligand_id: readyMol.artifact.ligand_id,
            status: "prepared",
            conformer_id: persistedConformer.artifact.conformer_id,
            pdbqt_preparation_id: "pdbqt-x",
            final_energy_kcal_mol: -3.3,
            error_message: null,
            updated_at: "2026-08-20T00:00:00Z",
          },
        },
      }, 200);
    }
    if (url.endsWith(`/ligands/${readyMol.artifact.ligand_id}/conformers/${persistedConformer.artifact.conformer_id}`)) {
      return json(persistedConformer, 200);
    }
    if (url.endsWith(`/ligands/${readyMol.artifact.ligand_id}/preparations/pdbqt-x`)) {
      return json(persistedPdbqt, 200);
    }
    return new Response(null, { status: 404 });
  });
  render(<LigandWorkspaceHarness structure={structure} tools={tools} />);

  fireEvent.click(screen.getByRole("button", { name: "Local file" }));
  const input = document.querySelector<HTMLInputElement>(".ligand-file-action input");
  fireEvent.change(input!, { target: { files: [new File(["synthetic"], "synthetic_library.sdf")] } });
  expect(await screen.findByRole("table")).toBeInTheDocument();

  await waitFor(() => {
    const summary = document.querySelector(".ligand-pdbqt-controls summary small")?.textContent;
    expect(summary).toBe("PDBQT ready");
  });
  expect(document.querySelector(".ligand-state-controls summary small")?.textContent).toBe("Confirmed");
  // Regression for the reported confusion: an already-prepared ligand must
  // not still show an actionable "Generate ligand PDBQT with Meeko" button -
  // a less experienced user could easily read that as something they still
  // need to click, when the work is already done.
  expect(screen.queryByRole("button", { name: "Generate ligand PDBQT with Meeko" })).not.toBeInTheDocument();
  expect(screen.getByText("PDBQT already generated")).toBeInTheDocument();
});
