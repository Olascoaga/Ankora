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
  const localTimestamp = new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).format(new Date("2026-08-27T12:00:00Z"));
  expect(screen.getByText(localTimestamp)).toBeInTheDocument();
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

it("exports a completed individual GNINA job with single-result labels, separate CNN metrics and hash-verified evidence", async () => {
  const fetcher = vi.fn().mockResolvedValue(json({
    export_id: "00000000-0000-0000-0000-000000000202",
    exported_at: "2026-11-04T18:00:00Z",
    source_kind: "gnina_job",
    source_id: "gnina-job-1",
    catalog_id: "gnina_job:gnina-job-1",
    display_name: null,
    input_identity_sha256: "1".repeat(64),
    bundle_identity_sha256: "2".repeat(64),
    archive_filename: "Ankora_GNINA-1.3.3_bundle.zip",
    engine: "GNINA",
    engine_version: "1.3.3",
    reproducibility: {
      status: "not_assessed",
      protocol: "ankora-reproducibility-v1",
      scope: "parsed scientific outputs and retained pose-artifact bytes",
      input_fingerprint_sha256: "3".repeat(64),
      executions: [],
    },
    row_count: 1,
    interaction_analysis_count: 1,
    figure_count: 1,
    directory: "synthetic/gnina-export",
    outside_project: false,
    record_directory: "synthetic/gnina-export",
    files: [
      "Ankora_GNINA-1.3.3_bundle.zip",
      "README.txt",
      "manifest.json",
      "methods.md",
      "results.csv",
    ],
  }));
  vi.stubGlobal("fetch", fetcher);

  render(<CampaignExportPanel sourceKind="gnina_job" sourceId="gnina-job-1" ready />);

  expect(
    screen.getByText(/individual single-ligand GNINA result — one docking job, not a multi-ligand screening campaign/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/separate CNN score, CNN affinity \(pK\) and minimized affinity \(kcal\/mol\) metrics/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/SHA-256 hash-verified poses and prepared receptor, conformer and ligand PDBQT inputs/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/never comparable across engines, and a single run or seed never claims repeat reproducibility/),
  ).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Export this GNINA result" }));

  expect(
    await screen.findByText("1 pose exported · single-ligand GNINA result"),
  ).toBeInTheDocument();
  expect(screen.getByText("GNINA result bundle written")).toBeInTheDocument();
  expect(
    screen.getByText("GNINA 1.3.3 · repeat reproducibility was not assessed"),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("Export identity")).toHaveTextContent("GNINA job gnina-job-1");
  expect(screen.getByText("111111111111…")).toBeInTheDocument();
  expect(screen.getByText("222222222222…")).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledWith(
    expect.stringContaining("/exports/campaigns?source_kind=gnina_job&source_id=gnina-job-1"),
    expect.objectContaining({ method: "POST" }),
  );

  vi.unstubAllGlobals();
});

it("keeps GNINA export disabled while the job is incomplete", () => {
  render(<CampaignExportPanel sourceKind="gnina_job" sourceId="gnina-job-1" ready={false} />);

  expect(screen.getByRole("button", { name: "Export this GNINA result" })).toBeDisabled();
  expect(
    screen.getByText("A GNINA job has to finish before it can be exported."),
  ).toBeInTheDocument();
});
