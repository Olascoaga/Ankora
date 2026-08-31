import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import responsiveStyles from "../styles.css?raw";
import { FigureExportControls } from "../features/results/FigureExportControls";
import { interactionFamily } from "../features/results/InteractionDiagram";
import { figureGeometry, inlineSvg } from "../features/results/figureRendering";
import * as chooseFolder from "../features/results/chooseFolder";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const savedFigure = {
  figure_id: "figure-1",
  exported_at: "2026-08-27T10:00:00Z",
  source: "interaction_diagram" as const,
  catalog_id: "vina_job:job-1",
  ligand_id: "ligand-1",
  molecule_name: "RV2",
  pose_artifact_id: "pose-1",
  pose_label: "Mode 1",
  analysis_id: "analysis-1",
  directory: "project-data/figures/figure-1",
  files: [
    {
      filename: "interaction_diagram.svg",
      format: "svg" as const,
      size_bytes: 4096,
      vector: true,
      width_px: null,
      height_px: null,
      dpi: null,
    },
  ],
};

function controls(overrides: Record<string, unknown> = {}) {
  return (
    <FigureExportControls
      source="interaction_diagram"
      aspectRatio={640 / 390}
      renderSvg={() => "<svg><line/></svg>"}
      catalogId="vina_job:job-1"
      ligandId="ligand-1"
      moleculeName="RV2"
      poseArtifactId="pose-1"
      poseLabel="Mode 1"
      analysisId="analysis-1"
      {...overrides}
    />
  );
}

// --- what a journal actually asks for ---------------------------------------

it("sizes a figure from a column width and a resolution", () => {
  // "2×" is not an answer to "300 dpi at 85 mm", which is what a submission
  // checklist states.
  expect(figureGeometry(640 / 390, 85, 300)).toEqual({ widthPx: 1004, heightPx: 612 });
  expect(figureGeometry(640 / 390, 180, 600)).toEqual({ widthPx: 4252, heightPx: 2591 });
});

it("never lets a figure exceed what a browser can rasterize", () => {
  expect(figureGeometry(1, 1000, 1200).widthPx).toBe(8000);
});

it("returns the stacked M9 review to document flow before figure controls can overlap", () => {
  const narrowReview = responsiveStyles.slice(
    responsiveStyles.indexOf("@media (max-width: 1450px)"),
  );

  expect(narrowReview).toMatch(
    /\.results-interaction-workspace \.pose-interaction-panel\s*\{[^}]*flex:\s*0 0 auto;[^}]*min-height:\s*auto;/,
  );
  expect(narrowReview).toMatch(
    /\.pose-interaction-review-grid\s*\{[^}]*flex:\s*0 0 auto;[^}]*grid-template-columns:\s*1fr;[^}]*min-height:\s*0;/,
  );
  expect(narrowReview).toMatch(
    /\.pose-interaction-evidence\s*\{[^}]*min-height:\s*auto;[^}]*overflow-y:\s*visible;/,
  );
  expect(narrowReview).toMatch(
    /\.workspace\.results-interaction-workspace\s*\{[^}]*overflow-y:\s*auto;/,
  );
});

it("keeps the wide 3D figure controls reachable in their own scroll column", () => {
  const wideReview = responsiveStyles.slice(
    responsiveStyles.indexOf(".pose-interaction-review-grid"),
    responsiveStyles.indexOf("@media (max-width: 1450px)"),
  );
  const narrowReview = responsiveStyles.slice(
    responsiveStyles.indexOf("@media (max-width: 1450px)"),
  );

  expect(wideReview).toMatch(
    /\.pose-interaction-viewer-column\s*\{[^}]*overflow-y:\s*auto;[^}]*scrollbar-gutter:\s*stable;/,
  );
  expect(narrowReview).toMatch(
    /\.pose-interaction-viewer-column\s*\{[^}]*overflow-y:\s*visible;[^}]*scrollbar-gutter:\s*auto;/,
  );
});

