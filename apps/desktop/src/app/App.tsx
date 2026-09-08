import { type ChangeEvent, type CSSProperties, type FormEvent, type PointerEvent as ReactPointerEvent, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ankoraApi, ApiError } from "../api/client";
import { AppIcon } from "../components/AppIcon";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { SplashScreen } from "../components/SplashScreen";
import { BindingSiteWorkspace } from "../features/binding-site/BindingSiteWorkspace";
import { DockingWorkspace } from "../features/docking/DockingWorkspace";
import { RedockingWorkspace } from "../features/validation/RedockingWorkspace";
import { ExportWorkspace } from "../features/export/ExportWorkspace";
import { ResultsWorkspace } from "../features/results/ResultsWorkspace";
import { LigandWorkspace } from "../features/ligand/LigandWorkspace";
import { ProjectWorkspace } from "../features/project/ProjectWorkspace";
import {
  isLigandLibraryStageComplete,
  summarizeLigandLibraryStatus,
  type LigandLibraryStatusSummary,
} from "../features/ligand/libraryProgress";
import { ReceptorWorkspace } from "../features/receptor/ReceptorWorkspace";
import type { BindingSiteRecord, HeterogenSummary, LigandDockingInput, LigandLibraryDockingInput, LigandRecord, ProjectCatalog, ProjectDependencyGraph, ProjectDependencyNode, ProjectRecord, ReceptorPreparationRecord, RecoveredWorkItem, StructureRecord, WorkRecoverySummary, WorkRetryResponse } from "../types/api";
import { MolecularViewer } from "../viewer/MolecularViewer";
import type { ViewerSelection } from "../viewer/adapter";
import { formatApplicationDateTime, formatCount, formatScientificNumber } from "../utils/format";
import { createInitialApplicationState, type ApplicationState } from "./state";
import type { WorkspaceActivity } from "./activity";
import { canNavigateTo, workflowSteps, type WorkflowStep } from "./workflow";
import { describeUsage, useResourceUsage } from "./useResourceUsage";
import { useWorkbenchLayout } from "./workbenchLayout";

type ActivityTab = "activity" | "warnings" | "provenance" | "tools" | "about";
type ThemeMode = "dark" | "light" | "blue" | "amethyst" | "system";
type DensityMode = "comfortable" | "compact";

const DEFAULT_PROJECT_CATALOG: ProjectCatalog = {
  active_project_id: "default",
  projects: [{
    project_id: "default",
    name: "Default project",
    registered_at: "",
    migrated_legacy: true,
  }],
};

