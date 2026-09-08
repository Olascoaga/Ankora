import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { ankoraApi } from "../../api/client";
import type { WorkspaceActivity } from "../../app/activity";
import type {
  BindingSiteRecord,
  DockingPoseResult,
  LigandDockingInput,
  LigandLibraryDockingInput,
  LigandRecord,
  ReceptorPreparationRecord,
  ToolsResponse,
  VinaDockingJobRecord,
  VinaDockingParameters,
} from "../../types/api";
import { MolecularViewer } from "../../viewer/MolecularViewer";
import type { ViewerSource } from "../../viewer/adapter";
import { formatScientificNumber } from "../../utils/format";
import { AutoDock4LibraryWorkspace } from "./AutoDock4LibraryWorkspace";
import { EngineComparisonWorkspace } from "./EngineComparisonWorkspace";
import { AutoDock4Workspace } from "./AutoDock4Workspace";
import { DockingModeSwitch } from "./DockingModeSwitch";
import type { DockingMode } from "./DockingModeSwitch";
import { LibraryDockingWorkspace } from "./LibraryDockingWorkspace";
import { VinaSamplingGuidance } from "./VinaSamplingGuidance";
import {
  applyVinaSamplingProtocol,
  isVinaSamplingParameter,
  vinaSamplingProtocolLabel,
  VinaSamplingProtocolControl,
} from "./VinaSamplingProtocol";
import type { VinaSamplingProtocol } from "./VinaSamplingProtocol";

interface DockingWorkspaceProps {
  receptor: ReceptorPreparationRecord;
  bindingSite: BindingSiteRecord;
  ligand: LigandRecord | null;
  ligandInput: LigandDockingInput | null;
  libraryInput?: LigandLibraryDockingInput | null;
  tools: ToolsResponse | null;
  onActivityChange?: (activity: WorkspaceActivity | null) => void;
}

const TERMINAL_STATUSES = new Set(["completed", "failed", "canceled"]);

function defaultParameters(): VinaDockingParameters {
  const logicalCores = typeof navigator === "undefined" ? 2 : navigator.hardwareConcurrency || 2;
  return {
    sampling_protocol: "screening",
    cpu_threads: Math.max(1, logicalCores - 1),
    seed: 20260823,
    exhaustiveness: 8,
    num_modes: 9,
    min_rmsd_angstrom: 1,
    energy_range_kcal_mol: 3,
    timeout_minutes: 360,
  };
}

export function DockingWorkspace(props: DockingWorkspaceProps) {
  const [mode, setMode] = useState<DockingMode>(
    props.libraryInput ? "screening" : "single",
  );
  const modeSwitch = (
    <DockingModeSwitch
      mode={mode}
      hasLibrary={Boolean(props.libraryInput)}
      onChange={setMode}
    />
  );
  if (mode === "screening" && props.libraryInput) {
    return (
      <LibraryDockingWorkspace
        {...props}
        libraryInput={props.libraryInput}
        modeSwitch={modeSwitch}
      />
    );
  }
  if (mode === "comparison") {
    return (
      <EngineComparisonWorkspace
        receptorId={props.receptor.receptor_id}
        bindingSiteId={props.bindingSite.binding_site_id}
        filterRunId={props.libraryInput?.filter_run_id ?? null}
        modeSwitch={modeSwitch}
      />
    );
  }
  if (mode === "autodock4-screening" && props.libraryInput) {
    return (
      <AutoDock4LibraryWorkspace
        {...props}
        libraryInput={props.libraryInput}
        modeSwitch={modeSwitch}
      />
    );
  }
  if (mode === "autodock4") {
    return <AutoDock4Workspace {...props} modeSwitch={modeSwitch} />;
  }
  return <SingleLigandDockingWorkspace {...props} modeSwitch={modeSwitch} />;
}

interface SingleLigandDockingWorkspaceProps extends DockingWorkspaceProps {
  modeSwitch?: ReactNode;
}

