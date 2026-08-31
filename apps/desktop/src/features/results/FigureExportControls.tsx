import { useState } from "react";

import { ankoraApi } from "../../api/client";
import type { FigureExport, FigureFormat, FigureSource } from "../../types/api";
import {
  chooseFolder,
  folderChooserAvailable,
  rememberFolder,
  rememberedFolder,
} from "./chooseFolder";
import { figureGeometry, rasterizeSvg } from "./figureRendering";

/**
 * Save one view as a figure, in the formats a journal asks for (M9).
 *
 * Size is chosen the way a submission checklist states it — a column width in
 * millimetres and a resolution in DPI — rather than as a multiplier, because
 * "2×" is not an answer to "300 dpi at 85 mm".
 *
 * What can be vector is said out loud rather than implied by an enabled
 * checkbox: the diagram is SVG and stays SVG, and the 3D view is a WebGL
 * render with no vector inside it to export.
 */

const FORMATS: { value: FigureFormat; label: string; note: string }[] = [
  { value: "svg", label: "SVG", note: "vector · the original" },
  { value: "png", label: "PNG", note: "raster" },
  { value: "tiff", label: "TIFF", note: "raster · LZW" },
  { value: "pdf", label: "PDF", note: "raster page" },
];

const WIDTHS = [
  { mm: 85, label: "Single column · 85 mm" },
  { mm: 180, label: "Double column · 180 mm" },
];

interface FigureExportControlsProps {
  source: FigureSource;
  /** The picture, produced on demand so nothing is rendered until asked. */
  renderSvg?: () => string;
  captureRaster?: (geometry: { widthPx: number; heightPx: number }) => Promise<string>;
  aspectRatio: number;
  catalogId: string;
  ligandId: string;
  moleculeName: string;
  poseArtifactId: string;
  poseLabel: string;
  analysisId: string | null;
}

export function FigureExportControls({
  source,
  renderSvg,
  captureRaster,
  aspectRatio,
  catalogId,
  ligandId,
  moleculeName,
  poseArtifactId,
  poseLabel,
  analysisId,
}: FigureExportControlsProps) {
  const vectorAvailable = source === "interaction_diagram" && Boolean(renderSvg);
  const [formats, setFormats] = useState<Set<FigureFormat>>(
    () => new Set<FigureFormat>(vectorAvailable ? ["svg", "png"] : ["png"]),
  );
  const [widthMm, setWidthMm] = useState(85);
  const [dpi, setDpi] = useState(300);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [figure, setFigure] = useState<FigureExport | null>(null);
  const [destination, setDestination] = useState<string | null>(() => rememberedFolder());
  const canBrowse = folderChooserAvailable();

  const geometry = figureGeometry(aspectRatio, widthMm, dpi);
  const needsRaster = [...formats].some((format) => format !== "svg");

  function toggle(format: FigureFormat) {
    setFormats((current) => {
      const next = new Set(current);
      if (next.has(format)) next.delete(format);
      else next.add(format);
      return next;
    });
  }

  async function browse() {
    setError(null);
    try {
      const picked = await chooseFolder("Where should the figure be saved?");
      if (picked === null) return;
      setDestination(picked);
      rememberFolder(picked);
      setFigure(null);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "The folder could not be chosen.");
    }
  }

  function useProjectFolder() {
    setDestination(null);
    rememberFolder(null);
    setFigure(null);
  }

  async function save() {
    if (formats.size === 0) return;
    setBusy(true);
    setError(null);
    setFigure(null);
    try {
      const svg = vectorAvailable ? renderSvg?.() ?? null : null;
      let png: string | null = null;
      if (needsRaster) {
        png = svg
          ? await rasterizeSvg(svg, geometry)
          : (await captureRaster?.(geometry)) ?? null;
        if (!png) throw new Error("This view could not be rendered for export.");
      }
      setFigure(await ankoraApi.exportFigure({
        source,
        formats: [...formats],
        svg,
        png_base64: png,
        dpi,
        catalog_id: catalogId,
        ligand_id: ligandId,
        molecule_name: moleculeName,
        pose_artifact_id: poseArtifactId,
        pose_label: poseLabel,
        analysis_id: analysisId,
        destination,
      }));
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "The figure could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="figure-export" aria-label={`Save ${label(source)} as a figure`}>
      <div className="figure-export-formats" role="group" aria-label="Figure formats">
        {FORMATS.map((format) => {
          const unavailable = format.value === "svg" && !vectorAvailable;
          return (
            <label key={format.value} className={unavailable ? "unavailable" : ""}>
              <input
                type="checkbox"
                checked={formats.has(format.value)}
                disabled={unavailable}
                onChange={() => toggle(format.value)}
              />
              <span>{format.label}</span>
              <small>
                {unavailable ? "the 3D view is a render, not vector" : format.note}
              </small>
            </label>
          );
        })}
      </div>
      <div className="figure-export-destination">
        <span className="section-label">Save into</span>
        <span className="figure-export-folder" title={destination ?? undefined}>
          {destination ?? "The Ankora project"}
        </span>
        <button
          type="button"
          disabled={!canBrowse}
          title={canBrowse ? undefined : "Choosing a folder needs the Ankora desktop app."}
          onClick={() => void browse()}
        >
          Choose folder…
        </button>
        {destination ? (
          <button type="button" onClick={useProjectFolder}>Use the project</button>
        ) : null}
      </div>
      <div className="figure-export-size">
        <label>
          Width
          <select value={widthMm} onChange={(event) => setWidthMm(Number(event.target.value))}>
            {WIDTHS.map((width) => (
              <option key={width.mm} value={width.mm}>{width.label}</option>
            ))}
          </select>
        </label>
        <label>
          Resolution
          <select value={dpi} onChange={(event) => setDpi(Number(event.target.value))}>
            <option value={300}>300 dpi</option>
            <option value={600}>600 dpi</option>
          </select>
        </label>
        <span className="figure-export-geometry">
          {geometry.widthPx} × {geometry.heightPx} px
        </span>
        <button
          type="button"
          className="primary-button"
          disabled={busy || formats.size === 0}
          onClick={() => void save()}
        >
          {busy ? "Saving…" : "Save figure"}
        </button>
      </div>
      {error ? <p className="protonation-blocker" role="alert">{error}</p> : null}
      {figure ? (
        <div className="figure-export-result">
          <strong>Saved</strong>
          <div className="export-files">
            {figure.files.map((file) => {
              const detail = file.vector
                ? "vector"
                : `${file.width_px}×${file.height_px} · ${file.dpi} dpi`;
              // Files written into a folder of the scientist's own are not the
              // project's to serve, so they are named rather than linked.
              return figure.outside_project ? (
                <span key={file.filename}>{file.filename}<small>{detail}</small></span>
              ) : (
                <a
                  key={file.filename}
                  href={ankoraApi.figureFileUrl(figure.figure_id, file.filename)}
                  download={file.filename}
                >
                  {file.filename}<small>{detail}</small>
                </a>
              );
            })}
            <a
              href={ankoraApi.figureFileUrl(figure.figure_id, "figure.json")}
              download="figure.json"
            >
              figure.json<small>which analysis this came from</small>
            </a>
          </div>
          <small className="export-location">{figure.directory}</small>
          {figure.outside_project ? (
            <small className="export-location">
              Recorded in the project · {figure.record_directory}
            </small>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function label(source: FigureSource): string {
  return source === "interaction_diagram" ? "the interaction diagram" : "the 3D view";
}
