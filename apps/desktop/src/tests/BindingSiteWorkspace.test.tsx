import { useState } from "react";

import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { BindingSiteWorkspace } from "../features/binding-site/BindingSiteWorkspace";
import type {
  BindingBox,
  BindingSiteRecord,
  BindingSiteSource,
  ReceptorPreparationRecord,
  StructureRecord,
  ToolsResponse,
} from "../types/api";

function json(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function BindingSiteWorkspaceHarness(
  props: Omit<Parameters<typeof BindingSiteWorkspace>[0], "record" | "onRecordChange" | "onContinue"> & {
    initialRecord?: BindingSiteRecord;
    onContinue?: (record: BindingSiteRecord) => void;
  },
) {
  const { initialRecord = null, onContinue = () => undefined, ...workspaceProps } = props;
  const [record, setRecord] = useState<BindingSiteRecord | null>(initialRecord);
  return <BindingSiteWorkspace {...workspaceProps} record={record} onRecordChange={setRecord} onContinue={onContinue} />;
}

// All molecular metadata and boxes in this file are explicitly synthetic UI fixtures.
const structure = {
  artifact: { artifact_id: "source-1", original_filename: "source.pdb", format: "pdb", sha256: "a".repeat(64), size_bytes: 100, source: "local", source_uri: null, imported_at: "2026-08-21T00:00:00Z" },
  metadata: {
    entry_id: "SYN", title: "Synthetic test structure", experimental_method: "SYNTHETIC", resolution_angstrom: null,
    model_count: 1, atom_count: 10, residue_count: 3, chains: [],
    heterogens: [{ name: "LIG", chain_id: "A", sequence_number: 101, insertion_code: "", atom_count: 2, kind: "ligand" as const }],
    alternate_location_atom_count: 0, missing_residue_count: 0, missing_atom_count: 0, nonstandard_polymer_residues: [],
  },
  warnings: [],
  provenance: { event_id: "source-1", event_type: "structure_imported", timestamp: "2026-08-21T00:00:00Z", input_artifacts: [], output_artifacts: ["source-1"], tool: { name: "synthetic", version: "1" }, parameters: {}, warnings: [], command: null },
  content_url: "/structures/source-1/content",
} satisfies StructureRecord;

const receptor = {
  receptor_id: "receptor-1", source_artifact_id: "source-1", created_at: "2026-08-21T00:00:00Z", status: "docking_ready" as const,
  decisions: {
    selected_chains: ["A"], water_action: "remove" as const, component_decisions: [], issue_decisions: [], reference_component_id: null,
    relaxation: { enabled: false, restraint_force_constant_kcal_mol_a2: 50, max_iterations: 200 },
    protonation: { enabled: true, ph: 7.4, force_field: "AMBER" }, generate_pdbqt: true,
  },
  outputs: [{ artifact_id: "output-1", stage: "protonated_pdb" as const, filename: "protonated_receptor.pdb", format: "pdb", sha256: "b".repeat(64), size_bytes: 200, created_at: "2026-08-21T00:00:00Z", content_url: "/receptors/receptor-1/outputs/output-1/content" }],
  warnings: [], provenance: [], display_output_artifact_id: "output-1",
} satisfies ReceptorPreparationRecord;

const tools = {
  vina: { available: false, path: null, version: null }, gnina: { available: false, path: null, version: null },
  autogrid4: { available: false, path: null, version: null }, autodock4: { available: false, path: null, version: null },
  autodock_gpu: { available: false, path: null, version: null },
  pdbfixer: { available: false, path: null, version: null }, pdb2pqr: { available: false, path: null, version: null },
  propka: { available: false, path: null, version: null }, meeko: { available: false, path: null, version: null },
  meeko_ligand: { available: false, path: null, version: null }, p2rank: { available: true, path: "tools/p2rank/prank.bat", version: "2.5.1" },
} satisfies ToolsResponse;

const blindBox: BindingBox = { center_x: 20, center_y: 10, center_z: 5, size_x: 45, size_y: 60, size_z: 38 };
const ligandBox: BindingBox = { center_x: 15.5, center_y: 15, center_z: 10, size_x: 11, size_y: 10, size_z: 10 };

function preview(source: BindingSiteSource, box: BindingBox) {
  return { receptor_id: receptor.receptor_id, source, box, warnings: [] };
}

function bindingSiteRecord(overrides: Partial<BindingSiteRecord> = {}): BindingSiteRecord {
  return {
    binding_site_id: "binding-site-1", receptor_id: receptor.receptor_id, source_artifact_id: structure.artifact.artifact_id,
    created_at: "2026-08-21T00:00:00Z",
    decisions: {
      source: "co_crystallized_ligand",
      ligand_origin: { heterogen: { chain_id: "A", residue_name: "LIG", sequence_number: 101, insertion_code: "" }, padding_angstrom: 5 },
      residue_selection: null, manual_box: null, blind_margin_angstrom: 6, pocket_selection: null, parent_binding_site_id: null,
    },
    box: ligandBox, stale: false, warnings: [], provenance: [], ...overrides,
  };
}

it("opens on a non-persistent full-protein box and finalizes it before continuing to Docking", async () => {
  const requests: Array<{ path: string; body: Record<string, unknown> }> = [];
  const continued = vi.fn();
  const finalRecord = bindingSiteRecord({
    decisions: {
      ...bindingSiteRecord().decisions,
      source: "full_protein_blind",
      ligand_origin: null,
      acknowledge_exploratory_full_protein: true,
    },
    box: blindBox,
  });
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    requests.push({ path, body });
    if (path.endsWith("/binding-site-preview")) return json(preview("full_protein_blind", blindBox), 200);
    if (path.endsWith("/binding-sites")) return json(finalRecord, 201);
    return json(null, 404);
  });

  render(<BindingSiteWorkspaceHarness structure={structure} receptor={receptor} tools={tools} onContinue={continued} />);
  expect(screen.getByRole("button", { name: "Full protein (blind)" })).toHaveClass("selected");
  await waitFor(() => expect(screen.getByLabelText("Box size X in angstroms")).toHaveValue(45));
  expect(requests).toHaveLength(1);
  expect(requests[0].body).toMatchObject({ source: "full_protein_blind", blind_margin_angstrom: 6 });

  expect(screen.getByText("Vina large search-space warning")).toBeInTheDocument();
  const finalize = screen.getByRole("button", { name: "Define this binding site and continue to Docking" });
  expect(finalize).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox", { name: /Acknowledge exploratory full-protein search/i }));
  expect(finalize).toBeEnabled();
  fireEvent.click(finalize);
  await waitFor(() => expect(continued).toHaveBeenCalledWith(finalRecord));
  expect(requests).toHaveLength(2);
  expect(requests[1].body).toMatchObject({
    source: "full_protein_blind",
    acknowledge_exploratory_full_protein: true,
  });
});

