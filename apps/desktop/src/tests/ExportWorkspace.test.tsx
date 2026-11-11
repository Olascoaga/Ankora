import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { ExportWorkspace } from "../features/export/ExportWorkspace";
import type { CatalogPage, ExportPage } from "../types/api";

/**
 * Workflow step 8.
 *
 * It read "Not implemented" in the sidebar while seven bundles, twenty-five
 * figures and two complexes accumulated on disk, because every export
 * recorded itself and nothing could list them.
 */

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const exports: ExportPage = {
  entries: [
    {
      export_id: "figure-outside",
      kind: "figure",
      exported_at: "2026-08-28T02:15:00Z",
      title: "RV2 · interaction diagram",
      subtitle: "RV2_Cluster-2-run-1_interaction_diagram.svg",
      catalog_id: "vina_job:job-1",
      source_kind: null,
      source_id: null,
      display_name: null,
      input_identity_sha256: null,
      bundle_identity_sha256: null,
      archive_filename: null,
      analysis_id: "analysis-1",
      ligand_id: "ligand-1",
      reproducibility: null,
      bitwise_reproducible: null,
      directory: "selected-output",
      outside_project: true,
      files: [
        { filename: "figure.json", size_bytes: 1024, content_url: null },
      ],
    },
    {
      export_id: "bundle-1",
      kind: "campaign",
      exported_at: "2026-08-28T05:12:00Z",
      title: "PIK3CD validation · repeat 2",
      subtitle: "25/25 molecules docked",
      catalog_id: "autodock_gpu_batch:batch-1",
      source_kind: "autodock_gpu_batch",
      source_id: "batch-1",
      display_name: "PIK3CD validation · repeat 2",
      input_identity_sha256: "a".repeat(64),
      bundle_identity_sha256: "e".repeat(64),
      archive_filename: "Ankora_PIK3CD-validation-repeat-2_bundle.zip",
      analysis_id: null,
      ligand_id: null,
      reproducibility: {
        status: "measured_variable",
        protocol: "ankora-reproducibility-v1",
        scope: "parsed scientific outputs and retained pose-artifact bytes",
        input_fingerprint_sha256: "a".repeat(64),
        executions: [
          { catalog_id: "autodock_gpu_batch:batch-1", output_fingerprint_sha256: "b".repeat(64) },
          { catalog_id: "autodock_gpu_batch:batch-2", output_fingerprint_sha256: "c".repeat(64) },
        ],
      },
      bitwise_reproducible: false,
      directory: "project-data/projects/default/exports/bundle-1",
      outside_project: false,
      files: [
        { filename: "results.csv", size_bytes: 4096, content_url: "/exports/bundle-1/results.csv" },
        {
          filename: "Ankora_PIK3CD-validation-repeat-2_bundle.zip",
          size_bytes: 131072,
          content_url: "/exports/bundle-1/Ankora_PIK3CD-validation-repeat-2_bundle.zip",
        },
      ],
    },
  ],
  total: 2,
  offset: 0,
  limit: 25,
};

const campaigns = {
  entries: [
    {
      catalog_id: "autodock_gpu_batch:batch-1",
      engine_key: "autodock_gpu_batch",
      record_id: "batch-1",
      mode: "screening",
      scoring_family: "autodock4",
      backend: "autodock_gpu",
      engine_label: "AutoDock4 · AutoDock-GPU 1.6",
      engine_version: "1.6",
      executable_sha256: null,
      device_name: null,
      reproducibility: {
        status: "measured_variable",
        protocol: "ankora-reproducibility-v1",
        scope: "parsed scientific outputs and retained pose-artifact bytes",
        input_fingerprint_sha256: "a".repeat(64),
        executions: [
          { catalog_id: "autodock_gpu_batch:batch-1", output_fingerprint_sha256: "b".repeat(64) },
          { catalog_id: "autodock_gpu_batch:batch-2", output_fingerprint_sha256: "c".repeat(64) },
        ],
      },
      status: "completed",
      created_at: "2026-08-26T15:47:00Z",
      completed_at: "2026-08-26T16:00:00Z",
      receptor_id: "receptor-1",
      binding_site_id: "site-1",
      box: {},
      map_set_id: null,
      map_set_identity_key: null,
      library_id: null,
      filter_run_id: null,
      selection_manifest_sha256: null,
      ligand_id: null,
      selected_count: 25,
      succeeded_count: 25,
      failed_count: 0,
      canceled_count: 0,
      best_result_kcal_mol: -5.75,
      best_molecule: "Compound 231",
    },
  ],
  total: 1,
  offset: 0,
  limit: 200,
} as unknown as CatalogPage;

