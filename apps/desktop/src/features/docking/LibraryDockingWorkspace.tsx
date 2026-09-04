import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { ankoraApi, ApiError } from "../../api/client";
import type { WorkspaceActivity } from "../../app/activity";
import type {
  BindingSiteRecord,
  LigandLibraryDockingInput,
  ReceptorPreparationRecord,
  ToolsResponse,
  VinaBatchDockingParameters,
  VinaBatchDockingRecord,
  VinaBatchLigandResult,
  VinaBatchProgress,
} from "../../types/api";
import { MolecularViewer } from "../../viewer/MolecularViewer";
import { CampaignExportPanel } from "./CampaignExportPanel";
import { CampaignHistoryPanel, useCampaignHistory } from "./CampaignHistoryPanel";
import type { ViewerSource } from "../../viewer/adapter";
import { VinaSamplingGuidance } from "./VinaSamplingGuidance";
import {
  applyVinaSamplingProtocol,
  isVinaSamplingParameter,
  vinaSamplingProtocolLabel,
  VinaSamplingProtocolControl,
} from "./VinaSamplingProtocol";
import type { VinaSamplingProtocol } from "./VinaSamplingProtocol";

interface LibraryDockingWorkspaceProps {
  receptor: ReceptorPreparationRecord;
  bindingSite: BindingSiteRecord;
  libraryInput: LigandLibraryDockingInput;
  tools: ToolsResponse | null;
  onActivityChange?: (activity: WorkspaceActivity | null) => void;
  modeSwitch?: ReactNode;
}

const TERMINAL_STATUSES = new Set(["completed", "failed", "canceled"]);

type ResultSortKey =
  | "source_index"
  | "name"
  | "canonical_smiles"
  | "molecular_weight_g_mol"
  | "top_score"
  | "pose_count"
  | "status";

type SortDirection = "ascending" | "descending";

function defaultParameters(): VinaBatchDockingParameters {
  const logicalCores = typeof navigator === "undefined" ? 2 : navigator.hardwareConcurrency || 2;
  const totalCpuThreads = Math.max(1, logicalCores - 1);
  return {
    sampling_protocol: "screening",
    total_cpu_threads: totalCpuThreads,
    parallel_ligands: Math.min(64, totalCpuThreads),
    seed: 20260823,
    exhaustiveness: 8,
    num_modes: 9,
    min_rmsd_angstrom: 1,
    energy_range_kcal_mol: 3,
    timeout_minutes_per_ligand: 360,
  };
}

