import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { ankoraApi } from "../../api/client";
import type { WorkspaceActivity } from "../../app/activity";
import type { BindingSiteRecord, GninaDockingJobRecord, GninaDockingParameters, LigandDockingInput, LigandRecord, ReceptorPreparationRecord, ToolsResponse } from "../../types/api";
import { formatScientificNumber } from "../../utils/format";
import { MolecularViewer } from "../../viewer/MolecularViewer";
import type { ViewerSource } from "../../viewer/adapter";
import {
  defaultGninaParameters,
  GNINA_NUMERIC_FIELDS,
  gninaParametersValid,
} from "./gninaParameters";

interface Props {
  receptor: ReceptorPreparationRecord;
  bindingSite: BindingSiteRecord;
  ligand: LigandRecord | null;
  ligandInput: LigandDockingInput | null;
  tools: ToolsResponse | null;
  modeSwitch: ReactNode;
  onActivityChange?: (activity: WorkspaceActivity | null) => void;
}

const terminal = new Set(["completed", "failed", "canceled"]);

export function GninaWorkspace({ receptor, bindingSite, ligand, ligandInput, tools, modeSwitch, onActivityChange }: Props) {
  const [parameters, setParameters] = useState<GninaDockingParameters>(defaultGninaParameters);
  const [acknowledged, setAcknowledged] = useState(false);
  const [job, setJob] = useState<GninaDockingJobRecord | null>(null);
  const [selectedMode, setSelectedMode] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [recovering, setRecovering] = useState(true);
  const active = starting || Boolean(job && !terminal.has(job.status));
  const receptorPdbqt = receptor.outputs.find((item) => item.stage === "pdbqt");
  const display = receptor.outputs.find((item) => item.artifact_id === receptor.display_output_artifact_id);
  const ligandPdbqt = ligand && ligandInput?.ligand_id === ligand.artifact.ligand_id ? ligandInput.pdbqt : null;
  const ready = Boolean(!recovering && tools?.gnina.available && receptorPdbqt && ligand && ligandPdbqt && !bindingSite.stale && gninaParametersValid(parameters));
  const selectedPose = job?.poses.find((pose) => pose.mode === selectedMode);
  const viewerSources = useMemo<ViewerSource[]>(() => {
    const sources: ViewerSource[] = [];
    if (display?.format === "pdb") sources.push({ id: display.artifact_id, url: ankoraApi.receptorOutputUrl(display.content_url), format: "pdb", label: `Prepared receptor · ${display.filename}` });
    if (job && selectedPose) sources.push({ id: selectedPose.artifact.artifact_id, url: ankoraApi.gninaPoseUrl(job.job_id, selectedPose.artifact.artifact_id), format: "pdb", label: `GNINA pose ${selectedPose.mode}` });
    return sources;
  }, [display, job, selectedPose]);

  useEffect(() => {
    let disposed = false;
    setJob(null); setSelectedMode(null); setError(null); setAcknowledged(false); setRecovering(true);
    if (!ligand || !ligandPdbqt) { setRecovering(false); return () => { disposed = true; }; }
    const key = `ankora:gnina:${receptor.receptor_id}:${bindingSite.binding_site_id}:${ligand.artifact.ligand_id}:${ligandPdbqt.artifact.preparation_id}`;
    let jobId: string | null = null;
    try { jobId = window.localStorage.getItem(key); } catch { /* storage is optional */ }
    if (!jobId) { setRecovering(false); return () => { disposed = true; }; }
    void ankoraApi.getGninaDockingJob(jobId).then((next) => {
      if (disposed) return;
      if (next.request.receptor_id !== receptor.receptor_id || next.request.binding_site_id !== bindingSite.binding_site_id || next.request.ligand_id !== ligand.artifact.ligand_id || next.request.ligand_preparation_id !== ligandPdbqt.artifact.preparation_id) throw new Error("The saved GNINA job does not match the selected inputs.");
      setJob(next);
      setParameters(next.request.parameters);
      if (next.status === "completed" && next.poses.length) setSelectedMode(next.poses[0].mode);
    }).catch((reason: unknown) => {
      if (!disposed) setError(reason instanceof Error ? reason.message : "The saved GNINA job could not be loaded.");
    }).finally(() => { if (!disposed) setRecovering(false); });
    return () => { disposed = true; };
  }, [receptor.receptor_id, bindingSite.binding_site_id, ligand?.artifact.ligand_id, ligandPdbqt?.artifact.preparation_id]);

  useEffect(() => {
    if (!job || terminal.has(job.status)) return;
    let disposed = false;
    let timer: number;
    const poll = async () => {
      try {
        const next = await ankoraApi.getGninaDockingJob(job.job_id);
        if (disposed) return;
        setJob((current) => current?.status === "cancel_requested" && !terminal.has(next.status) ? { ...next, status: "cancel_requested" } : next);
        if (next.status === "completed" && next.poses.length) setSelectedMode((current) => current ?? next.poses[0].mode);
      } catch (reason) {
        if (!disposed) setError(reason instanceof Error ? reason.message : "GNINA status could not be refreshed.");
      }
      if (!disposed) timer = window.setTimeout(() => void poll(), 1000);
    };
    timer = window.setTimeout(() => void poll(), 500);
    return () => { disposed = true; window.clearTimeout(timer); };
  }, [job?.job_id, job?.status]);

  useEffect(() => {
    if (!onActivityChange) return;
    onActivityChange(active ? { title: "GNINA", detail: job?.status === "cancel_requested" ? "Canceling GNINA" : "Running GNINA docking", workers: job && !terminal.has(job.status) ? job.request.parameters.cpu_threads : parameters.cpu_threads } : null);
    return () => onActivityChange(null);
  }, [active, job?.status, onActivityChange, parameters.cpu_threads]);

  function update<K extends keyof GninaDockingParameters>(name: K, value: GninaDockingParameters[K]) {
    setAcknowledged(false);
    setParameters((current) => ({ ...current, [name]: value }));
  }
  async function start() {
    if (!ready || !acknowledged || !ligand || !ligandPdbqt || active) return;
    setStarting(true); setError(null);
    try {
      const next = await ankoraApi.startGninaDocking({ receptor_id: receptor.receptor_id, binding_site_id: bindingSite.binding_site_id, ligand_id: ligand.artifact.ligand_id, ligand_preparation_id: ligandPdbqt.artifact.preparation_id, parameters, acknowledge_inputs_and_scoring: true });
      try { window.localStorage.setItem(`ankora:gnina:${receptor.receptor_id}:${bindingSite.binding_site_id}:${ligand.artifact.ligand_id}:${ligandPdbqt.artifact.preparation_id}`, next.job_id); } catch { /* job is still recorded by the backend */ }
      setJob(next);
      setSelectedMode(next.status === "completed" && next.poses.length ? next.poses[0].mode : null);
    } catch (reason) { setError(`Could not start a new GNINA job: ${reason instanceof Error ? reason.message : "Unknown error"}`); }
    finally { setStarting(false); }
  }
  async function cancel() {
    if (!job || starting || terminal.has(job.status)) return;
    try {
      const result = await ankoraApi.cancelGninaDockingJob(job.job_id);
      if (terminal.has(result.status)) {
        const refreshed = await ankoraApi.getGninaDockingJob(job.job_id);
        setJob(refreshed);
        if (refreshed.status === "completed" && refreshed.poses.length) setSelectedMode((current) => current ?? refreshed.poses[0].mode);
      } else {
        setJob((current) => current && !terminal.has(current.status) ? { ...current, status: result.status } : current);
      }
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : "GNINA could not be canceled."); }
  }

  return <>
    <section className="workspace docking-workspace" aria-label="GNINA docking workspace">
      <div className="workspace-heading"><div><span className="eyebrow">05 / Docking</span><h2>Dock a ligand with GNINA</h2></div><div className="workspace-actions">{modeSwitch}<span className="read-only-badge">GNINA · Linux</span></div></div>
      {active ? <div className="operation-progress" role="progressbar" aria-label="GNINA running"><span /><p>{job?.status === "cancel_requested" ? "Canceling GNINA" : "Running GNINA"}</p></div> : null}
      {error ? <div className="structure-error" role="alert">{error}</div> : null}
      {job?.failure ? <div className="structure-error" role="alert"><strong>{job.failure.message}</strong> <span>{job.failure.code}</span><details><summary>Technical evidence</summary><pre>{JSON.stringify(job.failure.details, null, 2)}</pre></details></div> : null}
      {viewerSources.length ? <MolecularViewer sources={viewerSources} selection={null} dockingBox={bindingSite.box} /> : <div className="viewer-placeholder ligand-placeholder"><div className="viewer-message"><h3>Prepared receptor unavailable</h3></div></div>}
      {job?.status === "completed" ? <section className="docking-results" aria-label="GNINA docking poses"><div className="docking-results-heading"><div><span className="eyebrow">Engine-ranked poses</span><h3>GNINA results</h3></div><p>Higher CNN score ranks poses first. CNN affinity is predicted pK; higher predicts stronger affinity. CNN_VS is CNNscore × CNNaffinity. Minimized affinity is in kcal/mol. Neither is measured affinity.</p></div><div className="docking-results-scroll"><table><thead><tr><th>Pose</th><th>CNN score</th><th>CNN affinity (pK)</th><th>CNN_VS</th><th>Minimized affinity (kcal/mol)</th><th>Artifact</th></tr></thead><tbody>{job.poses.map((pose) => <tr key={pose.mode} className={pose.mode === selectedMode ? "selected" : ""}><td><button type="button" className="pose-select" aria-pressed={pose.mode === selectedMode} onClick={() => setSelectedMode(pose.mode)}>Pose {pose.mode}</button></td><td>{formatScientificNumber(pose.cnn_score, 4)}</td><td>{formatScientificNumber(pose.cnn_affinity, 3)}</td><td>{pose.cnn_vs != null ? formatScientificNumber(pose.cnn_vs, 3) : "—"}</td><td>{formatScientificNumber(pose.minimized_affinity_kcal_mol, 3)}</td><td><code>{pose.artifact.sha256.slice(0, 12)}…</code></td></tr>)}</tbody></table></div></section> : null}
    </section>
    <aside className="inspector docking-inspector" aria-label="GNINA setup inspector">
      <div className="inspector-heading"><span className="section-label">Docking experiment</span><h2>GNINA</h2><p className="inspector-subtitle">One prepared ligand and one finalized search space. The latest matching job can be reopened here on this device; the full Results catalog is not yet available for GNINA.</p></div>
      <section className="receptor-section"><div className="filter-heading"><span>1 · Scientific inputs</span></div><div className={receptorPdbqt ? "state-resolved-note" : "protonation-blocker"}><strong>Receptor PDBQT</strong><small>{receptorPdbqt?.filename ?? "Prepare the receptor first."}</small></div><div className={!bindingSite.stale ? "state-resolved-note" : "protonation-blocker"}><strong>Binding site</strong><small>{bindingSite.stale ? "The binding site is stale." : `${bindingSite.box.size_x} × ${bindingSite.box.size_y} × ${bindingSite.box.size_z} Å`}</small></div><div className={ligandPdbqt ? "state-resolved-note" : "protonation-blocker"}><strong>Ligand PDBQT</strong><small>{ligandPdbqt?.artifact.filename ?? "Prepare the selected ligand first."}</small></div></section>
      <section className="receptor-section"><div className="filter-heading"><span>2 · Engine & search</span></div><div className={tools?.gnina.available ? "state-resolved-note" : "protonation-blocker"}><strong>GNINA 1.3.3</strong><small>{tools?.gnina.available ? "Detected; version and executable identity are checked at launch." : "Configure the Linux GNINA executable and rescan tools."}</small></div>
        <label className="numeric-field"><span className="field-label">Compute</span><select aria-label="Compute" value={parameters.compute} disabled={active} onChange={(event) => update("compute", event.target.value as "cpu" | "cuda")}><option value="cpu">CPU</option><option value="cuda">NVIDIA GPU · CUDA</option></select></label>
        {parameters.compute === "cuda" ? <p className="field-note">CUDA currently requires one identifiable NVIDIA GPU, device 0, without MIG or device visibility remapping. Ankora checks the process and device before publishing results.</p> : null}
        <div className="docking-parameter-grid">{GNINA_NUMERIC_FIELDS.map(({ key, label, min, max, step }) => <label className="numeric-field" key={key}><span className="field-label">{label}</span><input aria-label={label} type="number" min={min} max={max} step={step} disabled={active} value={Number.isNaN(parameters[key]) ? "" : parameters[key]} onChange={(event) => update(key, event.target.value === "" ? Number.NaN : Number(event.target.value))} /></label>)}</div>
        <p className="field-note">CNN rescoring · dense_1_3 · prepared PDBQT hydrogens preserved. Poses retain GNINA's CNN-score order.</p>
      </section>
      <section className="receptor-section"><div className="filter-heading"><span>3 · Confirm & run</span>{job ? <small>{job.status.replaceAll("_", " ")}</small> : null}</div><label className="docking-acknowledgement"><input type="checkbox" checked={acknowledged} disabled={active} onChange={(event) => setAcknowledged(event.target.checked)} /><span><strong>Use these exact inputs and parameters</strong><small>GNINA scores are predictions and are not experimental binding affinities.</small></span></label>{active ? <button type="button" className="danger-action docking-primary-action" onClick={() => void cancel()} disabled={starting || !job || terminal.has(job.status) || job.status === "cancel_requested"}>Cancel docking</button> : <button type="button" className="primary-action docking-primary-action" disabled={!ready || !acknowledged} onClick={() => void start()}>Run GNINA</button>}{!ready ? <p className="field-note">Check the prepared inputs, GNINA availability and parameter ranges above.</p> : null}</section>
      {job ? <section className="receptor-section"><div className="filter-heading"><span>4 · Evidence</span><small>{job.job_id.slice(0, 8)}…</small></div><dl className="docking-evidence"><div><dt>Engine</dt><dd>GNINA {job.tool.version}</dd></div><div><dt>Model</dt><dd>{job.request.parameters.cnn_model}</dd></div><div><dt>Compute</dt><dd>{job.request.parameters.compute.toUpperCase()}</dd></div><div><dt>GPU observed</dt><dd>{job.request.parameters.compute === "cpu" ? "Not applicable (CPU)" : !job.execution ? "Not recorded" : job.execution.gpu_process_observed ? "Yes" : "No"}</dd></div></dl><details className="technical-details"><summary>Command and raw output</summary><pre>{job.command.join(" ")}</pre>{job.execution ? <><h4>stdout</h4><pre>{job.execution.stdout || "(empty)"}</pre><h4>stderr</h4><pre>{job.execution.stderr || "(empty)"}</pre></> : null}</details></section> : null}
    </aside>
  </>;
}
