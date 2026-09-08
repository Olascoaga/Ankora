import { Fragment, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { ankoraApi } from "../../api/client";
import type { WorkspaceActivity } from "../../app/activity";
import type {
  AutoDock4ClusterResult,
  AutoDock4DockingJobRecord,
  AutoDock4DockingParameters,
  AutoDock4RunResult,
  AutoDockBackend,
  AutoGridMapJobRecord,
  BindingSiteRecord,
  LigandDockingInput,
  LigandRecord,
  ReceptorPreparationRecord,
  ToolsResponse,
} from "../../types/api";
import { formatScientificNumber } from "../../utils/format";
import { MolecularViewer } from "../../viewer/MolecularViewer";
import {
  AUTODOCK_BACKENDS,
  LOCAL_SEARCH_LABEL,
  isGpuJobParameters,
  jobBindingFor,
} from "./autodockBackend";
import type { JobParameters, JobView } from "./autodockBackend";
import type { ViewerSource } from "../../viewer/adapter";

interface AutoDock4WorkspaceProps {
  receptor: ReceptorPreparationRecord;
  bindingSite: BindingSiteRecord;
  ligand: LigandRecord | null;
  ligandInput: LigandDockingInput | null;
  tools: ToolsResponse | null;
  onActivityChange?: (activity: WorkspaceActivity | null) => void;
  modeSwitch?: ReactNode;
}

const TERMINAL = new Set(["completed", "failed", "canceled"]);

function defaultParameters(backend: AutoDockBackend): JobParameters {
  return jobBindingFor(backend).defaultParameters();
}

export function AutoDock4Workspace({
  receptor,
  bindingSite,
  ligand,
  ligandInput,
  tools,
  onActivityChange,
  modeSwitch,
}: AutoDock4WorkspaceProps) {
  const [backend, setBackend] = useState<AutoDockBackend>("autodock4_cpu");
  const [parameters, setParameters] = useState<JobParameters>(() =>
    defaultParameters("autodock4_cpu"),
  );
  const [acknowledged, setAcknowledged] = useState(false);
  const [mapJob, setMapJob] = useState<AutoGridMapJobRecord | null>(null);
  const [job, setJob] = useState<JobView | null>(null);
  const [selectedRun, setSelectedRun] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const displayOutput = receptor.outputs.find(
    (item) => item.artifact_id === receptor.display_output_artifact_id,
  );
  const receptorPdbqt = receptor.outputs.find((item) => item.stage === "pdbqt");
  const matchingLigandInput = ligandInput
    && ligandInput.ligand_id === ligand?.artifact.ligand_id
    ? ligandInput
    : null;
  const ligandPdbqt = matchingLigandInput?.pdbqt ?? null;

  const mapsBusy = Boolean(mapJob && !TERMINAL.has(mapJob.status));
  const dockingBusy = Boolean(job && !TERMINAL.has(job.status));
  const mapSetId = mapJob?.status === "completed" ? mapJob.map_set_id : null;
  const toolsReady = Boolean(
    tools?.autogrid4.available && tools.autodock4.available,
  );
  const inputsReady = Boolean(receptorPdbqt && ligand && ligandPdbqt);
  const selectedPose = job?.runs.find((item) => item.run === selectedRun) ?? null;

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
    if (selectedPose) {
      sources.push({
        id: selectedPose.artifact.artifact_id,
        url: ankoraApi.dockingPoseUrl(selectedPose.artifact.content_url),
        // The preserved artifact stays PDBQT; this only selects Mol*'s
        // compatible PDB coordinate parser for display.
        format: "pdb",
        label: `AutoDock4 run ${selectedPose.run}`,
      });
    }
    return sources;
  }, [displayOutput, selectedPose]);

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
    if (!job || TERMINAL.has(job.status)) return;
    let disposed = false;
    const timer = window.setInterval(() => {
      void jobBindingFor(backend).getJob(job.job_id)
        .then((next) => {
          if (disposed) return;
          setJob(next);
          if (next.status === "completed" && next.runs.length && selectedRun === null) {
            setSelectedRun(bestRun(next).run);
          }
        })
        .catch((reason: unknown) => {
          if (!disposed) setError(asMessage(reason, "Docking status could not be refreshed."));
        });
    }, 1000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [job, selectedRun]);

  useEffect(() => {
    if (!onActivityChange) return;
    if (mapsBusy && mapJob) {
      onActivityChange({ title: "AutoGrid4", detail: gridPhaseLabel(mapJob) });
      return;
    }
    if (dockingBusy && job) {
      onActivityChange({ title: "AutoDock4", detail: dockingPhaseLabel(job) });
      return;
    }
    onActivityChange(null);
  }, [mapsBusy, dockingBusy, mapJob, job, onActivityChange]);

  async function generateMaps() {
    if (!ligand || !ligandPdbqt) return;
    setError(null);
    setJob(null);
    setSelectedRun(null);
    try {
      const next = await ankoraApi.startAutoGridJob({
        receptor_id: receptor.receptor_id,
        binding_site_id: bindingSite.binding_site_id,
        source: "ligand_preparation",
        ligand_id: ligand.artifact.ligand_id,
        ligand_preparation_id: ligandPdbqt.artifact.preparation_id,
      });
      setMapJob(next);
    } catch (reason: unknown) {
      setError(asMessage(reason, "AutoGrid could not be started."));
    }
  }

  async function cancelMaps() {
    if (!mapJob) return;
    try {
      await ankoraApi.cancelAutoGridJob(mapJob.job_id);
      setMapJob((current) => current ? { ...current, status: "cancel_requested" } : current);
    } catch (reason: unknown) {
      setError(asMessage(reason, "The grid job could not be canceled."));
    }
  }

  async function startDocking() {
    if (!ligand || !ligandPdbqt || !mapSetId) return;
    setError(null);
    setSelectedRun(null);
    try {
      const next = await jobBindingFor(backend).startJob(
        {
          receptorId: receptor.receptor_id,
          bindingSiteId: bindingSite.binding_site_id,
          mapSetId,
          ligandId: ligand.artifact.ligand_id,
          ligandPreparationId: ligandPdbqt.artifact.preparation_id,
        },
        parameters,
        acknowledged,
      );
      setJob(next);
    } catch (reason: unknown) {
      setError(asMessage(reason, "Docking could not be started."));
    }
  }

  async function cancelDocking() {
    if (!job) return;
    try {
      await jobBindingFor(backend).cancelJob(job.job_id);
      setJob((current) => current ? { ...current, status: "cancel_requested" } : current);
    } catch (reason: unknown) {
      setError(asMessage(reason, "The docking job could not be canceled."));
    }
  }

  function updateParameter(name: string, value: number) {
    setParameters((current) => ({ ...current, [name]: value }));
  }

  return (
    <>
      <section className="workspace docking-workspace" aria-label="AutoDock4 docking workspace">
        <div className="workspace-heading">
          <div><span className="eyebrow">05 / Docking</span><h2>{backend === "autodock_gpu" ? "AutoDock-GPU" : "AutoDock4"} on one ligand</h2></div>
          <div className="workspace-actions">
            {modeSwitch}
            <span className="read-only-badge">
              {backend === "autodock_gpu"
                ? "M5 · AutoDock-GPU 1.6"
                : "M5 · AutoDock4 4.2.6 CPU"}
            </span>
          </div>
        </div>
        {mapsBusy && mapJob ? (
          <div className="operation-progress" role="progressbar" aria-label="AutoGrid running">
            <span /><p>{gridPhaseLabel(mapJob)} · {mapJob.geometry.npts.join(" × ")} intervals</p>
          </div>
        ) : null}
        {dockingBusy && job ? (
          <div className="operation-progress" role="progressbar" aria-label="AutoDock docking running">
            <span /><p>{dockingPhaseLabel(job)} · {job.protocol_summary}</p>
          </div>
        ) : null}
        {error ? <div className="structure-error" role="alert">{error}</div> : null}
        {mapJob?.failure ? (
          <div className="structure-error" role="alert">
            <strong>{mapJob.failure.message}</strong> <span>{mapJob.failure.code}</span>
          </div>
        ) : null}
        {job?.failure ? (
          <div className="structure-error" role="alert">
            <strong>{job.failure.message}</strong> <span>{job.failure.code}</span>
          </div>
        ) : null}
        {viewerSources.length ? (
          <MolecularViewer sources={viewerSources} selection={null} dockingBox={bindingSite.box} />
        ) : (
          <div className="viewer-placeholder ligand-placeholder">
            <div className="viewer-message"><div className="molecule-glyph">⬚</div><h3>Prepared receptor unavailable</h3></div>
          </div>
        )}
        {job?.status === "completed" ? (
          <ClusterResults
            clusters={job.clusters}
            runs={job.runs}
            selectedRun={selectedRun}
            onSelect={setSelectedRun}
          />
        ) : null}
      </section>
      <aside className="inspector docking-inspector" aria-label="AutoDock4 setup inspector">
        <div className="inspector-heading">
          <span className="section-label">Docking experiment</span>
          <h2>{backend === "autodock_gpu" ? "AutoDock-GPU" : "AutoDock4"}</h2>
          <p className="inspector-subtitle">
            AutoGrid maps the search space once; AutoDock4 then searches it with independent runs and clusters them.
          </p>
        </div>
        <section className="receptor-section">
          <div className="filter-heading"><span>1 · Scientific inputs</span></div>
          <InputState ready={Boolean(receptorPdbqt)} label="Receptor PDBQT" detail={receptorPdbqt ? `${receptorPdbqt.filename} · ${receptorPdbqt.sha256.slice(0, 12)}…` : "Return to Receptor and generate PDBQT."} />
          <InputState ready label="Binding site" detail={`${formatScientificNumber(bindingSite.box.size_x, 1)} × ${formatScientificNumber(bindingSite.box.size_y, 1)} × ${formatScientificNumber(bindingSite.box.size_z, 1)} Å`} />
          <InputState ready={Boolean(ligandPdbqt)} label="Ligand PDBQT" detail={ligandPdbqt ? `${ligand?.inspection.name ?? "Ligand"} · ${ligandPdbqt.artifact.sha256.slice(0, 12)}…` : "Return to Ligand and generate PDBQT."} />
        </section>
        <section className="receptor-section">
          <div className="filter-heading">
            <span>2 · Affinity maps</span>
            <small>{tools?.autogrid4.available ? tools.autogrid4.version : "Unavailable"}</small>
          </div>
          <p className="field-note">
            AutoDock4 scores against precomputed grid maps. An identical map set is reused rather than recomputed.
          </p>
          {mapJob?.status === "completed" ? (
            <div className="state-resolved-note">
              <strong>{mapJob.reused_existing_map_set ? "Reused existing map set" : "Map set generated"}</strong>
              <small>
                {mapJob.geometry.npts.join(" × ")} intervals at {mapJob.geometry.spacing_angstrom} Å ·{" "}
                {mapJob.preflight.ligand_atom_types.join(" ")} · {mapJob.identity_key.slice(0, 12)}…
              </small>
            </div>
          ) : null}
          {mapsBusy ? (
            <button type="button" className="danger-action docking-primary-action" onClick={() => void cancelMaps()} disabled={mapJob?.status === "cancel_requested"}>
              Cancel grid generation
            </button>
          ) : (
            <button type="button" className="apply-plan" onClick={() => void generateMaps()} disabled={!toolsReady || !inputsReady || dockingBusy}>
              {mapJob?.status === "completed" ? "Regenerate affinity maps" : "Generate affinity maps"}
            </button>
          )}
        </section>
        <section className="receptor-section">
          <div className="filter-heading"><span>3 · Execution backend</span></div>
          <p className="field-note">
            One engine, two backends. Both run AutoDock4&apos;s scoring function against
            the same maps; they differ in how the search is conducted.
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
                  disabled={dockingBusy || !available}
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
          <div className="filter-heading">
            <span>4 · Search</span>
            <small>{tools?.autodock4.available ? tools.autodock4.version : "Unavailable"}</small>
          </div>
          {isGpuJobParameters(parameters) ? (
            <>
              <div className="docking-parameter-grid">
                <NumberField label="Independent runs" value={parameters.runs} min={2} max={1000} disabled={dockingBusy} onChange={(value) => updateParameter("runs", value)} />
                <NumberField label="Population size" value={parameters.population_size} min={2} max={10000} disabled={dockingBusy} onChange={(value) => updateParameter("population_size", value)} />
                <NumberField label="Energy evaluations" value={parameters.energy_evaluations} min={1000} max={100000000} step={250000} disabled={dockingBusy || parameters.heuristics} onChange={(value) => updateParameter("energy_evaluations", value)} />
                <NumberField label="Cluster RMSD (Å)" value={parameters.cluster_rmsd_tolerance_angstrom} min={0.1} max={20} step={0.1} disabled={dockingBusy} onChange={(value) => updateParameter("cluster_rmsd_tolerance_angstrom", value)} />
                <NumberField label="Seed 1" value={parameters.seed_1} min={0} max={2147483647} disabled={dockingBusy} onChange={(value) => updateParameter("seed_1", value)} />
                <NumberField label="Seed 2" value={parameters.seed_2} min={0} max={2147483647} disabled={dockingBusy} onChange={(value) => updateParameter("seed_2", value)} />
                <NumberField label="Seed 3" value={parameters.seed_3} min={0} max={2147483647} disabled={dockingBusy} onChange={(value) => updateParameter("seed_3", value)} />
                <NumberField label="Timeout (minutes)" value={parameters.timeout_minutes} min={1} max={2880} disabled={dockingBusy} onChange={(value) => updateParameter("timeout_minutes", value)} />
              </div>
              <label className="field-label" htmlFor="gpu-job-local-search">Local search</label>
              <select
                id="gpu-job-local-search"
                value={parameters.local_search_method}
                disabled={dockingBusy}
                onChange={(event) => setParameters((current) => ({ ...current, local_search_method: event.target.value as typeof parameters.local_search_method }))}
              >
                <option value="ad">ADADELTA (tool default)</option>
                <option value="sw">Solis-Wets (what the CPU protocol uses)</option>
                <option value="fire">FIRE</option>
              </select>
              <label className="check-row">
                <input type="checkbox" checked={parameters.heuristics} disabled={dockingBusy} onChange={(event) => setParameters((current) => ({ ...current, heuristics: event.target.checked }))} />
                <span>
                  <strong>Let the tool choose the evaluation count</strong>
                  <small>Its ligand-based heuristic. Faster, but the budget is no longer something you stated.</small>
                </span>
              </label>
              <label className="check-row">
                <input type="checkbox" checked={parameters.autostop} disabled={dockingBusy} onChange={(event) => setParameters((current) => ({ ...current, autostop: event.target.checked }))} />
                <span>
                  <strong>Stop early on convergence</strong>
                  <small>Halts a run once the best energies settle. Roughly twice as fast again.</small>
                </span>
              </label>
            </>
          ) : (
            <div className="docking-parameter-grid">
              <NumberField label="Independent runs" value={parameters.ga_runs} min={2} max={256} disabled={dockingBusy} onChange={(value) => updateParameter("ga_runs", value)} />
              <NumberField label="Population size" value={parameters.ga_population_size} min={2} max={10000} disabled={dockingBusy} onChange={(value) => updateParameter("ga_population_size", value)} />
              <NumberField label="Energy evaluations" value={parameters.ga_energy_evaluations} min={1000} max={100000000} step={250000} disabled={dockingBusy} onChange={(value) => updateParameter("ga_energy_evaluations", value)} />
              <NumberField label="Generations" value={parameters.ga_generations} min={1} max={1000000} step={1000} disabled={dockingBusy} onChange={(value) => updateParameter("ga_generations", value)} />
              <NumberField label="Cluster RMSD (Å)" value={parameters.cluster_rmsd_tolerance_angstrom} min={0.1} max={20} step={0.1} disabled={dockingBusy} onChange={(value) => updateParameter("cluster_rmsd_tolerance_angstrom", value)} />
              <NumberField label="Seed 1" value={parameters.seed_1} min={2} max={2147483647} disabled={dockingBusy} onChange={(value) => updateParameter("seed_1", value)} />
              <NumberField label="Seed 2" value={parameters.seed_2} min={2} max={2147483647} disabled={dockingBusy} onChange={(value) => updateParameter("seed_2", value)} />
              <NumberField label="Timeout (minutes)" value={parameters.timeout_minutes} min={1} max={2880} disabled={dockingBusy} onChange={(value) => updateParameter("timeout_minutes", value)} />
            </div>
          )}
        </section>
        <section className="receptor-section">
          <div className="filter-heading"><span>5 · Confirm & run</span>{job ? <small>{job.status.replaceAll("_", " ")}</small> : null}</div>
          <label className="docking-acknowledgement">
            <input type="checkbox" checked={acknowledged} disabled={dockingBusy} onChange={(event) => setAcknowledged(event.target.checked)} />
            <span>
              <strong>Use these exact inputs and parameters</strong>
              <small>I understand that an AutoDock4 binding energy is a computational estimate in kcal/mol, not an experimental affinity, and that it is not comparable to a Vina score.</small>
            </span>
          </label>
          {dockingBusy ? (
            <button type="button" className="danger-action docking-primary-action" onClick={() => void cancelDocking()} disabled={job?.status === "cancel_requested"}>Cancel docking</button>
          ) : (
            <button type="button" className="primary-action docking-primary-action" onClick={() => void startDocking()} disabled={!mapSetId || !acknowledged || mapsBusy}>
              {backend === "autodock_gpu" ? "Run AutoDock-GPU" : "Run AutoDock4"}
            </button>
          )}
          {!mapSetId ? <p className="field-note">Generate the affinity maps above before docking. AutoDock4 cannot score without them.</p> : null}
        </section>
        {job ? (
          <section className="receptor-section">
            <div className="filter-heading"><span>6 · Evidence</span><small>{job.job_id.slice(0, 8)}…</small></div>
            <dl className="docking-evidence">
              <div><dt>Engine</dt><dd>{job.engine.name} {job.engine.version}</dd></div>
              {job.device_name ? <div><dt>Device</dt><dd>{job.device_name}</dd></div> : null}
              <div><dt>Clusters</dt><dd>{job.clusters.length} over {job.runs.length} runs</dd></div>
              <div><dt>Protocol</dt><dd>{job.protocol_summary}</dd></div>
              <div><dt>Reproducible</dt><dd>{job.bitwise_reproducible ? "Bit-identical on a repeat" : "Not from its seed"}</dd></div>
              <div><dt>Map set</dt><dd>{job.map_set_identity_key.slice(0, 12)}…</dd></div>
            </dl>
            <details className="technical-details">
              <summary>Command and raw output</summary>
              <pre>{job.command.join(" ")}</pre>
              <h4>stdout</h4><pre>{job.stdout || "(empty)"}</pre>
              <h4>stderr</h4><pre>{job.stderr || "(empty)"}</pre>
            </details>
          </section>
        ) : null}
      </aside>
    </>
  );
}