it("previews a co-crystallized ligand without writing, then finalizes its exact locator", async () => {
  const createdBodies: Array<Record<string, unknown>> = [];
  const continued = vi.fn();
  const created = bindingSiteRecord();
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    if (path.endsWith("/binding-site-preview")) return json(body.source === "co_crystallized_ligand" ? preview("co_crystallized_ligand", ligandBox) : preview("full_protein_blind", blindBox), 200);
    if (path.endsWith("/binding-sites")) { createdBodies.push(body); return json(created, 201); }
    return json(null, 404);
  });

  render(<BindingSiteWorkspaceHarness structure={structure} receptor={receptor} tools={tools} onContinue={continued} />);
  await screen.findByDisplayValue(45);
  fireEvent.click(screen.getByRole("button", { name: "Co-crystallized ligand" }));
  fireEvent.click(screen.getByRole("button", { name: "Preview box from this ligand" }));
  await waitFor(() => expect(screen.getByLabelText("Box size X in angstroms")).toHaveValue(11));
  expect(createdBodies).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Define this binding site and continue to Docking" }));
  await waitFor(() => expect(continued).toHaveBeenCalledWith(created));
  expect(createdBodies[0]).toMatchObject({
    source: "co_crystallized_ligand",
    ligand_origin: { heterogen: { chain_id: "A", residue_name: "LIG", sequence_number: 101, insertion_code: "" }, padding_angstrom: 5 },
  });
});

