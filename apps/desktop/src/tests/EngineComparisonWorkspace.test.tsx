import { fireEvent, render, screen, within } from "@testing-library/react";

import { EngineComparisonWorkspace } from "../features/docking/EngineComparisonWorkspace";
import type { EngineComparison } from "../types/api";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const comparison: EngineComparison = {
  generated_at: "2026-08-24T00:00:00Z",
  receptor_id: "receptor-1",
  binding_site_id: "site-1",
  library_id: "library-1",
  filter_run_id: "filter-1",
  selection_manifest_sha256: "c".repeat(64),
  vina_batch_id: "vina-batch-1",
  vina_version: "1.2.7",
  autodock4_batch_id: "ad4-batch-1",
  autodock4_version: "4.2.6",
  selected_count: 4,
  docked_by_both_count: 3,
  vina_only_count: 1,
  autodock4_only_count: 0,
  docked_by_neither_count: 0,
  agreement: {
    comparable_count: 3,
    spearman_rho: 0.5,
    top_n: 2,
    top_n_overlap: 1,
    top_n_shared_ligand_ids: ["ligand-1"],
  },
  rows: [
    {
      ligand_id: "ligand-0", source_index: 0, name: "Compound A", canonical_smiles: "CC",
      vina_best_score_kcal_mol: -8.2, vina_rank: 2,
      autodock4_best_energy_kcal_mol: -5.1, autodock4_rank: 3,
      autodock4_top_cluster_run_count: 6, rank_difference: 1, docked_by_both: true,
    },
    {
      ligand_id: "ligand-1", source_index: 1, name: "Compound B", canonical_smiles: "CCO",
      vina_best_score_kcal_mol: -9.4, vina_rank: 1,
      autodock4_best_energy_kcal_mol: -6.3, autodock4_rank: 1,
      autodock4_top_cluster_run_count: 9, rank_difference: 0, docked_by_both: true,
    },
    {
      ligand_id: "ligand-2", source_index: 2, name: "Compound C", canonical_smiles: "CCN",
      vina_best_score_kcal_mol: -7.1, vina_rank: 3,
      autodock4_best_energy_kcal_mol: -5.8, autodock4_rank: 2,
      autodock4_top_cluster_run_count: 4, rank_difference: 1, docked_by_both: true,
    },
    {
      ligand_id: "ligand-3", source_index: 3, name: "Compound D", canonical_smiles: null,
      vina_best_score_kcal_mol: -6.0, vina_rank: 4,
      autodock4_best_energy_kcal_mol: null, autodock4_rank: null,
      autodock4_top_cluster_run_count: null, rank_difference: null, docked_by_both: false,
    },
  ],
};

function mock(body: unknown = comparison, status = 200) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async () => json(body, status));
}

it("asks for an applied selection before it can compare anything", () => {
  mock();
  render(<EngineComparisonWorkspace receptorId="receptor-1" bindingSiteId="site-1" filterRunId={null} />);

  expect(screen.getByText("Apply a ligand selection first")).toBeInTheDocument();
  expect(
    screen.getByText(/same receptor, search space, and applied selection/),
  ).toBeInTheDocument();
});

it("shows each engine's own score and rank without ever combining them", async () => {
  mock();
  render(<EngineComparisonWorkspace receptorId="receptor-1" bindingSiteId="site-1" filterRunId="filter-1" />);

  const results = await screen.findByRole("region", { name: "Engine comparison results" });
  const header = within(results).getAllByRole("columnheader").map((h) => h.textContent);
  expect(header.some((h) => h?.includes("Vina score"))).toBe(true);
  expect(header.some((h) => h?.includes("AutoDock4 energy"))).toBe(true);
  // Nothing merges the two: no combined, consensus or averaged column exists.
  expect(header.some((h) => /combined|consensus|average/i.test(h ?? ""))).toBe(false);

  const rows = within(results).getAllByRole("row").slice(1);
  const top = within(rows[0]).getAllByRole("cell").map((c) => c.textContent);
  expect(top[2]).toBe("1");      // Vina rank
  expect(top[3]).toBe("-9.40");  // Vina's own score
  expect(top[4]).toBe("1");      // AutoDock4 rank
  expect(top[5]).toBe("-6.30");  // AutoDock4's own energy
});

it("explains why no consensus score exists", async () => {
  mock();
  render(<EngineComparisonWorkspace receptorId="receptor-1" bindingSiteId="site-1" filterRunId="filter-1" />);

  await screen.findByRole("region", { name: "Engine comparison results" });
  expect(
    screen.getByText(/averaging or\s+summing them would invent an agreement/),
  ).toBeInTheDocument();
});