export function LibraryDockingWorkspace({
  receptor,
  bindingSite,
  libraryInput,
  tools,
  onActivityChange,
  modeSwitch,
}: LibraryDockingWorkspaceProps) {
  const [parameters, setParameters] = useState<VinaBatchDockingParameters>(defaultParameters);
  const [acknowledged, setAcknowledged] = useState(false);
  const [batch, setBatch] = useState<VinaBatchDockingRecord | null>(null);
  const [selectedLigandId, setSelectedLigandId] = useState<string | null>(null);
  const [selectedMode, setSelectedMode] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const [opening, setOpening] = useState(false);
  const startInFlight = useRef(false);
  const revisionRef = useRef(0);
  const displayOutput = receptor.outputs.find(
    (item) => item.artifact_id === receptor.display_output_artifact_id,
  );
  const receptorPdbqt = receptor.outputs.find((item) => item.stage === "pdbqt");
  const active = Boolean(batch && !TERMINAL_STATUSES.has(batch.status));
  const controlsLocked = active || starting || restoring;
  const selectedEntry = batch?.entries.find((entry) => entry.ligand_id === selectedLigandId) ?? null;
  const selectedPose = selectedEntry?.poses.find((pose) => pose.mode === selectedMode) ?? null;
  const preparedCount = Math.min(
    libraryInput.prepared_count,
    libraryInput.selected_count,
  );
  const unavailableCount = libraryInput.selected_count - preparedCount;
  const ready = Boolean(
    tools?.vina.available
    && tools.vina.version === "1.2.7"
    && receptorPdbqt
    && preparedCount > 0,
  );
  const requestedWorkers = Math.min(
    parameters.parallel_ligands,
    Math.max(1, preparedCount),
  );
  const requestedThreadsPerLigand = Math.max(
    1,
    Math.floor(parameters.total_cpu_threads / requestedWorkers),
  );
  const runningCount = batch?.entries.filter((entry) => entry.status === "running").length ?? 0;
  const queuedCount = batch?.entries.filter((entry) => entry.status === "queued").length ?? 0;
  const progressPercent = batch
    ? Math.round(100 * batch.completed_count / batch.selected_count)
    : 0;
  const recentFinished = useMemo(
    () => (batch?.entries ?? [])
      .filter((entry) => entry.status === "completed" || entry.status === "failed")
      .sort((left, right) => {
        const timeOrder = (right.completed_at ?? "").localeCompare(left.completed_at ?? "");
        return timeOrder || right.source_index - left.source_index;
      })
      .slice(0, 6),
    [batch],
  );
  const bestEntry = useMemo(() => findBestEntry(batch?.entries ?? []), [batch]);

  const viewerSources = useMemo<ViewerSource[]>(() => {
    const sources: ViewerSource[] = [];
    if (displayOutput?.format === "pdb") {
      sources.push({
        id: displayOutput.artifact_id,
        url: ankoraApi.receptorOutputUrl(displayOutput.content_url),
        format: "pdb",
        label: `Prepared receptor · ${displayOutput.filename}`,
      });
    }
    if (selectedPose && selectedEntry) {
      sources.push({
        id: selectedPose.artifact.artifact_id,
        url: ankoraApi.dockingPoseUrl(selectedPose.artifact.content_url),
        format: "pdb",
        label: `${selectedEntry.name} · Vina pose ${selectedPose.mode}`,
      });
    }
    return sources;
  }, [displayOutput, selectedEntry, selectedPose]);

  const history = useCampaignHistory({
    engine: "autodock_vina",
    receptorId: receptor.receptor_id,
    bindingSiteId: bindingSite.binding_site_id,
  });

  useEffect(() => {
    let disposed = false;
    setRestoring(true);
    setError(null);
    void ankoraApi.latestDockingBatch(
      libraryInput.library_id,
      receptor.receptor_id,
      bindingSite.binding_site_id,
    ).then((restored) => {
      if (disposed) return;
      revisionRef.current = restored.revision;
      setBatch(restored);
      const first = restored.entries.find((entry) => entry.poses.length > 0);
      if (first) {
        setSelectedLigandId(first.ligand_id);
        setSelectedMode(first.poses[0].mode);
      }
    }).catch((reason: unknown) => {
      if (!disposed && !(reason instanceof ApiError && reason.status === 404)) {
        setError(reason instanceof Error ? reason.message : "Previous campaign history could not be restored.");
      }
    }).finally(() => {
      if (!disposed) setRestoring(false);
    });
    return () => { disposed = true; };
  }, [bindingSite.binding_site_id, libraryInput.library_id, receptor.receptor_id]);

  useEffect(() => {
    revisionRef.current = batch?.revision ?? 0;
  }, [batch?.batch_id, batch?.revision]);

  useEffect(() => {
    if (!batch || TERMINAL_STATUSES.has(batch.status)) return;
    let disposed = false;
    let refreshing = false;
    const timer = window.setInterval(() => {
      if (refreshing) return;
      refreshing = true;
      void ankoraApi.getDockingBatchProgress(batch.batch_id, revisionRef.current)
        .then((progress) => {
          if (disposed) return;
          revisionRef.current = progress.revision;
          setBatch((current) => current?.batch_id === progress.batch_id
            ? mergeBatchProgress(current, progress)
            : current);
          if (selectedLigandId === null) {
            const first = progress.entries.find((entry) => entry.poses.length > 0);
            if (first) {
              setSelectedLigandId(first.ligand_id);
              setSelectedMode(first.poses[0].mode);
            }
          } else if (selectedMode === null) {
            const selected = progress.entries.find(
              (entry) => entry.ligand_id === selectedLigandId,
            );
            if (selected?.poses.length) {
              setSelectedMode(selected.poses[0].mode);
            }
          }
        })
        .catch((reason: unknown) => {
          if (!disposed) {
            setError(reason instanceof Error ? reason.message : "Library docking status could not be refreshed.");
          }
        }).finally(() => {
          refreshing = false;
        });
    }, 750);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [batch?.batch_id, batch?.status, selectedLigandId, selectedMode]);

  const settled = batch ? TERMINAL_STATUSES.has(batch.status) : false;
  useEffect(() => {
    if (settled) void history.reload();
  }, [settled, history.reload]);

  useEffect(() => {
    if (!onActivityChange) return;
    if (!batch || TERMINAL_STATUSES.has(batch.status)) {
      onActivityChange(null);
      return;
    }
    onActivityChange({
      title: "AutoDock Vina library",
      detail: `${batch.completed_count} of ${batch.selected_count} ligands finished`,
      current: batch.completed_count,
      total: batch.selected_count,
      workers: batch.worker_count,
    });
  }, [batch, onActivityChange]);

  async function openCampaign(batchId: string) {
    setOpening(true);
    setError(null);
    try {
      const record = await ankoraApi.getDockingBatch(batchId);
      revisionRef.current = record.revision;
      setBatch(record);
      const first = record.entries.find((entry) => entry.poses.length > 0);
      setSelectedLigandId(first?.ligand_id ?? null);
      setSelectedMode(first?.poses[0].mode ?? null);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "That campaign could not be opened.");
    } finally {
      setOpening(false);
    }
  }

  function updateParameter(
    name: Exclude<keyof VinaBatchDockingParameters, "sampling_protocol">,
    value: number,
  ) {
    setAcknowledged(false);
    setParameters((current) => {
      const next = {
        ...current,
        [name]: value,
        ...(isVinaSamplingParameter(name) ? { sampling_protocol: "custom" as const } : {}),
      };
      if (name === "total_cpu_threads") {
        next.parallel_ligands = Math.min(next.parallel_ligands, Math.max(1, value));
      }
      return next;
    });
  }

  function selectSamplingProtocol(protocol: VinaSamplingProtocol) {
    setAcknowledged(false);
    setParameters((current) => applyVinaSamplingProtocol(current, protocol));
  }

  async function startBatch() {
    if (!ready || !acknowledged || startInFlight.current || controlsLocked) return;
    startInFlight.current = true;
    setStarting(true);
    setError(null);
    setSelectedLigandId(null);
    setSelectedMode(null);
    try {
      const next = await ankoraApi.startVinaDockingBatch({
        receptor_id: receptor.receptor_id,
        binding_site_id: bindingSite.binding_site_id,
        library_id: libraryInput.library_id,
        filter_run_id: libraryInput.filter_run_id,
        parameters,
        acknowledge_inputs_and_scoring: acknowledged,
      });
      revisionRef.current = next.revision;
      setBatch(next);
      void history.reload();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "The Vina library batch could not be started.");
    } finally {
      startInFlight.current = false;
      setStarting(false);
    }
  }

  async function cancelBatch() {
    if (!batch) return;
    try {
      await ankoraApi.cancelDockingBatch(batch.batch_id);
      setBatch((current) => current ? { ...current, status: "cancel_requested" } : current);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "The docking batch could not be canceled.");
    }
  }

  function selectEntry(entry: VinaBatchLigandResult) {
    setSelectedLigandId(entry.ligand_id);
    setSelectedMode(entry.poses[0]?.mode ?? null);
  }

  return <>
    <section className="workspace docking-workspace" aria-label="Virtual-screening docking workspace">
      <div className="workspace-heading">
        <div><span className="eyebrow">05 / Docking</span><h2>Dock the complete prepared screening library</h2></div>
        <div className="workspace-actions">
          {modeSwitch}
          <span className="read-only-badge">M5 · AutoDock Vina 1.2.7</span>
        </div>
      </div>
      {starting ? <div className="operation-progress" role="progressbar" aria-label="Creating AutoDock Vina campaign"><span /><p>Creating the virtual-screening campaign…</p></div> : null}
      {batch ? <div className="operation-progress" role="progressbar" aria-label="AutoDock Vina library progress" aria-valuemin={0} aria-valuemax={batch.selected_count} aria-valuenow={batch.completed_count}><span className="determinate" style={{ width: `${progressPercent}%` }} /><p>{batch.completed_count} / {batch.selected_count} completed · {runningCount} running · {queuedCount} queued · {batch.succeeded_count} succeeded · {batch.failed_count} failed</p></div> : null}
      {error ? <div className="structure-error" role="alert">{error}</div> : null}
      {batch?.failure ? <div className="structure-error" role="alert"><strong>{batch.failure.message}</strong> <span>{batch.failure.code}</span></div> : null}
      {bestEntry ? <button type="button" className="best-current-result" onClick={() => selectEntry(bestEntry)}><span><small>Most favorable current Vina score</small><strong>#{bestEntry.source_index + 1} · {bestEntry.name}</strong></span><b>{bestEntry.poses[0].affinity_kcal_mol.toFixed(3)} <small>kcal/mol</small></b></button> : null}
      {viewerSources.length ? <MolecularViewer sources={viewerSources} selection={null} dockingBox={bindingSite.box} /> : <div className="viewer-placeholder ligand-placeholder"><div className="viewer-message"><div className="molecule-glyph">⬚</div><h3>Prepared receptor unavailable</h3></div></div>}
      {batch ? <LibraryResults batch={batch} selectedLigandId={selectedLigandId} selectedMode={selectedMode} onSelect={selectEntry} onSelectPose={(entry, mode) => { setSelectedLigandId(entry.ligand_id); setSelectedMode(mode); }} /> : null}
    </section>
    <aside className="inspector docking-inspector" aria-label="Virtual-screening docking setup inspector">
      <div className="inspector-heading"><span className="section-label">Docking campaign</span><h2>Virtual screening</h2><p className="inspector-subtitle">Every molecule comes from one immutable applied selection manifest.</p></div>
      {batch ? <CampaignMonitor batch={batch} runningCount={runningCount} queuedCount={queuedCount} progressPercent={progressPercent} recentFinished={recentFinished} selectedLigandId={selectedLigandId} onSelect={selectEntry} /> : restoring ? <div className="campaign-live-panel"><strong>Checking campaign history…</strong><small>Ankora will reconnect to an existing screening without launching another one.</small></div> : null}
      <section className="receptor-section">
        <div className="filter-heading"><span>1 · Scientific inputs</span></div>
        <InputState ready={Boolean(receptorPdbqt)} label="Receptor PDBQT" detail={receptorPdbqt ? `${receptorPdbqt.filename} · ${receptorPdbqt.sha256.slice(0, 12)}…` : "Return to Receptor and generate PDBQT."} />
        <InputState ready label="Binding site" detail={`${bindingSite.box.size_x.toFixed(1)} × ${bindingSite.box.size_y.toFixed(1)} × ${bindingSite.box.size_z.toFixed(1)} Å`} />
        <InputState ready={preparedCount > 0} label="Applied library selection" detail={`${preparedCount} / ${libraryInput.selected_count} selected molecules prepared · ${libraryInput.library_name}`} />
        {unavailableCount > 0 ? <div className="protonation-blocker"><strong>{unavailableCount} selected {unavailableCount === 1 ? "molecule is" : "molecules are"} not docking-ready</strong><small>The complete manifest remains in the campaign. Ready molecules will run; every unavailable molecule will be retained as an explicit preflight failure.</small></div> : null}
        <p className="field-note">Manifest SHA-256 · {libraryInput.selection_manifest_sha256.slice(0, 16)}…</p>
      </section>
      <section className="receptor-section">
        <div className="filter-heading"><span>2 · Engine & resources</span><small>{tools?.vina.available ? tools.vina.version : "Unavailable"}</small></div>
        <div className={tools?.vina.available ? "state-resolved-note" : "protonation-blocker"}><strong>AutoDock Vina 1.2.7</strong><small>{tools?.vina.available ? tools.vina.path : "Install or configure the official Windows executable."}</small></div>
        <VinaSamplingProtocolControl
          protocol={parameters.sampling_protocol ?? "custom"}
          disabled={controlsLocked}
          onChange={selectSamplingProtocol}
        />
        <div className="docking-parameter-grid">
          <NumberField label="Total CPU threads" value={parameters.total_cpu_threads} min={1} max={256} disabled={controlsLocked} onChange={(value) => updateParameter("total_cpu_threads", value)} />
          <NumberField label="Concurrent ligands" value={parameters.parallel_ligands} min={1} max={Math.min(64, parameters.total_cpu_threads)} disabled={controlsLocked} onChange={(value) => updateParameter("parallel_ligands", value)} />
          <NumberField label="Seed" value={parameters.seed} min={1} max={2147483647} disabled={controlsLocked} onChange={(value) => updateParameter("seed", value)} />
          <NumberField label="Exhaustiveness" value={parameters.exhaustiveness} min={1} max={128} disabled={controlsLocked} onChange={(value) => updateParameter("exhaustiveness", value)} />
          <NumberField label="Maximum poses" value={parameters.num_modes} min={1} max={100} disabled={controlsLocked} onChange={(value) => updateParameter("num_modes", value)} />
          <NumberField label="Minimum RMSD (Å)" value={parameters.min_rmsd_angstrom} min={0} max={20} step={0.1} disabled={controlsLocked} onChange={(value) => updateParameter("min_rmsd_angstrom", value)} />
          <NumberField label="Energy range (kcal/mol)" value={parameters.energy_range_kcal_mol} min={0} max={100} step={0.5} disabled={controlsLocked} onChange={(value) => updateParameter("energy_range_kcal_mol", value)} />
          <NumberField label="Timeout / ligand (min)" value={parameters.timeout_minutes_per_ligand} min={1} max={2880} disabled={controlsLocked} onChange={(value) => updateParameter("timeout_minutes_per_ligand", value)} />
        </div>
        <VinaSamplingGuidance box={bindingSite.box} exhaustiveness={parameters.exhaustiveness} showWithinBoundary />
        <div className="state-resolved-note"><strong>Throughput-first CPU budget</strong><small>{requestedWorkers} concurrent Vina processes × {requestedThreadsPerLigand} {requestedThreadsPerLigand === 1 ? "thread" : "threads"} = {requestedWorkers * requestedThreadsPerLigand} of {parameters.total_cpu_threads} allocated threads. The default gives each library molecule its own single-thread process because Vina's inner parallelism is limited by exhaustiveness.</small></div>
      </section>
      <section className="receptor-section">
        <div className="filter-heading"><span>3 · Confirm & run</span>{batch ? <small>{batch.status.replaceAll("_", " ")}</small> : null}</div>
        <label className="docking-acknowledgement"><input type="checkbox" checked={acknowledged} disabled={controlsLocked} onChange={(event) => setAcknowledged(event.target.checked)} /><span><strong>Dock this exact applied selection</strong><small>I understand that Vina scores rank poses computationally and are not experimental binding affinities. A failure in one molecule will be retained without aborting its neighbors.</small></span></label>
        {active ? <button type="button" className="danger-action docking-primary-action" onClick={() => void cancelBatch()} disabled={batch?.status === "cancel_requested"}>Cancel library docking</button> : <button type="button" className="primary-action docking-primary-action" onClick={() => void startBatch()} disabled={!ready || !acknowledged || controlsLocked}>{restoring ? "Checking previous campaign…" : starting ? "Creating campaign…" : `Dock ${preparedCount} prepared ligands`}</button>}
        {unavailableCount > 0 ? <p className="field-note">The campaign will still account for all {libraryInput.selected_count} manifest entries: {preparedCount} Vina executions and {unavailableCount} explicit preflight {unavailableCount === 1 ? "failure" : "failures"}.</p> : null}
      </section>
      <CampaignExportPanel
        sourceKind="vina_batch"
        sourceId={batch?.batch_id ?? null}
        ready={Boolean(batch && TERMINAL_STATUSES.has(batch.status))}
      />
      <CampaignHistoryPanel
        engine="autodock_vina"
        campaigns={history.campaigns}
        loading={history.loading}
        error={history.error}
        activeBatchId={batch?.batch_id ?? null}
        currentFilterRunId={libraryInput.filter_run_id}
        opening={opening || active || starting}
        onOpen={(batchId) => void openCampaign(batchId)}
        onRefresh={() => void history.reload()}
      />
      {batch ? <section className="receptor-section">
        <div className="filter-heading"><span>4 · Campaign evidence</span><small>{batch.batch_id.slice(0, 8)}…</small></div>
        <dl className="docking-evidence"><div><dt>Purpose</dt><dd>{vinaSamplingProtocolLabel(batch.request.parameters.sampling_protocol)}</dd></div><div><dt>Completed</dt><dd>{batch.completed_count} / {batch.selected_count}</dd></div><div><dt>Succeeded</dt><dd>{batch.succeeded_count}</dd></div><div><dt>Failed</dt><dd>{batch.failed_count}</dd></div><div><dt>Resources</dt><dd>{batch.worker_count} × {batch.threads_per_ligand} CPU</dd></div></dl>
        {selectedEntry ? <details className="technical-details" open={Boolean(selectedEntry.failure)}><summary>Selected molecule evidence</summary>{selectedEntry.failure ? <p>{selectedEntry.failure.code} · {selectedEntry.failure.message}</p> : null}<pre>{selectedEntry.command.join(" ") || "No command was launched."}</pre>{selectedEntry.execution ? <><h4>stdout</h4><pre>{selectedEntry.execution.stdout || "(empty)"}</pre><h4>stderr</h4><pre>{selectedEntry.execution.stderr || "(empty)"}</pre></> : null}</details> : <p className="field-note">Select a library row to inspect its exact command and raw evidence.</p>}
      </section> : null}
    </aside>
  </>;
}

