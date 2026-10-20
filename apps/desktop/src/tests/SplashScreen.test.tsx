import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import indexHtml from "../../index.html?raw";
import themeBoot from "../../public/theme-boot.js?raw";
import sceneSource from "../assets/splash-scene.json?raw";
import { SplashScreen, type SplashScreenProps } from "../components/SplashScreen";
import { parseScene } from "../components/splash/anchoringScene";
import { deriveStartupRecord, originOf, startupPhase, themeName, type StartupInputs } from "../components/splash/startupRecord";
import type { ToolsResponse } from "../types/api";

// Synthetic fixtures: shaped like the backend's responses, not recorded results.
const health = { status: "ok", backend_version: "0.1.0" } as const;
const system = { platform: "windows", architecture: "x86_64", python_version: "3.12.14", python_environment: "ankora-dev", app_mode: "development" };
const tool = (available: boolean) => ({ available, path: available ? "tools/x.exe" : null, version: available ? "1.0" : null });
const allTools: ToolsResponse = {
  vina: tool(true), gnina: tool(false), autogrid4: tool(true), autodock4: tool(true), autodock_gpu: tool(true),
  pdbfixer: tool(true), pdb2pqr: tool(true), propka: tool(true), meeko: tool(true), meeko_ligand: tool(true), p2rank: tool(true),
};
const projects = { active_project_id: "default", projects: [{ project_id: "default", name: "default", registered_at: "2026-10-01T00:00:00Z", migrated_legacy: false }] };
const noRecovery = { reconciled_at: "2026-10-20T00:00:00Z", items: [] };

const inputs = (overrides: Partial<StartupInputs> = {}): StartupInputs => ({
  connection: "connected", origin: "127.0.0.1:8765", health, system, tools: allTools,
  recovery: noRecovery, recoveryError: null, projects, projectsError: null, ...overrides,
});

const props = (overrides: Partial<SplashScreenProps> = {}): SplashScreenProps => ({
  connection: "connected", health, system, tools: allTools, error: null,
  recovery: noRecovery, recoveryError: null, projects, projectsError: null, theme: "obsidian", ...overrides,
});

describe("startup record", () => {
  it("asserts nothing before the backend answers", () => {
    const record = deriveStartupRecord(inputs({ connection: "checking", health: null, system: null, tools: null, recovery: null, projects: null }));

    expect(record.map((row) => row.status)).toEqual(["pending", "pending", "pending", "pending", "pending"]);
    expect(record.every((row) => row.value === "awaiting")).toBe(true);
    expect(startupPhase(record)).toBe("starting");
  });

  it("reports exactly what each response said", () => {
    const [backend, runtime, tools, recovery, project] = deriveStartupRecord(inputs());

    expect(backend.value).toBe("ankora-backend 0.1.0 · 127.0.0.1:8765");
    expect(runtime.value).toBe("Python 3.12.14 · windows x86_64 · ankora-dev");
    expect(tools).toMatchObject({ status: "ok", value: "10 of 11 detected · GNINA deferred" });
    expect(recovery).toMatchObject({ status: "ok", value: "no interrupted work" });
    expect(project).toMatchObject({ status: "ok", value: "default · 1 project registered" });
  });

  it("names a missing tool instead of calling the system ready without it", () => {
    const tools = deriveStartupRecord(inputs({ tools: { ...allTools, pdbfixer: tool(false), p2rank: tool(false) } }))[2];

    expect(tools.status).toBe("notice");
    expect(tools.value).toBe("8 of 11 detected · GNINA deferred · PDBFixer, P2Rank not found");
    expect(tools.notice).toBe("PDBFixer, P2Rank not found");
  });

  it("treats the deferred engine's absence as expected, not as a notice", () => {
    expect(deriveStartupRecord(inputs())[2].status).toBe("ok");
  });

  it("counts interrupted work and says when recovery could not be inspected", () => {
    const interrupted = { work_kind: "vina_batch", work_id: "w1", previous_status: "running", interrupted_entry_count: 3,
      completed_entry_count: 7, last_heartbeat_at: null, previous_owner_instance_id: null };
    const withItems = deriveStartupRecord(inputs({ recovery: { ...noRecovery, items: [interrupted, interrupted] } as StartupInputs["recovery"] }))[3];
    const unknown = deriveStartupRecord(inputs({ recovery: null, recoveryError: "boom" }))[3];

    expect(withItems).toMatchObject({ status: "notice", value: "2 interrupted runs preserved" });
    expect(unknown).toMatchObject({ status: "notice", value: "could not be inspected" });
  });

  it("does not count the project until the catalog has actually answered", () => {
    const record = deriveStartupRecord(inputs({ projects: null }));

    expect(record[4].status).toBe("pending");
    expect(startupPhase(record)).toBe("starting");
  });

  it("stops the record, rather than papering over it, when the backend never answers", () => {
    const record = deriveStartupRecord(inputs({ connection: "disconnected" }));

    expect(record[0]).toMatchObject({ status: "fail", value: "no answer from 127.0.0.1:8765" });
    expect(record.slice(1).every((row) => row.status === "skipped")).toBe(true);
    expect(startupPhase(record)).toBe("failed");
  });

  it("names the backend address and the instrument", () => {
    expect(originOf("http://127.0.0.1:8765/api/v1")).toBe("127.0.0.1:8765");
    expect(themeName("obsidian")).toBe("Obsidian Instrument");
    expect(themeName("dark")).toBe("Midnight Laboratory");
    expect(themeName("unknown-theme")).toBe("Unknown-theme");
  });
});

