import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { ankoraApi } from "../../api/client";
import type {
  EngineComparison,
  EngineComparisonRow,
} from "../../types/api";
import { formatScientificNumber } from "../../utils/format";

interface EngineComparisonWorkspaceProps {
  receptorId: string;
  bindingSiteId: string;
  filterRunId: string | null;
  modeSwitch?: ReactNode;
}

type ComparisonSortKey =
  | "source_index"
  | "name"
  | "vina_rank"
  | "autodock4_rank"
  | "rank_difference";
type SortDirection = "ascending" | "descending";

export function EngineComparisonWorkspace({
  receptorId,
  bindingSiteId,
  filterRunId,
  modeSwitch,
}: EngineComparisonWorkspaceProps) {
  const [comparison, setComparison] = useState<EngineComparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [sortKey, setSortKey] = useState<ComparisonSortKey>("vina_rank");
  const [sortDirection, setSortDirection] = useState<SortDirection>("ascending");

  const ready = Boolean(filterRunId);

  // Campaigns are persisted, so the comparison is resolved from what is on
  // disk rather than from whatever this session happens to have launched. That
  // is what lets it survive a reload, or a campaign run days earlier.
  useEffect(() => {
    if (!filterRunId) {
      setComparison(null);
      return;
    }
    let disposed = false;
    setLoading(true);
    setError(null);
    void ankoraApi.compareLatestDockingCampaigns(receptorId, bindingSiteId, filterRunId)
      .then((next) => { if (!disposed) setComparison(next); })
      .catch((reason: unknown) => {
        if (!disposed) {
          setComparison(null);
          setError(reason instanceof Error ? reason.message : "The comparison could not be built.");
        }
      })
      .finally(() => { if (!disposed) setLoading(false); });
    return () => { disposed = true; };
  }, [receptorId, bindingSiteId, filterRunId]);

  const rows = useMemo(() => {
    const entries = [...(comparison?.rows ?? [])];
    const factor = sortDirection === "ascending" ? 1 : -1;
    return entries.sort((left, right) => {
      const a = sortValue(left, sortKey);
      const b = sortValue(right, sortKey);
      // A molecule one engine could not dock sorts last regardless of direction.
      if (a === null && b === null) return left.source_index - right.source_index;
      if (a === null) return 1;
      if (b === null) return -1;
      if (typeof a === "string" || typeof b === "string") {
        return String(a).localeCompare(String(b)) * factor;
      }
      return (a - b) * factor;
    });
  }, [comparison, sortDirection, sortKey]);

  function changeSort(nextKey: ComparisonSortKey) {
    if (nextKey === sortKey) {
      setSortDirection((current) => current === "ascending" ? "descending" : "ascending");
      return;
    }
    setSortKey(nextKey);
    setSortDirection("ascending");
  }

  return (
    <>
      <section className="workspace docking-workspace" aria-label="Engine comparison workspace">
        <div className="workspace-heading">
          <div><span className="eyebrow">05 / Docking</span><h2>Compare Vina and AutoDock4 over the same selection</h2></div>
          <div className="workspace-actions">
            {modeSwitch}
            <span className="read-only-badge">M5 · Side by side</span>
          </div>
        </div>
        {error ? <div className="structure-error" role="alert">{error}</div> : null}
        {!ready ? (
          <div className="viewer-placeholder ligand-placeholder">
            <div className="viewer-message">
              <div className="molecule-glyph">⇄</div>
              <h3>Apply a ligand selection first</h3>
              <p>
                A comparison needs one completed Vina campaign and one completed AutoDock4
                campaign over the same receptor, search space, and applied selection.
              </p>
            </div>
          </div>
        ) : loading ? (
          <div className="operation-progress" role="progressbar" aria-label="Building comparison">
            <span /><p>Comparing the two rankings</p>
          </div>
        ) : comparison ? (
          <ComparisonTable
            comparison={comparison}
            rows={rows}
            sortKey={sortKey}
            sortDirection={sortDirection}
            onSort={changeSort}
          />
        ) : null}
      </section>
      <aside className="inspector docking-inspector" aria-label="Engine comparison inspector">
        <div className="inspector-heading">
          <span className="section-label">Engine comparison</span>
          <h2>Vina vs AutoDock4</h2>
          <p className="inspector-subtitle">
            Two independent rankings of the same molecules, shown side by side.
          </p>
        </div>
        <section className="receptor-section">
          <div className="filter-heading"><span>Why there is no combined score</span></div>
          <p className="field-note">
            Vina reports an empirical score and AutoDock4 a semi-empirical binding energy.
            They come from different scoring functions on different scales, so averaging or
            summing them would invent an agreement the science does not support. Ankora shows
            each engine's own number and its own rank, and measures only how much the two
            orderings agree.
          </p>
        </section>
        {comparison ? (
          <>
            <section className="receptor-section">
              <div className="filter-heading"><span>Coverage</span></div>
              <dl className="docking-evidence">
                <div><dt>Selection</dt><dd>{comparison.selected_count} molecules</dd></div>
                <div><dt>Docked by both</dt><dd>{comparison.docked_by_both_count}</dd></div>
                <div><dt>Vina only</dt><dd>{comparison.vina_only_count}</dd></div>
                <div><dt>AutoDock4 only</dt><dd>{comparison.autodock4_only_count}</dd></div>
                <div><dt>Neither</dt><dd>{comparison.docked_by_neither_count}</dd></div>
              </dl>
            </section>
            <section className="receptor-section">
              <div className="filter-heading"><span>Rank agreement</span></div>
              <div className="state-resolved-note">
                <strong>
                  {comparison.agreement.spearman_rho === null
                    ? "Not enough shared molecules"
                    : `Spearman ρ = ${formatScientificNumber(comparison.agreement.spearman_rho, 3)}`}
                </strong>
                <small>
                  {comparison.agreement.spearman_rho === null
                    ? "At least three molecules must be docked by both engines."
                    : `Over ${comparison.agreement.comparable_count} molecules docked by both. This measures how the two orderings agree; it is not a score for any molecule.`}
                </small>
              </div>
              <div className="state-resolved-note">
                <strong>
                  {comparison.agreement.top_n_overlap} of the top {comparison.agreement.top_n} shared
                </strong>
                <small>
                  Molecules that both engines place in their own top {comparison.agreement.top_n}.
                </small>
              </div>
            </section>
            <section className="receptor-section">
              <div className="filter-heading"><span>Campaigns</span></div>
              <dl className="docking-evidence">
                <div><dt>Vina</dt><dd>{comparison.vina_version} · {comparison.vina_batch_id.slice(0, 8)}…</dd></div>
                <div><dt>AutoDock4</dt><dd>{comparison.autodock4_version} · {comparison.autodock4_batch_id.slice(0, 8)}…</dd></div>
                <div><dt>Selection</dt><dd>{comparison.selection_manifest_sha256.slice(0, 12)}…</dd></div>
              </dl>
            </section>
          </>
        ) : null}
      </aside>
    </>
  );
}