it("writes a source suggestion followed by a manual derivative when the preview was adjusted", async () => {
  const createdBodies: Array<Record<string, unknown>> = [];
  const continued = vi.fn();
  const suggested = bindingSiteRecord();
  const adjustedBox = { ...ligandBox, size_x: 16 };
  const adjusted = bindingSiteRecord({
    binding_site_id: "binding-site-adjusted",
    decisions: { ...suggested.decisions, source: "manual", ligand_origin: null, manual_box: adjustedBox, parent_binding_site_id: suggested.binding_site_id },
    box: adjustedBox,
  });
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    if (path.endsWith("/binding-site-preview")) return json(body.source === "co_crystallized_ligand" ? preview("co_crystallized_ligand", ligandBox) : preview("full_protein_blind", blindBox), 200);
    if (path.endsWith("/binding-sites")) { createdBodies.push(body); return json(body.source === "manual" ? adjusted : suggested, 201); }
    return json(null, 404);
  });

  render(<BindingSiteWorkspaceHarness structure={structure} receptor={receptor} tools={tools} onContinue={continued} />);
  await screen.findByDisplayValue(45);
  fireEvent.click(screen.getByRole("button", { name: "Co-crystallized ligand" }));
  fireEvent.click(screen.getByRole("button", { name: "Preview box from this ligand" }));
  await waitFor(() => expect(screen.getByLabelText("Box size X in angstroms")).toHaveValue(11));
  fireEvent.change(screen.getByLabelText("Box size X in angstroms"), { target: { value: "16" } });
  fireEvent.click(screen.getByRole("button", { name: "Define this binding site and continue to Docking" }));
  await waitFor(() => expect(continued).toHaveBeenCalledWith(adjusted));
  expect(createdBodies).toHaveLength(2);
  expect(createdBodies[0]).toMatchObject({ source: "co_crystallized_ligand" });
  expect(createdBodies[1]).toMatchObject({ source: "manual", manual_box: adjustedBox, parent_binding_site_id: suggested.binding_site_id });
});

it("finalizes manual coordinates directly", async () => {
  const bodies: Array<Record<string, unknown>> = [];
  const continued = vi.fn();
  const manualBox = { center_x: 5, center_y: 10, center_z: 5, size_x: 45, size_y: 60, size_z: 38 };
  const created = bindingSiteRecord({
    binding_site_id: "binding-site-manual",
    decisions: { ...bindingSiteRecord().decisions, source: "manual", ligand_origin: null, manual_box: manualBox }, box: manualBox,
  });
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    if (path.endsWith("/binding-site-preview")) return json(preview("full_protein_blind", blindBox), 200);
    if (path.endsWith("/binding-sites")) { bodies.push(body); return json(created, 201); }
    return json(null, 404);
  });

  render(<BindingSiteWorkspaceHarness structure={structure} receptor={receptor} tools={tools} onContinue={continued} />);
  await screen.findByDisplayValue(45);
  fireEvent.click(screen.getByRole("button", { name: "Manual coordinates" }));
  fireEvent.change(screen.getByLabelText("Box center X in angstroms"), { target: { value: "5" } });
  fireEvent.click(screen.getByRole("button", { name: "Define this binding site and continue to Docking" }));
  await waitFor(() => expect(continued).toHaveBeenCalledWith(created));
  expect(bodies[0]).toMatchObject({ source: "manual", manual_box: manualBox, parent_binding_site_id: null });
});

