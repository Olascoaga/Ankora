import { useEffect, useState } from "react";

import { ankoraApi } from "../api/client";
import type { ResourceUsage } from "../types/api";

/**
 * What the machine is doing, sampled while someone is looking.
 *
 * A docking campaign is the most expensive thing Ankora asks of a computer,
 * and the status bar is where a scientist already glances to see whether it is
 * still working. Polling it costs a request every few seconds, so this stops
 * on two conditions that both mean nobody is reading it: the backend is not
 * connected, and the window is not visible. A hidden window renders nothing —
 * measured at zero animation frames — so a poll behind it is pure waste.
 */

const INTERVAL_MS = 3000;

export function useResourceUsage(connected: boolean): ResourceUsage | null {
  const [usage, setUsage] = useState<ResourceUsage | null>(null);

  useEffect(() => {
    if (!connected) {
      setUsage(null);
      return undefined;
    }
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const sample = async () => {
      if (disposed) return;
      // Every entry point - the first call, the timer, coming back to the
      // window - cancels the pending tick first, so they collapse into one
      // chain. Without this each visibility change forked a second
      // self-scheduling loop: measured at six polls in 9.5 s instead of three.
      if (timer) clearTimeout(timer);
      if (!document.hidden) {
        try {
          const next = await ankoraApi.resourceUsage();
          if (!disposed) setUsage(next);
        } catch {
          // A reading that fails is not worth an error banner: the connection
          // pill above already says whether the backend is reachable.
          if (!disposed) setUsage(null);
        }
      }
      if (!disposed) timer = setTimeout(() => void sample(), INTERVAL_MS);
    };

    void sample();
    // Coming back to the window should not wait out a whole interval.
    const onVisible = () => { if (!document.hidden) void sample(); };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [connected]);

  return usage;
}

/** `16 / 32 GB`, the way a machine's memory is normally spoken about. */
export function formatBytes(bytes: number): string {
  const gigabytes = bytes / 1024 ** 3;
  if (gigabytes >= 10) return `${Math.round(gigabytes)} GB`;
  if (gigabytes >= 1) return `${gigabytes.toFixed(1)} GB`;
  return `${Math.round(bytes / 1024 ** 2)} MB`;
}

/** The one-line readout, and the detail behind it. */
export function describeUsage(usage: ResourceUsage | null): {
  label: string;
  detail: string;
} {
  // The status bar is peripheral; a reading Ankora cannot read is worth a
  // "Not measured", never taking the workbench down mid-campaign. This polls
  // every few seconds, so one malformed payload would crash it repeatedly.
  if (!usage || typeof usage.cpu_percent !== "number"
    || typeof usage.memory_used_bytes !== "number") {
    return { label: "Not measured", detail: "No reading from the backend." };
  }
  const gpu = usage.gpu
    ? `GPU ${Math.round(usage.gpu.utilization_percent)}%`
    : "GPU n/a";
  const label =
    `CPU ${Math.round(usage.cpu_percent)}%`
    + ` · ${gpu}`
    + ` · RAM ${formatBytes(usage.memory_used_bytes)}`;
  const scheduler = usage.scheduler;
  const detail = [
    `CPU ${usage.cpu_percent.toFixed(1)}% across ${usage.logical_cores} logical cores`,
    `Memory ${formatBytes(usage.memory_used_bytes)} of `
      + `${formatBytes(usage.memory_total_bytes)} (${Math.round(usage.memory_percent)}%)`,
    usage.gpu
      ? `${usage.gpu.name}: ${usage.gpu.utilization_percent.toFixed(0)}%, `
        + `${formatBytes(usage.gpu.memory_used_bytes)} of `
        + `${formatBytes(usage.gpu.memory_total_bytes)}`
      : usage.gpu_unavailable_reason ?? "No GPU reading.",
    scheduler
      ? `Ankora scheduler: ${scheduler.active_allocations.length} active, `
        + `${scheduler.queued_requests} queued; `
        + `${scheduler.cpu_threads_allocated}/${scheduler.cpu_threads_capacity} CPU threads `
        + `and ${scheduler.gpu_slots_allocated}/${scheduler.gpu_slots_capacity} GPU slots reserved.`
      : "Ankora scheduler not reported.",
  ].join("\n");
  return { label, detail };
}
