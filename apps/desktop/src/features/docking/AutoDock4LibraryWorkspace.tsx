import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { ankoraApi } from "../../api/client";
import type { WorkspaceActivity } from "../../app/activity";
import type {
  AutoDock4BatchParameters,
  AutoDockBackend,
  AutoDockGpuBatchParameters,
  AutoGridMapJobRecord,
  BindingSiteRecord,
  LigandLibraryDockingInput,
  ReceptorPreparationRecord,
  ToolsResponse,
} from "../../types/api";
import { MolecularViewer } from "../../viewer/MolecularViewer";
import { CampaignExportPanel } from "./CampaignExportPanel";
import { CampaignHistoryPanel, useCampaignHistory } from "./CampaignHistoryPanel";
import {
  AUTODOCK_BACKENDS,
  bindingFor,
  isGpuParameters,
} from "./autodockBackend";
import type {
  BackendParameters,
  CampaignEntryView,
  CampaignView,
} from "./autodockBackend";
import type { ViewerSource } from "../../viewer/adapter";

interface AutoDock4LibraryWorkspaceProps {
  receptor: ReceptorPreparationRecord;
  bindingSite: BindingSiteRecord;
  libraryInput: LigandLibraryDockingInput;
  tools: ToolsResponse | null;
  onActivityChange?: (activity: WorkspaceActivity | null) => void;
  modeSwitch?: ReactNode;
}

const TERMINAL = new Set(["completed", "failed", "canceled"]);

type EntrySortKey = "source_index" | "name" | "best_energy" | "cluster_count" | "status";
type SortDirection = "ascending" | "descending";

function defaultParameters(backend: AutoDockBackend): BackendParameters {
  const base = bindingFor(backend).defaultParameters();
  if (backend !== "autodock4_cpu") return base;
  // AutoDock4 4.2.6 is single-threaded, so one worker is one core and this
  // pool is the entire CPU budget. The GPU has no such setting: a campaign is
  // one process, and two on one device measured slower than one.
  const logicalCores =
    typeof navigator === "undefined" ? 2 : navigator.hardwareConcurrency || 2;
  return {
    ...(base as AutoDock4BatchParameters),
    parallel_ligands: Math.max(1, Math.min(64, logicalCores - 1)),
  };
}