function mergeBatchProgress(
  current: VinaBatchDockingRecord,
  progress: VinaBatchProgress,
): VinaBatchDockingRecord {
  const changed = new Map(progress.entries.map((entry) => [entry.ligand_id, entry]));
  return {
    ...current,
    status: progress.status,
    phase: progress.phase,
    revision: progress.revision,
    started_at: progress.started_at,
    completed_at: progress.completed_at,
    selected_count: progress.selected_count,
    worker_count: progress.worker_count,
    threads_per_ligand: progress.threads_per_ligand,
    completed_count: progress.completed_count,
    succeeded_count: progress.succeeded_count,
    failed_count: progress.failed_count,
    canceled_count: progress.canceled_count,
    entries: current.entries.map((entry) => changed.get(entry.ligand_id) ?? entry),
    failure: progress.failure,
    provenance: progress.provenance,
  };
}

function CampaignMonitor({
  batch,
  runningCount,
  queuedCount,
  progressPercent,
  recentFinished,
  selectedLigandId,
  onSelect,
}: {
  batch: VinaBatchDockingRecord;
  runningCount: number;
  queuedCount: number;
  progressPercent: number;
  recentFinished: VinaBatchLigandResult[];
  selectedLigandId: string | null;
  onSelect: (entry: VinaBatchLigandResult) => void;
}) {
  return <section className="campaign-live-panel" aria-live="polite">
    <div className="campaign-live-heading">
      <div><span className="eyebrow">Live progress</span><strong>{batch.status.replaceAll("_", " ")}</strong></div>
      <b>{progressPercent}%</b>
    </div>
    <div className="campaign-live-track" role="progressbar" aria-label="Completed screening molecules" aria-valuemin={0} aria-valuemax={batch.selected_count} aria-valuenow={batch.completed_count}>
      <span style={{ width: `${progressPercent}%` }} />
    </div>
    <dl className="campaign-live-stats">
      <div><dt>Completed</dt><dd>{batch.completed_count}/{batch.selected_count}</dd></div>
      <div><dt>Running</dt><dd>{runningCount}</dd></div>
      <div><dt>Queued</dt><dd>{queuedCount}</dd></div>
      <div><dt>Failed</dt><dd>{batch.failed_count}</dd></div>
    </dl>
    <div className="campaign-recent">
      <span className="field-label">Most recently finished</span>
      {recentFinished.length ? recentFinished.map((entry) => <button
        type="button"
        key={entry.ligand_id}
        className={entry.ligand_id === selectedLigandId ? "selected" : ""}
        onClick={() => onSelect(entry)}
      >
        <span><b>#{entry.source_index + 1}</b> {entry.name}</span>
        <small>{entry.failure ? entry.failure.code : `${entry.poses[0]?.affinity_kcal_mol.toFixed(3) ?? "—"} kcal/mol`}</small>
      </button>) : <small>{runningCount > 0 ? `Waiting for the first Vina result · ${runningCount} molecules active.` : "No molecule has finished yet."}</small>}
    </div>
  </section>;
}