it("previews exact selected residues and finalizes their source request", async () => {
  const selected = [
    { chain_id: "A", residue_name: "TYR", sequence_number: 60, insertion_code: "" },
    { chain_id: "A", residue_name: "ARG", sequence_number: 271, insertion_code: "" },
  ];
  const residueBox = { center_x: 20, center_y: 10, center_z: 5, size_x: 18, size_y: 16, size_z: 14 };
  const initialRecord = bindingSiteRecord({
    binding_site_id: "binding-site-residues",
    decisions: { ...bindingSiteRecord().decisions, source: "selected_residues", ligand_origin: null, residue_selection: { residues: selected, padding_angstrom: 5 } },
    box: residueBox,
  });
  const createdBodies: Array<Record<string, unknown>> = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    if (path.endsWith("/binding-site-preview")) return json(preview("selected_residues", residueBox), 200);
    if (path.endsWith("/binding-sites")) { createdBodies.push(body); return json(initialRecord, 201); }
    return json(null, 404);
  });

  render(<BindingSiteWorkspaceHarness structure={structure} receptor={receptor} tools={tools} initialRecord={initialRecord} />);
  expect(screen.getByText("2 selected residues")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Padding around selected residues in angstroms"), { target: { value: "6" } });
  fireEvent.click(screen.getByRole("button", { name: "Preview box from selection" }));
  await waitFor(() => expect(screen.getByLabelText("Box size X in angstroms")).toHaveValue(18));
  fireEvent.click(screen.getByRole("button", { name: "Define this binding site and continue to Docking" }));
  await waitFor(() => expect(createdBodies).toHaveLength(1));
  expect(createdBodies[0]).toMatchObject({ source: "selected_residues", residue_selection: { residues: selected, padding_angstrom: 6 } });
});

it("detects pockets, previews a candidate, and finalizes only on the common decision", async () => {
  const createdBodies: Array<Record<string, unknown>> = [];
  const report = {
    report_id: "report-1", receptor_id: receptor.receptor_id, source_output_artifact_id: "output-1", generated_at: "2026-08-21T00:00:00Z",
    tool: { name: "P2Rank", version: "2.5.1" },
    candidates: [
      { pocket_id: "pocket1", rank: 1, druggability_score: 0.82, volume_angstrom3: null, box: { center_x: 10, center_y: 20, center_z: 30, size_x: 18, size_y: 16, size_z: 14 }, lining_residues: [] },
      { pocket_id: "pocket2", rank: 2, druggability_score: 0.15, volume_angstrom3: null, box: { center_x: 40, center_y: 20, center_z: 5, size_x: 12, size_y: 12, size_z: 12 }, lining_residues: [] },
    ],
    warnings: [], provenance: { event_id: "report-1", event_type: "pockets_detected", timestamp: "2026-08-21T00:00:00Z", input_artifacts: ["receptor-1"], output_artifacts: ["report-1"], tool: { name: "P2Rank", version: "2.5.1" }, parameters: {}, warnings: [], command: ["cmd"] },
  };
  const created = bindingSiteRecord({
    decisions: { ...bindingSiteRecord().decisions, source: "pocket_detected", ligand_origin: null, pocket_selection: { report_id: "report-1", pocket_id: "pocket2" } },
    box: report.candidates[1].box,
  });
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (path.endsWith("/binding-site-preview")) return json(preview("full_protein_blind", blindBox), 200);
    if (path.endsWith("/pocket-detection")) return json(report, 201);
    if (path.endsWith("/binding-sites")) { createdBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>); return json(created, 201); }
    return json(null, 404);
  });

  render(<BindingSiteWorkspaceHarness structure={structure} receptor={receptor} tools={tools} />);
  await screen.findByDisplayValue(45);
  fireEvent.click(screen.getByRole("button", { name: "Detected pocket" }));
  fireEvent.click(screen.getByRole("button", { name: "Detect pockets with P2Rank" }));
  expect(await screen.findByText(/82% druggability/)).toBeInTheDocument();
  fireEvent.click(screen.getByText("Pocket 2"));
  expect(screen.getByLabelText("Box center X in angstroms")).toHaveValue(40);
  expect(createdBodies).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Define this binding site and continue to Docking" }));
  await waitFor(() => expect(createdBodies).toHaveLength(1));
  expect(createdBodies[0]).toMatchObject({ source: "pocket_detected", pocket_selection: { report_id: "report-1", pocket_id: "pocket2" } });
});

it("keeps the editor visible and explains an unavailable P2Rank installation", async () => {
  const toolsWithoutP2Rank = { ...tools, p2rank: { available: false, path: null, version: null } };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => String(input).endsWith("/binding-site-preview") ? json(preview("full_protein_blind", blindBox), 200) : json(null, 404));
  render(<BindingSiteWorkspaceHarness structure={structure} receptor={receptor} tools={toolsWithoutP2Rank} />);
  await screen.findByDisplayValue(45);
  expect(screen.getByRole("button", { name: "Move" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: "Resize" }));
  expect(screen.getByText(/opposite face stays fixed/i)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Detected pocket" }));
  expect(screen.getByText("P2Rank is not configured on this Windows system.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Detect pockets with P2Rank" })).toBeDisabled();
});

