import { fireEvent, render, screen, within } from "@testing-library/react";

import { App } from "../app/App";

it("opens Validation after restart without any current structure, receptor or box", async () => {
  const tools = Object.fromEntries(["vina", "gnina", "autogrid4", "autodock4", "autodock_gpu",
    "pdbfixer", "pdb2pqr", "propka", "meeko", "meeko_ligand", "p2rank"].map(
    (name) => [name, { available: false, path: null, version: null }],
  ));
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = new URL(String(input)).pathname;
    const body = path.endsWith("/health") ? { status: "ok", backend_version: "0.1.0" }
      : path.endsWith("/system") ? { platform: "windows", architecture: "x86_64", python_version: "test", python_environment: "synthetic", app_mode: "development" }
      : path.endsWith("/system/resources") ? { logical_cores: 1, memory_total_bytes: 1, memory_used_bytes: 0, cpu_percent: 0, gpu: null }
      : path.endsWith("/projects") ? { active_project_id: "default", projects: [{ project_id: "default", name: "Synthetic", registered_at: "", migrated_legacy: true }] }
      : path.endsWith("/work/recovery") ? { items: [] }
      : path.endsWith("/validation/redocking") ? []
      : path.endsWith("/results/campaigns") ? { entries: [], total: 0, offset: 0, limit: 25 }
      : tools;
    return new Response(JSON.stringify(body), { status: path.endsWith("/receptors/latest") ? 404 : 200,
      headers: { "Content-Type": "application/json" } });
  });
  render(<App />);
  const navigation = await screen.findByRole("navigation", { name: "Docking workflow" });
  const validation = within(navigation).getByRole("button", { name: /Validation/ });
  expect(validation).toBeEnabled();
  fireEvent.click(validation);
  expect(await screen.findByRole("region", { name: "Redocking validation workspace" })).toBeInTheDocument();
  expect(await screen.findByText("No redocking validation recorded yet")).toBeInTheDocument();
});