function mock(page: ExportPage = exports) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("/results/campaigns")) return json(campaigns);
    return json(page);
  });
}

it("lists every kind of export this project has produced", async () => {
  mock();
  render(<ExportWorkspace />);

  const list = await screen.findByRole("list", { name: "Recorded exports" });
  const cards = within(list).getAllByRole("listitem");
  expect(cards).toHaveLength(2);
  expect(cards[0]).toHaveTextContent("RV2 · interaction diagram");
  expect(cards[0]).toHaveTextContent("Figure");
  expect(cards[1]).toHaveTextContent("PIK3CD validation · repeat 2");
  expect(cards[1]).toHaveTextContent("Campaign bundle");
  expect(cards[1]).toHaveTextContent("Campaign batch-1");
  expect(cards[1]).toHaveTextContent("Inputs aaaaaaaaaaaa…");
  expect(cards[1]).toHaveTextContent("Bundle eeeeeeeeeeee…");
});

it("offers the files the project holds and only names the rest", async () => {
  // A figure saved into a manuscript folder is not Ankora's to hand back, and
  // a download link that 404s is worse than no link.
  mock();
  render(<ExportWorkspace />);

  const list = await screen.findByRole("list", { name: "Recorded exports" });
  const [figure, bundle] = within(list).getAllByRole("listitem");

  expect(within(bundle).getByRole("link", { name: /results\.csv/ })).toHaveAttribute(
    "href", expect.stringContaining("/exports/bundle-1/results.csv"),
  );
  expect(within(bundle).getByRole("link", { name: /Ankora_PIK3CD.*bundle\.zip/ }))
    .toHaveTextContent("128 KiB");

  expect(within(figure).queryAllByRole("link")).toHaveLength(0);
  expect(figure).toHaveTextContent("Written into a folder you chose");
  expect(figure).toHaveTextContent("selected-output");
});

it("carries measured variability into the export record", async () => {
  mock();
  render(<ExportWorkspace />);

  const list = await screen.findByRole("list", { name: "Recorded exports" });
  const cards = within(list).getAllByRole("listitem");

  expect(cards[1]).toHaveTextContent("Exact recorded repeats produced different outputs");
  expect(cards[0]).not.toHaveTextContent("Repeat reproducibility");
});

it("narrows the catalog to one kind of export", async () => {
  const fetcher = mock();
  render(<ExportWorkspace />);

  await screen.findByRole("list", { name: "Recorded exports" });
  fireEvent.click(screen.getByRole("button", { name: "Figures" }));

  await waitFor(() =>
    expect(fetcher.mock.calls.some(([url]) => String(url).includes("kind=figure"))).toBe(true));
});

it("offers only completed campaigns to bundle", async () => {
  mock();
  render(<ExportWorkspace />);

  const chooser = await screen.findByLabelText("Completed campaign");
  expect(within(chooser).getByRole("option", { name: /AutoDock-GPU 1\.6/ }))
    .toBeInTheDocument();
  // The export panel appears only once a campaign is actually chosen.
  expect(screen.queryByRole("region", { name: "Campaign export" })).not.toBeInTheDocument();

  fireEvent.change(chooser, { target: { value: "autodock_gpu_batch:batch-1" } });
  expect(await screen.findByRole("region", { name: "Campaign export" })).toBeInTheDocument();
});

it("says so plainly when nothing has been exported", async () => {
  mock({ entries: [], total: 0, offset: 0, limit: 25 });
  render(<ExportWorkspace />);

  expect(await screen.findByText("Nothing has been exported yet")).toBeInTheDocument();
});

