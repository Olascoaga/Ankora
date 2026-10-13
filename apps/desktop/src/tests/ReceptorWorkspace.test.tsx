import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ankoraApi, ApiError } from "../api/client";
import { ReceptorWorkspace } from "../features/receptor/ReceptorWorkspace";
import type { ReceptorInspectionReport, StructureRecord } from "../types/api";

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

async function openWorkspace(inspection: ReceptorInspectionReport = report) {
  vi.spyOn(ankoraApi, "inspectReceptor").mockResolvedValue(inspection);
  const onSelect = vi.fn();
  render(<ReceptorWorkspace structure={structure} initialRecord={null} tools={null} selection={null} onSelect={onSelect} onRecordChange={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Chain A" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  fireEvent.change(screen.getByLabelText("Decision for ALA 1"), { target: { value: "repair" } });
  return { onSelect, relaxation: screen.getByRole("checkbox", { name: /Relax repaired residues with OpenMM/ }) };
}

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
  await waitFor(() => expect(ankoraApi.inspectReceptor).toHaveBeenLastCalledWith("source-1", "reference-1"));
  expect(screen.getByText(/This failure belongs to a previous plan/)).toBeInTheDocument();
  expect(screen.getByText("Synthetic previous failure")).toBeInTheDocument();
  expect(screen.getByText("Technical evidence")).toBeInTheDocument();
  expect(prepare).toHaveBeenCalledTimes(1);
});
