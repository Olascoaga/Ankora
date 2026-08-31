import { useMemo, useState } from "react";

import { AppIcon } from "../../components/AppIcon";
import type {
  LigandFilterEvaluation,
  LigandLibraryFilterPreview,
  LigandLibraryRecord,
  LigandPdbqtRecord,
  LigandRuleEvaluation,
} from "../../types/api";

export type LigandBatchStatus =
  | "eligible"
  | "excluded"
  | "needs-decision"
  | "generating"
  | "minimized"
  | "prepared"
  | "nonconverged"
  | "failed";

export interface LigandBatchResult {
  status: LigandBatchStatus;
  conformer?: import("../../types/api").LigandConformerRecord;
  pdbqt?: LigandPdbqtRecord;
  // Present when this result was hydrated from persisted preparation status
  // rather than a live batch run this session - the full conformer/pdbqt
  // records above are not fetched eagerly, only these ids to fetch them on
  // demand once the ligand is actually selected for inspection.
  conformerId?: string | null;
  pdbqtPreparationId?: string | null;
  finalEnergyKcalMol?: number;
  error?: string;
}

type ColumnKey = "formula" | "mw" | "clogp" | "qed" | "rules" | "alerts" | "energy";
type SortKey = "source" | "name" | "mw" | "qed" | "energy" | "status";

const optionalColumns: { key: ColumnKey; label: string }[] = [
  { key: "formula", label: "Formula" },
  { key: "mw", label: "Molecular weight" },
  { key: "clogp", label: "cLogP" },
  { key: "qed", label: "QED" },
  { key: "rules", label: "Rules" },
  { key: "alerts", label: "Alerts" },
  { key: "energy", label: "MMFF energy" },
];

interface LigandLibraryTableProps {
  library: LigandLibraryRecord;
  preview: LigandLibraryFilterPreview | null;
  selectedLigandId: string | null;
  results: Record<string, LigandBatchResult>;
  onSelect: (ligandId: string) => void;
  onBulkKeepLargestFragment: (ligandIds: string[]) => void;
  onBulkExclude: (ligandIds: string[]) => void;
  bulkActionPending: boolean;
}

