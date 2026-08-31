import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../app/App";

const health = { status: "ok", backend_version: "0.1.0" } as const;
const system = { platform: "windows", architecture: "x86_64", python_version: "3.12.1", python_environment: "ankora-dev", app_mode: "development" };
const resources = { cpu_percent: 8.2, logical_cores: 16, memory_used_bytes: 17030922240, memory_total_bytes: 34053414912, memory_percent: 50, gpu: null, gpu_unavailable_reason: "No NVIDIA driver tools are installed on this machine." };
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
  meeko_ligand: { available: false, path: null, version: null },
  p2rank: { available: false, path: null, version: null },
};

function noSavedReceptor(): Response {
  return new Response(JSON.stringify({ code: "RECEPTOR_HISTORY_EMPTY", stage: "receptor_storage", message: "No saved receptor derivative is available in this project yet.", details: {}, recoverable: false }), { status: 404, headers: { "Content-Type": "application/json" } });
}

it("renders the connected backend and tool states", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith("/receptors/latest")) return noSavedReceptor();
    const payload = url.endsWith("/health") ? health : url.endsWith("/system/resources") ? resources : url.endsWith("/system") ? system : tools;
    return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
  });

  render(<App />);

  expect(screen.getAllByText("Connecting").length).toBeGreaterThan(0);
  await waitFor(() => expect(screen.getAllByText("Backend connected").length).toBeGreaterThan(0));
  expect(screen.getByText("of 11 tools detected")).toBeInTheDocument();
  expect(screen.getByText("0")).toBeInTheDocument();
  fireEvent.click(screen.getByText("View"));
  fireEvent.click(screen.getByRole("button", { name: "Light" }));
  expect(document.documentElement).toHaveAttribute("data-theme", "light");
  fireEvent.click(screen.getByText("Tools"));
  fireEvent.click(screen.getByRole("button", { name: "Scientific tool readiness" }));
  expect(screen.getByText("Python 3.12.1 · ankora-dev")).toBeInTheDocument();
  const rescanButton = await screen.findByRole("button", { name: "Rescan tools" });
  fireEvent.click(rescanButton);
  await waitFor(() => expect(rescanButton).toBeEnabled());
  expect(screen.getByTestId("viewer-placeholder")).toBeInTheDocument();
});

it("renders a disconnected state when the backend cannot be reached", async () => {
  vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));

  render(<App />);

  await waitFor(() => expect(screen.getAllByText("Backend disconnected").length).toBeGreaterThan(0));
  expect(screen.getAllByText(/Failed to fetch/).length).toBeGreaterThan(0);
});

