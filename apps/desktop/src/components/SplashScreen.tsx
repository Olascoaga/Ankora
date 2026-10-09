import { useEffect, useMemo, useState } from "react";

import splashMesh from "../assets/splash-bg-mesh-only.jpg";
import splashLogo from "../assets/splash-logo.jpg";
import type { HealthResponse, SystemResponse, ToolsResponse } from "../types/api";

export interface SplashScreenProps {
  connection: "checking" | "connected" | "disconnected";
  health: HealthResponse | null;
  system: SystemResponse | null;
  tools: ToolsResponse | null;
  error: string | null;
  onRetry?: () => void;
  onDismiss?: () => void;
}

export function SplashScreen({
  connection,
  health,
  system,
  tools,
  error,
  onRetry,
  onDismiss,
}: SplashScreenProps) {
  const [isLeaving, setIsLeaving] = useState(false);

  const isReady = connection === "connected" && Boolean(health) && Boolean(tools);

  useEffect(() => {
    if (!isReady) return;
    const isTest = typeof process !== "undefined" && process.env?.NODE_ENV === "test";
    if (isTest) {
      onDismiss?.();
      return;
    }

    let dismissTimer: number | undefined;
    const dwellTimer = window.setTimeout(() => {
      setIsLeaving(true);
      dismissTimer = window.setTimeout(() => {
        onDismiss?.();
      }, 600);
    }, 2500);

    return () => {
      window.clearTimeout(dwellTimer);
      window.clearTimeout(dismissTimer);
    };
  }, [isReady, onDismiss]);

  const progressPercent = isReady ? 100 : connection === "connected" ? 70 : 25;

  const telemetryText = useMemo(() => {
    if (connection === "disconnected") {
      return `[ERROR] Connection failed: ${error ?? "Could not reach local FastAPI server."}`;
    }
    if (!connection || connection === "checking") {
      return "[SYSTEM] Booting ANKORA Core... connecting to local backend";
    }
    if (!system) {
      return "[LOAD] Backend connected. Detecting Python runtime environment...";
    }
    if (!tools) {
      return "[LOAD] Python environment detected. Initializing Scientific Engine and scanning tools...";
    }
    if (isReady) {
      const ver = health?.backend_version ?? "1.0.0";
      return `[STATUS] All systems nominal. Loading Workbench UI... [VER] ${ver}_x64`;
    }
    return "[STATUS] System initialization in progress...";
  }, [connection, system, tools, isReady, health, error]);

  return (
    <div
      className={`splash-overlay${isLeaving ? " splash-leaving" : ""}`}
      data-testid="splash-screen"
      role="dialog"
      aria-label="Ankora initialization"
      aria-modal="true"
    >
      <div className="splash-backdrop" />
      <div className="splash-card">
        <div className="splash-graphic-mesh" aria-hidden="true">
          <img src={splashMesh} alt="" aria-hidden="true" />
        </div>

        <div className="splash-content">
          <div className="splash-logo" style={{ background: 'transparent' }}>
             <img src={splashLogo} alt="Logo" style={{ width: '100%', height: '100%', objectFit: 'contain', mixBlendMode: 'screen' }} />
          </div>

          <div className="splash-header">
            <h1 className="splash-title">ANKORA</h1>
            <h2 className="splash-subtitle">Advanced Molecular Docking Suite</h2>
            <p className="splash-tagline">Precision Drug Discovery Platform</p>
          </div>
        </div>

        <div className="splash-footer">
          <div className={`splash-telemetry-line ${connection === "disconnected" ? "error" : ""}`}>
            <span>{telemetryText}</span>
            {connection === "disconnected" && onRetry && (
              <button type="button" className="splash-retry-link" onClick={onRetry}>
                [Retry Connection]
              </button>
            )}
          </div>
          <div
            className="splash-progress-bar"
            role="progressbar"
            aria-label="Startup progress"
            aria-valuenow={progressPercent}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <span
              className={`splash-progress-fill${isReady ? " ready" : ""}`}
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
