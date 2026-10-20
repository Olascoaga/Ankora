import { isTauri } from "@tauri-apps/api/core";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { API_BASE_URL } from "../api/client";
import sceneSource from "../assets/splash-scene.json?raw";
import type {
  HealthResponse,
  ProjectCatalog,
  SystemResponse,
  ToolsResponse,
  WorkRecoverySummary,
} from "../types/api";
import { createAnchoringScene, parseScene, type AnchoringScene, type SceneData } from "./splash/anchoringScene";
import {
  deriveStartupRecord,
  originOf,
  startupPhase,
  themeName,
  type ChannelKey,
  type StartupChannel,
} from "./splash/startupRecord";
import "./splash/splash.css";

/**
 * Ankora's startup screen — "Anchoring".
 *
 * The screen is the workbench's first record. Its five rows are bound to the
 * responses that prove them; each is stamped with the time it actually arrived
 * and says exactly what that response reported. The scene behind them is the
 * recorded SERPINE1 pocket with RV2 searching for its deposited pose: the search
 * narrows as the record fills, anchors only when every row is confirmed, and
 * never anchors when the backend does not answer. See docs/design/STARTUP_SCREEN.md.
 */

export interface SplashScreenProps {
  connection: "checking" | "connected" | "disconnected";
  health: HealthResponse | null;
  system: SystemResponse | null;
  tools: ToolsResponse | null;
  error: string | null;
  /** `null` until /work/recovery has answered. */
  recovery: WorkRecoverySummary | null;
  recoveryError: string | null;
  /** `null` until /projects has answered — never a default stand-in. */
  projects: ProjectCatalog | null;
  projectsError: string | null;
  /** The active `data-theme`, so the bezel can name the instrument. */
  theme?: string;
  onRetry?: () => void;
  onDismiss?: () => void;
}

/** Long enough for the pocket to resolve before anything anchors in it. */
const MIN_BEFORE_ANCHOR_MS = 900;
/** Anchoring plus the contacts appearing, read once, then the workbench. */
const HOLD_AFTER_READY_MS = 1500;
const HOLD_REDUCED_MS = 400;
const EXIT_MS = 620;
// Read after the value, so a screen reader hears each state once.
const STATUS_WORDS: Record<StartupChannel["status"], string> = {
  pending: "(pending)", ok: "(confirmed)", notice: "(confirmed with a notice)", fail: "(failed)", skipped: "(skipped)",
};

const SCENE: SceneData | null = (() => {
  try {
    return parseScene(JSON.parse(sceneSource));
  } catch {
    return null;
  }
})();
const SCENE_CAPTION = "SERPINE1 · PDB 7AQF · RV2 A:401, deposited pose · search motion is illustrative";