function LibraryResults({ batch, selectedLigandId, selectedMode, onSelect, onSelectPose }: {
  batch: VinaBatchDockingRecord;
  selectedLigandId: string | null;
  selectedMode: number | null;
  onSelect: (entry: VinaBatchLigandResult) => void;
  onSelectPose: (entry: VinaBatchLigandResult, mode: number) => void;
}) {
  const [sortKey, setSortKey] = useState<ResultSortKey>("top_score");
  const [sortDirection, setSortDirection] = useState<SortDirection>("ascending");
  const [expandedLigandId, setExpandedLigandId] = useState<string | null>(null);
  const horizontalScrollRef = useRef<HTMLDivElement>(null);
  const tableScrollRef = useRef<HTMLDivElement>(null);
  const bestEntry = findBestEntry(batch.entries);
  const sortedEntries = useMemo(
    () => [...batch.entries].sort((left, right) => compareEntries(left, right, sortKey, sortDirection)),
    [batch.entries, sortDirection, sortKey],
  );

  function changeSort(nextKey: ResultSortKey) {
    if (nextKey === sortKey) {
      setSortDirection((current) => current === "ascending" ? "descending" : "ascending");
      return;
    }
    setSortKey(nextKey);
    setSortDirection("ascending");
  }

  function toggleEntry(entry: VinaBatchLigandResult) {
    onSelect(entry);
    setExpandedLigandId((current) => current === entry.ligand_id ? null : entry.ligand_id);
  }

  return <section className="docking-results library-docking-results" aria-label="Virtual-screening docking results">
    <div className="docking-results-heading"><div><span className="eyebrow">Compound results</span><h3>AutoDock Vina library results</h3></div><p>{bestEntry ? <><strong>{bestEntry.name}</strong> currently ranks first at <strong>{bestEntry.poses[0].affinity_kcal_mol.toFixed(3)} kcal/mol</strong>. </> : null}Lower Vina scores rank more favorably only within this recorded campaign. MMFF ΔE is geometry QC and is not used for ranking.</p></div>
    <div className="docking-results-horizontal-scroll" ref={horizontalScrollRef} tabIndex={0} aria-label="Horizontal compound results scroll" onScroll={(event) => syncHorizontalScroll(event.currentTarget, tableScrollRef.current)}><div /></div>
    <div className="docking-results-scroll" ref={tableScrollRef} tabIndex={0} aria-label="Scrollable compound results table" onScroll={(event) => syncHorizontalScroll(event.currentTarget, horizontalScrollRef.current)}><table><thead><tr>
      <SortHeader label="#" sortKey="source_index" activeKey={sortKey} direction={sortDirection} onSort={changeSort} />
      <SortHeader label="Name" sortKey="name" activeKey={sortKey} direction={sortDirection} onSort={changeSort} />
      <SortHeader label="Canonical isomeric SMILES" sortKey="canonical_smiles" activeKey={sortKey} direction={sortDirection} onSort={changeSort} />
      <SortHeader label="MW (g/mol)" sortKey="molecular_weight_g_mol" activeKey={sortKey} direction={sortDirection} onSort={changeSort} />
      <th title="Final minus initial MMFF energy for this molecule. Internal geometry QC only; do not compare compounds.">MMFF ΔE (kcal/mol) · QC</th>
      <SortHeader label="Top Vina score (kcal/mol)" sortKey="top_score" activeKey={sortKey} direction={sortDirection} onSort={changeSort} />
      <SortHeader label="Poses" sortKey="pose_count" activeKey={sortKey} direction={sortDirection} onSort={changeSort} />
      <SortHeader label="Status" sortKey="status" activeKey={sortKey} direction={sortDirection} onSort={changeSort} />
    </tr></thead><tbody>{sortedEntries.map((entry) => {
      const topScore = entry.poses[0]?.affinity_kcal_mol;
      const expanded = entry.ligand_id === expandedLigandId;
      const classes = [entry.ligand_id === selectedLigandId ? "selected" : "", entry.ligand_id === bestEntry?.ligand_id ? "best-ranked" : ""].filter(Boolean).join(" ");
      return <Fragment key={entry.ligand_id}><tr className={classes} onClick={() => toggleEntry(entry)} aria-expanded={expanded}><td>{entry.source_index + 1}</td><td><button type="button" className="compound-expand" aria-expanded={expanded} onClick={(event) => { event.stopPropagation(); toggleEntry(entry); }}><span aria-hidden="true">{expanded ? "▾" : "▸"}</span>{entry.name}{entry.ligand_id === bestEntry?.ligand_id ? <small>Current best</small> : null}</button></td><td><code title={entry.canonical_smiles ?? undefined}>{entry.canonical_smiles ?? "—"}</code></td><td>{entry.molecular_weight_g_mol?.toFixed(2) ?? "—"}</td><td><span title={preparationDeltaEvidence(entry)}>{formatPreparationDelta(entry)}</span></td><td>{topScore?.toFixed(3) ?? "—"}</td><td>{entry.poses.length}</td><td><span className={`docking-status ${entry.status}`}>{entry.status.replaceAll("_", " ")}</span>{entry.failure ? <small title={entry.failure.message}>{entry.failure.code}</small> : null}</td></tr>
        {expanded ? <tr className="pose-expansion"><td colSpan={8}>{entry.poses.length ? <div className="compound-poses"><div className="compound-poses-heading"><strong>{entry.name} · ranked poses</strong><small>Click a pose to display it in the 3D viewer.</small></div><table><thead><tr><th>Pose</th><th>Vina score (kcal/mol)</th><th>RMSD lower bound (Å)</th><th>RMSD upper bound (Å)</th><th>Artifact SHA-256</th></tr></thead><tbody>{entry.poses.map((pose) => <tr key={pose.mode} className={entry.ligand_id === selectedLigandId && pose.mode === selectedMode ? "selected" : ""}><td><button type="button" className="pose-select" aria-pressed={entry.ligand_id === selectedLigandId && pose.mode === selectedMode} onClick={(event) => { event.stopPropagation(); onSelectPose(entry, pose.mode); }}>Pose {pose.mode}</button></td><td>{pose.affinity_kcal_mol.toFixed(3)}</td><td>{pose.rmsd_lower_bound_angstrom.toFixed(3)}</td><td>{pose.rmsd_upper_bound_angstrom.toFixed(3)}</td><td><code>{pose.artifact.sha256.slice(0, 16)}…</code></td></tr>)}</tbody></table></div> : <p className="field-note">{entry.failure ? `${entry.failure.code} · ${entry.failure.message}` : "No poses are available while this molecule is still queued or running."}</p>}</td></tr> : null}</Fragment>;
    })}</tbody></table></div>
  </section>;
}