it("imports a structure and exposes chains, heterogens, warnings, and provenance", async () => {
  const structure = {
    artifact: {
      artifact_id: "00000000-0000-0000-0000-000000000001",
      original_filename: "synthetic_m1.pdb",
      format: "pdb",
      sha256: "a".repeat(64),
      size_bytes: 900,
      source: "local",
      source_uri: null,
      imported_at: "2026-08-19T12:00:00Z",
    },
    metadata: {
      entry_id: "TST1",
      title: "Synthetic M1 fixture; not experimental data",
      experimental_method: "SYNTHETIC TEST DATA",
      resolution_angstrom: null,
      model_count: 1,
      atom_count: 9,
      residue_count: 4,
      chains: [{ chain_id: "A", residue_count: 4, polymer_residue_count: 1, atom_count: 9 }],
      heterogens: [{ name: "LIG", chain_id: "A", sequence_number: 101, insertion_code: "", atom_count: 2, kind: "ligand" }],
      alternate_location_atom_count: 2,
      missing_residue_count: 1,
      missing_atom_count: 0,
      nonstandard_polymer_residues: [],
    },
    warnings: [{ code: "STR_MISSING_RESIDUES", message: "Synthetic warning fixture.", stage: "structure_inspection", details: { count: 1 }, recoverable: true }],
    provenance: {
      event_id: "synthetic-event",
      event_type: "structure_imported",
      timestamp: "2026-08-19T12:00:00Z",
      input_artifacts: [],
      output_artifacts: ["00000000-0000-0000-0000-000000000001"],
      tool: { name: "ankora-structure-inspector", version: "0.1.0" },
      parameters: { fixture: "synthetic" },
      warnings: [],
      command: null,
    },
    content_url: "/structures/00000000-0000-0000-0000-000000000001/content",
  };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/receptors/latest")) return noSavedReceptor();
    if (init?.method === "POST") return new Response(JSON.stringify(structure), { status: 201, headers: { "Content-Type": "application/json" } });
    const payload = url.endsWith("/health") ? health : url.endsWith("/system/resources") ? resources : url.endsWith("/system") ? system : tools;
    return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  render(<App />);
  const input = document.querySelector<HTMLInputElement>(".primary-action input");
  expect(input).not.toBeNull();

  fireEvent.change(input!, { target: { files: [new File(["SYNTHETIC"], "synthetic_m1.pdb")] } });

  await waitFor(() => expect(screen.getByTestId("molecular-viewer")).toBeInTheDocument());
  expect(screen.getByText("TST1")).toBeInTheDocument();
  expect(screen.getByText(/LIG A:101/)).toBeInTheDocument();
  expect(screen.getByText("STR_MISSING_RESIDUES")).toBeInTheDocument();
  const chainButton = screen.getByRole("button", { name: /Chain A/ });
  fireEvent.click(chainButton);
  expect(chainButton).toHaveClass("selected");
  expect(screen.getByText(/LOCAL · aaaaaaaaaaaa/)).toBeInTheDocument();
});

