import { useEffect, useMemo, useState } from "react";

import { ankoraApi } from "../../api/client";
import { CampaignExportPanel } from "../docking/CampaignExportPanel";
import { MethodsPanel } from "./MethodsPanel";
import type { CatalogEntry, ExportEntry, ExportKind } from "../../types/api";
import { formatApplicationDate, formatApplicationDateTime } from "../../utils/format";
import { reproducibilityTitle } from "../results/reproducibility";

/**
 * Everything this project has sent out of Ankora (workflow step 8).
 *
 * Each export already wrote a manifest saying what it was and where it came
 * from — that was the point of writing it into the project rather than
 * streaming it away — but nothing could enumerate them, so step 8 sat in the
 * workflow reading "Not implemented" while seven bundles, twenty-five figures
 * and two complexes accumulated on disk.
 *
 * What it will not do is re-derive anything. An export is a record of
 * something that already happened; this screen lists those records and hands
 * back the files the project still holds. A file written into a folder the
 * scientist chose is named rather than linked, because a download that 404s is
 * worse than no download.
 */

const PAGE_SIZE = 25;

const KINDS: { value: ExportKind | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "campaign", label: "Campaign bundles" },
  { value: "figure", label: "Figures" },
  { value: "pose_complex", label: "Complexes" },
];

const EXPORTABLE_ENGINES = new Set([
  "vina_batch",
  "autodock4_batch",
  "autodock_gpu_batch",
]);

export function ExportWorkspace() {
  const [entries, setEntries] = useState<ExportEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [kind, setKind] = useState<ExportKind | "all">("all");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  const [campaigns, setCampaigns] = useState<CatalogEntry[]>([]);
  const [chosen, setChosen] = useState<string>("");

  useEffect(() => {
    let disposed = false;
    setLoading(true);
    setError(null);
    void ankoraApi
      .listExports({ offset, limit: PAGE_SIZE, kind: kind === "all" ? undefined : kind })
      .then((page) => {
        if (disposed) return;
        setEntries(page.entries);
        setTotal(page.total);
      })
      .catch((reason: unknown) => {
        if (disposed) return;
        setEntries([]);
        setTotal(0);
        setError(reason instanceof Error ? reason.message : "The exports could not be read.");
      })
      .finally(() => { if (!disposed) setLoading(false); });
    return () => { disposed = true; };
  }, [offset, kind, revision]);

  // Only finished campaigns can be bundled, so only those are offered.
  useEffect(() => {
    let disposed = false;
    void ankoraApi.listResultCampaigns({ limit: 200, status: "completed" })
      .then((page) => {
        if (disposed) return;
        setCampaigns(page.entries.filter((item) => EXPORTABLE_ENGINES.has(item.engine_key)));
      })
      .catch(() => { if (!disposed) setCampaigns([]); });
    return () => { disposed = true; };
  }, []);

  const selected = useMemo(
    () => campaigns.find((item) => item.catalog_id === chosen) ?? null,
    [campaigns, chosen],
  );

  return (
    <>
      <section className="workspace export-workspace" aria-label="Export workspace">
        <div className="workspace-heading">
          <div>
            <span className="eyebrow">08 / Export</span>
            <h2>Everything this project has sent out</h2>
          </div>
          <div className="workspace-actions">
            <span className="read-only-badge">M8 · read-only</span>
          </div>
        </div>

        {error ? <div className="structure-error" role="alert">{error}</div> : null}

        <div className="export-filters" role="group" aria-label="Export kinds">
          {KINDS.map((option) => (
            <button
              type="button"
              key={option.value}
              className={kind === option.value ? "selected" : ""}
              aria-pressed={kind === option.value}
              onClick={() => { setKind(option.value); setOffset(0); }}
            >
              {option.label}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="operation-progress" role="progressbar" aria-label="Reading exports">
            <span /><p>Reading what has been exported</p>
          </div>
        ) : entries.length === 0 ? (
          <div className="viewer-placeholder ligand-placeholder">
            <div className="viewer-message">
              <div className="molecule-glyph">⇥</div>
              <h3>Nothing has been exported yet</h3>
              <p>
                Campaign bundles, publication figures and ligand–receptor complexes
                are recorded here as they are written, with the result each came from.
              </p>
            </div>
          </div>
        ) : (
          <div className="export-list" role="list" aria-label="Recorded exports">
            {entries.map((entry) => <ExportCard key={entry.export_id} entry={entry} />)}
          </div>
        )}

        {total > PAGE_SIZE ? (
          <div className="results-pager">
            <button
              type="button"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(offset - PAGE_SIZE, 0))}
            >
              Previous
            </button>
            <span>
              {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total} exports
            </span>
            <button
              type="button"
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Next
            </button>
          </div>
        ) : null}
      </section>

      <aside className="inspector docking-inspector" aria-label="Export inspector">
        <div className="inspector-heading">
          <span className="section-label">Export</span>
          <h2>Bundle a campaign</h2>
          <p className="inspector-subtitle">
            {total} recorded {total === 1 ? "export" : "exports"} in this project.
          </p>
        </div>
        <section className="receptor-section">
          <div className="filter-heading"><span>Campaign</span></div>
          <label className="export-campaign-choice">
            <span className="section-label">Completed campaign</span>
            <select value={chosen} onChange={(event) => setChosen(event.target.value)}>
              <option value="">Choose a campaign…</option>
              {campaigns.map((item) => (
                <option key={item.catalog_id} value={item.catalog_id}>
                  {item.engine_label} · {item.succeeded_count}/{item.selected_count} · {
                    formatApplicationDate(item.created_at)
                  }
                </option>
              ))}
            </select>
          </label>
          {campaigns.length === 0 ? (
            <p className="field-note">
              No completed campaign is recorded yet. Figures and complexes are exported
              from the pose they belong to, in Results.
            </p>
          ) : null}
        </section>
        {selected ? (
          <>
            <CampaignExportPanel
              key={selected.catalog_id}
              sourceKind={selected.engine_key as "vina_batch" | "autodock4_batch" | "autodock_gpu_batch"}
              sourceId={selected.record_id}
              ready
              onExported={() => setRevision((value) => value + 1)}
            />
            <MethodsPanel key={`methods-${selected.catalog_id}`} catalogId={selected.catalog_id} />
          </>
        ) : null}
      </aside>
    </>
  );
}