export function LigandLibraryTable({ library, preview, selectedLigandId, results, onSelect, onBulkKeepLargestFragment, onBulkExclude, bulkActionPending }: LigandLibraryTableProps) {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | LigandBatchStatus>("all");
  const [sortKey, setSortKey] = useState<SortKey>("source");
  const [sortAscending, setSortAscending] = useState(true);
  const [visibleColumns, setVisibleColumns] = useState<Set<ColumnKey>>(() => new Set(optionalColumns.map((column) => column.key)));
  const [checkedIds, setCheckedIds] = useState<Set<string>>(() => new Set());
  const evaluations = useMemo(() => new Map(preview?.evaluations.map((evaluation) => [evaluation.ligand_id, evaluation]) ?? []), [preview]);
  const rows = useMemo(() => library.entries.map((entry) => {
    const ligandId = entry.ligand?.artifact.ligand_id ?? null;
    const evaluation = ligandId ? evaluations.get(ligandId) : undefined;
    const result = ligandId ? results[ligandId] : undefined;
    const status: LigandBatchStatus = entry.ligand ? result?.status ?? dispositionStatus(evaluation) : "failed";
    return { entry, ligandId, evaluation, result, status };
  }).filter((row) => {
    const normalized = query.trim().toLowerCase();
    if (statusFilter !== "all" && row.status !== statusFilter) return false;
    if (!normalized) return true;
    const ligand = row.entry.ligand;
    return Boolean(
      ligand?.inspection.name.toLowerCase().includes(normalized)
      || ligand?.inspection.canonical_smiles?.toLowerCase().includes(normalized)
      || ligand?.inspection.formula.toLowerCase().includes(normalized)
      || row.entry.failure?.message.toLowerCase().includes(normalized),
    );
  }).sort((left, right) => {
    const direction = sortAscending ? 1 : -1;
    if (sortKey === "source") return direction * (left.entry.record_index - right.entry.record_index);
    if (sortKey === "name") return direction * (left.entry.ligand?.inspection.name ?? "").localeCompare(right.entry.ligand?.inspection.name ?? "");
    if (sortKey === "status") return direction * left.status.localeCompare(right.status);
    const leftValue = numericSortValue(left, sortKey);
    const rightValue = numericSortValue(right, sortKey);
    return direction * (leftValue - rightValue);
  }), [evaluations, library.entries, query, results, sortAscending, sortKey, statusFilter]);
  const visibleIds = useMemo(() => rows.flatMap((row) => (row.ligandId ? [row.ligandId] : [])), [rows]);
  const checkedVisibleCount = visibleIds.filter((id) => checkedIds.has(id)).length;
  const allVisibleChecked = visibleIds.length > 0 && checkedVisibleCount === visibleIds.length;

  function changeSort(next: SortKey) {
    if (sortKey === next) setSortAscending((value) => !value);
    else { setSortKey(next); setSortAscending(true); }
  }

  function toggleChecked(ligandId: string) {
    setCheckedIds((current) => {
      const next = new Set(current);
      if (next.has(ligandId)) next.delete(ligandId); else next.add(ligandId);
      return next;
    });
  }

  function toggleAllVisible() {
    setCheckedIds((current) => {
      if (allVisibleChecked) return new Set([...current].filter((id) => !visibleIds.includes(id)));
      return new Set([...current, ...visibleIds]);
    });
  }

  function runBulkAction(action: (ligandIds: string[]) => void) {
    action([...checkedIds]);
    setCheckedIds(new Set());
  }

  function toggleColumn(column: ColumnKey) {
    setVisibleColumns((current) => {
      const next = new Set(current);
      if (next.has(column)) next.delete(column); else next.add(column);
      return next;
    });
  }

  return <section className="data-panel ligand-library-panel" aria-label="Ligand library">
    <div className="data-panel-heading ligand-library-heading">
      <div><span className="section-label">Virtual screening library</span><strong>{library.artifact.filename}</strong></div>
      <div className="library-counts"><span><strong>{library.imported_count}</strong> imported</span><span className={library.failed_count ? "danger" : ""}><strong>{library.failed_count}</strong> failed</span><span>SHA-256 {library.artifact.sha256.slice(0, 12)}…</span></div>
    </div>
    <div className="data-panel-toolbar ligand-table-toolbar">
      <label className="table-search"><span className="visually-hidden">Search ligand library</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search name, SMILES, or formula" /></label>
      <select aria-label="Filter ligands by status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as "all" | LigandBatchStatus)}>
        <option value="all">All statuses</option><option value="eligible">Eligible only</option><option value="excluded">Excluded only</option><option value="needs-decision">Needs decision only</option><option value="prepared">PDBQT ready only</option><option value="failed">Failed only</option>
      </select>
      <details className="column-menu"><summary><AppIcon name="layout" />Columns</summary><div>{optionalColumns.map((column) => <label key={column.key}><input type="checkbox" checked={visibleColumns.has(column.key)} onChange={() => toggleColumn(column.key)} />{column.label}</label>)}</div></details>
      <span className="visible-row-count">{rows.length} visible</span>
    </div>
    {checkedIds.size > 0 ? <div className="data-panel-toolbar ligand-bulk-toolbar">
      <span className="bulk-selection-count">{checkedIds.size} selected</span>
      <div className="bulk-actions" role="toolbar" aria-label="Bulk actions">
        <button type="button" disabled={bulkActionPending} onClick={() => runBulkAction(onBulkKeepLargestFragment)}>Keep largest fragment</button>
        <button type="button" disabled={bulkActionPending} onClick={() => runBulkAction(onBulkExclude)}>Exclude selected</button>
        <button type="button" className="link-action" disabled={bulkActionPending} onClick={() => setCheckedIds(new Set())}>Clear selection</button>
      </div>
    </div> : null}
    <div className="ligand-table-scroll">
      <table className="ligand-library-table">
        <thead><tr>
          <th className="row-check-cell"><input
            type="checkbox"
            aria-label={allVisibleChecked ? "Deselect all visible rows" : "Select all visible rows"}
            checked={allVisibleChecked}
            ref={(element) => { if (element) element.indeterminate = checkedVisibleCount > 0 && !allVisibleChecked; }}
            onChange={toggleAllVisible}
          /></th>
          <SortableHeader label="#" active={sortKey === "source"} ascending={sortAscending} onClick={() => changeSort("source")} />
          <SortableHeader label="Name" active={sortKey === "name"} ascending={sortAscending} onClick={() => changeSort("name")} />
          <th>Canonical isomeric SMILES</th>
          {visibleColumns.has("formula") ? <th>Formula</th> : null}
          {visibleColumns.has("mw") ? <SortableHeader label="MW (g/mol)" active={sortKey === "mw"} ascending={sortAscending} onClick={() => changeSort("mw")} /> : null}
          {visibleColumns.has("clogp") ? <th>cLogP</th> : null}
          {visibleColumns.has("qed") ? <SortableHeader label="QED" active={sortKey === "qed"} ascending={sortAscending} onClick={() => changeSort("qed")} /> : null}
          {visibleColumns.has("rules") ? <th>Rules</th> : null}
          {visibleColumns.has("alerts") ? <th>Alerts</th> : null}
          {visibleColumns.has("energy") ? <SortableHeader label="Final MMFF E (kcal/mol)" active={sortKey === "energy"} ascending={sortAscending} onClick={() => changeSort("energy")} /> : null}
          <SortableHeader label="Status" active={sortKey === "status"} ascending={sortAscending} onClick={() => changeSort("status")} />
        </tr></thead>
        <tbody>{rows.map(({ entry, ligandId, evaluation, result, status }) => {
          const ligand = entry.ligand;
          const descriptors = evaluation?.descriptors;
          if (!ligand || !ligandId) return <tr key={entry.record_index} className="failed-row"><td /><td>{entry.record_index + 1}</td><td><strong>Import failed</strong></td><td colSpan={2 + visibleColumns.size}>{entry.failure?.message ?? "Record could not be imported"}</td><td><StatusBadge status="failed" /></td></tr>;
          return <tr key={ligandId} className={`${selectedLigandId === ligandId ? "selected" : ""} ${evaluation?.disposition ?? ""}`} onClick={() => onSelect(ligandId)}>
            <td className="row-check-cell"><input
              type="checkbox"
              aria-label={`Select ${ligand.inspection.name} for a bulk action`}
              checked={checkedIds.has(ligandId)}
              onClick={(event) => event.stopPropagation()}
              onChange={() => toggleChecked(ligandId)}
            /></td>
            <td>{entry.record_index + 1}</td>
            <td><button type="button" className="ligand-row-select" aria-pressed={selectedLigandId === ligandId} onClick={() => onSelect(ligandId)}><span className="selection-radio" /><strong>{ligand.inspection.name}</strong></button></td>
            <td className="smiles-cell"><button type="button" aria-label={`Copy SMILES for ${ligand.inspection.name}`} title="Copy SMILES" onClick={(event) => { event.stopPropagation(); void copyText(evaluation?.canonical_isomeric_smiles ?? ligand.inspection.canonical_smiles ?? ""); }}>{evaluation?.canonical_isomeric_smiles ?? ligand.inspection.canonical_smiles ?? "—"}</button></td>
            {visibleColumns.has("formula") ? <td>{ligand.inspection.formula}</td> : null}
            {visibleColumns.has("mw") ? <td>{descriptors?.molecular_weight_g_mol.toFixed(2) ?? ligand.inspection.molecular_weight_g_mol?.toFixed(2) ?? "—"}</td> : null}
            {visibleColumns.has("clogp") ? <td>{descriptors?.clogp.toFixed(2) ?? "—"}</td> : null}
            {visibleColumns.has("qed") ? <td>{descriptors?.qed.toFixed(3) ?? "—"}</td> : null}
            {visibleColumns.has("rules") ? <td>{evaluation ? <RuleBadges evaluation={evaluation} /> : "—"}</td> : null}
            {visibleColumns.has("alerts") ? <td>{evaluation ? <AlertBadges evaluation={evaluation} preview={preview} /> : "—"}</td> : null}
            {visibleColumns.has("energy") ? <td>{formatEnergy(result)}</td> : null}
            <td><StatusBadge status={status} title={result?.error ?? evaluation?.reasons.join(", ")} /></td>
          </tr>;
        })}</tbody>
      </table>
      {!rows.length ? <div className="data-panel-empty">No molecules match the current search and status filter.</div> : null}
    </div>
  </section>;
}