it("requires explicit M2 decisions before creating a receptor derivative", async () => {
  const structure = {
    artifact: { artifact_id: "00000000-0000-0000-0000-000000000002", original_filename: "synthetic_m2.pdb", format: "pdb", sha256: "b".repeat(64), size_bytes: 900, source: "local", source_uri: null, imported_at: "2026-08-19T12:00:00Z" },
    metadata: { entry_id: "SYN2", title: "Synthetic M2 fixture", experimental_method: "SYNTHETIC TEST DATA", resolution_angstrom: null, model_count: 1, atom_count: 9, residue_count: 4, chains: [{ chain_id: "A", residue_count: 4, polymer_residue_count: 1, atom_count: 9 }], heterogens: [{ name: "LIG", chain_id: "A", sequence_number: 101, insertion_code: "", atom_count: 2, kind: "ligand" }], alternate_location_atom_count: 0, missing_residue_count: 0, missing_atom_count: 1, nonstandard_polymer_residues: [] },
    warnings: [], provenance: { event_id: "source", event_type: "structure_imported", timestamp: "2026-08-19T12:00:00Z", input_artifacts: [], output_artifacts: [], tool: { name: "ankora", version: "0.1.0" }, parameters: {}, warnings: [], command: null }, content_url: "/structures/source/content",
  };
  const report = {
    source_artifact_id: structure.artifact.artifact_id, generated_at: "2026-08-19T12:01:00Z", candidate_chains: ["A"], components: [{ component_id: "ligand|A|LIG|101|", name: "LIG", chain_id: "A", sequence_number: 101, insertion_code: "", atom_count: 2, kind: "ligand" }], water_count: 1,
    issues: [{ issue_id: "missing_atoms|A|ALA|1|", kind: "missing_atoms", residue: { chain_id: "A", residue_name: "ALA", sequence_number: 1, insertion_code: "" }, missing_atoms: ["CB"], alternate_locations: [], distance_to_reference_angstrom: null, severity: "unassessed", allowed_actions: ["leave", "repair", "remove", "manual_review"], message: "Synthetic missing atom; not experimental data." }],
    reference_component_id: null, near_reference_cutoff_angstrom: 8, warnings: [], provenance: { event_id: "inspection", event_type: "receptor_inspected", timestamp: "2026-08-19T12:01:00Z", input_artifacts: [structure.artifact.artifact_id], output_artifacts: [], tool: { name: "ankora", version: "0.1.0" }, parameters: {}, warnings: [], command: null },
  };
  const prepared = {
    receptor_id: "10000000-0000-0000-0000-000000000001", source_artifact_id: structure.artifact.artifact_id, created_at: "2026-08-19T12:02:00Z", status: "docking_ready",
    decisions: {
      selected_chains: ["A"], water_action: "remove", component_decisions: [{ component_id: "ligand|A|LIG|101|", action: "keep" }], issue_decisions: [{ issue_id: "missing_atoms|A|ALA|1|", action: "remove", selected_altloc: null }], reference_component_id: null, relaxation: { enabled: false, restraint_force_constant_kcal_mol_a2: 50.0, max_iterations: 200 }, protonation: { enabled: true, ph: 7.4, force_field: "AMBER" }, generate_pdbqt: true,
    },
    warnings: [], provenance: [], display_output_artifact_id: "20000000-0000-0000-0000-000000000001",
    outputs: [{ artifact_id: "20000000-0000-0000-0000-000000000001", stage: "selected", filename: "selected_receptor.pdb", format: "pdb", sha256: "c".repeat(64), size_bytes: 500, created_at: "2026-08-19T12:02:00Z", content_url: "/receptors/result/content" }],
  };
  const ligand = {
    artifact: { ligand_id: "50000000-0000-0000-0000-000000000001", source: "crystallographic", source_structure_id: structure.artifact.artifact_id, locator: { component_name: "LIG", chain_id: "A", sequence_number: 101, insertion_code: "" }, filename: "LIG_A_101.sdf", format: "sdf", sha256: "f".repeat(64), size_bytes: 400, created_at: "2026-08-19T12:03:00Z" },
    state: { state_id: "51000000-0000-0000-0000-000000000001", ligand_id: "50000000-0000-0000-0000-000000000001", filename: "inspected_state.sdf", format: "sdf", sha256: "8".repeat(64), size_bytes: 400, created_at: "2026-08-19T12:03:00Z" },
    inspection: { name: "LIG", formula: "C2H4O", molecular_weight_g_mol: 44.053, exact_mass_da: 44.0262, formal_charge: 0, atom_count: 3, heavy_atom_count: 3, rotatable_bond_count: 1, aromatic_ring_count: 0, stereocenter_count: 0, undefined_stereocenter_count: 0, fragment_count: 1, conformer_count: 1, has_3d_coordinates: true },
    warnings: [], provenance: { event_id: "ligand", event_type: "crystallographic_ligand_extracted", timestamp: "2026-08-19T12:03:00Z", input_artifacts: [structure.artifact.artifact_id], output_artifacts: ["50000000-0000-0000-0000-000000000001"], tool: { name: "RDKit/mmCIF topology", version: "synthetic" }, parameters: { fixture: "synthetic" }, warnings: [], command: null }, content_url: "/ligands/result/state/content", original_content_url: "/ligands/result/content",
  };
  const protonationOptions = {
    parent_state_id: "50000000-0000-0000-0000-000000000002",
    ph_min: 7.4, ph_max: 7.4, precision: 1.0, selection_required: false,
    candidates: [{ index: 0, canonical_smiles: "CCO", formal_charge: 0 }],
  };
  const protonatedState = {
    artifact: { state_id: "50000000-0000-0000-0000-000000000003", ligand_id: "50000000-0000-0000-0000-000000000001", parent_state_id: "50000000-0000-0000-0000-000000000002", stage: "protonated", filename: "LIG_protonated.sdf", format: "sdf", sha256: "5".repeat(64), size_bytes: 300, created_at: "2026-08-19T12:03:30Z" },
    selection: { ph_min: 7.4, ph_max: 7.4, precision: 1.0, candidate_index: 0, candidate_count: 1 },
    tool: { name: "Dimorphite-DL", version: "synthetic" },
    inspection: { name: "LIG", formula: "C2H4O", molecular_weight_g_mol: 44.053, exact_mass_da: 44.0262, formal_charge: 0, atom_count: 3, heavy_atom_count: 3, rotatable_bond_count: 1, aromatic_ring_count: 0, stereocenter_count: 0, undefined_stereocenter_count: 0, fragment_count: 1, conformer_count: 1, has_3d_coordinates: true },
    warnings: [], provenance: { event_id: "protonated", event_type: "ligand_protonation_resolved", timestamp: "2026-08-19T12:03:30Z", input_artifacts: [], output_artifacts: [], tool: { name: "Dimorphite-DL", version: "synthetic" }, parameters: {}, warnings: [], command: null },
    content_url: "/ligands/result/protonated/content",
  };
  const ligandPdbqt = {
    artifact: { pdbqt_id: "70000000-0000-0000-0000-000000000001", ligand_id: "50000000-0000-0000-0000-000000000001", conformer_id: "60000000-0000-0000-0000-000000000001", filename: "LIG.pdbqt", format: "pdbqt", sha256: "7".repeat(64), size_bytes: 410, created_at: "2026-08-19T12:05:00Z" },
    tool: { name: "Meeko", version: "synthetic" }, charge_model: "gasteiger",
    command: ["meeko"], stdout: "", stderr: "", warnings: [],
    provenance: { event_id: "pdbqt", event_type: "ligand_pdbqt_prepared", timestamp: "2026-08-19T12:05:00Z", input_artifacts: [], output_artifacts: [], tool: { name: "Meeko", version: "synthetic" }, parameters: {}, warnings: [], command: null },
    content_url: "/ligands/result/pdbqt/content",
  };
  const minimizedLigand = {
    artifact: { conformer_id: "60000000-0000-0000-0000-000000000001", ligand_id: ligand.artifact.ligand_id, stage: "minimized", filename: "LIG_MMFF94s_minimized.sdf", format: "sdf", sha256: "9".repeat(64), size_bytes: 620, created_at: "2026-08-19T12:04:00Z" },
    inspection: { ...ligand.inspection, atom_count: 9 },
    minimization: { force_field: "MMFF94s", max_iterations: 500, converged: true, initial_energy_kcal_mol: 12.75, final_energy_kcal_mol: -4.125, embedding_method: "ETKDGv3", random_seed: 20260819, independent_from_source_coordinates: true, conformer_pool_size: 20 },
    warnings: [], provenance: { event_id: "minimized", event_type: "ligand_conformer_minimized", timestamp: "2026-08-19T12:04:00Z", input_artifacts: [ligand.artifact.ligand_id], output_artifacts: ["60000000-0000-0000-0000-000000000001"], tool: { name: "RDKit MMFF", version: "synthetic" }, parameters: { fixture: "synthetic" }, warnings: [], command: null }, content_url: "/ligands/result/conformers/minimized/content",
  };
  let preparationAttempts = 0;
  const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/receptors/latest")) return noSavedReceptor();
    if (url.includes("receptor-inspection")) return new Response(JSON.stringify(report), { status: 200, headers: { "Content-Type": "application/json" } });
    if (url.includes("/conformers/generate") && init?.method === "POST") return new Response(JSON.stringify(minimizedLigand), { status: 201, headers: { "Content-Type": "application/json" } });
    if (url.includes("/protonation-options")) return new Response(JSON.stringify(protonationOptions), { status: 200, headers: { "Content-Type": "application/json" } });
    if (url.includes("/states/protonate") && init?.method === "POST") return new Response(JSON.stringify(protonatedState), { status: 201, headers: { "Content-Type": "application/json" } });
    if (url.includes("/pdbqt") && init?.method === "POST") return new Response(JSON.stringify(ligandPdbqt), { status: 201, headers: { "Content-Type": "application/json" } });
    if (url.includes("/ligands/extract") && init?.method === "POST") return new Response(JSON.stringify(ligand), { status: 201, headers: { "Content-Type": "application/json" } });
    if (url.includes("/receptors") && init?.method === "POST") {
      preparationAttempts += 1;
      if (preparationAttempts === 1) return new Response(JSON.stringify({
        code: "PDB2PQR_UNAPPROVED_HEAVY_ATOM_CHANGE",
        stage: "receptor_protonation",
        message: "Synthetic terminal oxygen completion requires explicit authorization.",
        details: {
          added_heavy_atoms: ["A|ALA|1||OXT"],
          removed_heavy_atoms: [],
        },
        recoverable: true,
      }), { status: 422, headers: { "Content-Type": "application/json" } });
      if (preparationAttempts === 2) return new Response(JSON.stringify({
        code: "MEEKO_CONNECTIVITY_FAILURE",
        stage: "receptor_pdbqt",
        message: "Synthetic Meeko connectivity failure.",
        details: {
          affected_residues: [{ chain_id: "A", residue_name: "ALA", sequence_number: 1, insertion_code: "", diagnostic: "SyntheticConnectivityError: synthetic test evidence" }],
        },
        recoverable: true,
      }), { status: 422, headers: { "Content-Type": "application/json" } });
      return new Response(JSON.stringify(prepared), { status: 201, headers: { "Content-Type": "application/json" } });
    }
    if (init?.method === "POST") return new Response(JSON.stringify(structure), { status: 201, headers: { "Content-Type": "application/json" } });
    const payload = url.endsWith("/health") ? health : url.endsWith("/system/resources") ? resources : url.endsWith("/system") ? system : tools;
    return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  render(<App />);
  const input = document.querySelector<HTMLInputElement>(".primary-action input");
  fireEvent.change(input!, { target: { files: [new File(["SYNTHETIC"], "synthetic_m2.pdb")] } });
  const workflow = within(screen.getByRole("navigation", { name: "Docking workflow" }));
  await waitFor(() => expect(workflow.getByRole("button", { name: /Receptor/ })).not.toBeDisabled());
  fireEvent.click(workflow.getByRole("button", { name: /Receptor/ }));
  await screen.findByText("Receptor plan");
  fireEvent.click(await screen.findByRole("button", { name: "Chain A" }));
  const decisionRows = document.querySelectorAll<HTMLElement>(".decision-row");
  expect(decisionRows).toHaveLength(2);
  fireEvent.click(within(decisionRows[0]).getByRole("button", { name: "Remove" }));
  fireEvent.click(within(decisionRows[1]).getByRole("button", { name: "Keep" }));
  fireEvent.click(screen.getByRole("button", { name: "Explicitly leave all" }));
  const apply = screen.getByRole("button", { name: "Apply explicit preparation plan" });
  expect(apply).not.toBeDisabled();
  const protonation = screen.getByRole("checkbox", { name: /Run PDB2PQR/ });
  fireEvent.click(protonation);
  expect(apply).toBeDisabled();
  expect(screen.getByText(/must be resolved before protonation/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Repair 1 missing-atom residue with PDBFixer" }));
  fireEvent.click(screen.getByRole("checkbox", { name: /Generate receptor PDBQT/ }));
  expect(apply).not.toBeDisabled();
  fireEvent.click(apply);
  await screen.findByText("PDB2PQR proposed exact terminal oxygen completion:");
  fireEvent.click(screen.getByRole("button", { name: "Authorize 1 exact terminal OXT addition" }));
  expect(screen.getByRole("button", { name: "1 terminal addition authorized" })).toBeDisabled();
  expect(screen.getByText(/Only these identities may be added by PDB2PQR/)).toBeInTheDocument();
  fireEvent.click(apply);
  await screen.findByText("Invalid connectivity remained in these repaired residues:");
  fireEvent.click(screen.getByRole("button", { name: "Mark 1 affected residue for removal" }));
  expect(screen.getByRole("combobox", { name: "Decision for ALA 1" })).toHaveValue("remove");
  expect(screen.getByRole("button", { name: "1 affected residue marked for removal" })).toBeDisabled();
  fireEvent.click(apply);
  await screen.findByText(/1 immutable outputs/);
  expect(screen.getByRole("button", { name: "Prepared" })).toHaveClass("selected");
  expect(screen.getByText("Prepared receptor")).toBeInTheDocument();
  expect(screen.getByText(/Removed waters, components, chains, and residues are hidden/)).toBeInTheDocument();
  expect(screen.getByText(/waters removed/)).toBeInTheDocument();
  expect(screen.getByText(/1 residue removed/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Overlay" }));
  expect(screen.getByText("Comparison overlay")).toBeInTheDocument();
  expect(screen.getByText(/Original and prepared structures are both visible/)).toBeInTheDocument();
  const requestCalls = fetchSpy.mock.calls.filter(([url, init]) => String(url).includes("/receptors") && init?.method === "POST");
  expect(requestCalls).toHaveLength(3);
  const body = JSON.parse(String(requestCalls[2][1]?.body));
  expect(body).toEqual(expect.objectContaining({
    selected_chains: ["A"],
    water_action: "remove",
    generate_pdbqt: true,
    protonation: expect.objectContaining({
      enabled: true,
      authorized_terminal_heavy_atom_additions: [{
        chain_id: "A",
        residue_name: "ALA",
        sequence_number: 1,
        insertion_code: "",
        atom_name: "OXT",
      }],
    }),
  }));
  expect(body.issue_decisions[0]).toEqual(expect.objectContaining({ action: "remove" }));
  fireEvent.click(workflow.getByRole("button", { name: /Ligand/ }));
  await screen.findByText("Ligand preparation");
  fireEvent.click(screen.getByRole("button", { name: "Extract LIG" }));
  expect(await screen.findByText("LIG · C2H4O")).toBeInTheDocument();
  expect(screen.getByText("44.053 g/mol")).toBeInTheDocument();
  // One action, and it cannot run until the scientist confirms the plan.
  const prepare = screen.getByRole("button", { name: "Prepare conformer (Meeko unavailable)" });
  expect(prepare).toBeDisabled();
  // An unambiguous molecule presents no protonation choice, only a statement.
  expect((await screen.findByText("Ionization")).parentElement).toHaveTextContent(
    /single state, nothing to decide/,
  );
  fireEvent.click(screen.getByRole("checkbox", { name: /Use exactly this species/ }));
  fireEvent.click(prepare);

  // The one click carried the ligand all the way to a docking-ready PDBQT.
  expect(await screen.findByText("Conformer preparation converged")).toBeInTheDocument();
  expect(screen.getByText("-4.125 kcal/mol")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "minimized" })).toHaveClass("selected");
  // Meeko is not configured in this fixture, so the chain stops at the
  // conformer instead of blocking the chemistry that does not need it.
  const posted = fetchSpy.mock.calls.filter(([url, init]) => init?.method === "POST");
  expect(posted.some(([url]) => String(url).includes("/conformers/generate"))).toBe(true);
  expect(posted.some(([url]) => String(url).includes("/pdbqt"))).toBe(false);
  // The ionization decision is recorded as its own derivative, even when
  // Dimorphite-DL found a single state: the pH and tool version are evidence.
  expect(posted.some(([url]) => String(url).includes("/states/protonate"))).toBe(true);
  // Docking models one pH, so the default enumeration asks for one pH.
  expect(fetchSpy.mock.calls.some(([url]) =>
    String(url).includes("protonation-options?ph_min=7.4&ph_max=7.4"))).toBe(true);
});

it("reopens the latest receptor without rerunning scientific tools", async () => {
  const sourceId = "00000000-0000-0000-0000-000000000003";
  const structure = {
    artifact: { artifact_id: sourceId, original_filename: "saved_source.pdb", format: "pdb", sha256: "d".repeat(64), size_bytes: 900, source: "local", source_uri: null, imported_at: "2026-08-19T12:00:00Z" },
    metadata: { entry_id: "SAVE", title: "Saved synthetic receptor source", experimental_method: "SYNTHETIC TEST DATA", resolution_angstrom: null, model_count: 1, atom_count: 4, residue_count: 1, chains: [{ chain_id: "A", residue_count: 1, polymer_residue_count: 1, atom_count: 4 }], heterogens: [], alternate_location_atom_count: 0, missing_residue_count: 0, missing_atom_count: 0, nonstandard_polymer_residues: [] },
    warnings: [], provenance: { event_id: "source", event_type: "structure_imported", timestamp: "2026-08-19T12:00:00Z", input_artifacts: [], output_artifacts: [sourceId], tool: { name: "ankora", version: "0.1.0" }, parameters: { fixture: "synthetic" }, warnings: [], command: null }, content_url: `/structures/${sourceId}/content`,
  };
  const report = {
    source_artifact_id: sourceId, generated_at: "2026-08-19T12:01:00Z", candidate_chains: ["A"], components: [], water_count: 0, issues: [], reference_component_id: null, near_reference_cutoff_angstrom: 8, warnings: [], provenance: { event_id: "inspection", event_type: "receptor_inspected", timestamp: "2026-08-19T12:01:00Z", input_artifacts: [sourceId], output_artifacts: [], tool: { name: "ankora", version: "0.1.0" }, parameters: { fixture: "synthetic" }, warnings: [], command: null },
  };
  const saved = {
    receptor_id: "30000000-0000-0000-0000-000000000001", source_artifact_id: sourceId, created_at: "2026-08-19T12:02:00Z", status: "docking_ready",
    decisions: { selected_chains: ["A"], water_action: "remove", component_decisions: [], issue_decisions: [], reference_component_id: null, relaxation: { enabled: false, restraint_force_constant_kcal_mol_a2: 50.0, max_iterations: 200 }, protonation: { enabled: true, ph: 7.4, force_field: "AMBER" }, generate_pdbqt: true },
    warnings: [], provenance: [], display_output_artifact_id: "40000000-0000-0000-0000-000000000001",
    outputs: [{ artifact_id: "40000000-0000-0000-0000-000000000001", stage: "protonated_pdb", filename: "protonated_receptor.pdb", format: "pdb", sha256: "e".repeat(64), size_bytes: 800, created_at: "2026-08-19T12:02:00Z", content_url: "/receptors/saved/content" }],
  };
  const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith("/receptors/latest")) return new Response(JSON.stringify(saved), { status: 200, headers: { "Content-Type": "application/json" } });
    if (url.includes("receptor-inspection")) return new Response(JSON.stringify(report), { status: 200, headers: { "Content-Type": "application/json" } });
    if (url.endsWith(`/structures/${sourceId}`)) return new Response(JSON.stringify(structure), { status: 200, headers: { "Content-Type": "application/json" } });
    const payload = url.endsWith("/health") ? health : url.endsWith("/system/resources") ? resources : url.endsWith("/system") ? system : tools;
    return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
  });

  render(<App />);
  await waitFor(() => expect(document.querySelector(".resume-receptor-action")).not.toBeNull());
  fireEvent.click(document.querySelector<HTMLButtonElement>(".resume-receptor-action")!);

  await screen.findByText("Receptor plan");
  expect(screen.getByRole("button", { name: "Prepared" })).toHaveClass("selected");
  expect(await screen.findByText("docking ready")).toBeInTheDocument();
  expect(screen.getByText(/protonated_receptor.pdb only/)).toBeInTheDocument();
  expect(fetchSpy.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
});
