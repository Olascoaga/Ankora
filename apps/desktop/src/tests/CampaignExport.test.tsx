import { fireEvent, render, screen } from "@testing-library/react";

import { CampaignExportPanel } from "../features/docking/CampaignExportPanel";

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 201,
    headers: { "Content-Type": "application/json" },
  });
}

it("offers the portable campaign bundle and states its existing M9 evidence", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({
    export_id: "00000000-0000-0000-0000-000000000201",
    exported_at: "2026-08-27T12:00:00Z",
    source_kind: "vina_batch",
    source_id: "batch-1",
    engine: "AutoDock Vina",
    engine_version: "1.2.7",
    bitwise_reproducible: true,
    row_count: 283,
    interaction_analysis_count: 2,
    figure_count: 3,
    directory: "synthetic/export",
    files: ["README.txt", "campaign_bundle.zip", "manifest.json", "results.csv"],
  })));

  render(<CampaignExportPanel sourceKind="vina_batch" sourceId="batch-1" ready />);
  fireEvent.click(screen.getByRole("button", { name: "Export this campaign" }));

  expect(await screen.findByText("283 molecules exported")).toBeInTheDocument();
  expect(screen.getByText("2 pose analyses · 3 saved figures")).toBeInTheDocument();
  const archive = screen.getByRole("link", { name: "campaign_bundle.zip" });
  expect(archive).toHaveAttribute(
    "href",
    expect.stringContaining(
      "/exports/00000000-0000-0000-0000-000000000201/campaign_bundle.zip",
    ),
  );

  vi.unstubAllGlobals();
});