it("offers a completed individual GNINA result alongside screening batches, excludes incomplete jobs, and exports via source_kind=gnina_job", async () => {
  const catalogWithGnina = {
    entries: [
      ...campaigns.entries,
      {
        ...campaigns.entries[0],
        catalog_id: "gnina_job:gnina-1",
        engine_key: "gnina_job",
        record_id: "gnina-1",
        mode: "single_ligand",
        scoring_family: "gnina",
        backend: "cuda",
        engine_label: "GNINA 1.3.3",
        engine_version: "1.3.3",
        reproducibility: {
          status: "not_assessed",
          protocol: "ankora-reproducibility-v1",
          scope: "parsed scientific outputs and retained pose-artifact bytes",
          input_fingerprint_sha256: "3".repeat(64),
          executions: [],
        },
        status: "completed",
        selected_count: 1,
        succeeded_count: 1,
        failed_count: 0,
        best_result_kcal_mol: null,
        primary_cnn_score: 0.9123,
        cnn_affinity_pk: 7.45,
        minimized_affinity_kcal_mol: -8.12,
        best_molecule: "Synthetic GNINA ligand",
      },
      {
        ...campaigns.entries[0],
        catalog_id: "gnina_job:gnina-running",
        engine_key: "gnina_job",
        record_id: "gnina-running",
        mode: "single_ligand",
        scoring_family: "gnina",
        engine_label: "GNINA 1.3.3",
        status: "running",
        selected_count: 1,
        succeeded_count: 0,
        best_molecule: "Synthetic incomplete GNINA ligand",
      },
      {
        ...campaigns.entries[0],
        catalog_id: "vina_job:vina-single",
        engine_key: "vina_job",
        record_id: "vina-single",
        mode: "single_ligand",
        scoring_family: "vina",
        engine_label: "AutoDock Vina 1.2.7",
        status: "completed",
        selected_count: 1,
        succeeded_count: 1,
        best_molecule: "Synthetic Vina single ligand",
      },
    ],
    total: 4,
    offset: 0,
    limit: 200,
  } as unknown as CatalogPage;

  const gninaExports: ExportPage = {
    entries: [
      {
        export_id: "gnina-bundle-1",
        kind: "campaign",
        exported_at: "2026-11-04T19:00:00Z",
        title: "Synthetic GNINA 1.3.3 export",
        subtitle: "1/1 molecules docked",
        catalog_id: "gnina_job:gnina-1",
        source_kind: "gnina_job",
        source_id: "gnina-1",
        display_name: "Synthetic GNINA 1.3.3 export",
        input_identity_sha256: "1".repeat(64),
        bundle_identity_sha256: "2".repeat(64),
        archive_filename: "Ankora_Synthetic-GNINA_bundle.zip",
        analysis_id: null,
        ligand_id: "ligand-1",
        reproducibility: {
          status: "not_assessed",
          protocol: "ankora-reproducibility-v1",
          scope: "parsed scientific outputs and retained pose-artifact bytes",
          input_fingerprint_sha256: "3".repeat(64),
          executions: [],
        },
        bitwise_reproducible: null,
        directory: "synthetic/exports/gnina-bundle-1",
        outside_project: false,
        files: [
          { filename: "results.csv", size_bytes: 512, content_url: "/exports/gnina-bundle-1/results.csv" },
        ],
      },
    ],
    total: 1,
    offset: 0,
    limit: 25,
  };

  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.includes("/exports/campaigns") && init?.method === "POST") {
      return json({
        export_id: "gnina-bundle-1",
        exported_at: "2026-11-04T19:00:00Z",
        source_kind: "gnina_job",
        source_id: "gnina-1",
        catalog_id: "gnina_job:gnina-1",
        display_name: null,
        input_identity_sha256: "1".repeat(64),
        bundle_identity_sha256: "2".repeat(64),
        archive_filename: "Ankora_Synthetic-GNINA_bundle.zip",
        engine: "GNINA",
        engine_version: "1.3.3",
        reproducibility: {
          status: "not_assessed",
          protocol: "ankora-reproducibility-v1",
          scope: "parsed scientific outputs and retained pose-artifact bytes",
          input_fingerprint_sha256: "3".repeat(64),
          executions: [],
        },
        row_count: 2,
        interaction_analysis_count: 0,
        figure_count: 0,
        directory: "synthetic/exports/gnina-bundle-1",
        outside_project: false,
        record_directory: "synthetic/exports/gnina-bundle-1",
        files: ["README.txt", "manifest.json", "results.csv", "Ankora_Synthetic-GNINA_bundle.zip"],
      }, 201);
    }
    if (url.includes("/results/campaigns")) return json(catalogWithGnina);
    return json(gninaExports);
  });

  render(<ExportWorkspace />);

  const chooser = await screen.findByLabelText("Completed campaign");
  expect(within(chooser).getByRole("option", { name: /AutoDock-GPU 1\.6 · 25\/25/ })).toBeInTheDocument();
  expect(
    within(chooser).getByRole("option", {
      name: /GNINA 1\.3\.3 · Single ligand \(Synthetic GNINA ligand\) · 1\/1/,
    }),
  ).toBeInTheDocument();
  expect(within(chooser).queryByRole("option", { name: /Synthetic incomplete GNINA ligand/ })).not.toBeInTheDocument();
  expect(within(chooser).queryByRole("option", { name: /AutoDock Vina 1\.2\.7/ })).not.toBeInTheDocument();

  const recordedList = await screen.findByRole("list", { name: "Recorded exports" });
  const recordedCard = within(recordedList).getByRole("listitem");
  expect(recordedCard).toHaveTextContent("GNINA result bundle");
  expect(recordedCard).toHaveTextContent("GNINA job gnina-1");

  fireEvent.change(chooser, { target: { value: "gnina_job:gnina-1" } });

  const exportPanel = await screen.findByRole("region", { name: "Campaign export" });
  expect(exportPanel).toHaveTextContent(/individual single-ligand GNINA result/);
  expect(exportPanel).toHaveTextContent(/separate CNN score, CNN affinity \(pK\) and minimized affinity \(kcal\/mol\) metrics/);
  expect(exportPanel).toHaveTextContent(/SHA-256 hash-verified poses/);
  expect(exportPanel).toHaveTextContent(/never comparable across engines, and a single run or seed never claims repeat reproducibility/);

  fireEvent.click(within(exportPanel).getByRole("button", { name: "Export this GNINA result" }));

  expect(
    await within(exportPanel).findByText("2 poses exported · single-ligand GNINA result"),
  ).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledWith(
    expect.stringContaining("/exports/campaigns?source_kind=gnina_job&source_id=gnina-1"),
    expect.objectContaining({ method: "POST" }),
  );
});

