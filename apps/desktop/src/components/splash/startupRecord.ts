import type {
  HealthResponse,
  ProjectCatalog,
  SystemResponse,
  ToolsResponse,
  ToolStatus,
  WorkRecoverySummary,
} from "../../types/api";

/**
 * The startup record: what the workbench has actually confirmed about itself.
 *
 * Each channel is bound to the response that proves it — /health, /system,
 * /tools, /work/recovery and /projects. A channel stays pending until its
 * response arrives and reports exactly what that response said. Nothing here
 * infers a value, fills a gap with a default, or calls the system "nominal":
 * a missing tool is named, an interrupted campaign is counted, and a backend
 * that never answers stops the record rather than being papered over.
 */

export type ChannelKey = "backend" | "runtime" | "tools" | "recovery" | "project";
export type ChannelStatus = "pending" | "ok" | "notice" | "fail" | "skipped";

export interface StartupChannel {
  key: ChannelKey;
  label: string;
  status: ChannelStatus;
  value: string;
  /** The part of the value that is a notice, so it can be emphasised. */
  notice?: string;
}

export interface StartupInputs {
  connection: "checking" | "connected" | "disconnected";
  origin: string;
  health: HealthResponse | null;
  system: SystemResponse | null;
  tools: ToolsResponse | null;
  recovery: WorkRecoverySummary | null;
  recoveryError: string | null;
  projects: ProjectCatalog | null;
  projectsError: string | null;
}

// Display names and order match the workbench's own readiness panel.
const TOOL_NAMES: ReadonlyArray<readonly [keyof ToolsResponse, string]> = [
  ["pdbfixer", "PDBFixer"], ["pdb2pqr", "PDB2PQR"], ["propka", "PROPKA"],
  ["meeko", "Meeko receptor"], ["meeko_ligand", "Meeko ligand"], ["vina", "AutoDock Vina"],
  ["autogrid4", "AutoGrid4"], ["autodock4", "AutoDock4 CPU"], ["autodock_gpu", "AutoDock-GPU"],
  ["gnina", "GNINA"], ["p2rank", "P2Rank"],
];
// GNINA is deferred by product decision: its absence is expected, not a notice.
const DEFERRED: ReadonlySet<keyof ToolsResponse> = new Set(["gnina"]);

const LABELS: Record<ChannelKey, string> = {
  backend: "Backend", runtime: "Runtime", tools: "Tools", recovery: "Recovery", project: "Project",
};

const plural = (count: number, noun: string) => `${count} ${noun}${count === 1 ? "" : "s"}`;

function channel(key: ChannelKey, status: ChannelStatus, value: string, notice?: string): StartupChannel {
  return { key, label: LABELS[key], status, value, notice };
}

export function deriveStartupRecord(input: StartupInputs): StartupChannel[] {
  const failed = input.connection === "disconnected";
  const skipped = (key: ChannelKey) => channel(key, "skipped", "not checked");
  const pending = (key: ChannelKey) => channel(key, "pending", "awaiting");

  const backend = failed
    ? channel("backend", "fail", `no answer from ${input.origin}`)
    : input.health
      ? channel("backend", "ok", `ankora-backend ${input.health.backend_version} · ${input.origin}`)
      : pending("backend");

  if (failed) {
    return [backend, skipped("runtime"), skipped("tools"), skipped("recovery"), skipped("project")];
  }

  const runtime = input.system
    ? channel(
      "runtime", "ok",
      [`Python ${input.system.python_version}`, `${input.system.platform} ${input.system.architecture}`,
        input.system.python_environment].filter(Boolean).join(" · "),
    )
    : pending("runtime");

  return [backend, runtime, toolsChannel(input.tools), recoveryChannel(input), projectChannel(input)];
}

function toolsChannel(tools: ToolsResponse | null): StartupChannel {
  if (!tools) return channel("tools", "pending", "awaiting");
  const entries = TOOL_NAMES.map(([key, name]) => [key, name, tools[key] as ToolStatus | undefined] as const);
  const detected = entries.filter(([, , status]) => status?.available).length;
  const missing = entries
    .filter(([key, , status]) => !status?.available && !DEFERRED.has(key))
    .map(([, name]) => name);
  const deferred = entries.filter(([key, , status]) => !status?.available && DEFERRED.has(key)).map(([, name]) => name);
  const base = [`${detected} of ${entries.length} detected`, ...deferred.map((name) => `${name} deferred`)].join(" · ");
  if (!missing.length) return channel("tools", "ok", base);
  const notice = `${missing.join(", ")} not found`;
  return channel("tools", "notice", `${base} · ${notice}`, notice);
}

function recoveryChannel(input: StartupInputs): StartupChannel {
  if (input.recoveryError) {
    const notice = "could not be inspected";
    return channel("recovery", "notice", notice, notice);
  }
  if (!input.recovery) return channel("recovery", "pending", "awaiting");
  const count = input.recovery.items.length;
  if (!count) return channel("recovery", "ok", "no interrupted work");
  const notice = `${plural(count, "interrupted run")} preserved`;
  return channel("recovery", "notice", notice, notice);
}

function projectChannel(input: StartupInputs): StartupChannel {
  if (input.projectsError) {
    const notice = "project catalog could not be read";
    return channel("project", "notice", notice, notice);
  }
  if (!input.projects) return channel("project", "pending", "awaiting");
  const { active_project_id: active, projects } = input.projects;
  const name = projects.find((project) => project.project_id === active)?.name ?? active;
  return channel("project", "ok", `${name} · ${plural(projects.length, "project")} registered`);
}

export type StartupPhase = "starting" | "ready" | "failed";

export function startupPhase(channels: StartupChannel[]): StartupPhase {
  if (channels.some((item) => item.status === "fail")) return "failed";
  return channels.every((item) => item.status === "ok" || item.status === "notice") ? "ready" : "starting";
}

/** `127.0.0.1:8765` from the API base the client was built against. */
export function originOf(apiBase: string): string {
  try {
    return new URL(apiBase).host;
  } catch {
    return apiBase;
  }
}

// Names of the workbench's themes, as its View menu presents them.
const THEME_NAMES: Record<string, string> = {
  obsidian: "Obsidian Instrument", dark: "Midnight Laboratory", blue: "Cryo-EM Graphite",
  amethyst: "Spectra Quartz", light: "Light", system: "Follow Windows",
};

export function themeName(theme: string | undefined): string {
  if (!theme) return "Ankora";
  return THEME_NAMES[theme] ?? theme.charAt(0).toUpperCase() + theme.slice(1);
}