it("reports rank agreement as agreement, not as a score", async () => {
  mock();
  render(<EngineComparisonWorkspace receptorId="receptor-1" bindingSiteId="site-1" filterRunId="filter-1" />);

  expect(await screen.findByText("Spearman ρ = 0.500")).toBeInTheDocument();
  expect(screen.getByText(/it is not a score for any molecule/)).toBeInTheDocument();
  expect(screen.getByText("1 of the top 2 shared")).toBeInTheDocument();
});

it("states plainly when too few molecules are shared to correlate", async () => {
  mock({
    ...comparison,
    agreement: { ...comparison.agreement, comparable_count: 2, spearman_rho: null },
  });
  render(<EngineComparisonWorkspace receptorId="receptor-1" bindingSiteId="site-1" filterRunId="filter-1" />);

  expect(await screen.findByText("Not enough shared molecules")).toBeInTheDocument();
  expect(screen.getByText(/At least three molecules/)).toBeInTheDocument();
});

it("keeps a molecule only one engine docked visible, ranked against nothing", async () => {
  mock();
  render(<EngineComparisonWorkspace receptorId="receptor-1" bindingSiteId="site-1" filterRunId="filter-1" />);

  const results = await screen.findByRole("region", { name: "Engine comparison results" });
  const row = within(results).getAllByRole("row").find((r) => r.textContent?.includes("Compound D"));
  expect(row).toBeDefined();
  const cells = within(row as HTMLElement).getAllByRole("cell").map((c) => c.textContent);
  expect(cells[4]).toBe("—");  // no AutoDock4 rank
  expect(cells[7]).toBe("—");  // and therefore no rank difference
});

it("sorts by either engine's rank independently", async () => {
  mock();
  render(<EngineComparisonWorkspace receptorId="receptor-1" bindingSiteId="site-1" filterRunId="filter-1" />);

  const results = await screen.findByRole("region", { name: "Engine comparison results" });
  const names = () => within(results).getAllByRole("row").slice(1)
    .map((r) => within(r).getAllByRole("cell")[1].textContent);

  expect(names()[0]).toContain("Compound B");
  fireEvent.click(within(results).getByRole("button", { name: /AutoDock4 rank/ }));
  expect(names()[0]).toContain("Compound B");
  fireEvent.click(within(results).getByRole("button", { name: /AutoDock4 rank/ }));
  // Descending by AutoDock4 rank puts its worst first, and the molecule it
  // never docked stays last rather than sorting to the top.
  expect(names()[0]).toContain("Compound A");
  expect(names()[names().length - 1]).toContain("Compound D");
});

it("surfaces a refusal to compare campaigns over different inputs", async () => {
  mock(
    {
      code: "ENGINE_COMPARISON_INPUTS_DIFFER",
      stage: "engine_comparison",
      message: "These two campaigns did not dock the same selection into the same search space, so their rankings are not comparable.",
      details: {},
      recoverable: false,
    },
    422,
  );
  render(<EngineComparisonWorkspace receptorId="receptor-1" bindingSiteId="site-1" filterRunId="filter-1" />);

  expect(await screen.findByRole("alert")).toHaveTextContent(
    /did not dock the same selection/,
  );
});

it("resolves the campaigns from persisted history, not from this session", async () => {
  const fetchSpy = mock();
  render(
    <EngineComparisonWorkspace receptorId="receptor-1" bindingSiteId="site-1" filterRunId="filter-1" />,
  );

  await screen.findByRole("region", { name: "Engine comparison results" });
  // Nothing was run in this session; the comparison is resolved from disk by
  // receptor, binding site, and applied selection.
  const url = String(fetchSpy.mock.calls[0][0]);
  expect(url).toContain("/docking/comparison/latest");
  expect(url).toContain("receptor_id=receptor-1");
  expect(url).toContain("binding_site_id=site-1");
  expect(url).toContain("filter_run_id=filter-1");
});

it("names which engine still needs a campaign", async () => {
  mock(
    {
      code: "ENGINE_COMPARISON_CAMPAIGN_MISSING",
      stage: "engine_comparison",
      message: "No completed AutoDock4 campaign exists for this receptor and binding site. Run it before comparing the two engines.",
      details: { missing_engine: "AutoDock4" },
      recoverable: false,
    },
    404,
  );
  render(
    <EngineComparisonWorkspace receptorId="receptor-1" bindingSiteId="site-1" filterRunId="filter-1" />,
  );

  expect(await screen.findByRole("alert")).toHaveTextContent(
    /No completed AutoDock4 campaign exists/,
  );
});