function SortHeader({ label, sortKey, activeKey, direction, onSort }: { label: string; sortKey: ResultSortKey; activeKey: ResultSortKey; direction: SortDirection; onSort: (key: ResultSortKey) => void }) {
  const active = sortKey === activeKey;
  return <th aria-sort={active ? direction : "none"}><button type="button" className="result-sort" onClick={() => onSort(sortKey)}>{label}<span aria-hidden="true">{active ? direction === "ascending" ? "↑" : "↓" : "↕"}</span></button></th>;
}

function syncHorizontalScroll(source: HTMLDivElement, target: HTMLDivElement | null) {
  if (target && Math.abs(target.scrollLeft - source.scrollLeft) > 0.5) target.scrollLeft = source.scrollLeft;
}

function findBestEntry(entries: VinaBatchLigandResult[]): VinaBatchLigandResult | null {
  return entries.reduce<VinaBatchLigandResult | null>((best, entry) => {
    const score = entry.poses[0]?.affinity_kcal_mol;
    if (score === undefined) return best;
    const bestScore = best?.poses[0]?.affinity_kcal_mol;
    const bestSourceIndex = best?.source_index ?? Number.MAX_SAFE_INTEGER;
    if (bestScore === undefined || score < bestScore || (score === bestScore && entry.source_index < bestSourceIndex)) return entry;
    return best;
  }, null);
}