export function App() {
  const workbenchLayout = useWorkbenchLayout();
  const [state, setState] = useState<ApplicationState>(createInitialApplicationState);
  const [splashDismissed, setSplashDismissed] = useState(false);
  const [pdbId, setPdbId] = useState("");
  const [fetchSource, setFetchSource] = useState<"rcsb" | "alphafold">("rcsb");
  const [selection, setSelection] = useState<ViewerSelection | null>(null);
  const [activeStep, setActiveStep] = useState<WorkflowStep>("Structure");
  const [receptorRecord, setReceptorRecord] = useState<ReceptorPreparationRecord | null>(null);
  const [latestReceptor, setLatestReceptor] = useState<ReceptorPreparationRecord | null>(null);
  const [ligandRecord, setLigandRecord] = useState<LigandRecord | null>(null);
  const [ligandDockingInput, setLigandDockingInput] = useState<LigandDockingInput | null>(null);
  const [ligandLibraryDockingInput, setLigandLibraryDockingInput] = useState<LigandLibraryDockingInput | null>(null);
  const [ligandLibraryStatus, setLigandLibraryStatus] = useState<LigandLibraryStatusSummary | null>(null);
  const [bindingSiteRecord, setBindingSiteRecord] = useState<BindingSiteRecord | null>(null);
  const [workflowCollapsed, setWorkflowCollapsed] = useState(false);
  const [inspectorCollapsed, setInspectorCollapsed] = useState(false);
  const [workflowWidth, setWorkflowWidth] = useState(208);
  const [inspectorWidth, setInspectorWidth] = useState(360);
  const [activityOpen, setActivityOpen] = useState(false);
  const [activityTab, setActivityTab] = useState<ActivityTab>("activity");
  const [workspaceActivity, setWorkspaceActivity] = useState<WorkspaceActivity | null>(null);
  const [workRecovery, setWorkRecovery] = useState<WorkRecoverySummary | null>(null);
  const [recoveryLoadError, setRecoveryLoadError] = useState<string | null>(null);
  const [retryAcknowledgements, setRetryAcknowledgements] = useState<Record<string, boolean>>({});
  const [retryingWorkKey, setRetryingWorkKey] = useState<string | null>(null);
  const [retryResponses, setRetryResponses] = useState<Record<string, WorkRetryResponse>>({});
  const [retryErrors, setRetryErrors] = useState<Record<string, string>>({});
  const [toolsRefreshing, setToolsRefreshing] = useState(false);
  const [projectCatalog, setProjectCatalog] = useState<ProjectCatalog>(DEFAULT_PROJECT_CATALOG);
  const [projectGraph, setProjectGraph] = useState<ProjectDependencyGraph | null>(null);
  const [projectWorkspaceOpen, setProjectWorkspaceOpen] = useState(false);
  const [projectBusy, setProjectBusy] = useState(false);
  const [projectError, setProjectError] = useState<string | null>(null);
  const [projectGraphLimit, setProjectGraphLimit] = useState(100);
  const [theme, setTheme] = useState<ThemeMode>(() => readUiSetting("ankora-theme", ["dark", "light", "blue", "amethyst", "system"], "dark"));
  const [density, setDensity] = useState<DensityMode>(() => readUiSetting("ankora-density", ["comfortable", "compact"], "comfortable"));
  const importMenuRef = useRef<HTMLDetailsElement>(null);
  const globalFileInputRef = useRef<HTMLInputElement>(null);
  const autoAdvancedLigandRunRef = useRef<string | null>(null);
  // Advancing belongs to work that finished here, not to work being
  // reopened: a library loaded from the shelf arrives already complete, and
  // being thrown to Binding site for clicking it is not what was asked for.
  const sawIncompleteLigandRunRef = useRef<string | null>(null);
  const handleReceptorRecord = useCallback((record: ReceptorPreparationRecord | null) => {
    setReceptorRecord(record);
    if (record) setLatestReceptor(record);
  }, []);

  const initializeBackend = useCallback(() => {
    setState((current) => ({ ...current, connection: "checking", error: null }));
    return Promise.all([ankoraApi.health(), ankoraApi.system(), ankoraApi.tools()])
      .then(([health, system, tools]) => {
        setState((current) => ({ ...current, connection: "connected", health, system, tools, error: null }));
      })
      .catch((error: unknown) => {
        const message = error instanceof Error ? error.message : "Backend connection failed";
        setState((current) => ({ ...current, connection: "disconnected", health: null, system: null, tools: null, error: message }));
      });
  }, []);

  useEffect(() => {
    void initializeBackend();
  }, [initializeBackend]);

  useEffect(() => {
    let active = true;
    void ankoraApi.projects()
      .then((catalog) => {
        if (active && isProjectCatalog(catalog)) setProjectCatalog(catalog);
      })
      .catch(() => {
        // Project identity is additive during development. The rest of the
        // workbench remains usable against an older local backend.
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    void ankoraApi.workRecovery()
      .then((summary) => {
        if (!active) return;
        // Keep the workbench tolerant of an older development backend while
        // the desktop and API are being rebuilt independently.
        const items = Array.isArray(summary.items) ? summary.items : [];
        setWorkRecovery({ ...summary, items });
        setRecoveryLoadError(null);
        if (items.length) {
          setActivityTab("activity");
          setActivityOpen(true);
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setRecoveryLoadError(
            error instanceof Error ? error.message : "Startup recovery could not be inspected",
          );
        }
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.density = density;
    try {
      localStorage.setItem("ankora-theme", theme);
      localStorage.setItem("ankora-density", density);
    } catch { /* Settings persistence is optional in restricted WebViews. */ }
  }, [density, theme]);

  useEffect(() => {
    if (activityOpen && activityTab === "tools") void refreshTools();
  }, [activityOpen, activityTab]);

  useEffect(() => {
    function closeMenus(event: MouseEvent) {
      if (!(event.target as HTMLElement).closest(".app-menu")) {
        document.querySelectorAll<HTMLDetailsElement>(".app-menu[open]").forEach((menu) => { menu.open = false; });
      }
    }
    window.addEventListener("pointerdown", closeMenus);
    return () => window.removeEventListener("pointerdown", closeMenus);
  }, []);

  useEffect(() => {
    let active = true;
    void ankoraApi.latestReceptor()
      .then((record) => { if (active) setLatestReceptor(record); })
      .catch((error: unknown) => {
        if (active && error instanceof ApiError && error.status !== 404) {
          setState((current) => ({ ...current, structureError: error.message }));
        }
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const libraryId = ligandRecord?.artifact.library_id;
    if (!libraryId || ligandLibraryDockingInput?.library_id === libraryId) return;
    let active = true;
    void Promise.all([
      ankoraApi.getLigandLibrary(libraryId),
      ankoraApi.latestLigandLibraryFilterRun(libraryId),
      ankoraApi.getLigandLibraryPreparation(libraryId),
    ]).then(([library, filterRun, preparation]) => {
      if (!active) return;
      const libraryStatus = summarizeLigandLibraryStatus(
        filterRun.selected_ligand_ids,
        (ligandId) => {
          const entry = preparation.entries[ligandId];
          if (entry?.status === "prepared" && !entry.pdbqt_preparation_id) return undefined;
          return entry?.status;
        },
      );
      setLigandLibraryDockingInput({
        library_id: libraryId,
        library_name: library.artifact.filename,
        filter_run_id: filterRun.artifact.filter_run_id,
        selection_manifest_sha256: filterRun.artifact.sha256,
        selected_count: libraryStatus.total,
        prepared_count: libraryStatus.prepared,
      });
      setLigandLibraryStatus(libraryStatus);
    }).catch((error: unknown) => {
      if (active && !(error instanceof ApiError && error.status === 404)) {
        setState((current) => ({
          ...current,
          structureError: error instanceof Error
            ? error.message
            : "The applied ligand library could not be restored.",
        }));
      }
    });
    return () => { active = false; };
  }, [ligandLibraryDockingInput?.library_id, ligandRecord?.artifact.library_id]);

  useEffect(() => {
    const libraryId = ligandLibraryDockingInput?.library_id;
    const filterRunId = ligandLibraryDockingInput?.filter_run_id;
    if (!libraryId || !isLigandLibraryStageComplete(ligandLibraryStatus)) return;
    const completionKey = `${libraryId}:${filterRunId}`;
    if (activeStep !== "Ligand" || autoAdvancedLigandRunRef.current === completionKey) return;
    // Only a run this session watched go from unfinished to finished.
    if (sawIncompleteLigandRunRef.current !== completionKey) return;
    autoAdvancedLigandRunRef.current = completionKey;
    setActiveStep("Binding site");
  }, [activeStep, ligandLibraryDockingInput?.filter_run_id, ligandLibraryDockingInput?.library_id, ligandLibraryStatus]);

  useEffect(() => {
    const libraryId = ligandLibraryDockingInput?.library_id;
    const filterRunId = ligandLibraryDockingInput?.filter_run_id;
    if (!libraryId || !ligandLibraryStatus || isLigandLibraryStageComplete(ligandLibraryStatus)) return;
    const completionKey = `${libraryId}:${filterRunId}`;
    sawIncompleteLigandRunRef.current = completionKey;
    if (autoAdvancedLigandRunRef.current === completionKey) autoAdvancedLigandRunRef.current = null;
  }, [ligandLibraryDockingInput?.filter_run_id, ligandLibraryDockingInput?.library_id, ligandLibraryStatus]);

  const usage = useResourceUsage(state.connection === "connected");
  const resources = describeUsage(usage);
  const connectionLabel = state.connection === "checking"
    ? "Connecting"
    : state.connection === "connected" ? "Backend connected" : "Backend disconnected";

  async function runStructureOperation(operation: () => Promise<StructureRecord>) {
    if (importMenuRef.current) importMenuRef.current.open = false;
    setSelection(null);
    setState((current) => ({ ...current, structureOperation: "loading", structureError: null }));
    try {
      const structure = await operation();
      setState((current) => ({ ...current, structure, structureOperation: "idle", structureError: null }));
      setActiveStep("Structure");
      setReceptorRecord(null);
      setLigandRecord(null);
      setLigandDockingInput(null);
      setLigandLibraryDockingInput(null);
      setLigandLibraryStatus(null);
      setBindingSiteRecord(null);
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : "The structure could not be opened";
      setState((current) => ({ ...current, structureOperation: "idle", structureError: message }));
    }
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) void runStructureOperation(() => ankoraApi.importStructure(file));
  }

  function handleFetch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedId = pdbId.trim().toUpperCase();
    if (fetchSource === "alphafold") {
      if (!/^([OPQ][0-9][A-Z0-9]{3}[0-9])(-[0-9]{1,3})?$/.test(normalizedId)) {
        setState((current) => ({ ...current, structureError: "Enter a valid UniProt accession, e.g. P04637 or P04637-2." }));
        return;
      }
      void runStructureOperation(() => ankoraApi.fetchAlphafoldStructure(normalizedId));
      return;
    }
    if (!/^[A-Z0-9]{4}$/.test(normalizedId)) {
      setState((current) => ({ ...current, structureError: "Enter a four-character PDB ID." }));
      return;
    }
    void runStructureOperation(() => ankoraApi.fetchStructure(normalizedId));
  }

  async function reopenLatestReceptor() {
    if (!latestReceptor) return;
    if (importMenuRef.current) importMenuRef.current.open = false;
    setSelection(null);
    setState((current) => ({ ...current, structureOperation: "loading", structureError: null }));
    try {
      const structure = await ankoraApi.getStructure(latestReceptor.source_artifact_id);
      setState((current) => ({ ...current, structure, structureOperation: "idle", structureError: null }));
      setReceptorRecord(latestReceptor);
      setBindingSiteRecord(null);
      setActiveStep("Receptor");
    } catch (error: unknown) {
      setState((current) => ({
        ...current,
        structureOperation: "idle",
        structureError: error instanceof Error ? error.message : "The saved receptor could not be reopened",
      }));
    }
  }

  function resetScientificWorkspace() {
    setSelection(null);
    setState((current) => ({
      ...current,
      structure: null,
      structureOperation: "idle",
      structureError: null,
    }));
    setReceptorRecord(null);
    setLatestReceptor(null);
    setLigandRecord(null);
    setLigandDockingInput(null);
    setLigandLibraryDockingInput(null);
    setLigandLibraryStatus(null);
    setBindingSiteRecord(null);
    setWorkspaceActivity(null);
    setWorkRecovery(null);
    setActiveStep("Structure");
  }

  async function refreshProjectWorkspace(limit = projectGraphLimit) {
    const [catalog, graph] = await Promise.all([
      ankoraApi.projects(),
      ankoraApi.projectDependencies(0, limit),
    ]);
    if (!isProjectCatalog(catalog) || !isProjectDependencyGraph(graph)) {
      throw new Error("The backend returned an invalid project workspace.");
    }
    setProjectCatalog(catalog);
    setProjectGraph(graph);
  }

  async function openProjectWorkspace() {
    setProjectWorkspaceOpen(true);
    setProjectBusy(true);
    setProjectError(null);
    try {
      await refreshProjectWorkspace();
    } catch (error: unknown) {
      setProjectError(error instanceof Error ? error.message : "Projects could not be loaded.");
    } finally {
      setProjectBusy(false);
    }
  }

  async function activateProject(project: ProjectRecord) {
    setProjectBusy(true);
    setProjectError(null);
    try {
      const activated = await ankoraApi.activateProject(project.project_id);
      resetScientificWorkspace();
      const [catalog, graph, recovery, savedReceptor] = await Promise.all([
        ankoraApi.projects(),
        ankoraApi.projectDependencies(0, projectGraphLimit),
        ankoraApi.workRecovery().catch(() => null),
        ankoraApi.latestReceptor().catch((error: unknown) => {
          if (error instanceof ApiError && error.status === 404) return null;
          throw error;
        }),
      ]);
      if (!isProjectCatalog(catalog) || !isProjectDependencyGraph(graph)) {
        throw new Error("The activated project returned an invalid workspace.");
      }
      setProjectCatalog(catalog);
      setProjectGraph(graph);
      setLatestReceptor(savedReceptor);
      if (recovery && Array.isArray(recovery.items)) setWorkRecovery(recovery);
      setProjectError(null);
      if (activated.project_id !== catalog.active_project_id) {
        throw new Error("The backend did not retain the selected project.");
      }
    } catch (error: unknown) {
      setProjectError(error instanceof Error ? error.message : "The project could not be opened.");
    } finally {
      setProjectBusy(false);
    }
  }

  async function createProject(name: string) {
    setProjectBusy(true);
    setProjectError(null);
    try {
      const created = await ankoraApi.createProject(name);
      await activateProject(created);
    } catch (error: unknown) {
      setProjectError(error instanceof Error ? error.message : "The project could not be created.");
      setProjectBusy(false);
    }
  }

  async function markProjectDependencyStale(node: ProjectDependencyNode, reason: string) {
    setProjectBusy(true);
    setProjectError(null);
    try {
      await ankoraApi.markProjectDependencyStale(node.node_id, reason);
      await refreshProjectWorkspace();
    } catch (error: unknown) {
      setProjectError(error instanceof Error ? error.message : "Stale state could not be recorded.");
    } finally {
      setProjectBusy(false);
    }
  }

  async function loadMoreProjectDependencies() {
    const nextLimit = Math.min(500, projectGraphLimit + 100);
    setProjectBusy(true);
    setProjectError(null);
    try {
      await refreshProjectWorkspace(nextLimit);
      setProjectGraphLimit(nextLimit);
    } catch (error: unknown) {
      setProjectError(error instanceof Error ? error.message : "More records could not be loaded.");
    } finally {
      setProjectBusy(false);
    }
  }

  const structure = state.structure;
  const activeProject = projectCatalog.projects.find(
    (project) => project.project_id === projectCatalog.active_project_id,
  ) ?? DEFAULT_PROJECT_CATALOG.projects[0];
  const structureViewerSources = useMemo(() => structure ? [{
    id: structure.artifact.artifact_id,
    url: ankoraApi.structureContentUrl(structure),
    format: structure.artifact.format,
    label: structure.artifact.original_filename,
  }] : [], [structure]);
  const warningLabel = state.structureError ?? state.error ?? (structure?.warnings.length
    ? `${structure.warnings.length} structural warning${structure.warnings.length === 1 ? "" : "s"}`
    : "No structural warnings");
  const activeWarningCount = activeStep === "Ligand"
    ? ligandRecord?.warnings.length ?? 0
    : activeStep === "Receptor" ? receptorRecord?.warnings.length ?? 0 : structure?.warnings.length ?? 0;
  const warningStatusLabel = state.structureError ?? state.error ?? (activeWarningCount ? String(activeWarningCount) : "None");
  const provenanceLabel = activeStep === "Ligand" && ligandRecord
    ? `LIGAND · ${ligandRecord.artifact.ligand_id.slice(0, 12)}…`
    : receptorRecord
      ? `${receptorRecord.status.toUpperCase()} · ${receptorRecord.receptor_id.slice(0, 12)}…`
      : structure
        ? `${structure.artifact.source.toUpperCase()} · ${structure.artifact.sha256.slice(0, 12)}…`
        : "No structure imported";
  const generatedCommand = receptorRecord?.provenance.at(-1)?.command?.join(" ")
    ?? "No external preparation command executed";
  const pendingRecoveredWork = workRecovery?.items.filter(
    (item) => !retryResponses[recoveredWorkKey(item)],
  ).length ?? 0;

  function openActivity(tab: ActivityTab) {
    setActivityTab(tab);
    setActivityOpen(true);
  }

  async function refreshTools() {
    setToolsRefreshing(true);
    try {
      const tools = await ankoraApi.tools();
      setState((current) => ({ ...current, tools, error: null }));
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : "Scientific tools could not be rescanned";
      setState((current) => ({ ...current, error: message }));
    } finally {
      setToolsRefreshing(false);
    }
  }

  async function retryRecoveredWork(item: RecoveredWorkItem) {
    const key = recoveredWorkKey(item);
    setRetryingWorkKey(key);
    setRetryErrors((current) => ({ ...current, [key]: "" }));
    try {
      const response = await ankoraApi.retryRecoveredWork(item.work_kind, item.work_id);
      setRetryResponses((current) => ({ ...current, [key]: response }));
    } catch (error: unknown) {
      setRetryErrors((current) => ({
        ...current,
        [key]: error instanceof Error ? error.message : "The new attempt could not be started",
      }));
    } finally {
      setRetryingWorkKey((current) => current === key ? null : current);
    }
  }

  function openStructureMenu() {
    setActiveStep("Structure");
    window.setTimeout(() => {
      if (importMenuRef.current) importMenuRef.current.open = true;
    }, 0);
  }

  function workflowState(step: WorkflowStep): "complete" | "current" | "available" | "locked" {
    if (step === activeStep) return "current";
    const enabled = canNavigateTo(
      step,
      Boolean(structure),
      receptorRecord?.status === "docking_ready",
      Boolean(bindingSiteRecord),
    );
    if (!enabled) return "locked";
    if (step === "Structure" && structure) return "complete";
    if (step === "Receptor" && receptorRecord?.status === "docking_ready") return "complete";
    if (step === "Ligand" && isLigandLibraryStageComplete(ligandLibraryStatus)) return "complete";
    if (step === "Binding site" && bindingSiteRecord) return "complete";
    return "available";
  }

  function beginPanelResize(side: "workflow" | "inspector", event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = side === "workflow" ? workflowWidth : inspectorWidth;
    function move(pointerEvent: PointerEvent) {
      const delta = pointerEvent.clientX - startX;
      const next = side === "workflow" ? startWidth + delta : startWidth - delta;
      if (side === "workflow") setWorkflowWidth(Math.min(280, Math.max(176, next)));
      else setInspectorWidth(Math.min(480, Math.max(310, next)));
    }
    function finish() {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
    }
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish);
  }

  return (
    <>
      <main
        data-layout={workbenchLayout}
        style={{ "--workflow-preferred-width": `${workflowWidth}px`, "--inspector-preferred-width": `${inspectorWidth}px` } as CSSProperties}
        className={`app-shell${workflowCollapsed ? " workflow-collapsed" : ""}${inspectorCollapsed ? " inspector-collapsed" : ""}${activityOpen ? " activity-open" : ""}`}
      >
        <header className="topbar">
        <div className="brand-mark"><AppIcon name="molecule" /></div>
        <div className="brand-copy"><h1>Ankora</h1><p>Scientist-controlled docking workbench</p></div>
        <div className="app-menus" aria-label="Application menus">
          <AppMenu label="File">
            <button type="button" onClick={() => globalFileInputRef.current?.click()}><AppIcon name="file" />Open local structure…</button>
            <button type="button" onClick={openStructureMenu}><AppIcon name="molecule" />Fetch from RCSB / AlphaFold…</button>
            {latestReceptor ? <button type="button" onClick={() => void reopenLatestReceptor()}><AppIcon name="history" />Reopen latest receptor</button> : null}
            <button type="button" onClick={() => void openProjectWorkspace()}><AppIcon name="layout" />Project workspace…</button>
          </AppMenu>
          <AppMenu label="Workflow">
            {workflowSteps.map((step) => {
              const enabled = canNavigateTo(
                step,
                Boolean(structure),
                receptorRecord?.status === "docking_ready",
                Boolean(bindingSiteRecord),
              );
              return <button type="button" key={step} disabled={!enabled} onClick={() => setActiveStep(step)}><WorkflowStateIcon state={workflowState(step)} />{step}</button>;
            })}
          </AppMenu>
          <AppMenu label="Tools">
            <button type="button" onClick={() => openActivity("tools")}><AppIcon name="tools" />Scientific tool readiness</button>
            <button type="button" onClick={() => openActivity("provenance")}><AppIcon name="provenance" />Commands & provenance</button>
          </AppMenu>
          <AppMenu label="View">
            <button type="button" onClick={() => setWorkflowCollapsed((value) => !value)}><AppIcon name="panel-left" />{workflowCollapsed ? "Show" : "Hide"} workflow</button>
            <button type="button" onClick={() => setInspectorCollapsed((value) => !value)}><AppIcon name="panel-right" />{inspectorCollapsed ? "Show" : "Hide"} inspector</button>
            <button type="button" onClick={() => setActivityOpen((value) => !value)}><AppIcon name="activity" />{activityOpen ? "Close" : "Open"} activity center</button>
            <div className="menu-section-label">Theme</div>
            {(["dark", "light", "blue", "amethyst", "system"] as const).map((option) => <button type="button" className={theme === option ? "selected" : ""} key={option} onClick={() => setTheme(option)}>{option === "dark" ? "Dark (Green)" : option === "light" ? "Light" : option === "blue" ? "Dark (Blue)" : option === "amethyst" ? "Dark (Amethyst)" : "Follow Windows"}</button>)}
            <div className="menu-section-label">Density</div>
            {(["comfortable", "compact"] as const).map((option) => <button type="button" className={density === option ? "selected" : ""} key={option} onClick={() => setDensity(option)}>{option === "comfortable" ? "Comfortable" : "Compact"}</button>)}
          </AppMenu>
          <AppMenu label="Help">
            <button type="button" onClick={() => openActivity("about")}><AppIcon name="info" />About Ankora</button>
          </AppMenu>
        </div>
        <button type="button" className="project-context" onClick={() => void openProjectWorkspace()} title="Open project workspace">
          <span>{activeProject.name}</span>
          <strong>{structure ? `Structure · ${structure.metadata.entry_id ?? structure.artifact.original_filename}` : "No structure"}</strong>
        </button>
        <button type="button" className={`connection-pill ${state.connection}`} onClick={() => openActivity("tools")}><span aria-hidden="true" />{connectionLabel}</button>
        <div className="panel-buttons">
          <button type="button" aria-label="Toggle workflow panel" aria-pressed={!workflowCollapsed} onClick={() => setWorkflowCollapsed((value) => !value)}><AppIcon name="panel-left" /></button>
          <button type="button" aria-label="Toggle inspector panel" aria-pressed={!inspectorCollapsed} onClick={() => setInspectorCollapsed((value) => !value)}><AppIcon name="panel-right" /></button>
        </div>
        <input ref={globalFileInputRef} className="visually-hidden" type="file" accept=".pdb,.cif,.mmcif,chemical/x-pdb,chemical/x-mmcif" onChange={handleFileChange} />
      </header>

      <nav className="workflow" aria-label="Docking workflow">
        <div className="workflow-heading"><p className="section-label">Workflow</p><button type="button" aria-label="Collapse workflow" onClick={() => setWorkflowCollapsed(true)}><AppIcon name="panel-left" /></button></div>
        <ol>{workflowSteps.map((step, index) => {
          const enabled = canNavigateTo(
            step,
            Boolean(structure),
            receptorRecord?.status === "docking_ready",
            Boolean(bindingSiteRecord),
          );
          const stepState = workflowState(step);
          return (
            <li key={step} className={stepState === "current" ? "active" : stepState}>
              <button type="button" disabled={!enabled} aria-current={activeStep === step ? "step" : undefined} onClick={() => setActiveStep(step)}>
                <span className="workflow-index">{stepState === "complete" ? <AppIcon name="success" /> : index + 1}</span><span className="workflow-copy"><strong>{step}</strong><small>{workflowStepSummary(step, structure, receptorRecord, ligandRecord, ligandLibraryStatus, bindingSiteRecord)}</small></span>
              </button>
            </li>
          );
        })}</ol>
        <div className="workflow-note"><span>{activeStep}</span><p>{workflowNote(activeStep)}</p></div>
      </nav>
      {!workflowCollapsed ? <div className="panel-resizer workflow-resizer" role="separator" aria-label="Resize workflow panel" aria-orientation="vertical" onDoubleClick={() => setWorkflowWidth(208)} onPointerDown={(event) => beginPanelResize("workflow", event)} /> : null}
      {!inspectorCollapsed ? <div className="panel-resizer inspector-resizer" role="separator" aria-label="Resize inspector panel" aria-orientation="vertical" onDoubleClick={() => setInspectorWidth(360)} onPointerDown={(event) => beginPanelResize("inspector", event)} /> : null}

      <ErrorBoundary
        level="workspace"
        scope={`${activeProject.project_id} / ${activeStep}`}
        resetKey={`${activeProject.project_id}:${activeStep}`}
        onLeaveWorkspace={() => setActiveStep("Structure")}
      >
      {activeStep === "Receptor" && structure ? <ReceptorWorkspace structure={structure} initialRecord={receptorRecord} tools={state.tools} selection={selection} onSelect={setSelection} onRecordChange={handleReceptorRecord} onActivityChange={setWorkspaceActivity} /> : <>
      {activeStep === "Ligand" && structure && receptorRecord ? <LigandWorkspace structure={structure} record={ligandRecord} tools={state.tools} dockingInput={ligandDockingInput} onDockingInputChange={setLigandDockingInput} onLibraryDockingInputChange={setLigandLibraryDockingInput} onRecordChange={setLigandRecord} onActivityChange={setWorkspaceActivity} onLibraryStatusChange={setLigandLibraryStatus} /> : <>
      {activeStep === "Binding site" && structure && receptorRecord?.status === "docking_ready" ? <BindingSiteWorkspace structure={structure} receptor={receptorRecord} tools={state.tools} record={bindingSiteRecord} onRecordChange={setBindingSiteRecord} onContinue={(next) => {
        setBindingSiteRecord(next);
        setActiveStep("Docking");
      }} /> : <>
      {activeStep === "Export"
        ? <ExportWorkspace />
        : activeStep === "Results"
        ? <ResultsWorkspace />
        : activeStep === "Validation" && receptorRecord?.status === "docking_ready" && bindingSiteRecord
        ? <RedockingWorkspace />
        : activeStep === "Docking" && receptorRecord?.status === "docking_ready" && bindingSiteRecord ? <DockingWorkspace receptor={receptorRecord} bindingSite={bindingSiteRecord} ligand={ligandRecord} ligandInput={ligandDockingInput} libraryInput={ligandLibraryDockingInput} tools={state.tools} onActivityChange={setWorkspaceActivity} /> : <>
      <section className="workspace" aria-label="Structure workspace">
        <div className="workspace-heading">
          <div><span className="eyebrow">01 / Structure</span><h2>{structure?.metadata.title ?? "Inspect before transforming"}</h2></div>
          <div className="workspace-actions">
            <span className="read-only-badge">M1 · immutable source</span>
            <details className="import-menu" ref={importMenuRef}>
              <summary>Open structure <span aria-hidden="true">⌄</span></summary>
              <div className="import-menu-panel">
                <label className="local-file-action">
                  <span>Open local file</span><small>PDB, CIF, or mmCIF · max 50 MB</small>
                  <input type="file" accept=".pdb,.cif,.mmcif,chemical/x-pdb,chemical/x-mmcif" onChange={handleFileChange} disabled={state.structureOperation === "loading"} />
                </label>
                <div className="menu-divider"><span>{fetchSource === "alphafold" ? "or fetch from AlphaFold DB" : "or fetch from RCSB"}</span></div>
                <form className="pdb-fetch-form" onSubmit={handleFetch}>
                  <div className="fetch-source-toggle" role="radiogroup" aria-label="Online structure source">
                    <label><input type="radio" name="fetch-source" checked={fetchSource === "rcsb"} onChange={() => { setFetchSource("rcsb"); setPdbId(""); }} />RCSB PDB ID</label>
                    <label><input type="radio" name="fetch-source" checked={fetchSource === "alphafold"} onChange={() => { setFetchSource("alphafold"); setPdbId(""); }} />UniProt ID</label>
                  </div>
                  <label htmlFor="pdb-id">{fetchSource === "alphafold" ? "UniProt accession" : "PDB ID"}</label>
                  <div>
                    <input id="pdb-id" value={pdbId} onChange={(event) => setPdbId(event.target.value.slice(0, fetchSource === "alphafold" ? 10 : 4))} placeholder={fetchSource === "alphafold" ? "P04637" : "7AQF"} autoComplete="off" spellCheck={false} />
                    <button type="submit" disabled={state.structureOperation === "loading"}>Fetch</button>
                  </div>
                </form>
                {latestReceptor ? <>
                  <div className="menu-divider"><span>saved work</span></div>
                  <button type="button" className="saved-receptor-action" onClick={() => void reopenLatestReceptor()}>
                    <strong>Reopen last receptor</strong>
                    <small>{latestReceptor.status.replaceAll("_", " ")} · {latestReceptor.receptor_id.slice(0, 8)}…</small>
                  </button>
                </> : null}
              </div>
            </details>
          </div>
        </div>

        {state.structureOperation === "loading" ? (
          <div className="operation-progress" role="progressbar" aria-label="Opening structure"><span /><p>Validating, preserving, and inspecting the structure…</p></div>
        ) : null}
        {state.structureError ? <div className="structure-error" role="alert">{state.structureError}</div> : null}

        {structure ? (
          <MolecularViewer sources={structureViewerSources} selection={selection} />
        ) : (
          <div className="viewer-placeholder" data-testid="viewer-placeholder">
            <div className="orbital orbital-one" /><div className="orbital orbital-two" />
            <div className="viewer-message">
              <div className="molecule-glyph" aria-hidden="true">⌬</div>
              <h3>Open a molecular structure</h3>
              <p>Import a local PDB/mmCIF file, or fetch a four-character PDB ID from RCSB or a UniProt accession from AlphaFold DB. Ankora will inspect it without changing coordinates.</p>
              <div className="empty-actions">
                <label className="primary-action">Choose file<input type="file" accept=".pdb,.cif,.mmcif" onChange={handleFileChange} /></label>
                {latestReceptor ? <button type="button" className="resume-receptor-action" onClick={() => void reopenLatestReceptor()}>
                  <strong>Reopen last receptor</strong>
                  <small>{latestReceptor.status.replaceAll("_", " ")} · saved {formatApplicationDateTime(latestReceptor.created_at)}</small>
                </button> : null}
                <span>or use “Open structure” above</span>
              </div>
            </div>
          </div>
        )}
      </section>

      <aside className="inspector" aria-label="Inspector">
        {structure ? <StructureInspector structure={structure} selection={selection} onSelect={setSelection} /> : <SystemInspector state={state} onOpenTools={() => openActivity("tools")} />}
      </aside>
      </>}
      </>}
      </>}
      </>}
      </ErrorBoundary>

      <footer className="statusbar">
        <div className="status-summary">
          {/* The connection pill in the top bar already reports the backend,
              so this slot shows what the machine is doing instead - the one
              thing a running campaign changes that nothing else displayed. */}
          <button type="button" className={`status-item ${state.connection}`} title={resources.detail} onClick={() => openActivity("tools")}><AppIcon name="activity" /><span><small>Machine</small><strong>{resources.label}</strong></span></button>
          <button type="button" className={`status-item ${activeWarningCount || state.error || state.structureError ? "has-warning" : ""}`} onClick={() => openActivity("warnings")}><AppIcon name="alert" /><span><small>Warnings</small><strong>{warningStatusLabel}</strong></span></button>
          <button type="button" className="status-item" onClick={() => openActivity("provenance")}><AppIcon name="provenance" /><span><small>Provenance</small><strong>{provenanceLabel}</strong></span></button>
          <button type="button" className={`status-item activity-toggle${workspaceActivity || pendingRecoveredWork ? " running" : ""}`} aria-expanded={activityOpen} onClick={() => setActivityOpen((value) => !value)}><AppIcon name="activity" /><span><small>Activity</small><strong>{workspaceActivity?.title ?? (pendingRecoveredWork ? `${pendingRecoveredWork} interrupted` : activityOpen ? "Close center" : "Open details")}</strong></span><AppIcon name="chevron" /></button>
        </div>
        {activityOpen ? <section className="activity-center" aria-label="Activity center">
          <nav aria-label="Activity sections">
            {(["activity", "warnings", "provenance", "tools", "about"] as const).map((tab) => <button type="button" key={tab} className={activityTab === tab ? "selected" : ""} onClick={() => setActivityTab(tab)}>{activityTabLabel(tab)}</button>)}
          </nav>
          <div className="activity-content">
            {activityTab === "activity" ? <div className="activity-work-list">
              {workRecovery?.items.length ? <RecoveryPanel
                items={workRecovery.items}
                acknowledgements={retryAcknowledgements}
                retryingKey={retryingWorkKey}
                responses={retryResponses}
                errors={retryErrors}
                onAcknowledge={(key, checked) => setRetryAcknowledgements((current) => ({ ...current, [key]: checked }))}
                onRetry={(item) => void retryRecoveredWork(item)}
              /> : recoveryLoadError ? <div className="recovery-load-error" role="alert">{recoveryLoadError}</div> : null}
              {workspaceActivity ? <ActiveWorkspaceJob activity={workspaceActivity} /> : null}
              {!workspaceActivity && !workRecovery?.items.length && !recoveryLoadError ? <div className="activity-empty"><AppIcon name="activity" /><div><strong>No background operation is running</strong><p>Preparation and batch operations report progress and bounded worker usage here while they run.</p></div></div> : null}
            </div> : null}
            {activityTab === "warnings" ? <div className="activity-warning-list"><strong>{activeWarningCount ? `${activeWarningCount} retained warning${activeWarningCount === 1 ? "" : "s"}` : "No active warnings"}</strong><p>{activeStep === "Ligand" && ligandRecord ? ligandRecord.warnings.join(" · ") || "The selected ligand has no recorded warnings." : activeStep === "Receptor" && receptorRecord ? receptorRecord.warnings.join(" · ") || "The prepared receptor has no recorded warnings." : warningLabel}</p></div> : null}
            {activityTab === "provenance" ? <div className="activity-provenance"><div><small>Current artifact</small><strong>{provenanceLabel}</strong></div><div><small>Latest generated command</small><code>{generatedCommand}</code></div></div> : null}
            {activityTab === "tools" ? <div className="tools-activity-view">
              <div className="tools-activity-toolbar"><div><strong>Backend scientific environment</strong><span>Python {state.system?.python_version ?? "—"} · {state.system?.python_environment ?? "unknown environment"}</span></div><button type="button" disabled={toolsRefreshing} onClick={() => void refreshTools()}><AppIcon name="tools" />{toolsRefreshing ? "Scanning…" : "Rescan tools"}</button></div>
              <div className="activity-tools"><ToolSummary name="PDBFixer" status={state.tools?.pdbfixer} /><ToolSummary name="PDB2PQR" status={state.tools?.pdb2pqr} /><ToolSummary name="PROPKA" status={state.tools?.propka} /><ToolSummary name="Meeko receptor" status={state.tools?.meeko} /><ToolSummary name="Meeko ligand" status={state.tools?.meeko_ligand} /><ToolSummary name="AutoDock Vina" status={state.tools?.vina} /><ToolSummary name="AutoGrid4" status={state.tools?.autogrid4} /><ToolSummary name="AutoDock4 CPU" status={state.tools?.autodock4} /><ToolSummary name="AutoDock-GPU" status={state.tools?.autodock_gpu} /><ToolSummary name="GNINA · deferred" status={state.tools?.gnina} /><ToolSummary name="P2Rank" status={state.tools?.p2rank} /></div>
            </div> : null}
            {activityTab === "about" ? <div className="activity-about"><div className="brand-mark"><AppIcon name="molecule" /></div><div><strong>Ankora 0.1.0</strong><p>Native Windows workbench for explicit, inspectable, and reproducible molecular docking.</p></div></div> : null}
          </div>
        </section> : null}
      </footer>
    </main>
    {projectWorkspaceOpen ? (
      <ProjectWorkspace
        catalog={projectCatalog}
        graph={projectGraph}
        busy={projectBusy}
        error={projectError}
        onClose={() => setProjectWorkspaceOpen(false)}
        onCreate={createProject}
        onActivate={activateProject}
        onMarkStale={markProjectDependencyStale}
        onLoadMore={loadMoreProjectDependencies}
      />
    ) : null}
    {!splashDismissed ? (
      <SplashScreen
        connection={state.connection}
        health={state.health}
        system={state.system}
        tools={state.tools}
        error={state.error}
        onRetry={initializeBackend}
        onDismiss={() => setSplashDismissed(true)}
      />
    ) : null}
    </>
  );
}

function isProjectCatalog(value: unknown): value is ProjectCatalog {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<ProjectCatalog>;
  return typeof candidate.active_project_id === "string" && Array.isArray(candidate.projects);
}

function isProjectDependencyGraph(value: unknown): value is ProjectDependencyGraph {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<ProjectDependencyGraph>;
  return typeof candidate.project_id === "string"
    && Array.isArray(candidate.nodes)
    && Array.isArray(candidate.edges)
    && typeof candidate.total_nodes === "number";
}

function AppMenu({ label, children }: { label: string; children: ReactNode }) {
  return <details className="app-menu" onToggle={(event) => {
    if (event.currentTarget.open) document.querySelectorAll<HTMLDetailsElement>(".app-menu[open]").forEach((menu) => { if (menu !== event.currentTarget) menu.open = false; });
  }}><summary>{label}</summary><div className="app-menu-panel" onClick={(event) => {
    if ((event.target as HTMLElement).closest("button")) event.currentTarget.closest("details")?.removeAttribute("open");
  }}>{children}</div></details>;
}

function recoveredWorkKey(item: RecoveredWorkItem): string {
  return `${item.work_kind}:${item.work_id}`;
}

function recoveredWorkLabel(item: RecoveredWorkItem): string {
  const labels: Record<RecoveredWorkItem["work_kind"], string> = {
    vina_job: "AutoDock Vina job",
    vina_batch: "AutoDock Vina screening",
    autogrid_job: "AutoGrid map generation",
    autodock4_job: "AutoDock4 job",
    autodock4_batch: "AutoDock4 screening",
    autodock_gpu_job: "AutoDock-GPU job",
    autodock_gpu_batch: "AutoDock-GPU screening",
  };
  return labels[item.work_kind];
}

function RecoveryPanel({
  items,
  acknowledgements,
  retryingKey,
  responses,
  errors,
  onAcknowledge,
  onRetry,
}: {
  items: RecoveredWorkItem[];
  acknowledgements: Record<string, boolean>;
  retryingKey: string | null;
  responses: Record<string, WorkRetryResponse>;
  errors: Record<string, string>;
  onAcknowledge: (key: string, checked: boolean) => void;
  onRetry: (item: RecoveredWorkItem) => void;
}) {
  return <section className="recovery-panel" aria-label="Interrupted work recovered at startup">
    <header><AppIcon name="alert" /><div><strong>{items.length} interrupted operation{items.length === 1 ? "" : "s"} recovered</strong><p>The abandoned attempts and their raw evidence were preserved. Nothing will restart without your confirmation.</p></div></header>
    <div className="recovery-items">{items.map((item) => {
      const key = recoveredWorkKey(item);
      const response = responses[key];
      const isRetrying = retryingKey === key;
      return <article key={key} className={response ? "retried" : ""}>
        <div className="recovery-item-heading"><div><strong>{recoveredWorkLabel(item)}</strong><code title={item.work_id}>{item.work_id.slice(0, 12)}…</code></div><span>{item.previous_status.replaceAll("_", " ")}</span></div>
        {item.interrupted_entry_count || item.completed_entry_count ? <p className="recovery-counts">{item.completed_entry_count} completed molecule{item.completed_entry_count === 1 ? "" : "s"} preserved · {item.interrupted_entry_count} interrupted</p> : null}
        {response ? <div className="retry-started"><AppIcon name="success" /><span><strong>New attempt {response.status.replaceAll("_", " ")}</strong><code title={response.new_work_id}>{response.new_work_id.slice(0, 12)}…</code></span></div> : <>
          <label className="retry-acknowledgement"><input type="checkbox" checked={Boolean(acknowledgements[key])} onChange={(event) => onAcknowledge(key, event.target.checked)} /><span>I understand this creates a new immutable attempt; it does not resume or alter the interrupted one.</span></label>
          <button type="button" disabled={!acknowledgements[key] || isRetrying} onClick={() => onRetry(item)}>{isRetrying ? "Starting a new attempt…" : "Retry as new"}</button>
        </>}
        {errors[key] ? <p className="retry-error" role="alert">{errors[key]}</p> : null}
      </article>;
    })}</div>
  </section>;
}

function ActiveWorkspaceJob({ activity }: { activity: WorkspaceActivity }) {
  const hasProgress = activity.current !== undefined && activity.total !== undefined && activity.total > 0;
  const percentage = hasProgress ? Math.min(100, (activity.current! / activity.total!) * 100) : 0;
  return <div className="active-workspace-job">
    <div className="job-heading"><span className="status-dot" aria-hidden="true" /><div><strong>{activity.title}</strong><p>{activity.detail}</p></div></div>
    <div className={`job-progress${hasProgress ? " determinate" : ""}`} role="progressbar" aria-label={activity.title} aria-valuemin={hasProgress ? 0 : undefined} aria-valuemax={hasProgress ? activity.total : undefined} aria-valuenow={hasProgress ? activity.current : undefined}><span style={hasProgress ? { width: `${percentage}%` } : undefined} /></div>
    <div className="job-metrics"><span>{hasProgress ? `${activity.current}/${activity.total} molecules` : "Working"}</span>{activity.workers ? <span>{activity.workers} parallel workers</span> : null}</div>
  </div>;
}

function WorkflowStateIcon({ state }: { state: "complete" | "current" | "available" | "locked" }) {
  return state === "complete" ? <AppIcon name="success" /> : <span className={`menu-state-dot ${state}`} aria-hidden="true" />;
}

function workflowStepSummary(
  step: WorkflowStep,
  structure: StructureRecord | null,
  receptor: ReceptorPreparationRecord | null,
  ligand: LigandRecord | null,
  libraryStatus: LigandLibraryStatusSummary | null,
  bindingSite: BindingSiteRecord | null,
): string {
  if (step === "Structure") return structure ? `Loaded · ${structure.metadata.entry_id ?? structure.artifact.original_filename}` : "Open or fetch";
  if (step === "Receptor") return receptor?.status === "docking_ready" ? "Docking ready" : structure ? "Needs preparation" : "Requires structure";
  if (step === "Ligand") {
    if (libraryStatus) {
      if (isLigandLibraryStageComplete(libraryStatus)) {
        return libraryStatus.notReady > 0
          ? `${libraryStatus.prepared}/${libraryStatus.total} ready · ${libraryStatus.notReady} retained`
          : `${libraryStatus.prepared}/${libraryStatus.total} ready`;
      }
      return `${libraryStatus.terminal}/${libraryStatus.total} processed · ${libraryStatus.prepared} ready`;
    }
    return ligand ? ligand.inspection.name : receptor?.status === "docking_ready" ? "Choose source" : "Requires receptor";
  }
  if (step === "Binding site") {
    if (bindingSite) return `${formatScientificNumber(bindingSite.box.size_x, 0)}×${formatScientificNumber(bindingSite.box.size_y, 0)}×${formatScientificNumber(bindingSite.box.size_z, 0)} Å box`;
    return receptor?.status === "docking_ready" ? "Choose source" : "Requires receptor";
  }
  if (step === "Docking") return bindingSite ? "Ready to configure" : "Requires binding site";
  if (step === "Results") return "Everything recorded";
  if (step === "Export") return "Bundles and figures";
  if (step === "Validation") return bindingSite ? "Redocking" : "Requires binding site";
  return "Not implemented";
}

function workflowNote(step: WorkflowStep): string {
  if (step === "Structure") return "Inspect the immutable molecular source before creating any derivative.";
  if (step === "Receptor") return "Decide chains, components, structural issues, protonation, and docking format explicitly.";
  if (step === "Ligand") return "Prepare one compound or a filtered library while preserving source order and chemical state.";
  if (step === "Binding site") return "Define the docking search space explicitly — from a ligand, selected residues, manual coordinates, the full receptor, or a detected pocket.";
  if (step === "Docking") return "Configure an explicit engine, ligand input, search parameters, and reproducible command before execution.";
  if (step === "Export") return "Everything this project has sent out — campaign bundles, publication figures, and ligand–receptor complexes — with the result each one came from.";
  if (step === "Results") return "Browse every result this project has recorded — each with the engine that produced it, the space it searched, and whether repeating it would reproduce the numbers.";
  return "This stage remains locked until its scientific contract is implemented and validated.";
}

function activityTabLabel(tab: ActivityTab): string {
  if (tab === "activity") return "Activity";
  if (tab === "warnings") return "Warnings";
  if (tab === "provenance") return "Provenance & commands";
  if (tab === "tools") return "Scientific tools";
  return "About";
}

function ToolSummary({ name, status }: { name: string; status: { available: boolean; version: string | null; architecture?: string | null; path?: string | null } | null | undefined }) {
  const evidence = [status?.version, status?.architecture].filter(Boolean).join(" · ");
  return <article className={status?.available ? "available" : "missing"} title={status?.path ?? undefined}><span>{status?.available ? <AppIcon name="success" /> : <AppIcon name="alert" />}</span><div><strong>{name}</strong><small>{status?.available ? evidence || "Available" : "Not visible to this backend"}</small></div></article>;
}

function StructureInspector({ structure, selection, onSelect }: { structure: StructureRecord; selection: ViewerSelection | null; onSelect: (value: ViewerSelection | null) => void }) {
  const { metadata, artifact } = structure;
  const selectableHeterogens = metadata.heterogens.filter((item) => item.kind !== "water");
  const waterCount = metadata.heterogens.length - selectableHeterogens.length;
  return (
    <>
      <div className="inspector-heading"><span className="section-label">Structure inspector</span><h2>{metadata.entry_id ?? artifact.original_filename}</h2><p className="inspector-subtitle">{artifact.original_filename}</p></div>
      <section className="system-card metadata-card"><dl>
        <div><dt>Models</dt><dd>{metadata.model_count}</dd></div><div><dt>Atoms</dt><dd>{formatCount(metadata.atom_count)}</dd></div>
        <div><dt>Residues</dt><dd>{formatCount(metadata.residue_count)}</dd></div><div><dt>Resolution</dt><dd>{metadata.resolution_angstrom !== null ? `${formatScientificNumber(metadata.resolution_angstrom, 2)} Å` : "Not reported"}</dd></div>
      </dl></section>

      <InspectorGroup title="Chains" count={metadata.chains.length}>
        <div className="selection-list">{metadata.chains.map((chain) => {
          const selected = selection?.kind === "chain" && selection.chainId === chain.chain_id;
          return (
            <button type="button" key={chain.chain_id || "blank-chain"} className={selected ? "selected" : ""} onClick={() => onSelect(selected ? null : { kind: "chain", chainId: chain.chain_id })}>
              <span className="selection-monogram">{displayChain(chain.chain_id)}</span><span><strong>Chain {displayChain(chain.chain_id)}</strong><small>{chain.polymer_residue_count} polymer residues · {chain.atom_count} atoms</small></span>
            </button>
          );
        })}</div>
      </InspectorGroup>

      <InspectorGroup title="Heterogens" count={metadata.heterogens.length}>
        <div className="selection-list compact-list">{selectableHeterogens.length ? selectableHeterogens.map((heterogen, index) => {
          const selected = isSelectedHeterogen(selection, heterogen);
          return (
            <button type="button" key={`${heterogen.chain_id}-${heterogen.name}-${heterogen.sequence_number ?? "?"}-${index}`} className={selected ? "selected" : ""} onClick={() => onSelect(selected ? null : { kind: "heterogen", heterogen })}>
              <span className={`heterogen-dot ${heterogen.kind}`} /><span><strong>{heterogen.name} {displayChain(heterogen.chain_id)}:{heterogen.sequence_number ?? "?"}</strong><small>{heterogen.kind} · {heterogen.atom_count} {heterogen.atom_count === 1 ? "atom" : "atoms"}</small></span>
            </button>
          );
        }) : null}
        {waterCount ? <div className="water-summary"><span className="heterogen-dot water" /><span><strong>Resolved waters</strong><small>{waterCount} solvent molecules retained in the original</small></span></div> : null}
        {!metadata.heterogens.length ? <p className="empty-list">No heterogens in the primary model.</p> : null}</div>
      </InspectorGroup>

      <InspectorGroup title="Structural warnings" count={structure.warnings.length} initiallyOpen={structure.warnings.length > 0}>
        {structure.warnings.length ? <ul className="warning-list">{structure.warnings.map((warning) => <li key={warning.code}><strong>{warning.code}</strong><span>{warning.message}</span></li>)}</ul> : <p className="empty-list good">No reported structural warnings.</p>}
      </InspectorGroup>

      <details className="provenance-details"><summary>Original & provenance</summary><dl>
        <div><dt>Source</dt><dd>{artifact.source.toUpperCase()}</dd></div><div><dt>Format</dt><dd>{artifact.format.toUpperCase()}</dd></div>
        <div><dt>Size</dt><dd>{formatBytes(artifact.size_bytes)}</dd></div><div><dt>SHA-256</dt><dd title={artifact.sha256}>{artifact.sha256.slice(0, 16)}…</dd></div>
      </dl></details>
    </>
  );
}

function InspectorGroup({ title, count, children, initiallyOpen = true }: { title: string; count: number; children: React.ReactNode; initiallyOpen?: boolean }) {
  return <details className="inspector-group" open={initiallyOpen}><summary><span>{title}</span><small>{count}</small></summary>{children}</details>;
}

function SystemInspector({ state, onOpenTools }: { state: ApplicationState; onOpenTools: () => void }) {
  const toolEntries = state.tools ? [
    ["PDBFixer", state.tools.pdbfixer], ["PDB2PQR", state.tools.pdb2pqr], ["PROPKA", state.tools.propka], ["Meeko receptor", state.tools.meeko], ["Meeko ligand", state.tools.meeko_ligand], ["AutoDock Vina", state.tools.vina], ["AutoGrid4", state.tools.autogrid4], ["AutoDock4 CPU", state.tools.autodock4], ["AutoDock-GPU", state.tools.autodock_gpu], ["GNINA · deferred", state.tools.gnina], ["P2Rank", state.tools.p2rank],
  ] as const : [];
  const availableCount = toolEntries.filter(([, tool]) => tool.available).length;
  return (
    <>
      <div className="inspector-heading"><span className="section-label">System inspector</span><h2>Local readiness</h2></div>
      <section className="system-card"><dl>
        <div><dt>Backend</dt><dd>{state.health?.backend_version ?? "—"}</dd></div><div><dt>Platform</dt><dd>{state.system?.platform ?? "—"}</dd></div>
        <div><dt>Architecture</dt><dd>{state.system?.architecture ?? "—"}</dd></div><div><dt>Python</dt><dd>{state.system?.python_version ?? "—"}</dd></div>
        <div><dt>Environment</dt><dd>{state.system?.python_environment ?? "—"}</dd></div>
      </dl></section>
      <section className="readiness-card">
        <div className="readiness-score"><div><strong>{availableCount}</strong><span>of {toolEntries.length || 11} tools detected</span></div><span>{Math.round((availableCount / (toolEntries.length || 11)) * 100)}%</span></div>
        <div className="readiness-progress"><span style={{ width: `${(availableCount / (toolEntries.length || 11)) * 100}%` }} /></div>
        <p>Ankora checks executable presence without launching scientific tools. Missing tools are introduced when their workflow stage needs them.</p>
        <div className="readiness-tool-list">{toolEntries.map(([name, tool]) => <span className={tool.available ? "available" : "missing"} key={name}>{tool.available ? <AppIcon name="success" /> : <AppIcon name="alert" />}{name}</span>)}</div>
        <button type="button" onClick={onOpenTools}><AppIcon name="tools" />Review scientific tools</button>
      </section>
    </>
  );
}

function isSelectedHeterogen(selection: ViewerSelection | null, heterogen: HeterogenSummary): boolean {
  if (selection?.kind !== "heterogen") return false;
  const selected = selection.heterogen;
  return selected.chain_id === heterogen.chain_id && selected.name === heterogen.name && selected.sequence_number === heterogen.sequence_number && selected.insertion_code === heterogen.insertion_code;
}

function displayChain(chainId: string): string { return chainId || "∅"; }
function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function readUiSetting<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const value = localStorage.getItem(key) as T | null;
    return value && allowed.includes(value) ? value : fallback;
  } catch {
    return fallback;
  }
}
