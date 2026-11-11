import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { ankoraApi } from "../../api/client";
import type { WorkspaceActivity } from "../../app/activity";
import type {
  BindingSiteRecord,
  GninaDockingJobRecord,
  GninaDockingParameters,
  GninaPoseResult,
  GninaScreeningCampaignRecord,
  GninaScreeningEntry,
  GninaScreeningProgress,
  LigandLibraryDockingInput,
  ReceptorPreparationRecord,
  ToolsResponse,
} from "../../types/api";
import { formatScientificNumber } from "../../utils/format";
import { MolecularViewer } from "../../viewer/MolecularViewer";
import type { ViewerSource } from "../../viewer/adapter";
import {
  defaultGninaParameters,
  GNINA_NUMERIC_FIELDS,
  gninaParametersValid,
} from "./gninaParameters";

/**
 * A GNINA campaign over one applied filter selection, on Linux only.
 *
 * Two things shape this whole view. First, the campaign record holds no scores:
 * an entry names the single GNINA job that docked the molecule, and that job
 * owns the poses, the command and the execution evidence. So a score shown here
 * was read from the individual job, and a molecule whose job has not been read
 * has no score to show rather than a blank that looks like a result.
 *
 * Second, the campaign runs one job at a time. `worker_count` is a recorded fact
 * of the run, not a setting, and nothing here offers concurrency.
 *
 * Actions that exist for a single-ligand GNINA job and do not exist for a
 * campaign are listed as unavailable instead of being left to look broken.
 */

interface GninaScreeningWorkspaceProps {
  receptor: ReceptorPreparationRecord;
  bindingSite: BindingSiteRecord;
  libraryInput: LigandLibraryDockingInput;
  tools: ToolsResponse | null;
  modeSwitch?: ReactNode;
  onActivityChange?: (activity: WorkspaceActivity | null) => void;
}

const TERMINAL = new Set(["completed", "failed", "canceled"]);

type EntrySortKey = "selection" | "name" | "cnn_score" | "status";
type SortDirection = "ascending" | "descending";