const isTestEnvironment = () => typeof process !== "undefined" && process.env?.NODE_ENV === "test";
const prefersReducedMotion = () =>
  typeof window !== "undefined" && typeof window.matchMedia === "function"
  && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function SplashScreen({
  connection,
  health,
  system,
  tools,
  error,
  recovery,
  recoveryError,
  projects,
  projectsError,
  theme,
  onRetry,
  onDismiss,
}: SplashScreenProps) {
  const origin = originOf(API_BASE_URL);
  const channels = useMemo(
    () => deriveStartupRecord({ connection, origin, health, system, tools, recovery, recoveryError, projects, projectsError }),
    [connection, origin, health, system, tools, recovery, recoveryError, projects, projectsError],
  );
  const phase = startupPhase(channels);
  const recorded = channels.filter((item) => item.status === "ok" || item.status === "notice").length;
  const notices = channels.filter((item) => item.status === "notice").length;

  const rootRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const columnRef = useRef<HTMLDivElement>(null);
  const markRef = useRef<HTMLDivElement>(null);
  const retryRef = useRef<HTMLButtonElement>(null);
  const sceneRef = useRef<AnchoringScene | null>(null);
  const timers = useRef<number[]>([]);
  const flightRef = useRef<HTMLElement | null>(null);
  const leavingRef = useRef(false);

  const [t0, setT0] = useState(() => performance.now());
  const [stamps, setStamps] = useState<Partial<Record<ChannelKey, number>>>({});
  const [elapsed, setElapsed] = useState(0);
  const [leaving, setLeaving] = useState(false);
  const [reduced, setReduced] = useState(prefersReducedMotion);
  const [copied, setCopied] = useState<"idle" | "done" | "failed">("idle");

  // Stamp each row the first time its response arrives.
  useEffect(() => {
    const now = (performance.now() - t0) / 1000;
    setStamps((current) => {
      let changed = false;
      const next = { ...current };
      for (const item of channels) {
        if (item.status !== "pending" && item.status !== "skipped" && next[item.key] === undefined) {
          next[item.key] = now; changed = true;
        }
      }
      return changed ? next : current;
    });
  }, [channels, t0]);

  // A retry starts a new record rather than continuing the failed one.
  const previousConnection = useRef(connection);
  useEffect(() => {
    if (previousConnection.current === "disconnected" && connection !== "disconnected") {
      setT0(performance.now()); setStamps({}); setCopied("idle");
      sceneRef.current?.restart();
    }
    previousConnection.current = connection;
  }, [connection]);

  // A slow start says how long it has actually been waiting.
  useEffect(() => {
    if (phase !== "starting") return undefined;
    const id = window.setInterval(() => setElapsed((performance.now() - t0) / 1000), 100);
    return () => window.clearInterval(id);
  }, [phase, t0]);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return undefined;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);

  // ---- the scene ---------------------------------------------------------
  const layout = useCallback(() => {
    const column = columnRef.current, root = rootRef.current;
    if (!column || !root) return;
    const left = column.offsetLeft;
    root.style.setProperty("--scene-x", `${Math.round(left * 0.53)}px`);
    sceneRef.current?.layout(left);
  }, []);

  useEffect(() => {
    if (!SCENE || !canvasRef.current || isTestEnvironment()) return undefined;
    const scene = createAnchoringScene(canvasRef.current, SCENE, { reducedMotion: prefersReducedMotion() });
    sceneRef.current = scene;
    layout();
    window.addEventListener("resize", layout);
    return () => {
      window.removeEventListener("resize", layout);
      scene?.destroy();
      sceneRef.current = null;
    };
  }, [layout]);

  useEffect(() => { sceneRef.current?.setReducedMotion(reduced); }, [reduced]);
  useEffect(() => { sceneRef.current?.setProgress(recorded / channels.length); }, [recorded, channels.length]);
  useEffect(() => {
    if (phase === "failed") {
      sceneRef.current?.stall();
      retryRef.current?.focus();
    }
  }, [phase]);

  // ---- leaving -----------------------------------------------------------
  const later = (fn: () => void, ms: number) => { timers.current.push(window.setTimeout(fn, ms)); };

  const leave = useCallback(() => {
    if (leavingRef.current) return;
    leavingRef.current = true;
    setLeaving(true);
    // The mark flies to its place in the top bar: one identity, not two.
    const mark = markRef.current;
    const target = document.querySelector<HTMLElement>(".topbar .brand-mark") ?? document.querySelector<HTMLElement>(".brand-mark");
    if (mark && target && !reduced) {
      const from = mark.getBoundingClientRect(), to = target.getBoundingClientRect();
      const flight = mark.cloneNode(true) as HTMLElement;
      flight.className = "ak-flight";
      flight.removeAttribute("id");
      flight.querySelectorAll("path").forEach((path) => { path.style.animation = "none"; path.style.strokeDashoffset = "0"; });
      Object.assign(flight.style, { left: `${from.left}px`, top: `${from.top}px`, width: `${from.width}px`, height: `${from.height}px` });
      document.body.appendChild(flight);
      flightRef.current = flight;
      requestAnimationFrame(() => requestAnimationFrame(() => {
        Object.assign(flight.style, {
          left: `${to.left}px`, top: `${to.top}px`, width: `${to.width}px`, height: `${to.height}px`,
          borderRadius: getComputedStyle(target).borderRadius || "8px", opacity: "0",
        });
      }));
    }
    later(() => {
      flightRef.current?.remove(); flightRef.current = null;
      onDismiss?.();
    }, reduced ? 250 : EXIT_MS + 280);
  }, [onDismiss, reduced]);

  useEffect(() => {
    if (phase !== "ready") return undefined;
    if (isTestEnvironment()) {
      onDismiss?.();
      return undefined;
    }
    const wait = Math.max(0, MIN_BEFORE_ANCHOR_MS - (performance.now() - t0));
    later(() => {
      sceneRef.current?.anchor();
      later(leave, reduced ? HOLD_REDUCED_MS : HOLD_AFTER_READY_MS);
    }, wait);
    // Once everything is recorded the scientist may skip the rest.
    const skip = (event: Event) => {
      if (event instanceof KeyboardEvent && !["Enter", "Escape", " "].includes(event.key)) return;
      leave();
    };
    window.addEventListener("keydown", skip);
    window.addEventListener("pointerdown", skip);
    return () => {
      window.removeEventListener("keydown", skip);
      window.removeEventListener("pointerdown", skip);
    };
    // Only the record decides readiness; `later` and `leave` are stable enough
    // for a sequence that runs once per ready transition.
  }, [phase]);

  useEffect(() => () => {
    timers.current.forEach((id) => window.clearTimeout(id));
    timers.current = [];
    flightRef.current?.remove();
  }, []);

  // ---- diagnostics --------------------------------------------------------
  const copyDiagnostics = async () => {
    const lines = [
      `Ankora startup record · ${new Date().toISOString()}`,
      `Backend address: ${origin}`,
      ...channels.map((item) => `${item.label.padEnd(9)} ${item.status.padEnd(8)} ${item.value}`),
      error ? `Error: ${error}` : "",
    ].filter(Boolean);
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopied("done");
    } catch {
      setCopied("failed");
    }
  };

  const showLogs = phase === "failed" && import.meta.env.PROD && isTauri();
  const stateText = phase === "failed"
    ? "Stopped — nothing was opened"
    : phase === "ready"
      ? "Ready · opening workbench"
      : recorded === 0 && elapsed > 1.5
        ? `Waiting for the backend · ${elapsed.toFixed(1)} s`
        : recorded === 0 ? "Starting" : `${recorded} of ${channels.length} recorded`;
  const versionText = [health ? `Ankora ${health.backend_version}` : "Ankora",
    system ? `${system.platform} ${system.architecture}` : null].filter(Boolean).join(" · ");
  const activeKey = phase === "starting" ? channels.find((item) => item.status === "pending")?.key : undefined;

  return (
    <div
      ref={rootRef}
      className="ak-splash"
      data-testid="splash-screen"
      data-phase={phase}
      data-leaving={leaving}
      data-reduced-motion={reduced}
      role="dialog"
      aria-modal="true"
      aria-label="Ankora startup"
      aria-busy={phase === "starting"}
      aria-describedby="ak-state"
    >
      <div className="ak-atmo" aria-hidden="true" />
      <div className="ak-lattice" aria-hidden="true" />
      <canvas ref={canvasRef} className="ak-scene" aria-hidden="true" />

      <div className="ak-chrome">
        <header className="ak-bezel top">
          <div className="group"><span className="ak-led" aria-hidden="true" /><b>{themeName(theme)}</b><span>/ Startup</span></div>
          <div className="group">{versionText}</div>
        </header>

        <div className="ak-column" ref={columnRef}>
          <div className="ak-over">Molecular docking workbench</div>
          <div className="ak-word">
            <div className="ak-mark" ref={markRef} aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                <path pathLength={1} d="m8 5 4-2 4 2v5l4 2v5l-4 2-4-2-4 2-4-2v-5l4-2V5Z" />
                <path pathLength={1} d="m8 10 4 2 4-2M12 12v5" />
              </svg>
            </div>
            <h1 className="ak-name">Ankora</h1>
          </div>
          <p className="ak-claim"><strong>Scientist-controlled docking.</strong> Every decision explicit, every result recorded — starting with this one.</p>

          <section className="ak-record" aria-label="Startup record">
            <div className="ak-head"><span>Startup record</span><small>t = 0 · window open</small></div>
            <ol className="ak-ledger">
              {channels.map((item) => (
                <li key={item.key} className="ak-row" data-status={item.status}>
                  <span className="t">{stamps[item.key] !== undefined ? `+${(stamps[item.key] as number).toFixed(2)} s` : "—"}</span>
                  <span className="k">{item.label}</span>
                  <span className="v" title={item.value}>
                    <span className="val" key={`${item.key}-${item.status}`}>
                      {item.notice && item.value.endsWith(item.notice)
                        ? <>{item.value.slice(0, item.value.length - item.notice.length)}<em>{item.notice}</em></>
                        : item.value}
                    </span>
                  </span>
                  <span className="s" aria-hidden="true" />
                  <span className="ak-visually-hidden">{STATUS_WORDS[item.status]}</span>
                </li>
              ))}
            </ol>
            <div className="ak-cal">
              <div className="ak-segs" aria-hidden="true">
                {channels.map((item) => (
                  <span key={item.key} className="ak-seg" data-status={item.status} data-active={item.key === activeKey} />
                ))}
              </div>
              <div className="ak-meta">
                <span id="ak-state" className={phase === "ready" ? "ready" : phase === "failed" ? "failed" : ""} aria-live="polite">{stateText}</span>
                {notices ? <span className="notes">{notices} notice{notices === 1 ? "" : "s"}</span> : null}
              </div>
            </div>

            {phase === "failed" ? (
              <div className="ak-fail" role="alert">
                <h2>The backend did not start</h2>
                <p>{error ?? `Nothing answered at ${origin}.`}</p>
                {showLogs ? <code>%LOCALAPPDATA%\science.ankora.workbench\logs\backend.stderr.log</code> : null}
                <div className="ak-actions">
                  {onRetry ? <button ref={retryRef} type="button" className="primary" onClick={onRetry}>Retry connection</button> : null}
                  <button type="button" onClick={() => void copyDiagnostics()}>
                    {copied === "done" ? "Copied" : copied === "failed" ? "Copy unavailable" : "Copy diagnostics"}
                  </button>
                </div>
              </div>
            ) : null}
          </section>
        </div>

        <footer className="ak-bezel bottom">
          <span className="rule"><span className="rule-label">Ankora rule — </span><q>Nothing is asserted that was not recorded.</q></span>
          {SCENE ? <span className="caption" title={SCENE_CAPTION}>{SCENE_CAPTION}</span> : null}
        </footer>
      </div>
    </div>
  );
}
