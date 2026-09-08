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
    catalog_id: "vina_batch:batch-1",
    display_name: "PIK3CD validation · repeat 2",
    input_identity_sha256: "c".repeat(64),
    bundle_identity_sha256: "d".repeat(64),
    archive_filename: "Ankora_PIK3CD-validation-repeat-2_bundle.zip",
    engine: "AutoDock Vina",
    engine_version: "1.2.7",
    reproducibility: {
      status: "measured_reproducible",
      protocol: "ankora-reproducibility-v1",
      scope: "parsed scientific outputs and retained pose-artifact bytes",
      input_fingerprint_sha256: "a".repeat(64),
      executions: [
        { catalog_id: "vina_batch:batch-1", output_fingerprint_sha256: "b".repeat(64) },
        { catalog_id: "vina_batch:batch-2", output_fingerprint_sha256: "b".repeat(64) },
      ],
    },
    row_count: 283,
    interaction_analysis_count: 2,
    figure_count: 3,
    directory: "synthetic/export",
    files: [
      "README.txt",
      "Ankora_PIK3CD-validation-repeat-2_bundle.zip",
      "manifest.json",
      "results.csv",
    ],
  })));

  render(<CampaignExportPanel sourceKind="vina_batch" sourceId="batch-1" ready />);
  fireEvent.change(screen.getByLabelText("Bundle name (optional)"), {
    target: { value: "PIK3CD validation · repeat 2" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Export this campaign" }));

  expect(await screen.findByText("283 molecules exported")).toBeInTheDocument();
  expect(screen.getByText("PIK3CD validation · repeat 2")).toBeInTheDocument();
  expect(screen.getByText("27 Aug 2026, 06:00:00")).toBeInTheDocument();
  expect(screen.getByText("cccccccccccc…")).toBeInTheDocument();
  expect(screen.getByText("dddddddddddd…")).toBeInTheDocument();
  expect(screen.getByText("2 pose analyses · 3 saved figures")).toBeInTheDocument();
  const archive = screen.getByRole("link", {
    name: "Ankora_PIK3CD-validation-repeat-2_bundle.zip",
  });
  expect(archive).toHaveAttribute(
    "href",
    expect.stringContaining(
      "/exports/00000000-0000-0000-0000-000000000201/Ankora_PIK3CD-validation-repeat-2_bundle.zip",
    ),
  );
  expect(fetch).toHaveBeenCalledWith(
    expect.stringContaining("display_name=PIK3CD+validation+%C2%B7+repeat+2"),
    expect.anything(),
  );

  vi.unstubAllGlobals();
});
