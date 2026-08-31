import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SplashScreen } from "../components/SplashScreen";

const sampleHealth = { status: "ok", backend_version: "0.1.0" } as const;
const sampleSystem = {
  platform: "windows",
  architecture: "x86_64",
  python_version: "3.12.1",
  python_environment: "ankora-dev",
  app_mode: "development",
};
const sampleTools = {
  vina: { available: true, path: "tools/vina.exe", version: "1.2.5" },
  gnina: { available: true, path: "tools/gnina.exe", version: "1.1" },
  autogrid4: { available: true, path: "tools/autogrid4.exe", version: "4.2.6" },
  autodock4: { available: true, path: "tools/autodock4.exe", version: "4.2.6" },
  autodock_gpu: { available: true, path: "tools/AutoDock-GPU.exe", version: "1.6" },
  pdbfixer: { available: true, path: "tools/pdbfixer", version: "1.12.0" },
  pdb2pqr: { available: true, path: "tools/pdb2pqr", version: "3.7.1" },
  propka: { available: true, path: "tools/propka", version: "3.5.1" },
  meeko: { available: true, path: "tools/meeko", version: "0.7.1" },
  meeko_ligand: { available: true, path: "tools/meeko", version: "0.7.1" },
  p2rank: { available: true, path: "tools/p2rank/prank.bat", version: null },
};

describe("SplashScreen", () => {
  it("renders branding and checking telemetry", () => {
    render(
      <SplashScreen
        connection="checking"
        health={null}
        system={null}
        tools={null}
        error={null}
      />
    );

    expect(screen.getByText("ANKORA")).toBeInTheDocument();
    expect(screen.getByText("Advanced Molecular Docking Suite")).toBeInTheDocument();
    expect(screen.getByText("Precision Drug Discovery Platform")).toBeInTheDocument();
    expect(screen.getByText("[SYSTEM] Booting ANKORA Core... connecting to local backend")).toBeInTheDocument();
  });

  it("renders connected state with detected environment and tools", () => {
    const onDismiss = vi.fn();
    render(
      <SplashScreen
        connection="connected"
        health={sampleHealth}
        system={sampleSystem}
        tools={sampleTools}
        error={null}
        onDismiss={onDismiss}
      />
    );

    expect(screen.getByText(/\[STATUS\] All systems nominal\. Loading Workbench UI\.\.\. \[VER\] 0\.1\.0_x64/)).toBeInTheDocument();
  });

  it("renders disconnected error state and triggers onRetry", () => {
    const onRetry = vi.fn();
    render(
      <SplashScreen
        connection="disconnected"
        health={null}
        system={null}
        tools={null}
        error="Connection refused"
        onRetry={onRetry}
      />
    );

    expect(screen.getByText(/\[ERROR\] Connection failed: Connection refused/)).toBeInTheDocument();

    const retryButton = screen.getByRole("button", { name: /\[Retry Connection\]/ });
    expect(retryButton).toBeInTheDocument();
    fireEvent.click(retryButton);
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  describe("auto-dismiss timers", () => {
    afterEach(() => {
      vi.unstubAllEnvs();
      vi.useRealTimers();
    });

    it("clears the pending dismiss timer if unmounted between fade-out starting and completing", () => {
      vi.stubEnv("NODE_ENV", "production");
      vi.useFakeTimers();
      const onDismiss = vi.fn();
      const { unmount } = render(
        <SplashScreen
          connection="connected"
          health={sampleHealth}
          system={sampleSystem}
          tools={sampleTools}
          error={null}
          onDismiss={onDismiss}
        />
      );

      act(() => { vi.advanceTimersByTime(2500); });
      expect(onDismiss).not.toHaveBeenCalled();

      unmount();

      act(() => { vi.advanceTimersByTime(1000); });
      expect(onDismiss).not.toHaveBeenCalled();
    });
  });
});
