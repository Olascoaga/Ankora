import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { ankoraApi, ApiError } from "../api/client";
import { ReceptorWorkspace } from "../features/receptor/ReceptorWorkspace";
import type { ReceptorInspectionReport, ReceptorPreparationRecord, ReceptorProtonationAnalysis, StructureRecord } from "../types/api";

vi.mock("../viewer/MolecularViewer", () => ({ MolecularViewer: () => <div>Mock 3D viewer</div> }));

// Explicitly synthetic UI/diagnostic fixtures, not a 7AQF preparation or OpenMM result.
const provenance = { event_id: "synthetic", event_type: "synthetic", timestamp: "2026-10-13T00:00:00Z", input_artifacts: [], output_artifacts: [], tool: { name: "synthetic", version: "1" }, parameters: {}, warnings: [], command: null };
const structure = {
  artifact: { artifact_id: "source-1", original_filename: "synthetic.pdb", format: "pdb", sha256: "a".repeat(64), size_bytes: 100, source: "local", source_uri: null, imported_at: "2026-10-13T00:00:00Z" },
  metadata: { entry_id: "SYN", title: "Synthetic", experimental_method: null, resolution_angstrom: null, model_count: 1, atom_count: 5, residue_count: 1, chains: [], heterogens: [], alternate_location_atom_count: 0, missing_residue_count: 0, missing_atom_count: 1, nonstandard_polymer_residues: [] },
  warnings: [], provenance, content_url: "/structures/source-1/content",
} satisfies StructureRecord;
const residue = { chain_id: "A", residue_name: "ALA", sequence_number: 1, insertion_code: "" };
const report = {
  source_artifact_id: "source-1", generated_at: "2026-10-13T00:00:00Z", candidate_chains: ["A"], components: [], water_count: 0,
  issues: [{ issue_id: "missing-1", kind: "missing_atoms", residue, missing_atoms: ["CB"], alternate_locations: [], distance_to_reference_angstrom: null, severity: "unassessed", allowed_actions: ["repair", "leave", "remove", "manual_review"], message: "Synthetic missing atom" }],
  reference_component_id: null, near_reference_cutoff_angstrom: 8, warnings: [], provenance,
} satisfies ReceptorInspectionReport;

const analysis = {
  generated_at: "2026-10-14T00:00:00Z", input_sha256: "b".repeat(64), target_ph: 7.4,
  force_field: "AMBER", tool_version: "synthetic", reference_component_id: null,
  near_reference_cutoff_angstrom: 8, metal_warning_cutoff_angstrom: 4,
  proposals: [{ proposal_id: "his", residue: { ...residue, residue_name: "HIS", sequence_number: 5 },
    group_label: "Synthetic HIS A:5", group_type: "HIS", predicted_pka: 6.5, model_pka: null,
    buried_fraction: null, coupled_group: null, predicted_state: "HIS_NEUTRAL_AUTO",
    default_state: "HIS_NEUTRAL_AUTO", selected_state: "HIS_NEUTRAL_AUTO", output_state: "HID",
    allowed_states: ["HIS_NEUTRAL_AUTO", "HID", "HIE", "HIP"], decision_source: "propka_prediction",
    distance_to_reference_angstrom: null, near_reference: false, nearby_metals: [], warnings: ["PKA_NEAR_TARGET_PH"] },
  { proposal_id: "lys", residue: { ...residue, residue_name: "LYS", sequence_number: 6 },
    group_label: "Synthetic LYS A:6", group_type: "LYS", predicted_pka: 10.5, model_pka: null,
    buried_fraction: null, coupled_group: null, predicted_state: "LYS", default_state: "LYS",
    selected_state: "LYS", output_state: "LYS", allowed_states: ["LYS", "LYN"], decision_source: "propka_prediction",
    distance_to_reference_angstrom: null, near_reference: false, nearby_metals: [], warnings: [] }],
} satisfies ReceptorProtonationAnalysis;