function SingleLigandDockingWorkspace({
  receptor,
  bindingSite,
  ligand,
  ligandInput,
  tools,
  onActivityChange,
  modeSwitch,
}: SingleLigandDockingWorkspaceProps) {
  const [parameters, setParameters] = useState<VinaDockingParameters>(defaultParameters);
  const [acknowledged, setAcknowledged] = useState(false);
  const [job, setJob] = useState<VinaDockingJobRecord | null>(null);
  const [selectedMode, setSelectedMode] = useState<number | null>(null);
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
  const selectedPose = job?.poses.find((pose) => pose.mode === selectedMode) ?? null;
  const active = Boolean(job && !TERMINAL_STATUSES.has(job.status));
  const ready = Boolean(
    tools?.vina.available
    && tools.vina.version === "1.2.7"
    && receptorPdbqt
    && ligand
    && ligandPdbqt,
  );

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
        // The preserved source remains PDBQT. This selects only Mol*'s
        // compatible PDB coordinate parser for visualization.
        format: "pdb",
        label: `Vina pose ${selectedPose.mode}`,
      });
    }
    return sources;
  }, [displayOutput, selectedPose]);

  useEffect(() => {
    if (!job || TERMINAL_STATUSES.has(job.status)) return;
    let disposed = false;
    const timer = window.setInterval(() => {
      void ankoraApi.getDockingJob(job.job_id)
        .then((next) => {
          if (!disposed) {
            setJob(next);
            if (next.status === "completed" && next.poses.length && selectedMode === null) {
              setSelectedMode(next.poses[0].mode);
            }
          }
        })
        .catch((reason: unknown) => {
          if (!disposed) setError(reason instanceof Error ? reason.message : "Docking status could not be refreshed.");
        });
    }, 500);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [job, selectedMode]);

  useEffect(() => {
    if (!onActivityChange) return;
    if (!job || TERMINAL_STATUSES.has(job.status)) {
      onActivityChange(null);
      return;
    }
    onActivityChange({
      title: "AutoDock Vina",
      detail: phaseLabel(job),
      workers: job.request.parameters.cpu_threads,
    });
  }, [job, onActivityChange]);

  function updateParameter(
    name: Exclude<keyof VinaDockingParameters, "sampling_protocol">,
    value: number,
  ) {
    setAcknowledged(false);
    setParameters((current) => ({
      ...current,
      [name]: value,
      ...(isVinaSamplingParameter(name) ? { sampling_protocol: "custom" as const } : {}),
    }));
  }

  function selectSamplingProtocol(protocol: VinaSamplingProtocol) {
    setAcknowledged(false);
    setParameters((current) => applyVinaSamplingProtocol(current, protocol));
  }

  async function startDocking() {
    if (!ligand || !ligandPdbqt || !ready) return;
    setError(null);
    setSelectedMode(null);
    try {
      const next = await ankoraApi.startVinaDocking({
        receptor_id: receptor.receptor_id,
        binding_site_id: bindingSite.binding_site_id,
        ligand_id: ligand.artifact.ligand_id,
        ligand_preparation_id: ligandPdbqt.artifact.preparation_id,
        parameters,
        acknowledge_inputs_and_scoring: acknowledged,
      });
      setJob(next);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "AutoDock Vina could not be started.");
    }
  }

  async function cancelDocking() {
    if (!job) return;
    try {
      await ankoraApi.cancelDockingJob(job.job_id);
      setJob((current) => current ? { ...current, status: "cancel_requested" } : current);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "The docking job could not be canceled.");
    }
  }

  return (
    <>
      <section className="workspace docking-workspace" aria-label="Docking workspace">
        <div className="workspace-heading">
          <div><span className="eyebrow">05 / Docking</span><h2>Run and inspect a reproducible docking experiment</h2></div>
          <div className="workspace-actions">
            {modeSwitch}
            <span className="read-only-badge">M5 · AutoDock Vina 1.2.7</span>
          </div>
        </div>
        {active ? (
          <div className="operation-progress" role="progressbar" aria-label="AutoDock Vina running">
            <span /><p>{phaseLabel(job!)} · {job!.request.parameters.cpu_threads} CPU threads</p>
          </div>
        ) : null}
        {error ? <div className="structure-error" role="alert">{error}</div> : null}
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
          <PoseResults poses={job.poses} selectedMode={selectedMode} onSelect={setSelectedMode} />
        ) : null}
      </section>
      <aside className="inspector docking-inspector" aria-label="Docking setup inspector">
        <div className="inspector-heading">
          <span className="section-label">Docking experiment</span>
          <h2>AutoDock Vina</h2>
          <p className="inspector-subtitle">One prepared ligand, one immutable receptor, and one finalized search space.</p>
        </div>
        <section className="receptor-section">
          <div className="filter-heading"><span>1 · Scientific inputs</span></div>
          <InputState ready={Boolean(receptorPdbqt)} label="Receptor PDBQT" detail={receptorPdbqt ? `${receptorPdbqt.filename} · ${receptorPdbqt.sha256.slice(0, 12)}…` : "Return to Receptor and generate PDBQT."} />
          <InputState ready label="Binding site" detail={`${formatScientificNumber(bindingSite.box.size_x, 1)} × ${formatScientificNumber(bindingSite.box.size_y, 1)} × ${formatScientificNumber(bindingSite.box.size_z, 1)} Å · ${bindingSite.binding_site_id.slice(0, 8)}…`} />
          <InputState ready={Boolean(ligandPdbqt)} label="Ligand PDBQT" detail={ligandPdbqt ? `${ligand?.inspection.name ?? "Ligand"} · ${ligandPdbqt.artifact.sha256.slice(0, 12)}…` : "Return to Ligand, minimize it, and generate PDBQT."} />
        </section>
        <section className="receptor-section">
          <div className="filter-heading"><span>2 · Engine & search</span><small>{tools?.vina.available ? tools.vina.version : "Unavailable"}</small></div>
          <div className={tools?.vina.available ? "state-resolved-note" : "protonation-blocker"}>
            <strong>AutoDock Vina 1.2.7</strong>
            <small>{tools?.vina.available ? tools.vina.path : "Install or configure the official Windows executable."}</small>
          </div>
          <VinaSamplingProtocolControl
            protocol={parameters.sampling_protocol ?? "custom"}
            disabled={active}
            onChange={selectSamplingProtocol}
          />
          <div className="docking-parameter-grid">
            <NumberField label="CPU threads" value={parameters.cpu_threads} min={1} max={256} disabled={active} onChange={(value) => updateParameter("cpu_threads", value)} />
            <NumberField label="Seed" value={parameters.seed} min={1} max={2147483647} disabled={active} onChange={(value) => updateParameter("seed", value)} />
            <NumberField label="Exhaustiveness" value={parameters.exhaustiveness} min={1} max={128} disabled={active} onChange={(value) => updateParameter("exhaustiveness", value)} />
            <NumberField label="Maximum poses" value={parameters.num_modes} min={1} max={100} disabled={active} onChange={(value) => updateParameter("num_modes", value)} />
            <NumberField label="Minimum RMSD (Å)" value={parameters.min_rmsd_angstrom} min={0} max={20} step={0.1} disabled={active} onChange={(value) => updateParameter("min_rmsd_angstrom", value)} />
            <NumberField label="Energy range (kcal/mol)" value={parameters.energy_range_kcal_mol} min={0} max={100} step={0.5} disabled={active} onChange={(value) => updateParameter("energy_range_kcal_mol", value)} />
            <NumberField label="Timeout (minutes)" value={parameters.timeout_minutes} min={1} max={2880} disabled={active} onChange={(value) => updateParameter("timeout_minutes", value)} />
          </div>
          <VinaSamplingGuidance box={bindingSite.box} exhaustiveness={parameters.exhaustiveness} showWithinBoundary />
        </section>
        <section className="receptor-section">
          <div className="filter-heading"><span>3 · Confirm & run</span>{job ? <small>{job.status.replaceAll("_", " ")}</small> : null}</div>
          <label className="docking-acknowledgement">
            <input type="checkbox" checked={acknowledged} disabled={active} onChange={(event) => setAcknowledged(event.target.checked)} />
            <span><strong>Use these exact inputs and parameters</strong><small>I understand that a Vina score is a computational ranking in kcal/mol, not an experimental binding affinity.</small></span>
          </label>
          {active ? (
            <button type="button" className="danger-action docking-primary-action" onClick={() => void cancelDocking()} disabled={job?.status === "cancel_requested"}>Cancel docking</button>
          ) : (
            <button type="button" className="primary-action docking-primary-action" onClick={() => void startDocking()} disabled={!ready || !acknowledged}>Run AutoDock Vina</button>
          )}
          {!ready ? <p className="field-note">Complete the missing PDBQT input above before docking. Ankora will not substitute another molecular state silently.</p> : null}
        </section>
        {job ? (
          <section className="receptor-section">
            <div className="filter-heading"><span>4 · Evidence</span><small>{job.job_id.slice(0, 8)}…</small></div>
            <dl className="docking-evidence">
              <div><dt>Engine</dt><dd>{job.tool.name} {job.tool.version}</dd></div>
              <div><dt>Purpose</dt><dd>{vinaSamplingProtocolLabel(job.request.parameters.sampling_protocol)}</dd></div>
              <div><dt>Poses</dt><dd>{job.poses.length}</dd></div>
              <div><dt>Seed</dt><dd>{job.request.parameters.seed}</dd></div>
              <div><dt>CPU</dt><dd>{job.request.parameters.cpu_threads} threads</dd></div>
            </dl>
            <details className="technical-details">
              <summary>Command and raw output</summary>
              <pre>{job.command.join(" ")}</pre>
              {job.execution ? <><h4>stdout</h4><pre>{job.execution.stdout || "(empty)"}</pre><h4>stderr</h4><pre>{job.execution.stderr || "(empty)"}</pre></> : null}
            </details>
          </section>
        ) : null}
      </aside>
    </>
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