function ExportCard({ entry }: { entry: ExportEntry }) {
  const servable = entry.files.filter((file) => file.content_url);
  return (
    <article className="export-card" role="listitem">
      <div className="export-card-heading">
        <strong>{entry.title}</strong>
        <span className={`docking-status ${entry.kind === "campaign" ? "completed" : ""}`}>
          {label(entry.kind)}
        </span>
      </div>
      <div className="export-card-meta">
        <span>{formatApplicationDateTime(entry.exported_at)}</span>
        {entry.subtitle ? <span>{entry.subtitle}</span> : null}
      </div>
      {entry.kind === "campaign" && entry.reproducibility?.status !== "measured_reproducible" ? (
        <p className="results-card-warning">
          {reproducibilityTitle(entry.reproducibility)}
        </p>
      ) : null}
      {servable.length ? (
        <div className="export-files">
          {servable.map((file) => (
            <a
              key={file.filename}
              href={ankoraApi.exportContentUrl(file.content_url as string)}
              download={file.filename}
            >
              {file.filename}<small>{formatSize(file.size_bytes)}</small>
            </a>
          ))}
        </div>
      ) : null}
      {entry.outside_project ? (
        <p className="field-note">
          Written into a folder you chose, so Ankora records it but does not hand it
          back: {entry.files.map((file) => file.filename).join(", ") || "no files listed"}.
        </p>
      ) : null}
      <small className="export-location">{entry.directory}</small>
    </article>
  );
}

function label(kind: ExportKind): string {
  if (kind === "campaign") return "Campaign bundle";
  if (kind === "figure") return "Figure";
  return "Complex";
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}