function connectivityFailure() {
  return new ApiError("Synthetic Meeko failure", 422, {
    code: "MEEKO_CONNECTIVITY_FAILURE", stage: "receptor_pdbqt", recoverable: true,
    message: "Synthetic Meeko failure", details: { affected_residues: [residue] },
  });
}

async function openWorkspace(inspection: ReceptorInspectionReport = report, mode: "guided" | "advanced" = "advanced") {
  vi.spyOn(ankoraApi, "inspectReceptor").mockResolvedValue(inspection);
  const onSelect = vi.fn();
  render(<ReceptorWorkspace structure={structure} initialRecord={null} tools={null} selection={null} onSelect={onSelect} onRecordChange={vi.fn()} />);
  if (mode === "advanced") fireEvent.click(await screen.findByRole("button", { name: "Advanced controls" }));
  fireEvent.click(await screen.findByRole("button", { name: "Chain A" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  fireEvent.change(screen.getByLabelText("Decision for ALA 1"), { target: { value: "repair" } });
  return { onSelect, relaxation: screen.getByRole("checkbox", { name: /Relax repaired residues with OpenMM/, hidden: mode === "guided" }) };
}

async function guidedToPreparation() {
  vi.spyOn(ankoraApi, "inspectReceptor").mockResolvedValue(report);
  render(<ReceptorWorkspace structure={structure} initialRecord={null} tools={null} selection={null} onSelect={vi.fn()} onRecordChange={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Chain A" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  fireEvent.click(screen.getByRole("button", { name: "Next · review repairs" }));
  fireEvent.click(screen.getByRole("button", { name: "Repair 1 incomplete side-chain(s)" }));
  fireEvent.click(screen.getByRole("button", { name: "Next · hydrogens and preparation" }));
}

it("offers observed terminal oxygens for individual explicit review before protonation", async () => {
  const candidate = { ...residue, atom_name: "OXT" as const };
  const second = { ...candidate, chain_id: "B", sequence_number: 2 };
  const preview = vi.spyOn(ankoraApi, "previewReceptorProtonation").mockResolvedValue(analysis);
  await openWorkspace({ ...report, candidate_chains: ["A", "B"], terminal_oxygen_candidates: [candidate, second] });
  fireEvent.click(screen.getByRole("checkbox", { name: /Run PDB2PQR/ }));
  const option = screen.getByRole("checkbox", { name: /Allow OXT · ALA A:1/ });
  expect(option).not.toBeChecked();
  expect(screen.queryByRole("checkbox", { name: /Allow OXT · ALA B:2/ })).not.toBeInTheDocument();
  expect(preview).not.toHaveBeenCalled();
  fireEvent.click(option);
  expect(option).toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "Analyze pKa proposals" }));
  await waitFor(() => expect(preview).toHaveBeenCalledWith("source-1", expect.objectContaining({
    protonation: expect.objectContaining({ authorized_terminal_heavy_atom_additions: [candidate] }),
  })));
  fireEvent.click(screen.getByRole("button", { name: "Chain A" }));
  expect(screen.getByText("Clear terminal oxygen authorizations for deselected chains or removed residues.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Clear terminal oxygen authorizations" }));
  expect(screen.queryByText("Clear terminal oxygen authorizations for deselected chains or removed residues.")).not.toBeInTheDocument();
});

it("blocks a terminal authorization when its residue is marked for removal", async () => {
  const candidate = { ...residue, atom_name: "OXT" as const };
  const preview = vi.spyOn(ankoraApi, "previewReceptorProtonation");
  await openWorkspace({ ...report, terminal_oxygen_candidates: [candidate] });
  fireEvent.click(screen.getByRole("checkbox", { name: /Run PDB2PQR/ }));
  fireEvent.click(screen.getByRole("checkbox", { name: /Allow OXT · ALA A:1/ }));
  fireEvent.change(screen.getByLabelText("Decision for ALA 1"), { target: { value: "remove" } });
  expect(screen.getByText("Clear terminal oxygen authorizations for deselected chains or removed residues.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Analyze pKa proposals" })).not.toBeInTheDocument();
  expect(preview).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("checkbox", { name: /Allow OXT · ALA A:1/ }));
  expect(screen.queryByText("Clear terminal oxygen authorizations for deselected chains or removed residues.")).not.toBeInTheDocument();
});