describe("startup scene asset", () => {
  it("is the recorded 7AQF/RV2 reference case, verified by its frozen hashes", () => {
    const raw = JSON.parse(sceneSource);

    // Expected values come from docs/validation/reference_cases/SERPINE1_7AQF_RV2.md.
    expect(raw.provenance.structure_sha256).toBe("79fd3b96adca6bdbe17ded6e9c693534007ae2cb0538739044788754b7c6faac");
    expect(raw.provenance.ligand_sha256).toBe("6fa65e2d76adb3ba91d60a5747e4986d359766c965f29fdf3559203f26195fe4");
    const scene = parseScene(raw);
    expect(scene?.ligand.atoms).toHaveLength(27);            // RV2 heavy atoms, as recorded
    expect(scene?.box?.size).toEqual([21.6, 19.87, 19.32]); // the frozen co-crystal search space
    expect(new Set(scene?.contacts.map((c) => c.residue))).toEqual(new Set(["THR 120", "GLN 123"]));
  });

  it("refuses a malformed scene instead of drawing part of one", () => {
    expect(parseScene(null)).toBeNull();
    expect(parseScene({ ligand: { atoms: [], bonds: [] }, dots: [] })).toBeNull();
    const scene = parseScene({ ligand: { atoms: [[0, 0, 0, "C"], ["x"]], bonds: [[0, 9, 1]] }, dots: [[1, 1, 1, 0]], edges: [[0, 5]] });
    expect(scene?.ligand.atoms).toHaveLength(1);
    expect(scene?.ligand.bonds).toHaveLength(0);
    expect(scene?.edges).toHaveLength(0);
  });
});

describe("startup document", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    document.documentElement.setAttribute("data-theme", "dark");
  });

  it("draws nothing of its own before the startup screen mounts", () => {
    const page = new DOMParser().parseFromString(indexHtml, "text/html");

    expect(page.getElementById("root")?.childNodes).toHaveLength(0);
    expect(page.querySelectorAll("img")).toHaveLength(0);
    expect(indexHtml).not.toMatch(/splash-(bg|logo)|pre-splash/);
  });

  it("opens on the stored theme before the first paint", () => {
    localStorage.setItem("ankora-theme", "light");
    new Function(themeBoot)();

    expect(document.documentElement).toHaveAttribute("data-theme", "light");
  });

  it("keeps the default theme for a malformed value or refused storage", () => {
    localStorage.setItem("ankora-theme", "x\" onload=\"");
    new Function(themeBoot)();
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");

    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("denied"); });
    expect(() => new Function(themeBoot)()).not.toThrow();
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  });
});