function compareEntries(left: VinaBatchLigandResult, right: VinaBatchLigandResult, key: ResultSortKey, direction: SortDirection): number {
  const leftValue = resultSortValue(left, key);
  const rightValue = resultSortValue(right, key);
  if (leftValue === null && rightValue === null) return left.source_index - right.source_index;
  if (leftValue === null) return 1;
  if (rightValue === null) return -1;
  const order = typeof leftValue === "number" && typeof rightValue === "number"
    ? leftValue - rightValue
    : String(leftValue).localeCompare(String(rightValue), undefined, { numeric: true, sensitivity: "base" });
  return (direction === "ascending" ? order : -order) || left.source_index - right.source_index;
}

function resultSortValue(entry: VinaBatchLigandResult, key: ResultSortKey): number | string | null {
  if (key === "source_index") return entry.source_index;
  if (key === "name") return entry.name;
  if (key === "canonical_smiles") return entry.canonical_smiles;
  if (key === "molecular_weight_g_mol") return entry.molecular_weight_g_mol;
  if (key === "top_score") return entry.poses[0]?.affinity_kcal_mol ?? null;
  if (key === "pose_count") return entry.poses.length;
  return entry.status;
}

function preparationEnergyPair(entry: VinaBatchLigandResult): { initial: number; final: number } | null {
  return entry.preparation_initial_energy_kcal_mol == null || entry.preparation_energy_kcal_mol == null
    ? null
    : { initial: entry.preparation_initial_energy_kcal_mol, final: entry.preparation_energy_kcal_mol };
}

