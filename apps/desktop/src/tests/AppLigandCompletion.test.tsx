import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../app/App";

vi.mock("../features/receptor/ReceptorWorkspace", () => ({
  ReceptorWorkspace: ({ onRecordChange }: { onRecordChange: (record: unknown) => void }) => (
    <button type="button" onClick={() => onRecordChange({
      receptor_id: "synthetic-receptor",
      source_artifact_id: "synthetic-structure",
      status: "docking_ready",
      warnings: [],
      provenance: [],
      outputs: [],
    })}>Complete synthetic receptor</button>
  ),
}));

vi.mock("../features/ligand/LigandWorkspace", () => ({
  LigandWorkspace: ({
    onLibraryDockingInputChange,
    onLibraryStatusChange,
  }: {
    onLibraryDockingInputChange: (input: unknown) => void;
    onLibraryStatusChange: (status: unknown) => void;
  }) => (
    <>
      {/* The real workspace reports progress before it reports completion, so
          a batch is watched finishing rather than found finished. */}
      <button type="button" onClick={() => {
        onLibraryDockingInputChange({
          library_id: "synthetic-library",
          library_name: "synthetic.sdf",
          filter_run_id: "synthetic-filter",
          selection_manifest_sha256: "e".repeat(64),
          selected_count: 3,
          prepared_count: 0,
        });
        onLibraryStatusChange({ total: 3, terminal: 0, prepared: 0, notReady: 0 });
      }}>Start synthetic ligand batch</button>
      <button type="button" onClick={() => {
        onLibraryDockingInputChange({
          library_id: "synthetic-library",
          library_name: "synthetic.sdf",
          filter_run_id: "synthetic-filter",
          selection_manifest_sha256: "e".repeat(64),
          selected_count: 3,
          prepared_count: 2,
        });
        onLibraryStatusChange({ total: 3, terminal: 3, prepared: 2, notReady: 1 });
      }}>Finish synthetic ligand batch</button>
    </>
  ),
}));

vi.mock("../features/binding-site/BindingSiteWorkspace", () => ({
  BindingSiteWorkspace: () => <div>Binding site workspace reached</div>,
}));

const health = { status: "ok", backend_version: "0.1.0" };
const system = { platform: "windows", architecture: "x86_64", python_version: "3.12.13", python_environment: "ankora-dev", app_mode: "development" };
const resources = { cpu_percent: 8.2, logical_cores: 16, memory_used_bytes: 17030922240, memory_total_bytes: 34053414912, memory_percent: 50, gpu: null, gpu_unavailable_reason: "No NVIDIA driver tools are installed on this machine." };
const tools = {
  vina: { available: false, path: null, version: null },
  gnina: { available: false, path: null, version: null },
  pdbfixer: { available: false, path: null, version: null },
  pdb2pqr: { available: false, path: null, version: null },
  propka: { available: false, path: null, version: null },
  meeko: { available: false, path: null, version: null },
  meeko_ligand: { available: false, path: null, version: null },
  p2rank: { available: false, path: null, version: null },
};
const structure = {
  artifact: { artifact_id: "synthetic-structure", original_filename: "synthetic.pdb", format: "pdb", sha256: "a".repeat(64), size_bytes: 100, source: "local", source_uri: null, imported_at: "2026-08-24T00:00:00Z" },
  metadata: { entry_id: "SYN", title: "Synthetic workflow fixture", experimental_method: "SYNTHETIC TEST DATA", resolution_angstrom: null, model_count: 1, atom_count: 1, residue_count: 1, chains: [], heterogens: [], alternate_location_atom_count: 0, missing_residue_count: 0, missing_atom_count: 0, nonstandard_polymer_residues: [] },
  warnings: [],
  provenance: { event_id: "synthetic", event_type: "structure_imported", timestamp: "2026-08-24T00:00:00Z", input_artifacts: [], output_artifacts: ["synthetic-structure"], tool: { name: "synthetic", version: "1" }, parameters: {}, warnings: [], command: null },
  content_url: "/structures/synthetic-structure/content",
};

it("marks a terminal ligand batch complete and advances to Binding site without hiding retained failures", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/receptors/latest")) return new Response(null, { status: 404 });
    if (init?.method === "POST") return new Response(JSON.stringify(structure), { status: 201, headers: { "Content-Type": "application/json" } });
    const payload = url.endsWith("/health") ? health : url.endsWith("/system/resources") ? resources : url.endsWith("/system") ? system : tools;
    return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
  });

  render(<App />);
  const input = document.querySelector<HTMLInputElement>(".primary-action input");
  fireEvent.change(input!, { target: { files: [new File(["SYNTHETIC"], "synthetic.pdb")] } });

  const workflow = within(await screen.findByRole("navigation", { name: "Docking workflow" }));
  fireEvent.click(await workflow.findByRole("button", { name: /Receptor/ }));
  fireEvent.click(await screen.findByRole("button", { name: "Complete synthetic receptor" }));
  fireEvent.click(await workflow.findByRole("button", { name: /Ligand/ }));
  fireEvent.click(await screen.findByRole("button", { name: "Start synthetic ligand batch" }));
  fireEvent.click(await screen.findByRole("button", { name: "Finish synthetic ligand batch" }));

  expect(await screen.findByText("Binding site workspace reached")).toBeInTheDocument();
  const ligandStep = workflow.getByRole("button", { name: /Ligand/ });
  expect(ligandStep).toHaveTextContent("2/3 ready · 1 retained");
  expect(ligandStep.querySelector(".workflow-index svg")).not.toBeNull();

  fireEvent.click(ligandStep);
  await waitFor(() => expect(screen.getByRole("button", { name: "Finish synthetic ligand batch" })).toBeInTheDocument());
});

it("stays on Ligand when an already-finished library is reopened", async () => {
  // Reopening a library from the shelf reports a complete stage immediately.
  // Advancing then would move the scientist on for the act of looking at
  // something they had already done.
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/receptors/latest")) return new Response(null, { status: 404 });
    if (init?.method === "POST") return new Response(JSON.stringify(structure), { status: 201, headers: { "Content-Type": "application/json" } });
    const payload = url.endsWith("/health") ? health : url.endsWith("/system/resources") ? resources : url.endsWith("/system") ? system : tools;
    return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
  });

  render(<App />);
  const input = document.querySelector<HTMLInputElement>(".primary-action input");
  fireEvent.change(input!, { target: { files: [new File(["SYNTHETIC"], "synthetic.pdb")] } });

  const workflow = within(await screen.findByRole("navigation", { name: "Docking workflow" }));
  fireEvent.click(await workflow.findByRole("button", { name: /Receptor/ }));
  fireEvent.click(await screen.findByRole("button", { name: "Complete synthetic receptor" }));
  fireEvent.click(await workflow.findByRole("button", { name: /Ligand/ }));

  // Straight to complete, with no batch watched running: a reopened library.
  fireEvent.click(await screen.findByRole("button", { name: "Finish synthetic ligand batch" }));

  expect(screen.queryByText("Binding site workspace reached")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Finish synthetic ligand batch" })).toBeInTheDocument();
});