type ClusterSortKey =
  | "cluster_rank"
  | "lowest_binding_energy_kcal_mol"
  | "mean_binding_energy_kcal_mol"
  | "run_count";

type SortDirection = "ascending" | "descending";

function ClusterResults({ clusters, runs, selectedRun, onSelect }: {
  clusters: AutoDock4ClusterResult[];
  runs: AutoDock4RunResult[];
  selectedRun: number | null;
  onSelect: (run: number) => void;
}) {
  const [sortKey, setSortKey] = useState<ClusterSortKey>("cluster_rank");
  const [sortDirection, setSortDirection] = useState<SortDirection>("ascending");
  const [expandedRank, setExpandedRank] = useState<number | null>(
    clusters.length ? clusters[0].cluster_rank : null,
  );
  const byRun = useMemo(() => new Map(runs.map((item) => [item.run, item])), [runs]);
  const sorted = useMemo(
    () => [...clusters].sort((left, right) => {
      const factor = sortDirection === "ascending" ? 1 : -1;
      return (left[sortKey] - right[sortKey]) * factor;
    }),
    [clusters, sortDirection, sortKey],
  );
  // AutoDock ranks clusters by their lowest energy, so rank 1 is the best.
  const best = clusters.find((cluster) => cluster.cluster_rank === 1) ?? null;
  const totalRuns = clusters.reduce((sum, cluster) => sum + cluster.run_count, 0);

  function changeSort(nextKey: ClusterSortKey) {
    if (nextKey === sortKey) {
      setSortDirection((current) => current === "ascending" ? "descending" : "ascending");
      return;
    }
    setSortKey(nextKey);
    setSortDirection("ascending");
  }

  function toggleCluster(rank: number) {
    setExpandedRank((current) => current === rank ? null : rank);
  }

  return (
    <section className="docking-results library-docking-results" aria-label="AutoDock4 clusters">
      <div className="docking-results-heading">
        <div><span className="eyebrow">Conformational clusters</span><h3>AutoDock4 results</h3></div>
        <p>
          {best ? (
            <>
              <strong>Rank {best.cluster_rank}</strong> holds <strong>{best.run_count} of {totalRuns} runs</strong>
              {" "}at <strong>{formatScientificNumber(best.lowest_binding_energy_kcal_mol, 2)} kcal/mol</strong>.{" "}
            </>
          ) : null}
          AutoDock groups independent runs by RMSD. A larger cluster means the search kept finding the same
          solution; the energy is a computational estimate, not an experimental affinity.
        </p>
      </div>
      <div className="docking-results-scroll" tabIndex={0} aria-label="Scrollable cluster results table">
        <table>
          <thead>
            <tr>
              <ClusterSortHeader label="Cluster" sortKey="cluster_rank" activeKey={sortKey} direction={sortDirection} onSort={changeSort} />
              <ClusterSortHeader label="Lowest energy (kcal/mol)" sortKey="lowest_binding_energy_kcal_mol" activeKey={sortKey} direction={sortDirection} onSort={changeSort} />
              <ClusterSortHeader label="Mean energy (kcal/mol)" sortKey="mean_binding_energy_kcal_mol" activeKey={sortKey} direction={sortDirection} onSort={changeSort} />
              <ClusterSortHeader label="Runs in cluster" sortKey="run_count" activeKey={sortKey} direction={sortDirection} onSort={changeSort} />
              <th>Representative run</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((cluster) => {
              const expanded = cluster.cluster_rank === expandedRank;
              const holdsSelection = cluster.runs.includes(selectedRun ?? -1);
              return (
                <Fragment key={cluster.cluster_rank}>
                  <tr
                    className={holdsSelection ? "selected" : ""}
                    onClick={() => toggleCluster(cluster.cluster_rank)}
                    aria-expanded={expanded}
                  >
                    <td>
                      <button
                        type="button"
                        className="compound-expand"
                        aria-expanded={expanded}
                        onClick={(event) => { event.stopPropagation(); toggleCluster(cluster.cluster_rank); }}
                      >
                        <span aria-hidden="true">{expanded ? "▾" : "▸"}</span>
                        Rank {cluster.cluster_rank}
                        {cluster.cluster_rank === 1 ? <small>Best cluster</small> : null}
                      </button>
                    </td>
                    <td>{formatScientificNumber(cluster.lowest_binding_energy_kcal_mol, 2)}</td>
                    <td>{formatScientificNumber(cluster.mean_binding_energy_kcal_mol, 2)}</td>
                    <td>{cluster.run_count}</td>
                    <td>Run {cluster.representative_run}</td>
                  </tr>
                  {expanded ? (
                    <tr className="pose-expansion">
                      <td colSpan={5}>
                        <div className="compound-poses">
                          <div className="compound-poses-heading">
                            <strong>Rank {cluster.cluster_rank} · {cluster.run_count} run{cluster.run_count === 1 ? "" : "s"}</strong>
                            <small>Click a run to display that exact preserved conformation in the 3D viewer.</small>
                          </div>
                          <table>
                            <thead>
                              <tr>
                                <th>Run</th>
                                <th>Binding energy (kcal/mol)</th>
                                <th>Cluster RMSD (Å)</th>
                                <th>Reference RMSD (Å)</th>
                                <th>Artifact SHA-256</th>
                              </tr>
                            </thead>
                            <tbody>
                              {cluster.runs.map((run) => {
                                const result = byRun.get(run);
                                if (!result) return null;
                                return (
                                  <tr key={run} className={run === selectedRun ? "selected" : ""}>
                                    <td>
                                      <button
                                        type="button"
                                        className="pose-select"
                                        aria-pressed={run === selectedRun}
                                        onClick={(event) => { event.stopPropagation(); onSelect(run); }}
                                      >
                                        Run {run}
                                      </button>
                                    </td>
                                    <td>{formatScientificNumber(result.binding_energy_kcal_mol, 2)}</td>
                                    <td>{formatScientificNumber(result.cluster_rmsd_angstrom, 2)}</td>
                                    <td>{formatScientificNumber(result.reference_rmsd_angstrom, 2)}</td>
                                    <td><code>{result.artifact.sha256.slice(0, 16)}…</code></td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
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

function ClusterSortHeader({ label, sortKey, activeKey, direction, onSort }: {
  label: string;
  sortKey: ClusterSortKey;
  activeKey: ClusterSortKey;
  direction: SortDirection;
  onSort: (key: ClusterSortKey) => void;
}) {
  const active = sortKey === activeKey;
  return (
    <th aria-sort={active ? direction : "none"}>
      <button type="button" className="result-sort" onClick={() => onSort(sortKey)}>
        {label}
        <span aria-hidden="true">{active ? direction === "ascending" ? "↑" : "↓" : "↕"}</span>
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

/** The lowest-energy run of the top-ranked cluster, which is what AutoDock's own
 * ranking table puts first. */
function bestRun(job: JobView): AutoDock4RunResult {
  return [...job.runs].sort(
    (a, b) => a.cluster_rank - b.cluster_rank || a.sub_rank - b.sub_rank,
  )[0];
}

function gridPhaseLabel(job: AutoGridMapJobRecord): string {
  if (job.status === "cancel_requested") return "Canceling the native AutoGrid process";
  if (job.phase === "queued") return "Queued for grid generation";
  if (job.phase === "collecting_artifacts") return "Preserving and hashing every map";
  return "Computing affinity maps";
}

function dockingPhaseLabel(job: JobView): string {
  if (job.status === "cancel_requested") return "Canceling the native process";
  if (job.phase === "queued") {
    return job.backend === "autodock_gpu"
      ? "Queued for the GPU device"
      : "Queued for CPU execution";
  }
  if (job.phase === "parsing_results") return "Clustering runs and preserving conformations";
  return "Running independent Lamarckian GA searches";
}

function asMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}