function SortableHeader({ label, active, ascending, onClick }: { label: string; active: boolean; ascending: boolean; onClick: () => void }) {
  return <th><button type="button" className={active ? "active" : ""} onClick={onClick}>{label}<span aria-hidden="true">{active ? ascending ? "↑" : "↓" : "↕"}</span></button></th>;
}

function numericSortValue(row: { entry: LigandLibraryRecord["entries"][number]; evaluation?: LigandFilterEvaluation; result?: LigandBatchResult }, key: "mw" | "qed" | "energy"): number {
  if (key === "mw") return row.evaluation?.descriptors?.molecular_weight_g_mol ?? row.entry.ligand?.inspection.molecular_weight_g_mol ?? Number.POSITIVE_INFINITY;
  if (key === "qed") return row.evaluation?.descriptors?.qed ?? Number.POSITIVE_INFINITY;
  return finalEnergyOf(row.result) ?? Number.POSITIVE_INFINITY;
}

function finalEnergyOf(result: LigandBatchResult | undefined): number | null {
  return result?.finalEnergyKcalMol ?? result?.conformer?.minimization.final_energy_kcal_mol ?? null;
}

function formatEnergy(result: LigandBatchResult | undefined): string {
  const energy = finalEnergyOf(result);
  return energy === null ? "—" : energy.toFixed(3);
}