it("offers a completed multi-ligand GNINA screening campaign and exports via source_kind=gnina_screening", async () => {
  const catalogWithGninaScreening = {
    entries: [
      {
        ...campaigns.entries[0],
        catalog_id: "gnina_screening:screen-1",
        engine_key: "gnina_screening",
        record_id: "screen-1",
        mode: "screening",
        scoring_family: "gnina",
        backend: "cuda",
        engine_label: "GNINA 1.3.3",
        engine_version: "1.3.3",
        reproducibility: {
          status: "not_assessed",
          protocol: "ankora-reproducibility-v1",
          scope: "parsed scientific outputs and retained pose-artifact bytes",
          input_fingerprint_sha256: "3".repeat(64),
          executions: [],
        },
        status: "completed",
        selected_count: 11,
        succeeded_count: 10,
        failed_count: 1,
        best_result_kcal_mol: null,
        primary_cnn_score: 0.939,
        cnn_affinity_pk: 6.17,
        minimized_affinity_kcal_mol: -2.68,
        best_molecule: "Synthetic NCI-68",
      },
    ],
    total: 1,
    offset: 0,
    limit: 200,
  } as unknown as CatalogPage;

  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.includes("/exports/campaigns") && init?.method === "POST") {
      return json({
        export_id: "gnina-screen-bundle-1",
        exported_at: "2026-11-11T19:00:00Z",
        source_kind: "gnina_screening",
        source_id: "screen-1",
        catalog_id: "gnina_screening:screen-1",
        display_name: null,
        input_identity_sha256: "1".repeat(64),
        bundle_identity_sha256: "2".repeat(64),
        archive_filename: "Ankora_GNINA_gnina_screening_bundle.zip",
        engine: "GNINA",
        engine_version: "1.3.3",
        reproducibility: {
          status: "not_assessed",
          protocol: "ankora-reproducibility-v1",
          scope: "parsed scientific outputs and retained pose-artifact bytes",
          input_fingerprint_sha256: "3".repeat(64),
          executions: [],
        },
        row_count: 11,
        interaction_analysis_count: 1,
        figure_count: 0,
        directory: "synthetic/exports/gnina-screen-bundle-1",
        outside_project: false,
        record_directory: "synthetic/exports/gnina-screen-bundle-1",
        files: ["README.txt", "manifest.json", "methods.md", "results.csv", "Ankora_GNINA_gnina_screening_bundle.zip"],
      }, 201);
    }
    if (url.includes("/results/campaigns")) return json(catalogWithGninaScreening);
    return json({ entries: [], total: 0, offset: 0, limit: 25 });
  });

  render(<ExportWorkspace />);

  const chooser = await screen.findByLabelText("Completed campaign");
  expect(
    within(chooser).getByRole("option", { name: /GNINA 1\.3\.3 · 10\/11/ }),
  ).toBeInTheDocument();

  fireEvent.change(chooser, { target: { value: "gnina_screening:screen-1" } });

  const exportPanel = await screen.findByRole("region", { name: "Campaign export" });
  expect(exportPanel).toHaveTextContent(/multi-ligand GNINA screening campaign/);
  expect(exportPanel).toHaveTextContent(/descending top-pose CNN score with selection-order tie-breaking/);
  expect(exportPanel).toHaveTextContent(/The preserved command and logs may contain local file paths/);

  fireEvent.click(within(exportPanel).getByRole("button", { name: "Export this campaign" }));

  expect(
    await within(exportPanel).findByText("11 molecules exported"),
  ).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledWith(
    expect.stringContaining("/exports/campaigns?source_kind=gnina_screening&source_id=screen-1"),
    expect.objectContaining({ method: "POST" }),
  );
});
