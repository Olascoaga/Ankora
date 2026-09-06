import type { ComponentProps } from "react";

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { ProjectWorkspace } from "../features/project/ProjectWorkspace";
import type { ProjectCatalog, ProjectDependencyGraph } from "../types/api";

const catalog: ProjectCatalog = {
  active_project_id: "default",
  projects: [
    { project_id: "default", name: "Default project", registered_at: "2026-09-06T10:00:00Z", migrated_legacy: true },
    { project_id: "kinase", name: "Kinase screen", registered_at: "2026-09-06T11:00:00Z", migrated_legacy: false },
  ],
};

const graph: ProjectDependencyGraph = {
  project_id: "default",
  generated_at: "2026-09-06T12:00:00Z",
  nodes: [
    {
      node_id: "structure-1",
      kind: "structure",
      label: "7AQF",
      relative_path: "original/structures/structure-1/record.json",
      parent_ids: [],
      unresolved_parent_ids: [],
      stale: false,
      stale_reasons: [],
    },
    {
      node_id: "receptor-1",
      kind: "receptor",
      label: "Prepared receptor",
      relative_path: "derived/receptors/receptor-1/record.json",
      parent_ids: ["structure-1"],
      unresolved_parent_ids: [],
      stale: true,
      stale_reasons: ["A newer receptor decision was applied."],
    },
  ],
  edges: [{ parent_id: "structure-1", child_id: "receptor-1" }],
  total_nodes: 102,
  offset: 0,
  limit: 100,
  stale_count: 1,
  unresolved_reference_count: 0,
};

function renderWorkspace(overrides: Partial<ComponentProps<typeof ProjectWorkspace>> = {}) {
  const props: ComponentProps<typeof ProjectWorkspace> = {
    catalog,
    graph,
    busy: false,
    error: null,
    onClose: vi.fn(),
    onCreate: vi.fn().mockResolvedValue(undefined),
    onActivate: vi.fn().mockResolvedValue(undefined),
    onMarkStale: vi.fn().mockResolvedValue(undefined),
    onLoadMore: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
  render(<ProjectWorkspace {...props} />);
  return props;
}

it("switches and creates projects only through explicit actions", async () => {
  const props = renderWorkspace();

  const kinase = screen.getByText("Kinase screen").closest("li");
  fireEvent.click(within(kinase!).getByRole("button", { name: "Switch" }));
  expect(props.onActivate).toHaveBeenCalledWith(catalog.projects[1]);

  fireEvent.change(screen.getByLabelText("New project"), { target: { value: "  New campaign  " } });
  fireEvent.click(screen.getByRole("button", { name: "Create & open" }));
  await waitFor(() => expect(props.onCreate).toHaveBeenCalledWith("New campaign"));
});

it("requires a scientific reason before propagating stale state", async () => {
  const props = renderWorkspace();

  const source = screen.getByText("7AQF").closest("tr");
  fireEvent.click(within(source!).getByRole("button", { name: "Mark stale…" }));
  const confirm = screen.getByRole("button", { name: "Confirm stale state" });
  expect(confirm).toBeDisabled();

  fireEvent.change(screen.getByLabelText("Reason for stale state"), {
    target: { value: "Coordinates were superseded after inspection." },
  });
  fireEvent.click(confirm);

  await waitFor(() => expect(props.onMarkStale).toHaveBeenCalledWith(
    graph.nodes[0],
    "Coordinates were superseded after inspection.",
  ));
});

it("keeps stale evidence visible and exposes the bounded graph continuation", () => {
  const props = renderWorkspace();

  expect(screen.getByText("A newer receptor decision was applied.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Load more records" }));
  expect(props.onLoadMore).toHaveBeenCalledTimes(1);
});