it("shows a placeholder when the receptor has no PDB prepared output", async () => {
  const receptorWithoutPdb: ReceptorPreparationRecord = { ...receptor, outputs: [{ ...receptor.outputs[0], format: "pqr" }] };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => String(input).endsWith("/binding-site-preview") ? json(preview("full_protein_blind", blindBox), 200) : json(null, 404));
  render(<BindingSiteWorkspaceHarness structure={structure} receptor={receptorWithoutPdb} tools={tools} />);
  expect(screen.getByText("Prepared receptor unavailable")).toBeInTheDocument();
  await screen.findByDisplayValue(45);
});

it("shows druggability as magnitude, never as a verdict", async () => {
  // Deliberately not a traffic light. Red-green is the one pairing about eight
  // percent of men cannot separate, and this list is ordered by exactly the
  // value being encoded. A red band would also assert a judgement P2Rank's
  // probability does not make: it ranks candidates against each other, and the
  // best pocket on a hard target can score low and still be the right one.
  const report = {
    report_id: "report-1", receptor_id: receptor.receptor_id,
    source_output_artifact_id: "output-1", generated_at: "2026-08-21T00:00:00Z",
    tool: { name: "P2Rank", version: "2.5.1" },
    candidates: [
      { pocket_id: "p1", rank: 1, druggability_score: 0.77, volume_angstrom3: null, box: { center_x: 10, center_y: 20, center_z: 30, size_x: 18, size_y: 16, size_z: 14 }, lining_residues: [] },
      { pocket_id: "p2", rank: 2, druggability_score: 0.37, volume_angstrom3: null, box: { center_x: 11, center_y: 20, center_z: 30, size_x: 18, size_y: 16, size_z: 14 }, lining_residues: [] },
      { pocket_id: "p3", rank: 3, druggability_score: 0.12, volume_angstrom3: null, box: { center_x: 12, center_y: 20, center_z: 30, size_x: 18, size_y: 16, size_z: 14 }, lining_residues: [] },
      { pocket_id: "p4", rank: 4, druggability_score: 0.02, volume_angstrom3: null, box: { center_x: 13, center_y: 20, center_z: 30, size_x: 18, size_y: 16, size_z: 14 }, lining_residues: [] },
    ],
    warnings: [], provenance: { event_id: "report-1", event_type: "pockets_detected", timestamp: "2026-08-21T00:00:00Z", input_artifacts: ["receptor-1"], output_artifacts: ["report-1"], tool: { name: "P2Rank", version: "2.5.1" }, parameters: {}, warnings: [], command: ["cmd"] },
  };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = String(input);
    if (path.endsWith("/binding-site-preview")) return json(preview("full_protein_blind", blindBox), 200);
    if (path.endsWith("/pocket-detection")) return json(report, 201);
    return json(null, 404);
  });

  render(<BindingSiteWorkspaceHarness structure={structure} receptor={receptor} tools={tools} />);
  await screen.findByDisplayValue(45);
  fireEvent.click(screen.getByRole("button", { name: "Detected pocket" }));
  fireEvent.click(screen.getByRole("button", { name: "Detect pockets with P2Rank" }));
  await screen.findByText(/77% druggability/);

  const bars = [...document.querySelectorAll(".pocket-druggability")] as HTMLElement[];
  expect(bars).toHaveLength(4);

  // One hue, stepping with the value. Never a hue change, never red.
  expect(bars.map((bar) => bar.dataset.band)).toEqual([
    "high", "fair", "modest", "low",
  ]);
  // Length carries the magnitude, so the cliff between pockets is visible.
  const widths = bars.map((bar) => (bar.firstElementChild as HTMLElement).style.width);
  expect(widths).toEqual(["77%", "37%", "12%", "2%"]);
  // The number stays in text, so the value is never carried by colour alone,
  // and the bar itself is decorative to a screen reader.
  expect(screen.getByText(/^2% druggability/)).toBeInTheDocument();
  bars.forEach((bar) => expect(bar).toHaveAttribute("aria-hidden", "true"));
});