function PoseResults({ poses, selectedMode, onSelect }: {
  poses: DockingPoseResult[];
  selectedMode: number | null;
  onSelect: (mode: number) => void;
}) {
  return (
    <section className="docking-results" aria-label="Vina docking poses">
      <div className="docking-results-heading">
        <div><span className="eyebrow">Ranked poses</span><h3>AutoDock Vina results</h3></div>
        <p>Lower scores rank more favorably within this calculation; they are not experimental affinities.</p>
      </div>
      <div className="docking-results-scroll">
        <table>
          <thead><tr><th>Pose</th><th>Vina score (kcal/mol)</th><th>RMSD lower bound (Å)</th><th>RMSD upper bound (Å)</th><th>Artifact</th></tr></thead>
          <tbody>{poses.map((pose) => (
            <tr key={pose.mode} className={pose.mode === selectedMode ? "selected" : ""} onClick={() => onSelect(pose.mode)}>
              <td><button type="button" className="pose-select" aria-pressed={pose.mode === selectedMode} onClick={() => onSelect(pose.mode)}>Pose {pose.mode}</button></td>
              <td>{formatScientificNumber(pose.affinity_kcal_mol, 3)}</td>
              <td>{formatScientificNumber(pose.rmsd_lower_bound_angstrom, 3)}</td>
              <td>{formatScientificNumber(pose.rmsd_upper_bound_angstrom, 3)}</td>
              <td><code>{pose.artifact.sha256.slice(0, 12)}…</code></td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </section>
  );
}

function phaseLabel(job: VinaDockingJobRecord): string {
  if (job.status === "cancel_requested") return "Canceling the native Vina process";
  if (job.phase === "queued") return "Queued for CPU execution";
  if (job.phase === "parsing_poses") return "Validating and preserving poses";
  return "Searching the finalized binding site";
}