it("starts with three guided steps and no scientific defaults applied", async () => {
  vi.spyOn(ankoraApi, "inspectReceptor").mockResolvedValue(report);
  const prepare = vi.spyOn(ankoraApi, "prepareReceptor");
  const preview = vi.spyOn(ankoraApi, "previewReceptorProtonation");
  render(<ReceptorWorkspace structure={structure} initialRecord={null} tools={null} selection={null} onSelect={vi.fn()} onRecordChange={vi.fn()} />);
  expect(await screen.findByRole("button", { name: "Guided preparation" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "2 · Review repairs" })).toBeDisabled();
  expect(screen.queryByRole("checkbox", { name: /Run PDB2PQR/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Apply explicit preparation plan" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Chain A" }));
  expect(screen.getByLabelText("Decision for ALA 1")).toHaveValue("");
  expect(prepare).not.toHaveBeenCalled();
  expect(preview).not.toHaveBeenCalled();
});

it("requires individual review for a retained incomplete component without offering protein repair", async () => {
  const component = { component_id: "synthetic-component", name: "LIG", chain_id: "A", sequence_number: 101,
    insertion_code: "X", atom_count: 2, kind: "ligand" as const };
  const componentIssue = { ...report.issues[0], issue_id: "synthetic-component-missing",
    residue: { ...residue, residue_name: "LIG", sequence_number: 101, insertion_code: "X" },
    missing_atoms: ["N1"], allowed_actions: ["leave", "remove", "manual_review"] as const };
  vi.spyOn(ankoraApi, "inspectReceptor").mockResolvedValue({ ...report, candidate_chains: ["A", "B"],
    components: [component], issues: [report.issues[0], { ...componentIssue, allowed_actions: [...componentIssue.allowed_actions] }] });
  const preview = vi.spyOn(ankoraApi, "previewReceptorProtonation");
  const prepare = vi.spyOn(ankoraApi, "prepareReceptor");
  render(<ReceptorWorkspace structure={structure} initialRecord={null} tools={null} selection={null} onSelect={vi.fn()} onRecordChange={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Chain A" }));
  const rows = screen.getAllByRole("button", { name: "Remove" });
  fireEvent.click(rows[0]); // Explicit water choice, not a component default.
  fireEvent.click(screen.getAllByRole("button", { name: "Keep" })[1]);
  expect(screen.getByText(/Retained ligands and metals may require/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Next · review repairs" }));
  expect(screen.getByText(/1 incomplete component\(s\) need individual review/)).toBeInTheDocument();
  expect(within(screen.getByLabelText("Decision for LIG 101X")).queryByRole("option", { name: "Repair" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Repair 1 incomplete side-chain(s)" }));
  expect(screen.getByRole("button", { name: "Next · hydrogens and preparation" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Review component choices" }));
  fireEvent.click(screen.getAllByRole("button", { name: "Remove" })[1]);
  expect(screen.queryByLabelText("Decision for LIG 101X")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Next · review repairs" }));
  expect(screen.getByText(/1 observation\(s\) excluded by your component-removal choices/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Next · hydrogens and preparation" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Next · hydrogens and preparation" }));
  expect(screen.getByText("LIG A:101X · remove")).toBeInTheDocument();
  expect(preview).not.toHaveBeenCalled();
  expect(prepare).not.toHaveBeenCalled();
});

it("sends only included residue decisions after an explicit component exclusion", async () => {
  const component = { component_id: "synthetic-component", name: "LIG", chain_id: "A", sequence_number: 101,
    insertion_code: "", atom_count: 2, kind: "ligand" as const };
  const componentIssue = { ...report.issues[0], issue_id: "synthetic-component-missing",
    residue: { ...residue, residue_name: "LIG", sequence_number: 101 }, allowed_actions: ["leave", "remove", "manual_review"] as const };
  vi.spyOn(ankoraApi, "inspectReceptor").mockResolvedValue({ ...report, components: [component],
    issues: [report.issues[0], { ...componentIssue, allowed_actions: [...componentIssue.allowed_actions] }] });
  const prepare = vi.spyOn(ankoraApi, "prepareReceptor").mockRejectedValue(connectivityFailure());
  render(<ReceptorWorkspace structure={structure} initialRecord={null} tools={null} selection={null} onSelect={vi.fn()} onRecordChange={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Advanced controls" }));
  fireEvent.click(screen.getByRole("button", { name: "Chain A" }));
  for (const button of screen.getAllByRole("button", { name: "Remove" })) fireEvent.click(button);
  fireEvent.change(screen.getByLabelText("Decision for ALA 1"), { target: { value: "leave" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply explicit preparation plan" }));
  await waitFor(() => expect(prepare).toHaveBeenCalledWith("source-1", expect.objectContaining({
    component_decisions: [{ component_id: component.component_id, action: "remove" }],
    issue_decisions: [expect.objectContaining({ issue_id: "missing-1", action: "leave" })],
  })));
});

it("requires an exact protonation review and explicit confirmation before guided preparation", async () => {
  const preview = vi.spyOn(ankoraApi, "previewReceptorProtonation").mockResolvedValue(analysis);
  const prepare = vi.spyOn(ankoraApi, "prepareReceptor").mockRejectedValue(connectivityFailure());
  await guidedToPreparation();
  const apply = screen.getByRole("button", { name: "Apply explicit preparation plan" });
  expect(apply).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox", { name: /Prepare for docking/ }));
  expect(apply).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Analyze pKa proposals" }));
  await screen.findByText("2 pKa proposals");
  expect(screen.queryByLabelText("Protonation decision for Synthetic LYS A:6")).not.toBeInTheDocument();
  expect(apply).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox", { name: /I reviewed the system/ }));
  expect(apply).toBeEnabled();
  expect(prepare).not.toHaveBeenCalled();
  fireEvent.click(apply);
  await waitFor(() => expect(prepare).toHaveBeenCalledWith("source-1", expect.objectContaining({
    repair_method: "topology_guard_v3", repair_seed: 20261014,
    inspection_method: "templates_v1",
    relaxation: expect.objectContaining({ enabled: false }), generate_pdbqt: true,
    issue_decisions: [expect.objectContaining({ action: "repair" })],
  })));
  expect(preview).toHaveBeenCalledTimes(1);
});

it("preserves decisions across modes and invalidates a confirmed plan after a pH edit", async () => {
  vi.spyOn(ankoraApi, "previewReceptorProtonation").mockResolvedValue(analysis);
  const prepare = vi.spyOn(ankoraApi, "prepareReceptor");
  await guidedToPreparation();
  fireEvent.click(screen.getByRole("checkbox", { name: /Prepare for docking/ }));
  fireEvent.click(screen.getByRole("button", { name: "Analyze pKa proposals" }));
  await screen.findByText("2 pKa proposals");
  fireEvent.click(screen.getByRole("checkbox", { name: /I reviewed the system/ }));
  fireEvent.click(screen.getByRole("button", { name: "Advanced controls" }));
  expect(screen.getByLabelText("Decision for ALA 1")).toHaveValue("repair");
  expect(screen.getByLabelText("Repair method")).toHaveValue("topology_guard_v3");
  fireEvent.click(screen.getByRole("button", { name: "Guided preparation" }));
  fireEvent.change(screen.getByLabelText("Target pH"), { target: { value: "6.5" } });
  expect(screen.getByRole("checkbox", { name: /I reviewed the system/ })).not.toBeChecked();
  expect(screen.getByRole("button", { name: "Apply explicit preparation plan" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Analyze pKa proposals" })).toBeEnabled();
  expect(prepare).not.toHaveBeenCalled();
});

it("blocks an invalid numerical draft before starting scientific tools", async () => {
  const preview = vi.spyOn(ankoraApi, "previewReceptorProtonation");
  await guidedToPreparation();
  fireEvent.click(screen.getByRole("checkbox", { name: /Prepare for docking/ }));
  fireEvent.change(screen.getByLabelText("Target pH"), { target: { value: "15" } });
  expect(screen.getByText("Enter valid pH and advanced numerical parameters.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Analyze pKa proposals" })).not.toBeInTheDocument();
  expect(preview).not.toHaveBeenCalled();
});

it("does not silently upgrade a restored historical repair method", async () => {
  vi.spyOn(ankoraApi, "inspectReceptor").mockResolvedValue(report);
  const prepare = vi.spyOn(ankoraApi, "prepareReceptor").mockRejectedValue(connectivityFailure());
  const historical: ReceptorPreparationRecord = {
    receptor_id: "synthetic-historical", source_artifact_id: "source-1", created_at: provenance.timestamp,
    status: "selected", outputs: [], warnings: [], provenance: [], display_output_artifact_id: "synthetic-no-display",
    decisions: { selected_chains: ["A"], water_action: "remove", component_decisions: [],
      issue_decisions: [{ issue_id: "missing-1", action: "repair", selected_altloc: null }],
      reference_component_id: null, relaxation: { enabled: false, restraint_force_constant_kcal_mol_a2: 50, max_iterations: 200 },
      protonation: { enabled: false, ph: 7.4, force_field: "AMBER", overrides: [], authorized_terminal_heavy_atom_additions: [] }, generate_pdbqt: false },
  };
  render(<ReceptorWorkspace structure={structure} initialRecord={historical} tools={null} selection={null} onSelect={vi.fn()} onRecordChange={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Advanced controls" }));
  expect(screen.getByLabelText("Repair method")).toHaveValue("legacy");
  fireEvent.click(screen.getByRole("button", { name: "Prepare this receptor" }));
  await waitFor(() => expect(prepare).toHaveBeenCalledTimes(1));
  expect(prepare.mock.calls[0][1]).not.toHaveProperty("repair_method");
  expect(prepare.mock.calls[0][1]).not.toHaveProperty("inspection_method");
  expect(ankoraApi.inspectReceptor).toHaveBeenCalledWith("source-1", null, "reported_only");
});

it("explains incompatible observed anchors without offering clash relief as a bond repair", async () => {
  vi.spyOn(ankoraApi, "prepareReceptor").mockRejectedValue(new ApiError("Synthetic stretched bond rejection", 422, {
    code: "RECEPTOR_REPAIRED_GEOMETRY_INVALID", stage: "receptor_repair", recoverable: true,
    message: "Synthetic stretched bond rejection", details: { affected_residues: [{ ...residue,
      fixed_anchor_conflicts: [{ reconstructed_atom: "CB", observed_atoms: ["CA", "C"],
        observed_distance_angstrom: 3.6, template_bond_sum_angstrom: 2.8 }] }] },
  }));
  await openWorkspace();
  fireEvent.click(screen.getByRole("button", { name: "Prepare this receptor" }));
  expect(await screen.findByText(/are 3.600 Å apart/)).toHaveTextContent(/total 2.800 Å/);
  expect(screen.getByLabelText("Decision for ALA 1")).toHaveValue("repair");
  expect(screen.queryByRole("button", { name: /Enable clash relief/ })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Inspect ALA A:1 in 3D" })).toBeInTheDocument();
});

it("lets the scientist turn relaxation off after the last repair is changed to manual review", async () => {
  const { relaxation } = await openWorkspace();
  fireEvent.click(relaxation);
  fireEvent.change(screen.getByLabelText("Decision for ALA 1"), { target: { value: "manual_review" } });
  expect(relaxation).toBeChecked();
  expect(relaxation).toBeEnabled();
  fireEvent.click(relaxation);
  expect(relaxation).not.toBeChecked();
  expect(relaxation).toBeDisabled();
  expect(screen.queryByText(/Relaxation is enabled but no residue/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Apply explicit preparation plan" })).toBeDisabled();
});

it("shows displaced atom evidence and focuses its residue without applying or removing anything", async () => {
  const failure = new ApiError("Observed atom displacement exceeded the safety limit.", 422, {
    code: "RECEPTOR_RELAXATION_TOLERANCE_EXCEEDED", stage: "receptor_relaxation", recoverable: true,
    message: "Observed atom displacement exceeded the safety limit.",
    details: { max_displacement_angstrom: 0.9, tolerance_angstrom: 0.5, displaced_atom_count: 1, displaced_atoms: [{ residue, atom_name: "O", displacement_angstrom: 0.9, original_position_angstrom: [0, 0, 0], relaxed_position_angstrom: [0.9, 0, 0] }] },
  });
  const prepare = vi.spyOn(ankoraApi, "prepareReceptor").mockRejectedValue(failure);
  const { relaxation, onSelect } = await openWorkspace();
  fireEvent.click(relaxation);
  fireEvent.click(screen.getByRole("button", { name: "Apply explicit preparation plan" }));
  const focus = await screen.findByRole("button", { name: /Inspect ALA A:1.*O.*in 3D/ });
  expect(screen.getByText(/0.900 Å/)).toBeInTheDocument();
  fireEvent.click(focus);
  expect(onSelect).toHaveBeenLastCalledWith({ kind: "residue", residue: { chainId: "A", residueName: "ALA", sequenceNumber: 1, insertionCode: "" } });
  expect(prepare).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("Decision for ALA 1")).toHaveValue("repair");
  fireEvent.click(screen.getByRole("button", { name: "Disable relaxation in the plan" }));
  expect(relaxation).not.toBeChecked();
  expect(await screen.findByText(/This failure belongs to a previous plan/)).toBeInTheDocument();
  expect(screen.getByText("Technical evidence")).toBeInTheDocument();
  expect(prepare).toHaveBeenCalledTimes(1);
});

it("keeps advanced relaxation settings folded and preserves their defaults", async () => {
  const { relaxation } = await openWorkspace();
  fireEvent.click(relaxation);
  const advanced = screen.getByText("Advanced relaxation parameters").closest("details");
  expect(advanced).not.toHaveAttribute("open");
  expect(screen.getByLabelText(/Restraint force constant/)).toHaveValue(50);
  expect(screen.getByLabelText("Maximum iterations")).toHaveValue(200);
});

it("keeps legacy errors usable without inventing an affected residue", async () => {
  vi.spyOn(ankoraApi, "prepareReceptor").mockRejectedValue(new ApiError("Synthetic legacy error", 422, {
    code: "RECEPTOR_RELAXATION_TOLERANCE_EXCEEDED", stage: "receptor_relaxation", recoverable: true,
    message: "Synthetic legacy error", details: { max_displacement_angstrom: 0.9, tolerance_angstrom: 0.5 },
  }));
  const { relaxation } = await openWorkspace();
  fireEvent.click(relaxation);
  fireEvent.click(screen.getByRole("button", { name: "Apply explicit preparation plan" }));
  expect(await screen.findByText(/This older error does not identify individual atoms/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^Inspect .* in 3D/ })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Decision for ALA 1"), { target: { value: "manual_review" } });
  expect(screen.getByText(/This failure belongs to a previous plan/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Apply explicit preparation plan" })).toBeDisabled();
  expect(relaxation).toBeEnabled();
});

it("does not count alternate-conformation selection as missing-atom repair", async () => {
  const { relaxation } = await openWorkspace({ ...report, issues: [{ ...report.issues[0],
    kind: "alternate_location", missing_atoms: [], alternate_locations: ["A", "B"],
  }] });
  fireEvent.click(screen.getByRole("button", { name: "Use A" }));
  expect(relaxation).not.toBeChecked();
  expect(relaxation).toBeDisabled();
  expect(screen.getByRole("button", { name: "Apply explicit preparation plan" })).toBeEnabled();
});

it("retains preparation evidence after changing the distance reference and refreshing inspection", async () => {
  const prepare = vi.spyOn(ankoraApi, "prepareReceptor").mockRejectedValue(new ApiError("Synthetic previous failure", 422, {
    code: "RECEPTOR_RELAXATION_TOLERANCE_EXCEEDED", stage: "receptor_relaxation", recoverable: true,
    message: "Synthetic previous failure", details: { max_displacement_angstrom: 0.9, tolerance_angstrom: 0.5 },
  }));
  const { relaxation } = await openWorkspace({ ...report, components: [{
    component_id: "reference-1", name: "LIG", chain_id: "B", sequence_number: 101,
    insertion_code: "", atom_count: 2, kind: "ligand",
  }] });
  fireEvent.click(relaxation);
  fireEvent.click(screen.getByRole("button", { name: "Apply explicit preparation plan" }));
  await screen.findByText("Synthetic previous failure");
  fireEvent.change(screen.getByLabelText("Reference component"), { target: { value: "reference-1" } });
  await waitFor(() => expect(ankoraApi.inspectReceptor).toHaveBeenLastCalledWith("source-1", "reference-1", "templates_v1"));
  expect(screen.getByText(/This failure belongs to a previous plan/)).toBeInTheDocument();
  expect(screen.getByText("Synthetic previous failure")).toBeInTheDocument();
  expect(screen.getByText("Technical evidence")).toBeInTheDocument();
  expect(prepare).toHaveBeenCalledTimes(1);
});

it("guides a changed Meeko removal plan to a fresh review, without automatic preparation", async () => {
  const preview = vi.spyOn(ankoraApi, "previewReceptorProtonation").mockResolvedValue(analysis);
  const prepare = vi.spyOn(ankoraApi, "prepareReceptor").mockRejectedValue(connectivityFailure());
  await openWorkspace();
  fireEvent.click(screen.getByRole("checkbox", { name: /Run PDB2PQR/ }));
  fireEvent.click(screen.getByRole("checkbox", { name: /Generate receptor PDBQT/ }));
  const next = within(screen.getByRole("region", { name: "Preparation next step" }));
  fireEvent.click(next.getByRole("button", { name: "Analyze pKa proposals" }));
  await screen.findByText("2 pKa proposals");
  fireEvent.click(next.getByRole("button", { name: "Prepare this receptor" }));
  fireEvent.click(await screen.findByRole("button", { name: "Mark 1 affected residue for removal" }));
  expect(screen.getByText("Previous attempt · your updated plan has not run").closest(".receptor-error")).toHaveAttribute("role", "status");
  expect(screen.getByText(/Previous attempt evidence ·/).closest("details")).not.toHaveAttribute("open");
  expect(next.getByText(/Your structural plan changed/)).toBeInTheDocument();
  expect(next.getByRole("button", { name: "Analyze pKa proposals" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Apply explicit preparation plan" })).toBeDisabled();
  expect(prepare).toHaveBeenCalledTimes(1);
  expect(preview).toHaveBeenCalledTimes(1);
  fireEvent.click(next.getByRole("button", { name: "Analyze pKa proposals" }));
  await waitFor(() => expect(next.getByRole("button", { name: "Prepare this receptor" })).toBeEnabled());
  expect(preview).toHaveBeenLastCalledWith("source-1", expect.objectContaining({
    issue_decisions: [expect.objectContaining({ issue_id: "missing-1", action: "remove" })],
  }));
  expect(prepare).toHaveBeenCalledTimes(1);
});

it("offers opt-in clash relief and 3D inspection before removal, without rerunning tools", async () => {
  const prepare = vi.spyOn(ankoraApi, "prepareReceptor").mockRejectedValue(connectivityFailure());
  const { onSelect, relaxation } = await openWorkspace();
  fireEvent.click(screen.getByRole("button", { name: "Prepare this receptor" }));
  fireEvent.click(await screen.findByRole("button", { name: "Inspect ALA A:1 in 3D" }));
  expect(onSelect).toHaveBeenLastCalledWith({ kind: "residue", residue: { chainId: "A", residueName: "ALA", sequenceNumber: 1, insertionCode: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Enable clash relief for repaired atoms in the plan" }));
  expect(relaxation).toBeChecked();
  expect(screen.getByLabelText("Decision for ALA 1")).toHaveValue("repair");
  expect(prepare).toHaveBeenCalledTimes(1);
});

it("fills missing-atom and missing-residue decisions in groups without overwriting explicit removal", async () => {
  const prepare = vi.spyOn(ankoraApi, "prepareReceptor").mockRejectedValue(connectivityFailure());
  const varied = { ...report, issues: [report.issues[0],
    { ...report.issues[0], issue_id: "missing-2", residue: { ...residue, sequence_number: 2 } },
    { ...report.issues[0], issue_id: "absent-3", residue: { ...residue, sequence_number: 3 }, kind: "missing_residue" as const,
      missing_atoms: [], allowed_actions: ["leave", "remove", "manual_review"] as const },
  ] };
  // Copy the readonly literal to the API's mutable array contract.
  const inspection: ReceptorInspectionReport = { ...varied, issues: varied.issues.map((issue) => ({ ...issue, allowed_actions: [...issue.allowed_actions] })) };
  await openWorkspace(inspection);
  fireEvent.change(screen.getByLabelText("Decision for ALA 1"), { target: { value: "remove" } });
  fireEvent.click(screen.getByRole("button", { name: "Mark 1 missing-atom residue(s) for repair" }));
  fireEvent.click(screen.getByRole("button", { name: "Leave 1 missing residue(s) unmodelled" }));
  expect(screen.getByLabelText("Decision for ALA 1")).toHaveValue("remove");
  expect(screen.getByLabelText("Decision for ALA 2")).toHaveValue("repair");
  expect(screen.getByLabelText("Decision for ALA 3")).toHaveValue("leave");
  expect(screen.getByRole("button", { name: "Prepare this receptor" })).toBeEnabled();
  expect(prepare).not.toHaveBeenCalled();
});

it("filters attention proposals without losing hidden scientist overrides in the final request", async () => {
  vi.spyOn(ankoraApi, "previewReceptorProtonation").mockResolvedValue(analysis);
  const prepare = vi.spyOn(ankoraApi, "prepareReceptor").mockRejectedValue(connectivityFailure());
  await openWorkspace();
  fireEvent.click(screen.getByRole("checkbox", { name: /Run PDB2PQR/ }));
  fireEvent.click(screen.getByRole("button", { name: "Analyze pKa proposals" }));
  await screen.findByText("2 pKa proposals");
  fireEvent.change(screen.getByLabelText("Protonation decision for Synthetic LYS A:6"), { target: { value: "LYN" } });
  fireEvent.click(screen.getByRole("button", { name: "Needs attention (1)" }));
  expect(screen.queryByLabelText("Protonation decision for Synthetic LYS A:6")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Protonation decision for Synthetic HIS A:5")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Prepare this receptor" }));
  await waitFor(() => expect(prepare).toHaveBeenCalledWith("source-1", expect.objectContaining({
    protonation: expect.objectContaining({ overrides: [{ residue: analysis.proposals[1].residue, state: "LYN" }] }),
  })));
});
