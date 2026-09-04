import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ankoraApi, ApiError } from "../../api/client";
import { CampaignExportPanel } from "../docking/CampaignExportPanel";
import type { CatalogEntry, CompoundPage, CompoundRow } from "../../types/api";
import { PoseInteractionPanel } from "./PoseInteractionPanel";
import { reproducibilityDetail, reproducibilityTitle } from "./reproducibility";

/**
 * Every durable result in the project, in one place (M6).
 *
 * Two rules shape this screen more than anything else:
 *
 * The browser is ordered by time, never by result. A Vina score sits several
 * kcal/mol below an AutoDock4 binding energy for the same molecule, so a
 * "best first" catalog would put every Vina campaign on top and read as a
 * verdict about the engines. Each result's own number is shown only next to the
 * name of the engine that produced it.
 *
 * A campaign is opened, not embedded. The listing carries counts and identity;
 * the molecules are a second request. The real project already holds 25 MiB of
 * poses across nine campaigns, so a screen that loaded everything to show a
 * summary would get slower with every experiment the scientist runs.
 */

const PAGE_SIZE = 25;
const ROW_PAGE_SIZE = 100;
const MAX_TRASH_SELECTION = 100;
const TERMINAL_RESULTS = new Set(["completed", "failed", "canceled"]);

type ModeFilter = "all" | "screening" | "single_ligand";
type FamilyFilter = "all" | "vina" | "autodock4";

const EXPORTABLE = new Set([
  "vina_batch",
  "autodock4_batch",
  "autodock_gpu_batch",
]);