export function GninaScreeningWorkspace({
  receptor,
  bindingSite,
  libraryInput,
  tools,
  modeSwitch,
  onActivityChange,
}: GninaScreeningWorkspaceProps) {
  const [parameters, setParameters] = useState<GninaDockingParameters>(defaultGninaParameters);
  const [acknowledged, setAcknowledged] = useState(false);
  const [campaign, setCampaign] = useState<GninaScreeningCampaignRecord | null>(null);
  const [jobs, setJobs] = useState<Record<string, GninaDockingJobRecord>>({});
  const [jobErrors, setJobErrors] = useState<Record<string, string>>({});
  const [loadingJobs, setLoadingJobs] = useState(false);
  const [expandedLigandId, setExpandedLigandId] = useState<string | null>(null);
  const [selectedLigandId, setSelectedLigandId] = useState<string | null>(null);
  const [selectedMode, setSelectedMode] = useState<number | null>(null);
  const [sortKey, setSortKey] = useState<EntrySortKey>("selection");
  const [sortDirection, setSortDirection] = useState<SortDirection>("ascending");
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const [history, setHistory] = useState<GninaScreeningProgress[]>([]);
  const [openingHistory, setOpeningHistory] = useState(false);
  const revisionRef = useRef(0);
  const startInFlight = useRef(false);
  const loadingJobIds = useRef(new Set<string>());
  const campaignIdRef = useRef<string | null>(null);
  campaignIdRef.current = campaign?.campaign_id ?? null;
  // Which molecule the scientist is actually looking at, so a job that resolves
  // late never moves the viewer to a pose of a molecule they have left.
  const openedLigandRef = useRef<string | null>(null);

  const storageKey = `ankora:gnina-screening:${receptor.receptor_id}:${bindingSite.binding_site_id}`
    + `:${libraryInput.library_id}:${libraryInput.filter_run_id}`;
  const displayOutput = receptor.outputs.find(
    (item) => item.artifact_id === receptor.display_output_artifact_id,
  );
  const receptorPdbqt = receptor.outputs.find((item) => item.stage === "pdbqt");
  const active = Boolean(campaign && !TERMINAL.has(campaign.status));
  const controlsLocked = active || starting || restoring || openingHistory;
  const preparedCount = Math.min(libraryInput.prepared_count, libraryInput.selected_count);
  const unpreparedCount = libraryInput.selected_count - preparedCount;
  const ready = Boolean(
    !restoring
    && tools?.gnina.available
    && receptorPdbqt
    && !bindingSite.stale
    && preparedCount > 0
    && gninaParametersValid(parameters),
  );

  const entries = campaign?.entries ?? [];
  const runningCount = entries.filter(
    (entry) => entry.status === "running" || entry.status === "cancel_requested",
  ).length;
  const queuedCount = entries.filter((entry) => entry.status === "queued").length;
  const preflightFailureCount = entries.filter(isPreflightFailure).length;
  const engineFailureCount = campaign ? campaign.failed_count - preflightFailureCount : 0;
  const progressPercent = campaign && campaign.selected_count > 0
    ? Math.round((100 * campaign.completed_count) / campaign.selected_count)
    : 0;
  const succeededEntries = entries.filter(
    (entry) => entry.status === "completed" && entry.gnina_job_id !== null,
  );
  const unreadScoreCount = succeededEntries.filter(
    (entry) => entry.gnina_job_id !== null && jobs[entry.gnina_job_id]?.status !== "completed",
  ).length;

  const selectedEntry = entries.find((entry) => entry.ligand_id === selectedLigandId) ?? null;
  const selectedJob = selectedEntry?.gnina_job_id ? jobs[selectedEntry.gnina_job_id] ?? null : null;
  const selectedPose = selectedJob?.poses.find((pose) => pose.mode === selectedMode) ?? null;

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
    if (selectedJob && selectedPose && selectedEntry) {
      sources.push({
        id: selectedPose.artifact.artifact_id,
        url: ankoraApi.gninaPoseUrl(selectedJob.job_id, selectedPose.artifact.artifact_id),
        // The preserved artifact remains PDBQT; this only selects Mol*'s
        // compatible coordinate parser.
        format: "pdb",
        label: `${entryLabel(selectedEntry)} · GNINA pose ${selectedPose.mode}`,
      });
    }
    return sources;
  }, [displayOutput, selectedEntry, selectedJob, selectedPose]);

  // A campaign outlives the session that launched it. This device remembers the
  // last campaign identifier for exactly these inputs; the backend record is
  // the authority, and a record that does not name these inputs is refused
  // rather than displayed over a different selection.
  useEffect(() => {
    let disposed = false;
    setRestoring(true);
    setCampaign(null);
    setJobs({});
    setJobErrors({});
    setSelectedLigandId(null);
    setSelectedMode(null);
    setExpandedLigandId(null);
    setError(null);
    setAcknowledged(false);
    revisionRef.current = 0;
    let campaignId: string | null = null;
    try {
      campaignId = window.localStorage.getItem(storageKey);
    } catch {
      /* storage is optional */
    }
    if (!campaignId) {
      setRestoring(false);
      return () => { disposed = true; };
    }
    void ankoraApi.getGninaScreening(campaignId)
      .then((record) => {
        if (disposed) return;
        const mismatch = describeInputMismatch(record, receptor, bindingSite, libraryInput);
        if (mismatch) throw new Error(mismatch);
        revisionRef.current = record.revision;
        setCampaign(record);
        setParameters(record.request.parameters);
      })
      .catch((reason: unknown) => {
        if (!disposed) {
          setError(asMessage(reason, "The saved GNINA campaign could not be loaded."));
        }
      })
      .finally(() => { if (!disposed) setRestoring(false); });
    return () => { disposed = true; };
  }, [storageKey]);

  useEffect(() => {
    let disposed = false;
    void ankoraApi.listGninaScreenings().then((items) => {
      if (!disposed) setHistory(items);
    }).catch((reason: unknown) => {
      if (!disposed) setError(asMessage(reason, "Recorded GNINA campaigns could not be listed."));
    });
    return () => { disposed = true; };
  }, [storageKey, campaign?.campaign_id, campaign?.status]);

  async function openRecordedCampaign(campaignId: string) {
    if (controlsLocked || campaignId === campaign?.campaign_id) return;
    setOpeningHistory(true);
    setError(null);
    try {
      const record = await ankoraApi.getGninaScreening(campaignId);
      const mismatch = describeInputMismatch(record, receptor, bindingSite, libraryInput);
      if (mismatch) throw new Error(mismatch);
      revisionRef.current = record.revision;
      setCampaign(record);
      setParameters(record.request.parameters);
      setJobs({});
      setJobErrors({});
      setSelectedLigandId(null);
      setSelectedMode(null);
      setExpandedLigandId(null);
      openedLigandRef.current = null;
      try { window.localStorage.setItem(storageKey, record.campaign_id); } catch { /* optional */ }
    } catch (reason: unknown) {
      setError(asMessage(reason, "The recorded GNINA campaign could not be opened."));
    } finally {
      setOpeningHistory(false);
    }
  }

  // Poll the compact header; fetch only the entries that actually changed.
  useEffect(() => {
    if (!campaign || TERMINAL.has(campaign.status)) return;
    const campaignId = campaign.campaign_id;
    let disposed = false;
    let refreshing = false;
    const timer = window.setInterval(() => {
      if (refreshing) return;
      refreshing = true;
      void (async () => {
        try {
          const progress = await ankoraApi.getGninaScreeningProgress(campaignId);
          if (disposed) return;
          if (progress.revision < revisionRef.current) return;
          const previousRevision = revisionRef.current;
          const received = progress.revision > previousRevision
            ? await ankoraApi.getGninaScreeningEntries(campaignId, previousRevision)
            : [];
          if (disposed) return;
          if (progress.revision < revisionRef.current) return;
          validateChangedEntries(campaign.entries, received);
          const changed = received.filter((entry) => entry.revision <= progress.revision);
          revisionRef.current = progress.revision;
          setCampaign((current) => current && current.campaign_id === progress.campaign_id
            ? applyProgress(current, progress, changed)
            : current);
        } catch (reason: unknown) {
          if (!disposed) {
            setError(asMessage(reason, "GNINA campaign progress could not be refreshed."));
          }
        } finally {
          refreshing = false;
        }
      })();
    }, 1000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [campaign?.campaign_id, campaign?.status]);

  useEffect(() => {
    if (!onActivityChange) return;
    if (!campaign || TERMINAL.has(campaign.status)) {
      onActivityChange(null);
      return;
    }
    onActivityChange({
      title: "GNINA campaign",
      detail: campaign.status === "cancel_requested"
        ? "Canceling the GNINA campaign"
        : `${campaign.completed_count} of ${campaign.selected_count} molecules finished`,
      current: campaign.completed_count,
      total: campaign.selected_count,
      workers: campaign.worker_count,
    });
  }, [campaign, onActivityChange]);

  function updateParameter<K extends keyof GninaDockingParameters>(
    name: K,
    value: GninaDockingParameters[K],
  ) {
    setAcknowledged(false);
    setParameters((current) => ({ ...current, [name]: value }));
  }

  async function startCampaign() {
    if (!ready || !acknowledged || startInFlight.current || controlsLocked) return;
    startInFlight.current = true;
    setStarting(true);
    setError(null);
    try {
      const next = await ankoraApi.startGninaScreening({
        receptor_id: receptor.receptor_id,
        binding_site_id: bindingSite.binding_site_id,
        library_id: libraryInput.library_id,
        filter_run_id: libraryInput.filter_run_id,
        parameters,
        acknowledge_inputs_and_scoring: true,
      });
      try {
        window.localStorage.setItem(storageKey, next.campaign_id);
      } catch {
        /* the campaign is still recorded by the backend */
      }
      revisionRef.current = next.revision;
      setCampaign(next);
      setJobs({});
      setJobErrors({});
      setSelectedLigandId(null);
      setSelectedMode(null);
      setExpandedLigandId(null);
    } catch (reason: unknown) {
      setError(asMessage(reason, "The GNINA campaign could not be started."));
    } finally {
      startInFlight.current = false;
      setStarting(false);
    }
  }

  async function cancelCampaign() {
    if (!campaign || starting || TERMINAL.has(campaign.status)) return;
    try {
      const progress = await ankoraApi.cancelGninaScreening(campaign.campaign_id);
      if (progress.revision < revisionRef.current) return;
      const received = progress.revision > revisionRef.current
        ? await ankoraApi.getGninaScreeningEntries(campaign.campaign_id, revisionRef.current)
        : [];
      if (progress.revision < revisionRef.current) return;
      validateChangedEntries(campaign.entries, received);
      const changed = received.filter((entry) => entry.revision <= progress.revision);
      revisionRef.current = progress.revision;
      setCampaign((current) => current && current.campaign_id === progress.campaign_id
        ? applyProgress(current, progress, changed)
        : current);
    } catch (reason: unknown) {
      setError(asMessage(reason, "The GNINA campaign could not be canceled."));
    }
  }

  /** Read one molecule's scores from the exact job that produced them. */
  async function loadJob(jobId: string, openedLigandId?: string): Promise<void> {
    if (jobs[jobId]?.status === "completed" || loadingJobIds.current.has(jobId)) return;
    const expectedCampaignId = campaign?.campaign_id ?? null;
    loadingJobIds.current.add(jobId);
    try {
      const job = await ankoraApi.getGninaDockingJob(jobId);
      if (campaignIdRef.current !== expectedCampaignId) return;
      const entry = entries.find((item) => item.gnina_job_id === jobId);
      if (!campaign || !entry || job.screening_campaign_id !== campaign.campaign_id
          || job.request.ligand_id !== entry.ligand_id
          || (entry.status === "completed" && job.status !== "completed")) {
        throw new Error("The GNINA job does not match this campaign entry.");
      }
      setJobs((current) => ({ ...current, [jobId]: job }));
      if (
        openedLigandId !== undefined
        && openedLigandRef.current === openedLigandId
        && job.status === "completed"
        && job.poses.length
      ) {
        // GNINA's first recorded pose is its highest CNN score.
        setSelectedMode((current) => current ?? job.poses[0].mode);
      }
      setJobErrors((current) => {
        if (current[jobId] === undefined) return current;
        const next = { ...current };
        delete next[jobId];
        return next;
      });
    } catch (reason: unknown) {
      if (campaignIdRef.current !== expectedCampaignId) return;
      setJobErrors((current) => ({
        ...current,
        [jobId]: asMessage(reason, "That GNINA job could not be read."),
      }));
    } finally {
      loadingJobIds.current.delete(jobId);
    }
  }

  // Read newly completed jobs as they arrive, one request at a time. A job
  // opened while it was running must be fetched again when its entry completes.
  useEffect(() => {
    if (!campaign) return;
    let disposed = false;
    void (async () => {
      for (const entry of succeededEntries) {
        if (disposed) break;
        const jobId = entry.gnina_job_id;
        if (jobId && jobs[jobId]?.status !== "completed" && !jobErrors[jobId]) {
          await loadJob(jobId);
        }
      }
    })();
    return () => { disposed = true; };
  }, [campaign?.campaign_id, campaign?.revision, jobs, jobErrors]);

  // One request at a time, in selection order: the same discipline the runner
  // uses, and a campaign can be hundreds of molecules.
  async function loadSucceededJobs() {
    if (loadingJobs) return;
    setLoadingJobs(true);
    try {
      for (const entry of succeededEntries) {
        if (entry.gnina_job_id === null) continue;
        await loadJob(entry.gnina_job_id);
      }
    } finally {
      setLoadingJobs(false);
    }
  }

  function toggleEntry(entry: GninaScreeningEntry) {
    const opening = expandedLigandId !== entry.ligand_id;
    setExpandedLigandId(opening ? entry.ligand_id : null);
    setSelectedLigandId(entry.ligand_id);
    setSelectedMode(null);
    openedLigandRef.current = opening ? entry.ligand_id : null;
    if (opening && entry.gnina_job_id !== null) void loadJob(entry.gnina_job_id, entry.ligand_id);
  }

  function selectPose(entry: GninaScreeningEntry, mode: number) {
    setSelectedLigandId(entry.ligand_id);
    setSelectedMode(mode);
    openedLigandRef.current = entry.ligand_id;
  }

  function changeSort(nextKey: EntrySortKey) {
    if (nextKey === sortKey) {
      setSortDirection((current) => current === "ascending" ? "descending" : "ascending");
      return;
    }
    setSortKey(nextKey);
    // GNINA ranks poses by descending CNN score, so that is the direction a
    // score column starts in; everything else reads naturally ascending.
    setSortDirection(nextKey === "cnn_score" ? "descending" : "ascending");
  }

  const topPoseFor = (entry: GninaScreeningEntry): GninaPoseResult | null => {
    if (entry.gnina_job_id === null) return null;
    const job = jobs[entry.gnina_job_id];
    // GNINA's own order is authoritative: the first recorded pose is its
    // highest CNN score, and nothing here re-sorts the poses.
    return job?.status === "completed" ? job.poses[0] ?? null : null;
  };

  const sortedEntries = useMemo(() => {
    const ordered = entries.map((entry, index) => ({ entry, index }));
    const factor = sortDirection === "ascending" ? 1 : -1;
    ordered.sort((left, right) => {
      if (sortKey === "selection") return (left.index - right.index) * factor;
      const a = sortValue(left.entry, sortKey, topPoseFor);
      const b = sortValue(right.entry, sortKey, topPoseFor);
      // A molecule with no number yet sorts last in either direction rather
      // than pretending to be the best or the worst.
      if (a === null && b === null) return left.index - right.index;
      if (a === null) return 1;
      if (b === null) return -1;
      const order = typeof a === "number" && typeof b === "number"
        ? a - b
        : String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
      return (order * factor) || (left.index - right.index);
    });
    return ordered.map((item) => item.entry);
  }, [entries, jobs, sortDirection, sortKey]);

  return (
    <>
      <section className="workspace docking-workspace" aria-label="GNINA screening workspace">
        <div className="workspace-heading">
          <div>
            <span className="eyebrow">05 / Docking</span>
            <h2>Dock the applied selection with GNINA</h2>
          </div>
          <div className="workspace-actions">
            {modeSwitch}
            <span className="read-only-badge">GNINA · Linux</span>
          </div>
        </div>
        {starting ? (
          <div className="operation-progress" role="progressbar" aria-label="Creating GNINA campaign">
            <span /><p>Recording the campaign over the applied selection…</p>
          </div>
        ) : null}
        {campaign ? (
          <div
            className="operation-progress"
            role="progressbar"
            aria-label="GNINA campaign progress"
            aria-valuemin={0}
            aria-valuemax={campaign.selected_count}
            aria-valuenow={campaign.completed_count}
          >
            <span className="determinate" style={{ width: `${progressPercent}%` }} />
            <p>
              {campaign.completed_count} / {campaign.selected_count} finished ·{" "}
              {runningCount} running · {queuedCount} queued · {campaign.succeeded_count} succeeded ·{" "}
              {campaign.failed_count} failed · {campaign.canceled_count} canceled
            </p>
          </div>
        ) : null}
        {error ? <div className="structure-error" role="alert">{error}</div> : null}
        {campaign?.failure ? (
          <div className="structure-error" role="alert">
            <strong>{campaign.failure.message}</strong> <span>{campaign.failure.code}</span>
            <details>
              <summary>Technical evidence</summary>
              <pre>{JSON.stringify(campaign.failure.details, null, 2)}</pre>
            </details>
          </div>
        ) : null}
        {viewerSources.length ? (
          <MolecularViewer sources={viewerSources} selection={null} dockingBox={bindingSite.box} />
        ) : (
          <div className="viewer-placeholder ligand-placeholder">
            <div className="viewer-message">
              <div className="molecule-glyph">⬚</div>
              <h3>Prepared receptor unavailable</h3>
            </div>
          </div>
        )}
        {restoring && !campaign ? (
          <div className="campaign-live-panel">
            <strong>Checking for a recorded GNINA campaign…</strong>
            <small>Ankora reopens an existing campaign instead of launching another one.</small>
          </div>
        ) : null}
        {campaign ? (
          <CampaignResults
            entries={sortedEntries}
            jobs={jobs}
            jobErrors={jobErrors}
            sortKey={sortKey}
            sortDirection={sortDirection}
            onSort={changeSort}
            expandedLigandId={expandedLigandId}
            onToggle={toggleEntry}
            selectedLigandId={selectedLigandId}
            selectedMode={selectedMode}
            onSelectPose={selectPose}
            topPoseFor={topPoseFor}
            loadingJobs={loadingJobs}
            unreadScoreCount={unreadScoreCount}
            onLoadScores={() => void loadSucceededJobs()}
          />
        ) : null}
      </section>
      <aside className="inspector docking-inspector" aria-label="GNINA campaign inspector">
        <div className="inspector-heading">
          <span className="section-label">Docking campaign</span>
          <h2>GNINA screening</h2>
          <p className="inspector-subtitle">
            One immutable applied selection, one receptor and one search box, docked one
            molecule at a time by the same GNINA service the single-ligand workspace uses.
          </p>
        </div>
        <section className="receptor-section">
          <div className="filter-heading"><span>1 · Scientific inputs</span></div>
          <InputState
            ready={Boolean(receptorPdbqt)}
            label="Receptor PDBQT"
            detail={receptorPdbqt
              ? `${receptorPdbqt.filename} · ${receptorPdbqt.sha256.slice(0, 12)}…`
              : "Return to Receptor and generate PDBQT."}
          />
          <InputState
            ready={!bindingSite.stale}
            label="Binding site"
            detail={bindingSite.stale
              ? "The binding site is stale. Re-finalize it before docking a selection against it."
              : `${formatScientificNumber(bindingSite.box.size_x, 1)} × `
                + `${formatScientificNumber(bindingSite.box.size_y, 1)} × `
                + `${formatScientificNumber(bindingSite.box.size_z, 1)} Å`}
          />
          <InputState
            ready={preparedCount > 0}
            label="Applied library selection"
            detail={`${preparedCount} / ${libraryInput.selected_count} selected molecules prepared · `
              + `${libraryInput.library_name}`}
          />
          {unpreparedCount > 0 ? (
            <div className="protonation-blocker">
              <strong>
                {unpreparedCount} selected {unpreparedCount === 1 ? "molecule is" : "molecules are"} not
                docking-ready
              </strong>
              <small>
                The complete manifest stays in the campaign. Prepared molecules run; every
                unprepared or altered one is retained as an explicit preflight failure in
                selection order, not dropped.
              </small>
            </div>
          ) : null}
          <p className="field-note">
            Manifest SHA-256 · {libraryInput.selection_manifest_sha256.slice(0, 16)}…
          </p>
        </section>
        <section className="receptor-section">
          <div className="filter-heading">
            <span>2 · Engine & search</span>
            <small>{tools?.gnina.available ? tools.gnina.version ?? "detected" : "Unavailable"}</small>
          </div>
          <div className={tools?.gnina.available ? "state-resolved-note" : "protonation-blocker"}>
            <strong>GNINA 1.3.3 · Linux only</strong>
            <small>
              {tools?.gnina.available
                ? "Detected; version and executable identity are checked by the backend at launch."
                : "Configure the Linux GNINA executable and rescan tools."}
            </small>
          </div>
          <label className="numeric-field">
            <span className="field-label">Compute</span>
            <select
              aria-label="Compute"
              value={parameters.compute}
              disabled={controlsLocked}
              onChange={(event) => {
                setAcknowledged(false);
                setParameters((current) => ({
                  ...current,
                  compute: event.target.value as "cpu" | "cuda",
                }));
              }}
            >
              <option value="cpu">CPU</option>
              <option value="cuda">NVIDIA GPU · CUDA</option>
            </select>
          </label>
          {parameters.compute === "cuda" ? (
            <p className="field-note">
              CUDA currently requires one identifiable NVIDIA GPU, device 0, without MIG or
              device visibility remapping. Every molecule is checked against the observed
              process and device before its poses are published, and a requested GPU is never
              silently replaced by the CPU.
            </p>
          ) : null}
          <div className="docking-parameter-grid">
            {GNINA_NUMERIC_FIELDS.map(({ key, label, min, max, step }) => (
              <label className="numeric-field" key={key}>
                <span className="field-label">
                  {key === "timeout_minutes" ? "Timeout / molecule (min)" : label}
                </span>
                <input
                  aria-label={key === "timeout_minutes" ? "Timeout / molecule (min)" : label}
                  type="number"
                  min={min}
                  max={max}
                  step={step}
                  disabled={controlsLocked}
                  value={Number.isNaN(parameters[key]) ? "" : parameters[key]}
                  onChange={(event) => updateParameter(
                    key,
                    event.target.value === "" ? Number.NaN : Number(event.target.value),
                  )}
                />
              </label>
            ))}
          </div>
          <p className="field-note">
            CNN rescoring · dense_1_3 · prepared PDBQT hydrogens preserved. One search
            protocol is applied to every molecule in the selection.
          </p>
          <div className="state-resolved-note">
            <strong>One GNINA job at a time</strong>
            <small>
              The existing GNINA service runs a single job, so the molecules are docked
              sequentially and there is no concurrency to set. Bounded CPU and GPU scheduling
              is not implemented.
            </small>
          </div>
        </section>
        <section className="receptor-section">
          <div className="filter-heading">
            <span>3 · Confirm & run</span>
            {campaign ? <small>{campaign.status.replaceAll("_", " ")}</small> : null}
          </div>
          <label className="docking-acknowledgement">
            <input
              type="checkbox"
              checked={acknowledged}
              disabled={controlsLocked}
              onChange={(event) => setAcknowledged(event.target.checked)}
            />
            <span>
              <strong>Dock this exact applied selection with GNINA</strong>
              <small>
                I understand that the CNN pose score, the predicted CNN affinity and the
                minimized empirical affinity are GNINA predictions, not measured binding
                affinities, and that they are not comparable with a Vina or AutoDock4 number.
              </small>
            </span>
          </label>
          {active ? (
            <button
              type="button"
              className="danger-action docking-primary-action"
              onClick={() => void cancelCampaign()}
              disabled={starting || campaign?.status === "cancel_requested"}
            >
              Cancel campaign
            </button>
          ) : (
            <button
              type="button"
              className="primary-action docking-primary-action"
              onClick={() => void startCampaign()}
              disabled={!ready || !acknowledged || controlsLocked}
            >
              {restoring
                ? "Checking for a recorded campaign…"
                : starting
                  ? "Recording the campaign…"
                  : `Dock ${preparedCount} prepared ${preparedCount === 1 ? "molecule" : "molecules"}`}
            </button>
          )}
          {!ready && !restoring ? (
            <p className="field-note">
              Check the prepared receptor, the binding site, GNINA availability and the
              parameter ranges above. Ankora will not substitute another molecular state.
            </p>
          ) : null}
          {unpreparedCount > 0 ? (
            <p className="field-note">
              The campaign still accounts for all {libraryInput.selected_count} manifest entries:{" "}
              {preparedCount} GNINA {preparedCount === 1 ? "execution" : "executions"} and{" "}
              {unpreparedCount} explicit preflight{" "}
              {unpreparedCount === 1 ? "failure" : "failures"}.
            </p>
          ) : null}
        </section>
        <section className="receptor-section" aria-label="GNINA score meaning">
          <div className="filter-heading"><span>How to read these numbers</span></div>
          <p className="field-note">
            GNINA ranks its poses by the dimensionless CNN pose score, descending. The
            predicted CNN affinity is a pK, where higher predicts stronger affinity, and the
            minimized empirical affinity is in kcal/mol, where lower is more favorable. The
            minimized affinity did not determine the ranking.
          </p>
          <div className="protonation-blocker" role="note">
            <strong>Not comparable across engines</strong>
            <small>
              A CNN score is not a kcal/mol energy and shares no scale with a Vina score or an
              AutoDock4 binding energy, so these molecules cannot be pooled or co-ranked with
              a Vina or AutoDock4 campaign. The &ldquo;Compare engines&rdquo; view covers Vina
              and AutoDock4 only and does not include GNINA.
            </small>
          </div>
        </section>
        <section className="receptor-section" aria-label="Unavailable campaign actions">
          <div className="filter-heading"><span>Not available for a campaign</span></div>
          <p className="field-note">
            Recorded campaigns appear in the Results catalog under the GNINA CNN score family.
            These single-ligand or Vina/AutoDock4 actions are still not offered for a campaign:
          </p>
          <ul className="field-note">
            <li>Export: there is no multi-ligand GNINA campaign bundle.</li>
            <li>Redocking validation: no campaign entry point exists.</li>
            <li>Methods report: no campaign-level section is generated.</li>
            <li>Engine comparison: GNINA is not part of it.</li>
          </ul>
          <p className="field-note">
            An interrupted campaign is reconciled by the backend at startup and can be retried
            only as a new campaign from the startup recovery panel.
          </p>
        </section>
        {history.length ? (
          <section className="receptor-section" aria-label="Recorded GNINA campaigns">
            <div className="filter-heading"><span>Recorded GNINA campaigns</span></div>
            <p className="field-note">Open a previous run using the same receptor, search box and selection.</p>
            {history.map((item) => (
              <button key={item.campaign_id} type="button" disabled={controlsLocked || item.campaign_id === campaign?.campaign_id}
                onClick={() => void openRecordedCampaign(item.campaign_id)}>
                {item.campaign_id.slice(0, 8)} · {item.status.replaceAll("_", " ")} · {item.completed_count}/{item.selected_count}
              </button>
            ))}
          </section>
        ) : null}
        {campaign ? (
          <section className="receptor-section">
            <div className="filter-heading">
              <span>4 · Campaign evidence</span>
              <small>{campaign.campaign_id.slice(0, 8)}…</small>
            </div>
            <dl className="docking-evidence">
              <div><dt>Engine</dt><dd>GNINA {campaign.tool.version}</dd></div>
              <div><dt>Executable</dt><dd><code>{campaign.tool.sha256.slice(0, 12)}…</code></dd></div>
              <div><dt>Model</dt><dd>{campaign.request.parameters.cnn_model}</dd></div>
              <div><dt>Compute</dt><dd>{campaign.request.parameters.compute.toUpperCase()}</dd></div>
              <div><dt>Workers</dt><dd>{campaign.worker_count}</dd></div>
              <div><dt>Succeeded</dt><dd>{campaign.succeeded_count} / {campaign.selected_count}</dd></div>
              <div><dt>Preflight failures</dt><dd>{preflightFailureCount}</dd></div>
              <div><dt>Engine failures</dt><dd>{Math.max(0, engineFailureCount)}</dd></div>
              <div><dt>Canceled</dt><dd>{campaign.canceled_count}</dd></div>
              <div><dt>Selection</dt><dd><code>{campaign.selection.manifest_sha256.slice(0, 12)}…</code></dd></div>
            </dl>
            {campaign.warnings.length ? (
              <details className="technical-details">
                <summary>{campaign.warnings.length} recorded warnings</summary>
                <ul>
                  {campaign.warnings.map((warning, index) => (
                    <li key={`${warning.code}-${index}`}>{warning.code} · {warning.message}</li>
                  ))}
                </ul>
              </details>
            ) : null}
            {selectedEntry ? (
              <details className="technical-details" open={Boolean(selectedEntry.failure)}>
                <summary>Selected molecule evidence</summary>
                {selectedEntry.failure ? (
                  <p>{selectedEntry.failure.code} · {selectedEntry.failure.message}</p>
                ) : null}
                {selectedEntry.gnina_job_id ? (
                  <p>GNINA job <code>{selectedEntry.gnina_job_id}</code></p>
                ) : (
                  <p>
                    No GNINA job exists for this molecule: it was refused before the engine ran.
                  </p>
                )}
                {selectedJob ? (
                  <>
                    <pre>{selectedJob.command.join(" ")}</pre>
                    <p>
                      GPU observed ·{" "}
                      {selectedJob.request.parameters.compute === "cpu"
                        ? "Not applicable (CPU)"
                        : !selectedJob.execution
                          ? "Not recorded"
                          : selectedJob.execution.gpu_process_observed
                            ? "Yes — the process was seen on the device, which does not prove every network operation ran there"
                            : "No"}
                    </p>
                    {selectedJob.execution ? (
                      <>
                        <h4>stdout</h4>
                        <pre>{selectedJob.execution.stdout || "(empty)"}</pre>
                        <h4>stderr</h4>
                        <pre>{selectedJob.execution.stderr || "(empty)"}</pre>
                      </>
                    ) : null}
                  </>
                ) : selectedEntry.gnina_job_id ? (
                  <p>Open this molecule in the results table to read its individual job.</p>
                ) : null}
              </details>
            ) : (
              <p className="field-note">
                Select a molecule to read the individual GNINA job recorded as its attempt.
              </p>
            )}
          </section>
        ) : null}
      </aside>
    </>
  );
}

function CampaignResults({
  entries,
  jobs,
  jobErrors,
  sortKey,
  sortDirection,
  onSort,
  expandedLigandId,
  onToggle,
  selectedLigandId,
  selectedMode,
  onSelectPose,
  topPoseFor,
  loadingJobs,
  unreadScoreCount,
  onLoadScores,
}: {
  entries: GninaScreeningEntry[];
  jobs: Record<string, GninaDockingJobRecord>;
  jobErrors: Record<string, string>;
  sortKey: EntrySortKey;
  sortDirection: SortDirection;
  onSort: (key: EntrySortKey) => void;
  expandedLigandId: string | null;
  onToggle: (entry: GninaScreeningEntry) => void;
  selectedLigandId: string | null;
  selectedMode: number | null;
  onSelectPose: (entry: GninaScreeningEntry, mode: number) => void;
  topPoseFor: (entry: GninaScreeningEntry) => GninaPoseResult | null;
  loadingJobs: boolean;
  unreadScoreCount: number;
  onLoadScores: () => void;
}) {
  const horizontalScrollRef = useRef<HTMLDivElement>(null);
  const tableScrollRef = useRef<HTMLDivElement>(null);
  return (
    <section
      className="docking-results library-docking-results"
      aria-label="GNINA campaign results"
    >
      <div className="docking-results-heading">
        <div>
          <span className="eyebrow">Compound results</span>
          <h3>GNINA library results</h3>
        </div>
        <p>
          The campaign records which GNINA job docked each molecule, in selection order; it
          records no scores of its own. A score below was read from that individual job, where
          the poses keep GNINA&apos;s own descending CNN-score order. Predictions, not measured
          affinities.
        </p>
      </div>
      <div className="campaign-recent">
        <button
          type="button"
          onClick={onLoadScores}
          disabled={loadingJobs || unreadScoreCount === 0}
        >
          {loadingJobs
            ? "Reading individual GNINA jobs…"
            : unreadScoreCount === 0
              ? "Every finished molecule's job has been read"
              : `Read scores from ${unreadScoreCount} finished `
                + `${unreadScoreCount === 1 ? "job" : "jobs"}`}
        </button>
        <small>
          Each score comes from one individual job request, so nothing is shown until its job
          has been read.
        </small>
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
              <SortHeader label="#" sortKey="selection" activeKey={sortKey} direction={sortDirection} onSort={onSort} />
              <SortHeader label="Molecule" sortKey="name" activeKey={sortKey} direction={sortDirection} onSort={onSort} />
              <SortHeader label="Top CNN score (dimensionless)" sortKey="cnn_score" activeKey={sortKey} direction={sortDirection} onSort={onSort} />
              <th title="GNINA's predicted affinity for the same pose, as a pK. Higher predicts stronger affinity. Not a measured affinity.">
                CNN affinity (pK)
              </th>
              <th title="The minimized empirical affinity of the same pose. It did not determine GNINA's ranking.">
                Minimized affinity (kcal/mol)
              </th>
              <SortHeader label="Status" sortKey="status" activeKey={sortKey} direction={sortDirection} onSort={onSort} />
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => {
              const expanded = entry.ligand_id === expandedLigandId;
              const job = entry.gnina_job_id ? jobs[entry.gnina_job_id] ?? null : null;
              const jobError = entry.gnina_job_id ? jobErrors[entry.gnina_job_id] ?? null : null;
              const top = topPoseFor(entry);
              return (
                <Fragment key={entry.ligand_id}>
                  <tr
                    className={entry.ligand_id === selectedLigandId ? "selected" : ""}
                    onClick={() => onToggle(entry)}
                    aria-expanded={expanded}
                  >
                    <td>{entry.source_index === null ? "—" : entry.source_index + 1}</td>
                    <td>
                      <button
                        type="button"
                        className="compound-expand"
                        aria-expanded={expanded}
                        onClick={(event) => { event.stopPropagation(); onToggle(entry); }}
                      >
                        <span aria-hidden="true">{expanded ? "▾" : "▸"}</span>
                        {entryLabel(entry)}
                      </button>
                    </td>
                    <td>{top ? formatScientificNumber(top.cnn_score, 4) : "—"}</td>
                    <td>{top ? formatScientificNumber(top.cnn_affinity, 3) : "—"}</td>
                    <td>
                      {top ? formatScientificNumber(top.minimized_affinity_kcal_mol, 3) : "—"}
                    </td>
                    <td>
                      <span className={`docking-status ${entry.status}`}>
                        {entryStatusLabel(entry)}
                      </span>
                      {entry.failure ? (
                        <small title={entry.failure.message}>{entry.failure.code}</small>
                      ) : null}
                    </td>
                  </tr>
                  {expanded ? (
                    <tr className="pose-expansion">
                      <td colSpan={6}>
                        {entry.failure ? (
                          <p className="protonation-blocker" role="note">
                            <strong>{entry.failure.code}</strong> · {entry.failure.message}
                            {isPreflightFailure(entry)
                              ? " This molecule was refused before any GNINA process existed, so it has no job, no poses and no scores."
                              : ""}
                          </p>
                        ) : null}
                        {jobError ? (
                          <p className="protonation-blocker" role="alert">{jobError}</p>
                        ) : null}
                        {job?.status === "completed" && job.poses.length ? (
                          <div className="compound-poses">
                            <div className="compound-poses-heading">
                              <strong>{entryLabel(entry)} · {job.poses.length} poses</strong>
                              <small>
                                GNINA&apos;s own order: descending CNN score, not lowest
                                minimized affinity. Click a pose to display the preserved
                                coordinates.
                              </small>
                            </div>
                            <table>
                              <thead>
                                <tr>
                                  <th>Pose</th>
                                  <th>CNN score</th>
                                  <th>CNN affinity (pK)</th>
                                  <th>Minimized affinity (kcal/mol)</th>
                                  <th>Artifact SHA-256</th>
                                </tr>
                              </thead>
                              <tbody>
                                {job.poses.map((pose) => {
                                  const selected = entry.ligand_id === selectedLigandId
                                    && pose.mode === selectedMode;
                                  return (
                                    <tr key={pose.mode} className={selected ? "selected" : ""}>
                                      <td>
                                        <button
                                          type="button"
                                          className="pose-select"
                                          aria-pressed={selected}
                                          onClick={(event) => {
                                            event.stopPropagation();
                                            onSelectPose(entry, pose.mode);
                                          }}
                                        >
                                          Pose {pose.mode}
                                        </button>
                                      </td>
                                      <td>{formatScientificNumber(pose.cnn_score, 4)}</td>
                                      <td>{formatScientificNumber(pose.cnn_affinity, 3)}</td>
                                      <td>
                                        {formatScientificNumber(pose.minimized_affinity_kcal_mol, 3)}
                                      </td>
                                      <td><code>{pose.artifact.sha256.slice(0, 16)}…</code></td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                        ) : job && job.status !== "completed" ? (
                          <p className="field-note">
                            This molecule&apos;s GNINA job is {job.status.replaceAll("_", " ")}{" "}
                            and publishes no poses.
                            {job.failure
                              ? ` ${job.failure.code} · ${job.failure.message}`
                              : ""}
                          </p>
                        ) : entry.gnina_job_id && !jobError ? (
                          <p className="field-note">Reading the individual GNINA job…</p>
                        ) : !entry.failure ? (
                          <p className="field-note">
                            No GNINA job has been recorded for this molecule yet.
                          </p>
                        ) : null}
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

/**
 * Apply a polled header, plus whatever entries changed with it.
 *
 * The entries that did not change are kept exactly as they were, and the order
 * is the campaign's selection order - a changed entry is replaced in place and
 * never appended, because that order is what the scientist applied.
 */
function applyProgress(
  current: GninaScreeningCampaignRecord,
  progress: GninaScreeningProgress,
  changed: GninaScreeningEntry[],
): GninaScreeningCampaignRecord {
  const updates = new Map(changed.map((entry) => [entry.ligand_id, entry]));
  const entries = current.entries.map((entry) => updates.get(entry.ligand_id) ?? entry);
  return {
    ...current,
    status: progress.status,
    phase: progress.phase,
    revision: progress.revision,
    started_at: progress.started_at,
    completed_at: progress.completed_at,
    selected_count: progress.selected_count,
    completed_count: progress.completed_count,
    succeeded_count: progress.succeeded_count,
    failed_count: progress.failed_count,
    canceled_count: progress.canceled_count,
    entries,
  };
}

function validateChangedEntries(original: GninaScreeningEntry[], changed: GninaScreeningEntry[]) {
  const known = new Set(original.map((entry) => entry.ligand_id));
  const seen = new Set<string>();
  for (const entry of changed) {
    if (!known.has(entry.ligand_id) || seen.has(entry.ligand_id)) {
      throw new Error("The GNINA campaign returned an inconsistent selection update.");
    }
    seen.add(entry.ligand_id);
  }
}

/**
 * A recorded campaign has to name the inputs this workspace is showing.
 *
 * Displaying a campaign over another receptor, box or selection beside these
 * inputs would invite exactly the comparison that is not valid, so a mismatch
 * is reported rather than reconciled.
 */
function describeInputMismatch(
  record: GninaScreeningCampaignRecord,
  receptor: ReceptorPreparationRecord,
  bindingSite: BindingSiteRecord,
  libraryInput: LigandLibraryDockingInput,
): string | null {
  const request = record.request;
  if (
    request.receptor_id !== receptor.receptor_id
    || request.binding_site_id !== bindingSite.binding_site_id
    || request.library_id !== libraryInput.library_id
    || request.filter_run_id !== libraryInput.filter_run_id
  ) {
    return "The saved GNINA campaign was run against different inputs than the ones selected here.";
  }
  if (record.selection.manifest_sha256 !== libraryInput.selection_manifest_sha256) {
    return "The saved GNINA campaign screened a different applied selection: its manifest hash "
      + "does not match the selection currently applied.";
  }
  const output = receptor.outputs.find((item) => item.stage === "pdbqt");
  if (!output || record.receptor_output_artifact_id !== output.artifact_id
      || record.receptor_sha256 !== output.sha256
      || (Object.keys(bindingSite.box) as Array<keyof typeof bindingSite.box>)
        .some((key) => record.box[key] !== bindingSite.box[key])) {
    return "The saved GNINA campaign used a different receptor or search box.";
  }
  return null;
}

/** A refusal recorded before any GNINA process existed for this molecule. */
function isPreflightFailure(entry: GninaScreeningEntry): boolean {
  return entry.status === "failed" && entry.gnina_job_id === null;
}

/**
 * A preflight refusal is still a failure, and saying only "failed" would hide
 * that no GNINA process ever ran for this molecule.
 */
function entryStatusLabel(entry: GninaScreeningEntry): string {
  if (isPreflightFailure(entry)) return "failed (preflight)";
  return entry.status.replaceAll("_", " ");
}

function entryLabel(entry: GninaScreeningEntry): string {
  return entry.name ?? `Ligand ${entry.ligand_id.slice(0, 8)}…`;
}

function sortValue(
  entry: GninaScreeningEntry,
  key: Exclude<EntrySortKey, "selection">,
  topPoseFor: (entry: GninaScreeningEntry) => GninaPoseResult | null,
): number | string | null {
  if (key === "name") return entryLabel(entry);
  if (key === "status") return entryStatusLabel(entry);
  return topPoseFor(entry)?.cnn_score ?? null;
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
        {label}
        <span aria-hidden="true">{active ? direction === "ascending" ? "↑" : "↓" : "↕"}</span>
      </button>
    </th>
  );
}

function InputState({ ready, label, detail }: { ready: boolean; label: string; detail: string }) {
  return (
    <div className={ready ? "state-resolved-note" : "protonation-blocker"}>
      <strong>{label}</strong>
      <small>{detail}</small>
    </div>
  );
}

function asMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}