it("uses one workspace scrollbar on wide screens with limited height", () => {
  const shortWideStart = responsiveStyles.indexOf(
    "@media (min-width: 1451px) and (max-height: 1100px)",
  );
  const shortWideReview = responsiveStyles.slice(
    shortWideStart,
    responsiveStyles.indexOf("@media (max-width: 1450px)", shortWideStart),
  );

  expect(shortWideReview).toMatch(
    /\.results-interaction-workspace \.pose-interaction-panel\s*\{[^}]*flex:\s*0 0 auto;[^}]*min-height:\s*auto;/,
  );
  expect(shortWideReview).toMatch(
    /\.pose-interaction-review-grid\s*\{[^}]*flex:\s*0 0 auto;[^}]*align-items:\s*start;[^}]*min-height:\s*0;/,
  );
  expect(shortWideReview).toMatch(
    /\.pose-interaction-viewer-column\s*\{[^}]*overflow-y:\s*visible;[^}]*scrollbar-gutter:\s*auto;/,
  );
  expect(shortWideReview).toMatch(
    /\.pose-interaction-evidence\s*\{[^}]*min-height:\s*auto;[^}]*overflow-y:\s*visible;/,
  );
  expect(shortWideReview).toMatch(
    /\.workspace\.results-interaction-workspace\s*\{[^}]*overflow-y:\s*auto;[^}]*scrollbar-gutter:\s*stable;/,
  );
  expect(shortWideReview).not.toContain("grid-template-columns: 1fr");
});

// --- the exported SVG has to look like the figure on screen ------------------

it("writes the drawing's own styles into the exported SVG", () => {
  // The diagram's colours live in a stylesheet, so serializing the node alone
  // would export a black-on-nothing skeleton of the approved figure.
  document.body.innerHTML = `
    <svg viewBox="0 0 640 390" class="diagram" role="img">
      <line x1="0" y1="0" x2="10" y2="10" class="interaction-edge" tabindex="0"/>
    </svg>`;
  const element = document.querySelector("svg") as SVGSVGElement;
  const line = element.querySelector("line") as SVGLineElement;
  line.style.stroke = "rgb(79, 163, 255)";
  line.style.strokeDasharray = "5px 5px";

  const exported = inlineSvg(element, { background: "#101418" });

  expect(exported).toContain('xmlns="http://www.w3.org/2000/svg"');
  expect(exported).toContain('width="640"');
  expect(exported).toContain("stroke:rgb(79, 163, 255)");
  expect(exported).toContain("stroke-dasharray:5px 5px");
  // A figure dropped on a dark slide must not lose its dark labels.
  expect(exported).toContain('fill="#101418"');
  // Interaction hooks are noise in a file nobody can click.
  expect(exported).not.toContain("interaction-edge");
  expect(exported).not.toContain("tabindex");
});

it("leaves the exported SVG transparent when no surface is given", () => {
  document.body.innerHTML = '<svg viewBox="0 0 10 10"><line/></svg>';
  const element = document.querySelector("svg") as SVGSVGElement;

  expect(inlineSvg(element, { background: null })).not.toContain("<rect");
});

// --- what can and cannot be vector ------------------------------------------

it("refuses to offer the 3D view as a vector figure, and says why", () => {
  render(controls({ source: "pose_view_3d", renderSvg: undefined, captureRaster: async () => "" }));

  const svg = screen.getByRole("checkbox", { name: /SVG/ });
  expect(svg).toBeDisabled();
  expect(screen.getByText("the 3D view is a render, not vector")).toBeInTheDocument();
});

it("offers the diagram as vector and preselects it", () => {
  render(controls());

  expect(screen.getByRole("checkbox", { name: /SVG/ })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: /SVG/ })).toBeEnabled();
});

// --- saving -----------------------------------------------------------------

it("sends exactly the formats and resolution that were chosen", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch")
    .mockImplementation(async () => json(savedFigure, 201));
  render(controls());

  fireEvent.click(screen.getByRole("checkbox", { name: /PNG/ }));
  fireEvent.change(screen.getByLabelText("Resolution"), { target: { value: "600" } });
  fireEvent.click(screen.getByRole("button", { name: "Save figure" }));

  await waitFor(() => expect(fetcher).toHaveBeenCalled());
  const call = fetcher.mock.calls.at(-1);
  const body = JSON.parse(String((call?.[1] as RequestInit).body));
  expect(body.formats).toEqual(["svg"]);
  expect(body.dpi).toBe(600);
  expect(body.svg).toBe("<svg><line/></svg>");
  // A figure with no traceable source is what Ankora exists not to produce.
  expect(body.analysis_id).toBe("analysis-1");
  expect(body.pose_label).toBe("Mode 1");
});

it("labels each saved file with what it actually is", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => json(savedFigure, 201));
  render(controls());

  // Rasterizing needs a canvas, which jsdom has none of; the raster path is
  // verified in the running app instead.
  fireEvent.click(screen.getByRole("checkbox", { name: /PNG/ }));
  fireEvent.click(screen.getByRole("button", { name: "Save figure" }));

  const link = await screen.findByRole("link", { name: /interaction_diagram\.svg/ });
  expect(link).toHaveTextContent("vector");
  // The manifest travels with the figure, not as an afterthought.
  expect(screen.getByRole("link", { name: /figure\.json/ })).toBeInTheDocument();
});