export function ResultsWorkspace() {
  const [entries, setEntries] = useState<CatalogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [mode, setMode] = useState<ModeFilter>("all");
  const [family, setFamily] = useState<FamilyFilter>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [campaignDetailOpen, setCampaignDetailOpen] = useState(false);
  const [inspectedMolecule, setInspectedMolecule] = useState<CompoundRow | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [catalogRevision, setCatalogRevision] = useState(0);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedForDeletion, setSelectedForDeletion] = useState(
    () => new Map<string, CatalogEntry>(),
  );
  const [confirmingDeletion, setConfirmingDeletion] = useState(false);
  const [deletionAcknowledged, setDeletionAcknowledged] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deletionError, setDeletionError] = useState<string | null>(null);
  const [deletionNotice, setDeletionNotice] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    setLoading(true);
    setError(null);
    void ankoraApi
      .listResultCampaigns({
        offset,
        limit: PAGE_SIZE,
        mode: mode === "all" ? undefined : mode,
        scoringFamily: family === "all" ? undefined : family,
      })
      .then((page) => {
        if (disposed) return;
        setEntries(page.entries);
        setTotal(page.total);
      })
      .catch((reason: unknown) => {
        if (disposed) return;
        setEntries([]);
        setTotal(0);
        setError(reason instanceof Error ? reason.message : "The catalog could not be read.");
      })
      .finally(() => { if (!disposed) setLoading(false); });
    return () => { disposed = true; };
  }, [offset, mode, family, catalogRevision]);

  const selected = useMemo(
    () => entries.find((entry) => entry.catalog_id === selectedId) ?? null,
    [entries, selectedId],
  );
  const showingCampaignDetail = Boolean(selected && campaignDetailOpen);
  const deletionSelection = useMemo(
    () => [...selectedForDeletion.values()],
    [selectedForDeletion],
  );
  const deletablePageEntries = useMemo(
    () => entries.filter((entry) => TERMINAL_RESULTS.has(entry.status)),
    [entries],
  );
  const wholePageSelected = deletablePageEntries.length > 0
    && deletablePageEntries.every((entry) => selectedForDeletion.has(entry.catalog_id));

  function changeFilter(next: () => void) {
    // A filtered catalog is a different list, so the old page number and the
    // old selection would both point at something that is no longer there.
    next();
    setOffset(0);
    setSelectedId(null);
    setCampaignDetailOpen(false);
    setInspectedMolecule(null);
    setSelectionMode(false);
    setSelectedForDeletion(new Map());
    setConfirmingDeletion(false);
    setDeletionNotice(null);
  }

  function toggleDeletionSelection(entry: CatalogEntry) {
    if (!TERMINAL_RESULTS.has(entry.status)) return;
    setSelectedForDeletion((current) => {
      const next = new Map(current);
      if (next.has(entry.catalog_id)) next.delete(entry.catalog_id);
      else if (next.size < MAX_TRASH_SELECTION) next.set(entry.catalog_id, entry);
      return next;
    });
  }

  function togglePageSelection() {
    setSelectedForDeletion((current) => {
      const next = new Map(current);
      if (wholePageSelected) {
        for (const entry of deletablePageEntries) next.delete(entry.catalog_id);
      } else {
        for (const entry of deletablePageEntries) {
          if (next.size >= MAX_TRASH_SELECTION) break;
          next.set(entry.catalog_id, entry);
        }
      }
      return next;
    });
  }

  /**
   * Back to the catalog from wherever the reader is.
   *
   * Both planes have to be closed: leaving an inspected molecule set would
   * keep the catalog hidden behind an analysis that is no longer on screen.
   */
  function backToCatalog() {
    setInspectedMolecule(null);
    setCampaignDetailOpen(false);
  }

  function cancelSelection() {
    setSelectionMode(false);
    setSelectedForDeletion(new Map());
    setConfirmingDeletion(false);
    setDeletionAcknowledged(false);
    setDeletionError(null);
  }

  function confirmSingleDeletion(entry: CatalogEntry) {
    if (!TERMINAL_RESULTS.has(entry.status)) return;
    setSelectedForDeletion(new Map([[entry.catalog_id, entry]]));
    setDeletionAcknowledged(false);
    setDeletionError(null);
    setDeletionNotice(null);
    setConfirmingDeletion(true);
  }

  async function trashSelection() {
    if (!deletionAcknowledged || deletionSelection.length === 0) return;
    setDeleting(true);
    setDeletionError(null);
    try {
      const response = await ankoraApi.trashResultCampaigns(
        deletionSelection.map((entry) => entry.catalog_id),
      );
      const removed = new Set(response.campaigns.map((entry) => entry.catalog_id));
      const remainingOnPage = entries.filter((entry) => !removed.has(entry.catalog_id));
      setEntries(remainingOnPage);
      setTotal((current) => Math.max(0, current - response.campaigns.length));
      if (selectedId && removed.has(selectedId)) {
        setSelectedId(null);
        setCampaignDetailOpen(false);
        setInspectedMolecule(null);
      }
      setDeletionNotice(
        `${response.campaigns.length} ${response.campaigns.length === 1 ? "result" : "results"} moved to Trash`
        + `${response.interaction_analysis_count ? ` · ${response.interaction_analysis_count} pose ${response.interaction_analysis_count === 1 ? "analysis" : "analyses"} moved with them` : ""}`
        + `${response.redocking_validation_count ? ` · ${response.redocking_validation_count} redocking ${response.redocking_validation_count === 1 ? "validation" : "validations"} moved with them` : ""}`
        + `${response.exports_preserved ? " · Export bundles remain" : ""}.`,
      );
      setSelectionMode(false);
      setSelectedForDeletion(new Map());
      setConfirmingDeletion(false);
      setDeletionAcknowledged(false);
      if (remainingOnPage.length === 0 && offset > 0) {
        setOffset(Math.max(0, offset - PAGE_SIZE));
      } else {
        setCatalogRevision((current) => current + 1);
      }
    } catch (reason: unknown) {
      setDeletionError(
        reason instanceof ApiError && reason.status === 404 && reason.code === null
          ? "Results Trash is unavailable in the backend currently running. Close and restart Ankora to load the updated backend, then try again. No result was removed."
          : reason instanceof Error
            ? reason.message
            : "The selected results could not be removed.",
      );
    } finally {
      setDeleting(false);
    }
  }

  return (
    <>
      <section
        className={`workspace results-workspace${inspectedMolecule ? " results-interaction-workspace" : ""}`}
        aria-label="Results workspace"
      >
        <div className="workspace-heading">
          <div>
            <span className="eyebrow">06 / Results</span>
            <h2>
              {inspectedMolecule
                ? `Pose interactions · ${inspectedMolecule.name}`
                : showingCampaignDetail
                  ? "Molecules in this result"
                  : "Every result this project holds"}
            </h2>
          </div>
          <div className="workspace-actions">
            <span className="read-only-badge">
              {inspectedMolecule
                ? "M9 · pose interactions"
                : showingCampaignDetail
                  ? "M6 · campaign detail"
                  : "M6 · result catalog"}
            </span>
          </div>
        </div>

        {showingCampaignDetail ? (
          <nav className="results-breadcrumb" aria-label="Results navigation">
            <button type="button" onClick={backToCatalog}>All results</button>
            <span aria-hidden="true">›</span>
            {inspectedMolecule ? (
              <>
                <button type="button" onClick={() => setInspectedMolecule(null)}>
                  {selected?.engine_label}
                </button>
                <span aria-hidden="true">›</span>
                <strong aria-current="page">{inspectedMolecule.name}</strong>
              </>
            ) : (
              <strong aria-current="page">{selected?.engine_label}</strong>
            )}
          </nav>
        ) : null}

        <div
          className="results-catalog-plane"
          hidden={Boolean(inspectedMolecule) || showingCampaignDetail}
        >
          {error ? <div className="structure-error" role="alert">{error}</div> : null}

          <div className="results-filters" role="group" aria-label="Catalog filters">
            <Choice
              label="Mode"
              value={mode}
              options={[
                ["all", "All"],
                ["screening", "Screening"],
                ["single_ligand", "Single ligand"],
              ]}
              onChange={(value) => changeFilter(() => setMode(value as ModeFilter))}
            />
            <Choice
              label="Scoring"
              value={family}
              options={[
                ["all", "All"],
                ["vina", "Vina score"],
                ["autodock4", "AutoDock4 energy"],
              ]}
              onChange={(value) => changeFilter(() => setFamily(value as FamilyFilter))}
            />
            <p className="field-note results-order-note">
              Newest first. Results are never ordered against each other: a Vina score and an
              AutoDock4 binding energy come from different scoring functions and are not on a
              shared scale.
            </p>
          </div>

          <div className="results-management" role="toolbar" aria-label="Manage result campaigns">
            {selectionMode ? (
              <>
                <button type="button" className="quiet-button" onClick={togglePageSelection}>
                  {wholePageSelected ? "Clear this page" : "Select this page"}
                </button>
                <span>{deletionSelection.length} selected · maximum {MAX_TRASH_SELECTION}</span>
                <span className="results-management-spacer" />
                <button type="button" className="quiet-button" onClick={cancelSelection}>
                  Cancel
                </button>
                <button
                  type="button"
                  className="danger-action"
                  disabled={deletionSelection.length === 0}
                  onClick={() => {
                    setDeletionAcknowledged(false);
                    setDeletionError(null);
                    setConfirmingDeletion(true);
                  }}
                >
                  Delete {deletionSelection.length || "selected"}
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  className="quiet-button"
                  disabled={entries.length === 0}
                  onClick={() => {
                    setSelectionMode(true);
                    setSelectedId(null);
                    setCampaignDetailOpen(false);
                    setInspectedMolecule(null);
                    setDeletionNotice(null);
                  }}
                >
                  Select multiple
                </button>
                <span>Select several campaigns and remove them together.</span>
                <span className="results-management-spacer" />
                <button
                  type="button"
                  className="danger-action"
                  disabled={!selected || !TERMINAL_RESULTS.has(selected.status)}
                  onClick={() => { if (selected) confirmSingleDeletion(selected); }}
                >
                  Delete open result
                </button>
              </>
            )}
          </div>

          {deletionNotice ? <div className="results-trash-notice" role="status">{deletionNotice}</div> : null}

          {loading ? (
            <div className="operation-progress" role="progressbar" aria-label="Reading the result catalog">
              <span /><p>Reading the result catalog</p>
            </div>
          ) : entries.length === 0 ? (
            <div className="viewer-placeholder ligand-placeholder">
              <div className="viewer-message">
                <div className="molecule-glyph">◔</div>
                <h3>No results recorded yet</h3>
                <p>
                  Every docking run this project completes — one ligand or a whole library, on
                  either engine — is recorded here and stays findable afterwards.
                </p>
              </div>
            </div>
          ) : (
            <CampaignBrowser
              entries={entries}
              selectedId={selectedId}
              selectionMode={selectionMode}
              selectedForDeletion={selectedForDeletion}
              onSelect={(id) => {
                setInspectedMolecule(null);
                // A result card represents a durable selection, not a
                // disclosure toggle. Keeping the same ID selected means the
                // two click events in a native double-click cannot open and
                // immediately close the campaign again.
                setSelectedId(id);
                setCampaignDetailOpen(true);
              }}
              onToggleDeletion={toggleDeletionSelection}
            />
          )}

          <Pager
            offset={offset}
            limit={PAGE_SIZE}
            total={total}
            noun="results"
            onOffset={(next) => {
              setOffset(next);
              setSelectedId(null);
              setCampaignDetailOpen(false);
              setInspectedMolecule(null);
            }}
          />
        </div>

        {selected && showingCampaignDetail && !inspectedMolecule ? (
          <div className="results-campaign-detail-plane">
            <div className="results-detail-navigation" role="toolbar" aria-label="Open result actions">
              <div>
                <strong>{selected.engine_label}</strong>
                <span>
                  {selected.mode === "screening" ? "Screening" : "Single ligand"}
                  {` · ${formatMoment(selected.created_at)}`}
                </span>
              </div>
              <span className="results-management-spacer" />
              <button
                type="button"
                className="danger-action"
                disabled={!TERMINAL_RESULTS.has(selected.status)}
                onClick={() => confirmSingleDeletion(selected)}
              >
                Delete this result
              </button>
            </div>
            <CompoundTable entry={selected} onInspect={setInspectedMolecule} />
          </div>
        ) : null}

        {selected && inspectedMolecule ? (
          <PoseInteractionPanel
            entry={selected}
            molecule={inspectedMolecule}
            onClose={() => setInspectedMolecule(null)}
          />
        ) : null}
      </section>

      <aside className="inspector docking-inspector" aria-label="Results inspector">
        <div className="inspector-heading">
          <span className="section-label">Results</span>
          <h2>{selected ? selected.engine_label : "Result catalog"}</h2>
          <p className="inspector-subtitle">
            {selected
              ? "What it would take to ask this question again."
              : `${total} recorded ${total === 1 ? "result" : "results"} in this project.`}
          </p>
        </div>
        {selected ? <Evidence entry={selected} /> : <CatalogNote />}
      </aside>

      {confirmingDeletion ? (
        <div className="results-delete-backdrop">
          <section
            className="results-delete-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="results-delete-title"
          >
            <div>
              <span className="section-label">Results · destructive action</span>
              <h2 id="results-delete-title">
                Delete {deletionSelection.length} {deletionSelection.length === 1 ? "result" : "results"}?
              </h2>
              <p>
                The complete campaign folders and their dependent pose analyses or redocking
                validations will move together to Ankora Trash. Receptors, ligands, binding sites,
                shared grid maps, and export bundles are not deleted.
              </p>
            </div>
            <ul className="results-delete-list">
              {deletionSelection.map((entry) => (
                <li key={entry.catalog_id}>
                  <strong>{entry.engine_label}</strong>
                  <span>{entry.mode === "screening" ? "Screening" : "Single ligand"} · {formatMoment(entry.created_at)}</span>
                </li>
              ))}
            </ul>
            <label className="check-row results-delete-acknowledgement">
              <input
                type="checkbox"
                checked={deletionAcknowledged}
                onChange={(event) => setDeletionAcknowledged(event.target.checked)}
              />
              <span>
                <strong>Remove this exact selection from active Results</strong>
                <small>The operation is recorded and recoverable from Ankora's internal Trash.</small>
              </span>
            </label>
            {deletionError ? <div className="structure-error" role="alert">{deletionError}</div> : null}
            <div className="results-delete-actions">
              <button
                type="button"
                className="quiet-button"
                disabled={deleting}
                onClick={() => {
                  setConfirmingDeletion(false);
                  setDeletionAcknowledged(false);
                  setDeletionError(null);
                }}
              >
                Keep results
              </button>
              <button
                type="button"
                className="danger-action"
                disabled={!deletionAcknowledged || deleting}
                onClick={() => void trashSelection()}
              >
                {deleting ? "Moving to Trash…" : `Delete ${deletionSelection.length}`}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </>
  );
}

function CampaignBrowser({
  entries,
  selectedId,
  selectionMode,
  selectedForDeletion,
  onSelect,
  onToggleDeletion,
}: {
  entries: CatalogEntry[];
  selectedId: string | null;
  selectionMode: boolean;
  selectedForDeletion: Map<string, CatalogEntry>;
  onSelect: (catalogId: string) => void;
  onToggleDeletion: (entry: CatalogEntry) => void;
}) {
  return (
    <div className="results-browser" role="list" aria-label="Recorded results">
      {entries.map((entry) => {
        const selected = selectionMode
          ? selectedForDeletion.has(entry.catalog_id)
          : entry.catalog_id === selectedId;
        const deletable = TERMINAL_RESULTS.has(entry.status);
        return (
          <button
            type="button"
            role="listitem"
            key={entry.catalog_id}
            className={`results-card${selected ? " selected" : ""}`}
            aria-pressed={selected}
            disabled={selectionMode && !deletable}
            onClick={() => {
              if (selectionMode) onToggleDeletion(entry);
              else onSelect(entry.catalog_id);
            }}
          >
            <div className="results-card-heading">
              <strong>
                {selectionMode ? (
                  <span className={`results-selection-mark${selected ? " selected" : ""}`} aria-hidden="true">
                    {selected ? "✓" : ""}
                  </span>
                ) : null}
                {entry.engine_label}
              </strong>
              <span className={`docking-status ${entry.status}`}>{entry.status}</span>
            </div>
            <div className="results-card-meta">
              <span>{entry.mode === "screening" ? "Screening" : "Single ligand"}</span>
              <span>{formatMoment(entry.created_at)}</span>
              <span>
                {entry.succeeded_count}/{entry.selected_count} docked
                {entry.failed_count > 0 ? ` · ${entry.failed_count} failed` : ""}
              </span>
            </div>
            {entry.best_result_kcal_mol === null ? (
              <p className="results-card-best muted">No result was produced.</p>
            ) : (
              <p className="results-card-best">
                <strong>{entry.best_result_kcal_mol.toFixed(2)} kcal/mol</strong>
                {/* Never a bare number: the engine's name travels with it. */}
                <small>
                  best {entry.scoring_family === "vina" ? "Vina score" : "binding energy"}
                  {entry.best_molecule ? ` · ${entry.best_molecule}` : ""}
                </small>
              </p>
            )}
            {entry.reproducibility.status !== "measured_reproducible" ? (
              <p className="results-card-warning">
                {entry.reproducibility.status === "measured_variable"
                  ? "Exact repeats produced different outputs"
                  : "Repeat reproducibility not assessed"}
              </p>
            ) : null}
            {selectionMode && !deletable ? (
              <p className="results-card-warning">Finish or cancel before deleting</p>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

function CompoundTable({ entry, onInspect }: {
  entry: CatalogEntry;
  onInspect: (molecule: CompoundRow) => void;
}) {
  const [page, setPage] = useState<CompoundPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const [onlyFailed, setOnlyFailed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const horizontalScrollRef = useRef<HTMLDivElement>(null);
  const tableScrollRef = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    let disposed = false;
    setLoading(true);
    setError(null);
    void ankoraApi
      .listResultCompounds(entry.catalog_id, {
        offset,
        limit: ROW_PAGE_SIZE,
        search: search.trim() || undefined,
        status: onlyFailed ? "failed" : undefined,
      })
      .then((next) => { if (!disposed) setPage(next); })
      .catch((reason: unknown) => {
        if (disposed) return;
        setPage(null);
        setError(reason instanceof Error ? reason.message : "The molecules could not be read.");
      })
      .finally(() => { if (!disposed) setLoading(false); });
    return () => { disposed = true; };
  }, [entry.catalog_id, offset, search, onlyFailed]);

  useEffect(() => load(), [load]);
  // A different result is a different table, so the page number resets with it.
  useEffect(() => {
    setOffset(0); setSearch(""); setOnlyFailed(false);
  }, [entry.catalog_id]);

  const clusterNative = entry.scoring_family === "autodock4";

  return (
    <section
      className="docking-results library-docking-results results-compounds"
      aria-label="Molecules in this result"
    >
      <div className="docking-results-heading">
        <div>
          <span className="eyebrow">{page?.engine_label ?? entry.engine_label}</span>
          <h3>{page ? `${page.total} molecules` : "Molecules"}</h3>
        </div>
        <div className="results-row-controls">
          <input
            type="search"
            aria-label="Search molecules"
            placeholder="Name or SMILES"
            value={search}
            onChange={(event) => { setSearch(event.target.value); setOffset(0); }}
          />
          <label>
            <input
              type="checkbox"
              checked={onlyFailed}
              onChange={(event) => { setOnlyFailed(event.target.checked); setOffset(0); }}
            />
            Only molecules that failed
          </label>
        </div>
      </div>
      {error ? <div className="structure-error" role="alert">{error}</div> : null}
      {/* The table is wider than the column, and a scrollbar only at the bottom
          of a long table is one the reader has to go looking for. This one sits
          above the header and stays in step with the table's own. */}
      <div
        className="docking-results-horizontal-scroll"
        ref={horizontalScrollRef}
        tabIndex={0}
        aria-label="Horizontal molecule table scroll"
        onScroll={(event) => syncHorizontalScroll(event.currentTarget, tableScrollRef.current)}
      >
        <div />
      </div>
      <div
        className="docking-results-scroll"
        ref={tableScrollRef}
        tabIndex={0}
        aria-label="Scrollable molecule table"
        onScroll={(event) => syncHorizontalScroll(event.currentTarget, horizontalScrollRef.current)}
      >
        <table>
          <thead>
            <tr>
              <th>Rank</th>
              <th>#</th>
              <th>Molecule</th>
              <th>Chemical state</th>
              {/* The engine's own column name, so it is never just "score". */}
              <th>{page?.value_label ?? "Result (kcal/mol)"}</th>
              {clusterNative ? <th>Clusters</th> : <th>Poses</th>}
              {clusterNative ? <th>Top cluster runs</th> : null}
              <th>MW (g/mol)</th>
              <th>SMILES</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {(page?.rows ?? []).map((row, index) => (
              <tr
                key={row.ligand_id}
                className={row.status === "completed" ? "result-row-selectable" : "muted-row"}
                tabIndex={row.status === "completed" ? 0 : undefined}
                onClick={() => {
                  if (row.status === "completed") onInspect(row);
                }}
                onKeyDown={(event) => {
                  if (row.status === "completed" && (event.key === "Enter" || event.key === " ")) {
                    onInspect(row);
                  }
                }}
              >
                <td>{row.best_result_kcal_mol === null ? "—" : offset + index + 1}</td>
                {/* Manifest order, kept beside the ranking that reordered it. */}
                <td>{row.source_index + 1}</td>
                <td>{row.name}</td>
                <td>{row.chemical_state_id ? <><code>{row.chemical_state_id.slice(0, 10)}…</code><small>charge {row.chemical_state_formal_charge !== null && row.chemical_state_formal_charge !== undefined ? `${row.chemical_state_formal_charge >= 0 ? "+" : ""}${row.chemical_state_formal_charge}` : "not recorded"}</small></> : "Historical · not recorded"}</td>
                <td>{row.best_result_kcal_mol?.toFixed(2) ?? "—"}</td>
                <td>{(clusterNative ? row.cluster_count : row.pose_count) ?? "—"}</td>
                {clusterNative ? <td>{row.top_cluster_runs ?? "—"}</td> : null}
                <td>{row.molecular_weight_g_mol?.toFixed(1) ?? "—"}</td>
                <td><code>{row.canonical_smiles ?? "—"}</code></td>
                <td>
                  <span className={`docking-status ${row.status}`}>{row.status}</span>
                  {row.failure_code ? <small>{row.failure_code}</small> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {loading ? <p className="field-note">Reading molecules…</p> : null}
      <Pager
        offset={offset}
        limit={ROW_PAGE_SIZE}
        total={page?.total ?? 0}
        noun="molecules"
        onOffset={setOffset}
      />
      <p className="field-note results-pose-hint">
        Select a completed molecule to inspect every preserved pose or run and calculate its 2D contacts.
      </p>
    </section>
  );
}

function syncHorizontalScroll(source: HTMLDivElement, target: HTMLDivElement | null) {
  if (target && Math.abs(target.scrollLeft - source.scrollLeft) > 0.5) {
    target.scrollLeft = source.scrollLeft;
  }
}

function Evidence({ entry }: { entry: CatalogEntry }) {
  const box = entry.box;
  const hasBox = typeof box.size_x === "number";
  return (
    <>
      <section className="receptor-section">
        <div className="filter-heading"><span>What this result is</span></div>
        <dl className="docking-evidence">
          <div><dt>Mode</dt><dd>{entry.mode === "screening" ? "Screening" : "Single ligand"}</dd></div>
          <div><dt>Engine</dt><dd>{entry.engine_label}</dd></div>
          <div><dt>Status</dt><dd>{entry.status}</dd></div>
          <div><dt>Started</dt><dd>{formatMoment(entry.created_at)}</dd></div>
          {entry.completed_at
            ? <div><dt>Finished</dt><dd>{formatMoment(entry.completed_at)}</dd></div>
            : null}
        </dl>
      </section>
      <section className="receptor-section">
        <div className="filter-heading"><span>Reproducibility</span></div>
        <div className="state-resolved-note">
          <strong>{reproducibilityTitle(entry.reproducibility)}</strong>
          <small>{reproducibilityDetail(entry.reproducibility)}</small>
          {entry.reproducibility.input_fingerprint_sha256 ? (
            <small>
              Input fingerprint {entry.reproducibility.input_fingerprint_sha256.slice(0, 12)}… · {entry.reproducibility.protocol}
            </small>
          ) : null}
          {entry.reproducibility.executions.map((execution) => (
            <small key={execution.catalog_id}>
              {execution.catalog_id} · output {execution.output_fingerprint_sha256.slice(0, 12)}…
            </small>
          ))}
        </div>
      </section>
      <section className="receptor-section">
        <div className="filter-heading"><span>Inputs</span></div>
        <dl className="docking-evidence">
          <div><dt>Receptor</dt><dd>{entry.receptor_id.slice(0, 8)}…</dd></div>
          <div><dt>Binding site</dt><dd>{entry.binding_site_id.slice(0, 8)}…</dd></div>
          {hasBox ? (
            <>
              <div>
                <dt>Box centre</dt>
                <dd>
                  {box.center_x.toFixed(1)}, {box.center_y.toFixed(1)}, {box.center_z.toFixed(1)} Å
                </dd>
              </div>
              <div>
                <dt>Box size</dt>
                <dd>
                  {box.size_x.toFixed(0)}×{box.size_y.toFixed(0)}×{box.size_z.toFixed(0)} Å
                </dd>
              </div>
            </>
          ) : null}
          {entry.map_set_identity_key
            ? <div><dt>Map set</dt><dd>{entry.map_set_identity_key.slice(0, 12)}…</dd></div>
            : null}
          {entry.selection_manifest_sha256
            ? <div><dt>Selection</dt><dd>{entry.selection_manifest_sha256.slice(0, 12)}…</dd></div>
            : null}
          {entry.ligand_id
            ? <div><dt>Ligand</dt><dd>{entry.ligand_id.slice(0, 8)}…</dd></div>
            : null}
          {entry.executable_sha256
            ? <div><dt>Executable</dt><dd>{entry.executable_sha256.slice(0, 12)}…</dd></div>
            : null}
          {entry.device_name
            ? <div><dt>Device</dt><dd>{entry.device_name}</dd></div>
            : null}
        </dl>
        <p className="field-note">
          Two records can name the same pocket, so the box — not the identifier — is what
          says whether two results searched the same space.
        </p>
      </section>
      {EXPORTABLE.has(entry.engine_key) ? (
        <CampaignExportPanel
          sourceKind={entry.engine_key as "vina_batch" | "autodock4_batch" | "autodock_gpu_batch"}
          sourceId={entry.record_id}
          ready={entry.status === "completed"}
        />
      ) : null}
    </>
  );
}

function CatalogNote() {
  return (
    <section className="receptor-section">
      <div className="filter-heading"><span>Why results are not ranked together</span></div>
      <p className="field-note">
        Vina reports an empirical score and AutoDock4 a semi-empirical binding energy. They
        come from different scoring functions on different scales, so a single "best result"
        column across the catalog would invent a comparison the science does not support.
        Each result carries its own number beside the name of the engine that produced it,
        and the catalog itself is ordered only by time.
      </p>
      <p className="field-note">
        Open a result to see its molecules, the exact search space it ran in, and what it
        would take to ask the same question again.
      </p>
    </section>
  );
}

function Pager({ offset, limit, total, noun, onOffset }: {
  offset: number;
  limit: number;
  total: number;
  noun: string;
  onOffset: (next: number) => void;
}) {
  if (total <= limit) return null;
  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + limit, total);
  return (
    <div className="results-pager">
      <button type="button" disabled={offset === 0} onClick={() => onOffset(Math.max(offset - limit, 0))}>
        Previous
      </button>
      <span>{first}–{last} of {total} {noun}</span>
      <button type="button" disabled={last >= total} onClick={() => onOffset(offset + limit)}>
        Next
      </button>
    </div>
  );
}

function Choice({ label, value, options, onChange }: {
  label: string;
  value: string;
  options: [string, string][];
  onChange: (value: string) => void;
}) {
  return (
    <div className="results-choice">
      <span className="section-label">{label}</span>
      <div role="group" aria-label={label}>
        {options.map(([option, caption]) => (
          <button
            type="button"
            key={option}
            className={value === option ? "selected" : ""}
            aria-pressed={value === option}
            onClick={() => onChange(option)}
          >
            {caption}
          </button>
        ))}
      </div>
    </div>
  );
}

function formatMoment(value: string): string {
  const moment = new Date(value);
  if (Number.isNaN(moment.getTime())) return value;
  return moment.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export type { CompoundRow };