function RuleBadges({ evaluation }: { evaluation: LigandFilterEvaluation }) {
  const rules: [string, string, LigandRuleEvaluation | null][] = [["L", "Lipinski", evaluation.lipinski], ["V", "Veber", evaluation.veber], ["G", "Ghose", evaluation.ghose], ["M", "Muegge", evaluation.muegge]];
  return <span className="filter-rule-badges" aria-label={rules.map(([, name, rule]) => `${name}: ${rule?.passed ? "pass" : rule?.violations.join(", ")}`).join("; ")}>{rules.map(([label, name, rule]) => <span key={label} className={rule?.passed ? "pass" : "fail"} title={`${name}: ${rule?.violations.length ? rule.violations.join("; ") : "Pass"}`}>{label}{rule?.violations.length ? rule.violations.length : "✓"}</span>)}</span>;
}

function AlertBadges({ evaluation, preview }: { evaluation: LigandFilterEvaluation; preview: LigandLibraryFilterPreview | null }) {
  const duplicate = evaluation.duplicate_of_ligand_id ? <span className="filter-alert duplicate">Duplicate</span> : null;
  if (!evaluation.alerts.length) return duplicate ?? <span className="filter-alert clear">Clear</span>;
  const catalogs = [...new Set(evaluation.alerts.map((alert) => alert.catalog))].join(" + ");
  const policies = evaluation.alerts.map((alert) => alert.catalog === "PAINS" ? preview?.plan.pains_policy : preview?.plan.brenk_policy);
  const outcome = policies.includes("exclude") ? "excluded" : policies.includes("review") ? "review" : "recorded";
  return <span className="filter-alert-stack" aria-label={evaluation.alerts.map((alert) => `${alert.catalog}: ${alert.description}`).join("; ")}>{duplicate}<span className={`filter-alert ${outcome}`}>{catalogs} · {outcome}</span></span>;
}

function dispositionStatus(evaluation: LigandFilterEvaluation | undefined): LigandBatchStatus {
  if (!evaluation) return "needs-decision";
  if (evaluation.disposition === "needs_decision") return "needs-decision";
  return evaluation.disposition;
}

function StatusBadge({ status, title }: { status: LigandBatchStatus; title?: string }) {
  const label: Record<LigandBatchStatus, string> = { eligible: "Eligible", excluded: "Excluded", "needs-decision": "Needs decision", generating: "Processing", minimized: "Minimized", prepared: "PDBQT ready", nonconverged: "Not converged", failed: "Failed" };
  return <span className={`ligand-row-status ${status}`} aria-label={title ? `${label[status]}: ${title}` : label[status]} title={title}>{label[status]}</span>;
}

async function copyText(value: string) {
  if (!value || !navigator.clipboard) return;
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    // Clipboard access can be disabled in restricted WebViews; copying is optional.
  }
}