function ComparisonTable({ comparison, rows, sortKey, sortDirection, onSort }: {
  comparison: EngineComparison;
  rows: EngineComparisonRow[];
  sortKey: ComparisonSortKey;
  sortDirection: SortDirection;
  onSort: (key: ComparisonSortKey) => void;
}) {
  return (
    <section className="docking-results library-docking-results engine-comparison-results" aria-label="Engine comparison results">
      <div className="docking-results-heading">
        <div><span className="eyebrow">Side by side</span><h3>Vina and AutoDock4 rankings</h3></div>
        <p>
          Each engine keeps its own score and its own rank. The two are never combined:
          the columns use different scoring functions and are not on a shared scale.
        </p>
      </div>
      <div className="docking-results-scroll" tabIndex={0} aria-label="Scrollable comparison table">
        <table>
          <thead>
            <tr>
              <SortHeader label="#" sortKey="source_index" activeKey={sortKey} direction={sortDirection} onSort={onSort} />
              <SortHeader label="Name" sortKey="name" activeKey={sortKey} direction={sortDirection} onSort={onSort} />
              <SortHeader label="Vina rank" sortKey="vina_rank" activeKey={sortKey} direction={sortDirection} onSort={onSort} />
              <th>Vina score (kcal/mol)</th>
              <SortHeader label="AutoDock4 rank" sortKey="autodock4_rank" activeKey={sortKey} direction={sortDirection} onSort={onSort} />
              <th>AutoDock4 energy (kcal/mol)</th>
              <th>Top cluster runs</th>
              <SortHeader label="Rank difference" sortKey="rank_difference" activeKey={sortKey} direction={sortDirection} onSort={onSort} />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.ligand_id} className={row.docked_by_both ? "" : "muted-row"}>
                <td>{row.source_index + 1}</td>
                <td>
                  {row.name}
                  {comparison.agreement.top_n_shared_ligand_ids.includes(row.ligand_id)
                    ? <small> · both top {comparison.agreement.top_n}</small>
                    : null}
                </td>
                <td>{row.vina_rank ?? "—"}</td>
                <td>{formatScientificNumber(row.vina_best_score_kcal_mol, 2)}</td>
                <td>{row.autodock4_rank ?? "—"}</td>
                <td>{formatScientificNumber(row.autodock4_best_energy_kcal_mol, 2)}</td>
                <td>{row.autodock4_top_cluster_run_count ?? "—"}</td>
                <td>{row.rank_difference ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function SortHeader({ label, sortKey, activeKey, direction, onSort }: {
  label: string;
  sortKey: ComparisonSortKey;
  activeKey: ComparisonSortKey;
  direction: SortDirection;
  onSort: (key: ComparisonSortKey) => void;
}) {
  const active = sortKey === activeKey;
  return (
    <th aria-sort={active ? direction : "none"}>
      <button type="button" className="result-sort" onClick={() => onSort(sortKey)}>
        {label}<span aria-hidden="true">{active ? direction === "ascending" ? "↑" : "↓" : "↕"}</span>
      </button>
    </th>
  );
}

function sortValue(
  row: EngineComparisonRow,
  key: ComparisonSortKey,
): number | string | null {
  if (key === "source_index") return row.source_index;
  if (key === "name") return row.name;
  if (key === "vina_rank") return row.vina_rank;
  if (key === "autodock4_rank") return row.autodock4_rank;
  return row.rank_difference;
}
