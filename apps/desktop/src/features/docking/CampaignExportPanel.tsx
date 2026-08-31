import { useState } from "react";

import { ankoraApi } from "../../api/client";
import {
  chooseFolder,
  folderChooserAvailable,
  rememberFolder,
  rememberedFolder,
} from "../results/chooseFolder";
import type { CampaignExport } from "../../types/api";

/**
 * Export a finished campaign as a bundle someone else could act on.
 *
 * Not a download button over a table. The bundle carries the receptor, the
 * search space, the map set identity, the executable's hash and the complete
 * protocol beside the numbers, because a column of energies with no statement
 * of where they came from is exactly what Ankora exists not to produce.
 *
 * The bundle is written into the project rather than streamed away, so an
 * export is itself something that happened and can be found again.
 */

interface CampaignExportPanelProps {
  sourceKind: "vina_batch" | "autodock4_batch" | "autodock_gpu_batch";
  sourceId: string | null;
  /** Only a finished campaign is worth exporting. */
  ready: boolean;
  /** So a catalog watching this panel can pick the new bundle up. */
  onExported?: () => void;
}

export function CampaignExportPanel({
  sourceKind,
  sourceId,
  ready,
  onExported,
}: CampaignExportPanelProps) {
  const [bundle, setBundle] = useState<CampaignExport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [destination, setDestination] = useState<string | null>(() => rememberedFolder());
  const canBrowse = folderChooserAvailable();

  async function browse() {
    setError(null);
    try {
      const picked = await chooseFolder("Where should the campaign bundle be saved?");
      if (picked === null) return;
      setDestination(picked);
      rememberFolder(picked);
      setBundle(null);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "The folder could not be chosen.");
    }
  }

  async function exportCampaign() {
    if (!sourceId) return;
    setBusy(true);
    setError(null);
    try {
      setBundle(await ankoraApi.exportCampaign(sourceKind, sourceId, destination));
      onExported?.();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "The export failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="receptor-section" aria-label="Campaign export">
      <div className="filter-heading"><span>Export</span></div>
      <p className="field-note">
        Writes a folder holding the results table, a manifest of the receptor,
        search space, map set, executable hash and full protocol, and a note
        stating what the numbers are. Existing pose analyses and saved figures
        travel with it in a portable ZIP. Nothing is recomputed.
      </p>
      {error ? <p className="protonation-blocker" role="alert">{error}</p> : null}
      <div className="figure-export-destination">
        <span className="section-label">Save into</span>
        <span className="figure-export-folder" title={destination ?? undefined}>
          {destination ?? "The Ankora project"}
        </span>
        <button
          type="button"
          disabled={!canBrowse || busy}
          title={canBrowse ? undefined : "Choosing a folder needs the Ankora desktop app."}
          onClick={() => void browse()}
        >
          Choose folder…
        </button>
        {destination ? (
          <button
            type="button"
            onClick={() => { setDestination(null); rememberFolder(null); setBundle(null); }}
          >
            Use the project
          </button>
        ) : null}
      </div>
      <button
        type="button"
        className="apply-plan"
        disabled={!ready || !sourceId || busy}
        onClick={() => void exportCampaign()}
      >
        {busy ? "Writing the bundle…" : "Export this campaign"}
      </button>
      {!ready ? (
        <p className="field-note">A campaign has to finish before it can be exported.</p>
      ) : null}
      {bundle ? (
        <div className="state-resolved-note">
          <strong>{bundle.row_count} molecules exported</strong>
          <small>
            {bundle.engine} {bundle.engine_version}
            {bundle.bitwise_reproducible
              ? " · repeating this campaign reproduces these numbers"
              : " · repeating this campaign will NOT reproduce these numbers"}
          </small>
          <small>
            {bundle.interaction_analysis_count} pose analyses · {bundle.figure_count} saved figures
          </small>
          <div className="export-files">
            {bundle.files.map((filename) => (
              <a
                key={filename}
                href={ankoraApi.exportFileUrl(bundle.export_id, filename)}
                download={filename}
              >
                {filename}
              </a>
            ))}
          </div>
          <small className="export-location">{bundle.directory}</small>
          {bundle.outside_project ? (
            <small className="export-location">
              A copy stays in the project · {bundle.record_directory}
            </small>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
