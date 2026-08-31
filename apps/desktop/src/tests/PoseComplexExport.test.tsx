import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PoseComplexExportControls } from "../features/results/PoseComplexExportControls";
import * as chooseFolder from "../features/results/chooseFolder";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const saved = {
  export_id: "export-1",
  exported_at: "2026-08-28T10:00:00Z",
  catalog_id: "vina_job:job-1",
  ligand_id: "ligand-1",
  molecule_name: "RV2",
  pose_artifact_id: "pose-1",
  pose_label: "Mode 1",
  directory: "selected-output/work",
  outside_project: true,
  record_directory: "project-data/exports/pose_complexes/export-1",
  file: {
    filename: "RV2_complex_Mode_1.pdb",
    sha256: "a".repeat(64),
    size_bytes: 2048,
  },
};

function controls() {
  return (
    <PoseComplexExportControls
      catalogId="vina_job:job-1"
      ligandId="ligand-1"
      moleculeName="RV2"
      poseArtifactId="pose-1"
    />
  );
}

describe("explicit ligand-receptor PDB export", () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it("asks the backend to write the PDB instead of starting a browser download", async () => {
    window.localStorage.setItem("ankora.exports.destination", "selected-output/work");
    const fetcher = vi.spyOn(globalThis, "fetch")
      .mockImplementation(async () => json(saved, 201));

    render(controls());
    fireEvent.click(screen.getByRole("button", { name: "Save PDB" }));

    await waitFor(() => expect(fetcher).toHaveBeenCalled());
    const [url, options] = fetcher.mock.calls.at(-1) ?? [];
    expect(String(url)).toContain(
      "/results/campaigns/vina_job/job-1/compounds/ligand-1/poses/pose-1/complex/export",
    );
    expect((options as RequestInit).method).toBe("POST");
    expect(JSON.parse(String((options as RequestInit).body))).toEqual({
      molecule_name: "RV2",
      destination: "selected-output/work",
    });
    expect(await screen.findByText("Saved PDB")).toBeInTheDocument();
    expect(screen.getByText("RV2_complex_Mode_1.pdb")).toBeInTheDocument();
    expect(screen.getAllByText("selected-output/work")).toHaveLength(2);
  });

  it("can choose a working folder and remembers it for other exports", async () => {
    vi.spyOn(chooseFolder, "folderChooserAvailable").mockReturnValue(true);
    vi.spyOn(chooseFolder, "chooseFolder").mockResolvedValue("selected-output/session-7");
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => json({
      ...saved,
      directory: "selected-output/session-7",
    }, 201));

    render(controls());
    fireEvent.click(screen.getByRole("button", { name: "Choose folder…" }));

    expect(await screen.findByText("selected-output/session-7")).toBeInTheDocument();
    expect(window.localStorage.getItem("ankora.exports.destination"))
      .toBe("selected-output/session-7");
  });

  it("shows a refused write rather than pretending the PDB was saved", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => json({
      code: "POSE_COMPLEX_WRITE_FAILED",
      message: "The selected folder is not writable.",
    }, 422));

    render(controls());
    fireEvent.click(screen.getByRole("button", { name: "Save PDB" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("not writable");
    expect(screen.queryByText("Saved PDB")).not.toBeInTheDocument();
  });

  it("migrates the previously chosen figure folder into the shared working folder", () => {
    window.localStorage.setItem("ankora.figures.destination", "selected-output/legacy-figures");

    render(controls());

    expect(screen.getByText("selected-output/legacy-figures")).toBeInTheDocument();
    expect(window.localStorage.getItem("ankora.exports.destination"))
      .toBe("selected-output/legacy-figures");
    expect(window.localStorage.getItem("ankora.figures.destination")).toBeNull();
  });
});