export function AutoDock4LibraryWorkspace({
  receptor,
  bindingSite,
  libraryInput,
  tools,
  onActivityChange,
  modeSwitch,
}: AutoDock4LibraryWorkspaceProps) {
  const [backend, setBackend] = useState<AutoDockBackend>("autodock4_cpu");
  const [parameters, setParameters] = useState<BackendParameters>(() =>
    defaultParameters("autodock4_cpu"),
  );
  const [acknowledged, setAcknowledged] = useState(false);
  const [mapJob, setMapJob] = useState<AutoGridMapJobRecord | null>(null);
  const [batch, setBatch] = useState<CampaignView | null>(null);
  const [selectedLigandId, setSelectedLigandId] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<number | null>(null);
  const [expandedLigandId, setExpandedLigandId] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<EntrySortKey>("best_energy");
  const [sortDirection, setSortDirection] = useState<SortDirection>("ascending");
  const [error, setError] = useState<string | null>(null);
  const [restoring, setRestoring] = useState(true);
  const [opening, setOpening] = useState(false);
  const revisionRef = useRef(0);

  const displayOutput = receptor.outputs.find(
    (item) => item.artifact_id === receptor.display_output_artifact_id,
  );
  const receptorPdbqt = receptor.outputs.find((item) => item.stage === "pdbqt");
  const mapsBusy = Boolean(mapJob && !TERMINAL.has(mapJob.status));
  const batchBusy = Boolean(batch && !TERMINAL.has(batch.status));
  // Either freshly generated, or the one the restored campaign already used:
  // same receptor, site and selection means the same maps.
  const mapSetId = mapJob?.status === "completed"
    ? mapJob.map_set_id
    : batch?.map_set_id ?? null;
  const toolsReady = Boolean(tools?.autogrid4.available && tools.autodock4.available);
  const selectedEntry = batch?.entries.find((e) => e.ligand_id === selectedLigandId) ?? null;
  const selectedPose = selectedEntry?.runs.find((r) => r.run === selectedRun) ?? null;
  const progressPercent = batch
    ? Math.round((100 * batch.completed_count) / batch.selected_count)
    : 0;

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
        label: `${selectedEntry.name} · run ${selectedPose.run}`,
      });
    }
    return sources;
  }, [displayOutput, selectedPose, selectedEntry]);

  const binding = bindingFor(backend);
  const campaignInputs = {
    receptorId: receptor.receptor_id,
    bindingSiteId: bindingSite.binding_site_id,
    mapSetId: mapSetId ?? "",
    libraryId: libraryInput.library_id,
    filterRunId: libraryInput.filter_run_id,
  };

  const history = useCampaignHistory({
    engine: "autodock4",
    receptorId: receptor.receptor_id,
    bindingSiteId: bindingSite.binding_site_id,
  });

  // A campaign outlives the session that launched it, so reconnect to the one
  // already on disk instead of showing an empty workspace over completed work.
  useEffect(() => {
    let disposed = false;
    setRestoring(true);
    setBatch(null);
    void bindingFor(backend)
      .latestBatch({
        receptorId: receptor.receptor_id,
        bindingSiteId: bindingSite.binding_site_id,
        mapSetId: "",
        libraryId: libraryInput.library_id,
        filterRunId: libraryInput.filter_run_id,
      })
      .then((next) => {
        if (disposed) return;
        setBatch(next);
        revisionRef.current = next.revision;
      })
      .catch(() => {
        // No campaign for these inputs on this backend is the normal first-run
        // state, not an error worth showing.
      })
      .finally(() => { if (!disposed) setRestoring(false); });
    return () => { disposed = true; };
  }, [
    backend,
    receptor.receptor_id,
    bindingSite.binding_site_id,
    libraryInput.library_id,
    libraryInput.filter_run_id,
  ]);

  async function openCampaign(batchId: string) {
    setOpening(true);
    setError(null);
    try {
      const record = await binding.getBatch(batchId);
      revisionRef.current = record.revision;
      setBatch(record);
      setSelectedLigandId(null);
      setSelectedRun(null);
      setExpandedLigandId(null);
    } catch (reason: unknown) {
      setError(asMessage(reason, "That campaign could not be opened."));
    } finally {
      setOpening(false);
    }
  }

  useEffect(() => {
    if (!mapJob || TERMINAL.has(mapJob.status)) return;
    let disposed = false;
    const timer = window.setInterval(() => {
      void ankoraApi.getAutoGridJob(mapJob.job_id)
        .then((next) => { if (!disposed) setMapJob(next); })
        .catch((reason: unknown) => {
          if (!disposed) setError(asMessage(reason, "Grid status could not be refreshed."));
        });
    }, 1000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [mapJob]);

  useEffect(() => {
    if (!batch || TERMINAL.has(batch.status)) return;
    let disposed = false;
    const timer = window.setInterval(() => {
      // Poll the cheap progress endpoint; only refetch the full record when
      // something actually changed, so a long campaign does not resend results.
      void binding.getProgressRevision(batch.batch_id, revisionRef.current)
        .then(async (revision) => {
          if (disposed || revision === null) return;
          revisionRef.current = revision;
          const next = await binding.getBatch(batch.batch_id);
          if (disposed) return;
          setBatch(next);
          // A finished campaign changes what the history should report about
          // it: its final counts and its best energy.
          if (TERMINAL.has(next.status)) void history.reload();
        })
        .catch((reason: unknown) => {
          if (!disposed) setError(asMessage(reason, "Campaign status could not be refreshed."));
        });
    }, 1000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [batch]);

  useEffect(() => {
    if (!onActivityChange) return;
    if (mapsBusy && mapJob) {
      onActivityChange({ title: "AutoGrid4", detail: "Computing affinity maps" });
      return;
    }
    if (batchBusy && batch) {
      onActivityChange({
        title: "AutoDock4 campaign",
        detail: `${batch.completed_count}/${batch.selected_count} molecules`,
        workers: batch.worker_count,
        current: batch.completed_count,
        total: batch.selected_count,
      });
      return;
    }
    onActivityChange(null);
  }, [mapsBusy, batchBusy, mapJob, batch, onActivityChange]);

  const sortedEntries = useMemo(() => {
    const entries = [...(batch?.entries ?? [])];
    const factor = sortDirection === "ascending" ? 1 : -1;
    return entries.sort((left, right) => {
      const a = entrySortValue(left, sortKey);
      const b = entrySortValue(right, sortKey);
      if (a === null && b === null) return left.source_index - right.source_index;
      if (a === null) return 1;
      if (b === null) return -1;
      if (typeof a === "string" || typeof b === "string") {
        return String(a).localeCompare(String(b)) * factor;
      }
      return (a - b) * factor;
    });
  }, [batch, sortDirection, sortKey]);

  const best = useMemo(() => {
    let champion: CampaignEntryView | null = null;
    for (const entry of batch?.entries ?? []) {
      const energy = bestEnergy(entry);
      if (energy === null) continue;
      if (champion === null || energy < (bestEnergy(champion) ?? Infinity)) champion = entry;
    }
    return champion;
  }, [batch]);

  async function generateMaps() {
    setError(null);
    setBatch(null);
    try {
      const next = await ankoraApi.startAutoGridJob({
        receptor_id: receptor.receptor_id,
        binding_site_id: bindingSite.binding_site_id,
        source: "filter_run",
        library_id: libraryInput.library_id,
        filter_run_id: libraryInput.filter_run_id,
      });
      setMapJob(next);
    } catch (reason: unknown) {
      setError(asMessage(reason, "AutoGrid could not be started."));
    }
  }

  async function startCampaign() {
    if (!mapSetId) return;
    setError(null);
    revisionRef.current = 0;
    try {
      const next = await binding.startBatch(
        { ...campaignInputs, mapSetId },
        parameters,
        acknowledged,
      );
      setBatch(next);
      // The new campaign exists on disk now, so it belongs in the history.
      void history.reload();
    } catch (reason: unknown) {
      setError(asMessage(reason, "The campaign could not be started."));
    }
  }

  async function cancelCampaign() {
    if (!batch) return;
    try {
      await binding.cancelBatch(batch.batch_id);
      setBatch((current) => current ? { ...current, status: "cancel_requested" } : current);
    } catch (reason: unknown) {
      setError(asMessage(reason, "The campaign could not be canceled."));
    }
  }

  function changeSort(nextKey: EntrySortKey) {
    if (nextKey === sortKey) {
      setSortDirection((current) => current === "ascending" ? "descending" : "ascending");
      return;
    }
    setSortKey(nextKey);
    setSortDirection("ascending");
  }

  function selectPose(ligandId: string, run: number) {
    setSelectedLigandId(ligandId);
    setSelectedRun(run);
  }

  return (
    <>
      <section className="workspace docking-workspace" aria-label="AutoDock4 screening workspace">
        <div className="workspace-heading">
          <div><span className="eyebrow">05 / Docking</span><h2>{backend === "autodock_gpu" ? "AutoDock-GPU" : "AutoDock4"} over the applied selection</h2></div>
          <div className="workspace-actions">
            {modeSwitch}
            <span className="read-only-badge">
              {backend === "autodock_gpu"
                ? "M5 · AutoDock-GPU 1.6"
                : "M5 · AutoDock4 4.2.6 CPU"}
            </span>
          </div>
        </div>
        {mapsBusy ? (
          <div className="operation-progress" role="progressbar" aria-label="AutoGrid running">
            <span /><p>Computing affinity maps once for the whole selection</p>
          </div>
        ) : null}
        {batchBusy && batch ? (
          <div
            className="operation-progress"
            role="progressbar"
            aria-label="AutoDock4 campaign running"
            aria-valuemin={0}
            aria-valuemax={batch.selected_count}
            aria-valuenow={batch.completed_count}
          >
            <span className="determinate" style={{ width: `${progressPercent}%` }} />
            <p>
              {batch.completed_count}/{batch.selected_count} molecules ·{" "}
              {batch.worker_count} parallel AutoDock4 processes
            </p>
          </div>
        ) : null}
        {error ? <div className="structure-error" role="alert">{error}</div> : null}
        {mapJob?.failure ? (
          <div className="structure-error" role="alert">
            <strong>{mapJob.failure.message}</strong> <span>{mapJob.failure.code}</span>
          </div>
        ) : null}
        {viewerSources.length ? (
          <MolecularViewer sources={viewerSources} selection={null} dockingBox={bindingSite.box} />
        ) : (
          <div className="viewer-placeholder ligand-placeholder">
            <div className="viewer-message"><div className="molecule-glyph">⬚</div><h3>Prepared receptor unavailable</h3></div>
          </div>
        )}
        {restoring && !batch ? (
          <div className="campaign-live-panel">
            <strong>Checking campaign history…</strong>
            <small>Ankora reconnects to an existing campaign instead of launching another one.</small>
          </div>
        ) : null}
        {batch ? (
          <CampaignResults
            entries={sortedEntries}
            best={best}
            sortKey={sortKey}
            sortDirection={sortDirection}
            onSort={changeSort}
            expandedLigandId={expandedLigandId}
            onToggle={(ligandId) => setExpandedLigandId((c) => c === ligandId ? null : ligandId)}
            selectedLigandId={selectedLigandId}
            selectedRun={selectedRun}
            onSelectPose={selectPose}
          />
        ) : null}
      </section>
      <aside className="inspector docking-inspector" aria-label="AutoDock4 campaign inspector">
        <div className="inspector-heading">
          <span className="section-label">Docking campaign</span>
          <h2>AutoDock4</h2>
          <p className="inspector-subtitle">
            One map set for the whole selection; every molecule runs its own AutoDock4 process and its own clustering.
          </p>
        </div>
        <section className="receptor-section">
          <div className="filter-heading"><span>1 · Scientific inputs</span></div>
          <InputState ready={Boolean(receptorPdbqt)} label="Receptor PDBQT" detail={receptorPdbqt ? `${receptorPdbqt.filename} · ${receptorPdbqt.sha256.slice(0, 12)}…` : "Return to Receptor and generate PDBQT."} />
          <InputState ready label="Applied selection" detail={`${libraryInput.selected_count} molecules · ${libraryInput.prepared_count} prepared`} />
        </section>
        <section className="receptor-section">
          <div className="filter-heading"><span>2 · Affinity maps</span><small>{tools?.autogrid4.available ? tools.autogrid4.version : "Unavailable"}</small></div>
          <p className="field-note">
            The maps are computed once and shared by every molecule. An identical map set is reused rather than recomputed.
          </p>
          {mapJob?.status === "completed" ? (
            <div className="state-resolved-note">
              <strong>{mapJob.reused_existing_map_set ? "Reused existing map set" : "Map set generated"}</strong>
              <small>
                {mapJob.preflight.compatible_count}/{mapJob.preflight.selected_count} molecules compatible ·{" "}
                {mapJob.preflight.ligand_atom_types.join(" ")}
              </small>
            </div>
          ) : null}
          <button type="button" className="apply-plan" onClick={() => void generateMaps()} disabled={!toolsReady || mapsBusy || batchBusy}>
            {mapJob?.status === "completed" ? "Regenerate affinity maps" : "Generate affinity maps"}
          </button>
        </section>
        <section className="receptor-section">
          <div className="filter-heading"><span>3 · Execution backend</span></div>
          <p className="field-note">
            One engine, two backends. Both run AutoDock4&apos;s scoring function against
            the same maps; they differ in how the search is conducted, so their
            results are recorded separately and never pooled.
          </p>
          <div className="backend-selector" role="radiogroup" aria-label="Execution backend">
            {AUTODOCK_BACKENDS.map((option) => {
              const available =
                option.backend === "autodock_gpu"
                  ? Boolean(tools?.autodock_gpu.available)
                  : Boolean(tools?.autodock4.available);
              return (
                <button
                  key={option.backend}
                  type="button"
                  role="radio"
                  aria-checked={backend === option.backend}
                  className={backend === option.backend ? "backend-option selected" : "backend-option"}
                  disabled={batchBusy || !available}
                  onClick={() => {
                    setBackend(option.backend);
                    setParameters(defaultParameters(option.backend));
                  }}
                >
                  <strong>{option.label}</strong>
                  <small>{available ? option.summary : "Not configured on this system."}</small>
                </button>
              );
            })}
          </div>
          {backend === "autodock_gpu" ? (
            <div className="protonation-blocker" role="note">
              <p>
                AutoDock-GPU does not reproduce a run from its seed. Six repeats of one
                seed gave six different rankings, spanning 0.13 kcal/mol. Use the CPU
                backend when an exactly repeatable result is required.
              </p>
            </div>
          ) : null}
        </section>
        <section className="receptor-section">
          <div className="filter-heading"><span>4 · Search & scheduling</span><small>{tools?.autodock4.available ? tools.autodock4.version : "Unavailable"}</small></div>
          <p className="field-note">
            AutoDock4 4.2.6 has no OpenMP support, so each process uses one core and this count is the whole CPU budget.
          </p>
          {isGpuParameters(parameters) ? (
            <>
              <p className="field-note">
                A campaign is one process over the whole selection. Two processes on one
                device measured slower than one, so there is no parallelism to set.
              </p>
              <div className="docking-parameter-grid">
                <NumberField label="Independent runs" value={parameters.runs} min={2} max={1000} disabled={batchBusy} onChange={(v) => setParameters((c) => ({ ...c, runs: v }))} />
                <NumberField label="Energy evaluations" value={parameters.energy_evaluations} min={1000} max={100000000} step={250000} disabled={batchBusy || parameters.heuristics} onChange={(v) => setParameters((c) => ({ ...c, energy_evaluations: v }))} />
                <NumberField label="Population size" value={parameters.population_size} min={2} max={10000} disabled={batchBusy} onChange={(v) => setParameters((c) => ({ ...c, population_size: v }))} />
                <NumberField label="Cluster RMSD (Å)" value={parameters.cluster_rmsd_tolerance_angstrom} min={0.1} max={20} step={0.1} disabled={batchBusy} onChange={(v) => setParameters((c) => ({ ...c, cluster_rmsd_tolerance_angstrom: v }))} />
                <NumberField label="Seed 1" value={parameters.seed_1} min={0} max={2147483647} disabled={batchBusy} onChange={(v) => setParameters((c) => ({ ...c, seed_1: v }))} />
                <NumberField label="Seed 2" value={parameters.seed_2} min={0} max={2147483647} disabled={batchBusy} onChange={(v) => setParameters((c) => ({ ...c, seed_2: v }))} />
                <NumberField label="Seed 3" value={parameters.seed_3} min={0} max={2147483647} disabled={batchBusy} onChange={(v) => setParameters((c) => ({ ...c, seed_3: v }))} />
                <NumberField label="Campaign timeout (min)" value={parameters.timeout_minutes} min={1} max={2880} disabled={batchBusy} onChange={(v) => setParameters((c) => ({ ...c, timeout_minutes: v }))} />
              </div>
              <label className="field-label" htmlFor="gpu-local-search">Local search</label>
              <select
                id="gpu-local-search"
                value={parameters.local_search_method}
                disabled={batchBusy}
                onChange={(e) => setParameters((c) => ({ ...c, local_search_method: e.target.value as typeof parameters.local_search_method }))}
              >
                <option value="ad">ADADELTA (tool default)</option>
                <option value="sw">Solis-Wets (what the CPU protocol uses)</option>
                <option value="fire">FIRE</option>
              </select>
              <label className="check-row">
                <input type="checkbox" checked={parameters.heuristics} disabled={batchBusy} onChange={(e) => setParameters((c) => ({ ...c, heuristics: e.target.checked }))} />
                <span>
                  <strong>Let the tool choose the evaluation count</strong>
                  <small>Its ligand-based heuristic. Faster, but the budget is no longer something you stated.</small>
                </span>
              </label>
              <label className="check-row">
                <input type="checkbox" checked={parameters.autostop} disabled={batchBusy} onChange={(e) => setParameters((c) => ({ ...c, autostop: e.target.checked }))} />
                <span>
                  <strong>Stop early on convergence</strong>
                  <small>Halts a run once the best energies settle. Roughly twice as fast again.</small>
                </span>
              </label>
            </>
          ) : (
            <div className="docking-parameter-grid">
              <NumberField label="Parallel molecules" value={parameters.parallel_ligands} min={1} max={64} disabled={batchBusy} onChange={(v) => setParameters((c) => ({ ...c, parallel_ligands: v }))} />
              <NumberField label="Independent runs" value={parameters.ga_runs} min={2} max={256} disabled={batchBusy} onChange={(v) => setParameters((c) => ({ ...c, ga_runs: v }))} />
              <NumberField label="Energy evaluations" value={parameters.ga_energy_evaluations} min={1000} max={100000000} step={250000} disabled={batchBusy} onChange={(v) => setParameters((c) => ({ ...c, ga_energy_evaluations: v }))} />
              <NumberField label="Population size" value={parameters.ga_population_size} min={2} max={10000} disabled={batchBusy} onChange={(v) => setParameters((c) => ({ ...c, ga_population_size: v }))} />
              <NumberField label="Cluster RMSD (Å)" value={parameters.cluster_rmsd_tolerance_angstrom} min={0.1} max={20} step={0.1} disabled={batchBusy} onChange={(v) => setParameters((c) => ({ ...c, cluster_rmsd_tolerance_angstrom: v }))} />
              <NumberField label="Seed 1" value={parameters.seed_1} min={2} max={2147483647} disabled={batchBusy} onChange={(v) => setParameters((c) => ({ ...c, seed_1: v }))} />
              <NumberField label="Seed 2" value={parameters.seed_2} min={2} max={2147483647} disabled={batchBusy} onChange={(v) => setParameters((c) => ({ ...c, seed_2: v }))} />
              <NumberField label="Timeout per molecule (min)" value={parameters.timeout_minutes} min={1} max={2880} disabled={batchBusy} onChange={(v) => setParameters((c) => ({ ...c, timeout_minutes: v }))} />
            </div>
          )}
        </section>
        <section className="receptor-section">
          <div className="filter-heading"><span>5 · Confirm & run</span>{batch ? <small>{batch.status.replaceAll("_", " ")}</small> : null}</div>
          <label className="docking-acknowledgement">
            <input type="checkbox" checked={acknowledged} disabled={batchBusy} onChange={(e) => setAcknowledged(e.target.checked)} />
            <span>
              <strong>Use these exact inputs and parameters</strong>
              <small>I understand that an AutoDock4 binding energy is a computational estimate in kcal/mol, not an experimental affinity, and that it is not comparable to a Vina score.</small>
            </span>
          </label>
          {batchBusy ? (
            <button type="button" className="danger-action docking-primary-action" onClick={() => void cancelCampaign()} disabled={batch?.status === "cancel_requested"}>Cancel campaign</button>
          ) : (
            <button type="button" className="primary-action docking-primary-action" onClick={() => void startCampaign()} disabled={!mapSetId || !acknowledged || mapsBusy || restoring}>
              {restoring ? "Checking campaign history…" : "Dock the applied selection"}
            </button>
          )}
          {!mapSetId ? <p className="field-note">Generate the affinity maps above before docking. AutoDock4 cannot score without them.</p> : null}
        </section>
        <CampaignExportPanel
          sourceKind={backend === "autodock_gpu" ? "autodock_gpu_batch" : "autodock4_batch"}
          sourceId={batch?.batch_id ?? null}
          ready={Boolean(batch && TERMINAL.has(batch.status))}
        />
        <CampaignHistoryPanel
          engine="autodock4"
          campaigns={history.campaigns}
          loading={history.loading}
          error={history.error}
          activeBatchId={batch?.batch_id ?? null}
          currentFilterRunId={libraryInput.filter_run_id}
          opening={opening || batchBusy}
          onOpen={(batchId) => void openCampaign(batchId)}
          onRefresh={() => void history.reload()}
        />
        {batch ? (
          <section className="receptor-section">
            <div className="filter-heading"><span>6 · Evidence</span><small>{batch.batch_id.slice(0, 8)}…</small></div>
            <dl className="docking-evidence">
              <div><dt>Engine</dt><dd>{batch.engine.name} {batch.engine.version}</dd></div>
              {batch.device_name ? <div><dt>Device</dt><dd>{batch.device_name}</dd></div> : null}
              <div><dt>Reproducible</dt><dd>{batch.bitwise_reproducible ? "Bit-identical on a repeat" : "Not from its seed"}</dd></div>
              <div><dt>Docked</dt><dd>{batch.succeeded_count}/{batch.selected_count}</dd></div>
              <div><dt>Failed</dt><dd>{batch.failed_count}</dd></div>
              <div><dt>Workers</dt><dd>{batch.worker_count}</dd></div>
              <div><dt>Map set</dt><dd>{batch.map_set_identity_key.slice(0, 12)}…</dd></div>
            </dl>
          </section>
        ) : null}
      </aside>
    </>
  );
}

function CampaignResults({
  entries, best, sortKey, sortDirection, onSort,
  expandedLigandId, onToggle, selectedLigandId, selectedRun, onSelectPose,
}: {
  entries: CampaignEntryView[];
  best: CampaignEntryView | null;
  sortKey: EntrySortKey;
  sortDirection: SortDirection;
  onSort: (key: EntrySortKey) => void;
  expandedLigandId: string | null;
  onToggle: (ligandId: string) => void;
  selectedLigandId: string | null;
  selectedRun: number | null;
  onSelectPose: (ligandId: string, run: number) => void;
}) {
  const horizontalScrollRef = useRef<HTMLDivElement>(null);
  const tableScrollRef = useRef<HTMLDivElement>(null);
  return (
    <section className="docking-results library-docking-results" aria-label="AutoDock4 campaign results">
      <div className="docking-results-heading">
        <div><span className="eyebrow">Compound results</span><h3>AutoDock4 library results</h3></div>
        <p>
          {best ? (
            <><strong>{best.name}</strong> currently ranks first at{" "}
            <strong>{(bestEnergy(best) ?? 0).toFixed(2)} kcal/mol</strong>. </>
          ) : null}
          Each molecule is clustered by AutoDock itself. Energies are computational estimates, not experimental affinities.
        </p>
      </div>
      <div
        className="docking-results-horizontal-scroll"
        ref={horizontalScrollRef}
        tabIndex={0}
        aria-label="Horizontal campaign results scroll"
        onScroll={(event) => syncHorizontalScroll(event.currentTarget, tableScrollRef.current)}
      >
        <div />
      </div>
      <div
        className="docking-results-scroll"
        ref={tableScrollRef}
        tabIndex={0}
        aria-label="Scrollable campaign results table"
        onScroll={(event) => syncHorizontalScroll(event.currentTarget, horizontalScrollRef.current)}
      >
        <table>
          <thead>
            <tr>
              <SortHeader label="#" sortKey="source_index" activeKey={sortKey} direction={sortDirection} onSort={onSort} />
              <SortHeader label="Name" sortKey="name" activeKey={sortKey} direction={sortDirection} onSort={onSort} />
              <SortHeader label="Best energy (kcal/mol)" sortKey="best_energy" activeKey={sortKey} direction={sortDirection} onSort={onSort} />
              <SortHeader label="Clusters" sortKey="cluster_count" activeKey={sortKey} direction={sortDirection} onSort={onSort} />
              <SortHeader label="Status" sortKey="status" activeKey={sortKey} direction={sortDirection} onSort={onSort} />
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => {
              const expanded = entry.ligand_id === expandedLigandId;
              const energy = bestEnergy(entry);
              return (
                <Fragment key={entry.ligand_id}>
                  <tr
                    className={entry.ligand_id === selectedLigandId ? "selected" : ""}
                    onClick={() => onToggle(entry.ligand_id)}
                    aria-expanded={expanded}
                  >
                    <td>{entry.source_index + 1}</td>
                    <td>
                      <button
                        type="button"
                        className="compound-expand"
                        aria-expanded={expanded}
                        onClick={(event) => { event.stopPropagation(); onToggle(entry.ligand_id); }}
                      >
                        <span aria-hidden="true">{expanded ? "▾" : "▸"}</span>
                        {entry.name}
                        {best?.ligand_id === entry.ligand_id ? <small>Current best</small> : null}
                      </button>
                    </td>
                    <td>{energy === null ? "—" : energy.toFixed(2)}</td>
                    <td>{entry.clusters.length || "—"}</td>
                    <td>
                      <span className={`docking-status ${entry.status}`}>{entry.status.replaceAll("_", " ")}</span>
                      {entry.failure ? <small title={entry.failure.message}>{entry.failure.code}</small> : null}
                    </td>
                  </tr>
                  {expanded ? (
                    <tr className="pose-expansion">
                      <td colSpan={5}>
                        {entry.clusters.length ? (
                          <div className="compound-poses">
                            <div className="compound-poses-heading">
                              <strong>{entry.name} · {entry.clusters.length} clusters over {entry.runs.length} runs</strong>
                              <small>Click a run to display that exact preserved conformation.</small>
                            </div>
                            <table>
                              <thead>
                                <tr>
                                  <th>Cluster</th>
                                  <th>Lowest energy (kcal/mol)</th>
                                  <th>Mean energy (kcal/mol)</th>
                                  <th>Runs in cluster</th>
                                  <th>Conformations</th>
                                </tr>
                              </thead>
                              <tbody>
                                {entry.clusters.map((cluster) => (
                                  <tr key={cluster.cluster_rank}>
                                    <td>Rank {cluster.cluster_rank}</td>
                                    <td>{cluster.lowest_binding_energy_kcal_mol.toFixed(2)}</td>
                                    <td>{cluster.mean_binding_energy_kcal_mol.toFixed(2)}</td>
                                    <td>{cluster.run_count}</td>
                                    <td>
                                      <div className="autodock4-run-buttons">
                                        {cluster.runs.map((run) => (
                                          <button
                                            key={run}
                                            type="button"
                                            className="pose-select"
                                            aria-pressed={entry.ligand_id === selectedLigandId && run === selectedRun}
                                            onClick={(event) => { event.stopPropagation(); onSelectPose(entry.ligand_id, run); }}
                                          >
                                            Run {run}
                                          </button>
                                        ))}
                                      </div>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        ) : (
                          <p className="field-note">
                            {entry.failure
                              ? `${entry.failure.code} · ${entry.failure.message}`
                              : "No clusters are available while this molecule is still queued or running."}
                          </p>
                        )}
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function syncHorizontalScroll(source: HTMLDivElement, target: HTMLDivElement | null) {
  if (target && Math.abs(target.scrollLeft - source.scrollLeft) > 0.5) {
    target.scrollLeft = source.scrollLeft;
  }
}

function SortHeader({ label, sortKey, activeKey, direction, onSort }: {
  label: string;
  sortKey: EntrySortKey;
  activeKey: EntrySortKey;
  direction: SortDirection;
  onSort: (key: EntrySortKey) => void;
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

function InputState({ ready, label, detail }: { ready: boolean; label: string; detail: string }) {
  return <div className={ready ? "state-resolved-note" : "protonation-blocker"}><strong>{label}</strong><small>{detail}</small></div>;
}

function NumberField({ label, value, min, max, step = 1, disabled, onChange }: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  disabled: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <label className="numeric-field">
      <span className="field-label">{label}</span>
      <input type="number" aria-label={label} value={value} min={min} max={max} step={step} disabled={disabled} onChange={(event) => onChange(Number(event.target.value))} />
    </label>
  );
}

/** AutoDock ranks cluster 1 best, so its lowest energy is the molecule's score. */
function bestEnergy(entry: CampaignEntryView): number | null {
  if (!entry.clusters.length) return null;
  return Math.min(...entry.clusters.map((c) => c.lowest_binding_energy_kcal_mol));
}

function entrySortValue(
  entry: CampaignEntryView,
  key: EntrySortKey,
): number | string | null {
  if (key === "source_index") return entry.source_index;
  if (key === "name") return entry.name;
  if (key === "best_energy") return bestEnergy(entry);
  if (key === "cluster_count") return entry.clusters.length;
  return entry.status;
}

function asMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}
