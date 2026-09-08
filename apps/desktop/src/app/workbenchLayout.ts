import { useEffect, useState } from "react";

export type WorkbenchLayout = "wide" | "medium" | "small";

export interface WorkbenchViewport {
  width: number;
  height: number;
}

export const WORKBENCH_LAYOUT_BREAKPOINTS = {
  mediumWidth: 1180,
  mediumHeight: 700,
  wideWidth: 1800,
  wideHeight: 1100,
} as const;

/**
 * Classify the effective CSS viewport rather than physical display pixels.
 * WebView2 reports Windows display scaling through these dimensions, so the
 * same contract covers both a smaller monitor and a scaled high-DPI monitor.
 */
export function classifyWorkbenchLayout(viewport: WorkbenchViewport): WorkbenchLayout {
  const { width, height } = viewport;
  if (
    width >= WORKBENCH_LAYOUT_BREAKPOINTS.wideWidth
    && height >= WORKBENCH_LAYOUT_BREAKPOINTS.wideHeight
  ) return "wide";
  if (
    width >= WORKBENCH_LAYOUT_BREAKPOINTS.mediumWidth
    && height >= WORKBENCH_LAYOUT_BREAKPOINTS.mediumHeight
  ) return "medium";
  return "small";
}

function currentViewport(): WorkbenchViewport {
  const visualViewport = window.visualViewport;
  return {
    width: visualViewport?.width ?? window.innerWidth,
    height: visualViewport?.height ?? window.innerHeight,
  };
}

export function useWorkbenchLayout(): WorkbenchLayout {
  const [layout, setLayout] = useState<WorkbenchLayout>(() => (
    typeof window === "undefined"
      ? "medium"
      : classifyWorkbenchLayout(currentViewport())
  ));

  useEffect(() => {
    const update = () => setLayout(classifyWorkbenchLayout(currentViewport()));
    update();
    window.addEventListener("resize", update);
    window.visualViewport?.addEventListener("resize", update);
    return () => {
      window.removeEventListener("resize", update);
      window.visualViewport?.removeEventListener("resize", update);
    };
  }, []);

  return layout;
}