function formatPreparationDelta(entry: VinaBatchLigandResult): string {
  const pair = preparationEnergyPair(entry);
  if (!pair) return "—";
  const delta = pair.final - pair.initial;
  return `${delta > 0 ? "+" : ""}${delta.toFixed(3)}`;
}

function preparationDeltaEvidence(entry: VinaBatchLigandResult): string {
  const pair = preparationEnergyPair(entry);
  return pair
    ? `Initial ${pair.initial.toFixed(3)} → final ${pair.final.toFixed(3)} kcal/mol. Internal geometry QC only; do not compare compounds.`
    : "Initial MMFF energy was not recorded for this historical campaign, so ΔE cannot be calculated.";
}

function InputState({ ready, label, detail }: { ready: boolean; label: string; detail: string }) {
  return <div className={ready ? "state-resolved-note" : "protonation-blocker"}><strong>{label}</strong><small>{detail}</small></div>;
}

function NumberField({ label, value, min, max, step = 1, disabled, onChange }: { label: string; value: number; min: number; max: number; step?: number; disabled: boolean; onChange: (value: number) => void }) {
  return <label className="numeric-field"><span className="field-label">{label}</span><input type="number" aria-label={label} value={value} min={min} max={max} step={step} disabled={disabled} onChange={(event) => onChange(Number(event.target.value))} /></label>;
}