describe("SplashScreen", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.useRealTimers();
  });

  it("shows the record as awaiting, with no version it has not been told", () => {
    render(<SplashScreen {...props({ connection: "checking", health: null, system: null, tools: null, recovery: null, projects: null })} />);

    const record = screen.getByRole("region", { name: "Startup record" });
    expect(within(record).getAllByText("awaiting")).toHaveLength(5);
    expect(screen.queryByText(/nominal/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/0\.1\.0/)).not.toBeInTheDocument();
    expect(screen.getByText("Obsidian Instrument")).toBeInTheDocument();
  });

  it("opens the workbench once every row is confirmed", () => {
    const onDismiss = vi.fn();
    render(<SplashScreen {...props({ onDismiss })} />);

    expect(screen.getByText("ankora-backend 0.1.0 · 127.0.0.1:8765")).toBeInTheDocument();
    expect(screen.getByText("Ready · opening workbench")).toBeInTheDocument();
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("does not open while the project catalog is still unanswered", () => {
    const onDismiss = vi.fn();
    render(<SplashScreen {...props({ projects: null, onDismiss })} />);

    expect(screen.getByText("4 of 5 recorded")).toBeInTheDocument();
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it("names its notices", () => {
    render(<SplashScreen {...props({ tools: { ...allTools, pdbfixer: tool(false) }, recovery: null, recoveryError: "timeout", onDismiss: vi.fn() })} />);

    expect(screen.getByText("2 notices")).toBeInTheDocument();
    expect(screen.getByText("PDBFixer not found")).toBeInTheDocument();
  });

  it("stops on failure, focuses Retry, and never claims to be ready", () => {
    const onRetry = vi.fn();
    const onDismiss = vi.fn();
    render(<SplashScreen {...props({ connection: "disconnected", health: null, error: "Connection refused", onRetry, onDismiss })} />);

    expect(screen.getByRole("alert")).toHaveTextContent("The backend did not start");
    expect(screen.getByText("Connection refused")).toBeInTheDocument();
    expect(screen.getAllByText("not checked")).toHaveLength(4);
    expect(screen.getByText("Stopped — nothing was opened")).toBeInTheDocument();
    const retry = screen.getByRole("button", { name: "Retry connection" });
    expect(retry).toHaveFocus();
    fireEvent.click(retry);
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it("anchors, holds, then hands over to the workbench in a real build", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.useFakeTimers();
    // jsdom has no 2D canvas; the scene declines to draw, the record still runs.
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    const onDismiss = vi.fn();
    render(<SplashScreen {...props({ onDismiss })} />);

    act(() => { vi.advanceTimersByTime(900 + 1500); });
    expect(onDismiss).not.toHaveBeenCalled();
    act(() => { vi.advanceTimersByTime(1000); });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("clears its pending hand-over if unmounted first", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.useFakeTimers();
    // jsdom has no 2D canvas; the scene declines to draw, the record still runs.
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    const onDismiss = vi.fn();
    const { unmount } = render(<SplashScreen {...props({ onDismiss })} />);

    act(() => { vi.advanceTimersByTime(900 + 1500); });
    unmount();
    act(() => { vi.advanceTimersByTime(2000); });
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it("lets the scientist skip the hold once everything is recorded", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.useFakeTimers();
    // jsdom has no 2D canvas; the scene declines to draw, the record still runs.
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    const onDismiss = vi.fn();
    render(<SplashScreen {...props({ onDismiss })} />);

    fireEvent.keyDown(window, { key: "Enter" });
    act(() => { vi.advanceTimersByTime(1000); });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