it("reports a refused export instead of appearing to have saved", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(
    async () => json({ code: "FIGURE_TOO_LARGE", message: "Too large." }, 422),
  );
  render(controls());

  fireEvent.click(screen.getByRole("checkbox", { name: /PNG/ }));
  fireEvent.click(screen.getByRole("button", { name: "Save figure" }));

  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(screen.queryByText("Saved")).not.toBeInTheDocument();
});

// --- one classification, two pictures ---------------------------------------

it("classifies a contact the same way for the diagram and the 3D view", () => {
  // A contact drawn amber in one picture and blue in the other would be two
  // different claims about one measurement.
  expect(interactionFamily("HBDonor")).toBe("hydrogen");
  expect(interactionFamily("HBAcceptor")).toBe("hydrogen");
  expect(interactionFamily("Hydrophobic")).toBe("hydrophobic");
  expect(interactionFamily("EdgeToFace")).toBe("aromatic");
  expect(interactionFamily("CationPi")).toBe("aromatic");
  expect(interactionFamily("Anionic")).toBe("ionic");
  expect(interactionFamily("XBDonor")).toBe("special");
  expect(interactionFamily("MetalAcceptor")).toBe("special");
});

// --- where the figure goes ---------------------------------------------------

it("saves into the project until a folder is chosen", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch")
    .mockImplementation(async () => json(savedFigure, 201));
  render(controls());

  expect(screen.getByText("The Ankora project")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: /PNG/ }));
  fireEvent.click(screen.getByRole("button", { name: "Save figure" }));

  await waitFor(() => expect(fetcher).toHaveBeenCalled());
  const body = JSON.parse(String((fetcher.mock.calls.at(-1)?.[1] as RequestInit).body));
  expect(body.destination).toBeNull();
});

it("sends the folder the scientist picked", async () => {
  vi.spyOn(chooseFolder, "folderChooserAvailable").mockReturnValue(true);
  vi.spyOn(chooseFolder, "chooseFolder").mockResolvedValue("selected-output/figures");
  const fetcher = vi.spyOn(globalThis, "fetch")
    .mockImplementation(async () => json(savedFigure, 201));
  render(controls());

  fireEvent.click(screen.getByRole("button", { name: "Choose folder…" }));
  await screen.findByText("selected-output/figures");

  fireEvent.click(screen.getByRole("checkbox", { name: /PNG/ }));
  fireEvent.click(screen.getByRole("button", { name: "Save figure" }));
  await waitFor(() => expect(fetcher).toHaveBeenCalled());

  const body = JSON.parse(String((fetcher.mock.calls.at(-1)?.[1] as RequestInit).body));
  expect(body.destination).toBe("selected-output/figures");
});

it("can be sent back to the project after choosing a folder", async () => {
  vi.spyOn(chooseFolder, "folderChooserAvailable").mockReturnValue(true);
  vi.spyOn(chooseFolder, "chooseFolder").mockResolvedValue("selected-output/elsewhere");
  render(controls());

  fireEvent.click(screen.getByRole("button", { name: "Choose folder…" }));
  await screen.findByText("selected-output/elsewhere");
  fireEvent.click(screen.getByRole("button", { name: "Use the project" }));

  expect(screen.getByText("The Ankora project")).toBeInTheDocument();
});

it("says why a folder cannot be chosen outside the desktop app", () => {
  vi.spyOn(chooseFolder, "folderChooserAvailable").mockReturnValue(false);
  render(controls());

  const button = screen.getByRole("button", { name: "Choose folder…" });
  expect(button).toBeDisabled();
  expect(button).toHaveAttribute("title", expect.stringContaining("desktop app"));
});

it("names a figure it cannot serve rather than linking to it", async () => {
  // Written into the scientist's own folder, the file is not the project's to
  // hand back, and a download link would 404.
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => json({
    ...savedFigure,
    outside_project: true,
    directory: "selected-output/figures",
    files: [{ ...savedFigure.files[0], filename: "RV2_Mode-1_interaction_diagram.svg" }],
  }, 201));
  render(controls());

  fireEvent.click(screen.getByRole("checkbox", { name: /PNG/ }));
  fireEvent.click(screen.getByRole("button", { name: "Save figure" }));

  await screen.findByText("RV2_Mode-1_interaction_diagram.svg");
  expect(
    screen.queryByRole("link", { name: /RV2_Mode-1_interaction_diagram\.svg/ }),
  ).not.toBeInTheDocument();
  // The record stays reachable, because the project still holds it.
  expect(screen.getByRole("link", { name: /figure\.json/ })).toBeInTheDocument();
  expect(screen.getByText(/Recorded in the project/)).toBeInTheDocument();
});
