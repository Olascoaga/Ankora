import { describeUsage, formatBytes } from "../app/useResourceUsage";
import type { ResourceUsage } from "../types/api";

function usage(overrides: Partial<ResourceUsage> = {}): ResourceUsage {
  return {
    cpu_percent: 5.5,
    logical_cores: 16,
    memory_used_bytes: 17_030_922_240,
    memory_total_bytes: 34_053_414_912,
    memory_percent: 50,
    gpu: {
      name: "NVIDIA GeForce RTX 5050 Laptop GPU",
      utilization_percent: 12,
      memory_used_bytes: 575_668_224,
      memory_total_bytes: 8_546_942_976,
    },
    gpu_unavailable_reason: null,
    ...overrides,
  };
}

it("reads the three numbers a running campaign changes", () => {
  const { label } = describeUsage(usage());

  expect(label).toBe("CPU 6% · GPU 12% · RAM 16 GB");
});

it("says a GPU is unavailable rather than showing it idle", () => {
  // 0% and "no GPU" look identical on a status bar and mean opposite things.
  const { label, detail } = describeUsage(usage({
    gpu: null,
    gpu_unavailable_reason: "No NVIDIA driver tools are installed on this machine.",
  }));

  expect(label).toContain("GPU n/a");
  expect(label).not.toContain("GPU 0%");
  expect(detail).toContain("No NVIDIA driver tools are installed");
});

it("carries the detail a one-line readout cannot hold", () => {
  const { detail } = describeUsage(usage());

  expect(detail).toContain("16 logical cores");
  expect(detail).toContain("of 32 GB");
  expect(detail).toContain("NVIDIA GeForce RTX 5050 Laptop GPU");
});

it("says nothing was measured rather than showing zeros", () => {
  const { label } = describeUsage(null);

  expect(label).toBe("Not measured");
  expect(label).not.toContain("0%");
});

it("scales memory the way a machine's is spoken about", () => {
  expect(formatBytes(34_053_414_912)).toBe("32 GB");
  expect(formatBytes(8_546_942_976)).toBe("8.0 GB");
  expect(formatBytes(575_668_224)).toBe("549 MB");
});

it("survives a reading it cannot read", () => {
  // The status bar polls every few seconds. A payload that does not match the
  // schema used to throw inside render and take the whole workbench down.
  const malformed = { status: "ok" } as unknown as ResourceUsage;

  const { label } = describeUsage(malformed);

  expect(label).toBe("Not measured");
});
