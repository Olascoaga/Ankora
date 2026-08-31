import { useState } from "react";

import { ankoraApi } from "../../api/client";
import type { PoseComplexExport } from "../../types/api";
import {
  chooseFolder,
  folderChooserAvailable,
  rememberFolder,
  rememberedFolder,
} from "./chooseFolder";

interface PoseComplexExportControlsProps {
  catalogId: string;
  ligandId: string;
  moleculeName: string;
  poseArtifactId: string;
}

/** Save a traceable coordinate file through the backend, never via WebView download. */
export function PoseComplexExportControls({
  catalogId,
  ligandId,
  moleculeName,
  poseArtifactId,
}: PoseComplexExportControlsProps) {
  const [destination, setDestination] = useState<string | null>(() => rememberedFolder());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exported, setExported] = useState<PoseComplexExport | null>(null);
  const canBrowse = folderChooserAvailable();

  async function browse() {
    setError(null);
    try {
      const picked = await chooseFolder("Where should the ligand-receptor PDB be saved?");
      if (picked === null) return;
      setDestination(picked);
      rememberFolder(picked);
      setExported(null);
    } catch (reason: unknown) {
      setError(message(reason, "The folder could not be chosen."));
    }
  }

  function useProjectFolder() {
    setDestination(null);
    rememberFolder(null);
    setExported(null);
  }

  async function save() {
    setBusy(true);
    setError(null);
    setExported(null);
    try {
      setExported(await ankoraApi.exportPoseComplex(
        catalogId,
        ligandId,
        poseArtifactId,
        { molecule_name: moleculeName, destination },
      ));
    } catch (reason: unknown) {
      setError(message(reason, "The ligand-receptor PDB could not be saved."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="pose-complex-export" aria-label="Save ligand-receptor complex as PDB">
      <div className="pose-complex-export-heading">
        <div>
          <strong>Ligand–receptor complex (PDB)</strong>
          <small>
            The exact prepared receptor and this pose in one file for PyMOL,
            Chimera or another viewer. Coordinates are copied unchanged.
          </small>
        </div>
        <button
          type="button"
          className="primary-button"
          disabled={busy}
          onClick={() => void save()}
        >
          {busy ? "Saving PDB…" : "Save PDB"}
        </button>
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
      {error ? <p className="protonation-blocker" role="alert">{error}</p> : null}
      {exported ? (
        <div className="figure-export-result" role="status">
          <strong>Saved PDB</strong>
          <span className="pose-complex-file">{exported.file.filename}</span>
          <small className="export-location">{exported.directory}</small>
          <small className="export-location">
            SHA-256 · {exported.file.sha256.slice(0, 16)}… · {formatBytes(exported.file.size_bytes)}
          </small>
          {exported.outside_project ? (
            <small className="export-location">
              Recorded in the project · {exported.record_directory}
            </small>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  return `${(size / 1024).toFixed(1)} KB`;
}

function message(reason: unknown, fallback: string): string {
  return reason instanceof Error && reason.message ? reason.message : fallback;
}
