import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ankoraApi, ApiError } from "../api/client";
import { BACKEND_STARTUP_TIMEOUT_MS, loadBackend } from "../app/backendStartup";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

function mockReady() {
  const health = vi.spyOn(ankoraApi, "health").mockResolvedValue({ status: "ok", backend_version: "0.1.0" });
  const system = vi.spyOn(ankoraApi, "system").mockResolvedValue({} as never);
  const tools = vi.spyOn(ankoraApi, "tools").mockResolvedValue({} as never);
  return { health, system, tools };
}

it("automatically waits through a cold start before scanning tools", async () => {
  const { health, system, tools } = mockReady();
  health.mockRejectedValueOnce(new TypeError("Failed to fetch"))
    .mockRejectedValueOnce(new ApiError("Starting", 503));
  const result = loadBackend(new AbortController().signal);
  await vi.advanceTimersByTimeAsync(750);
  expect(tools).not.toHaveBeenCalled();
  expect(system).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(750);
  expect((await result).health.status).toBe("ok");
  expect(health).toHaveBeenCalledTimes(3);
  expect(tools).toHaveBeenCalledOnce();
  expect(vi.getTimerCount()).toBe(0);
});

it("bounds unavailable startup and permits a fresh manual retry", async () => {
  const { health } = mockReady();
  health.mockRejectedValue(new TypeError("Failed to fetch"));
  const failed = expect(loadBackend(new AbortController().signal)).rejects.toThrow("120 seconds");
  await vi.advanceTimersByTimeAsync(BACKEND_STARTUP_TIMEOUT_MS);
  await failed;
  expect(vi.getTimerCount()).toBe(0);
  health.mockResolvedValue({ status: "ok", backend_version: "0.1.0" });
  expect((await loadBackend(new AbortController().signal)).health.status).toBe("ok");
});

it("aborts a stalled health request and retries it", async () => {
  const { health } = mockReady();
  health.mockImplementationOnce((signal) => new Promise((_, reject) => {
    signal!.addEventListener("abort", () => reject(signal!.reason), { once: true });
  }));
  const result = loadBackend(new AbortController().signal);
  await vi.advanceTimersByTimeAsync(3750);
  await result;
  expect(health).toHaveBeenCalledTimes(2);
});

it("cancels pending attempts on unmount or replacement", async () => {
  const { health, tools } = mockReady();
  health.mockRejectedValue(new TypeError("Failed to fetch"));
  const controller = new AbortController();
  const cancelled = expect(loadBackend(controller.signal)).rejects.toThrow("cancelled");
  await vi.advanceTimersByTimeAsync(1);
  controller.abort(new Error("cancelled"));
  await cancelled;
  await vi.advanceTimersByTimeAsync(5000);
  expect(health).toHaveBeenCalledOnce();
  expect(tools).not.toHaveBeenCalled();
  expect(vi.getTimerCount()).toBe(0);
});

it("does not hide protocol errors behind retries", async () => {
  const { health } = mockReady();
  health.mockRejectedValue(new ApiError("Wrong service", 404));
  await expect(loadBackend(new AbortController().signal)).rejects.toThrow("Wrong service");
  expect(health).toHaveBeenCalledOnce();
  expect(vi.getTimerCount()).toBe(0);
});

it("bounds tool discovery too and does not retry a failed scan", async () => {
  const { health, tools } = mockReady();
  tools.mockImplementation((signal) => new Promise((_, reject) => {
    signal!.addEventListener("abort", () => reject(signal!.reason), { once: true });
  }));
  const failed = expect(loadBackend(new AbortController().signal)).rejects.toThrow("120 seconds");
  await vi.advanceTimersByTimeAsync(BACKEND_STARTUP_TIMEOUT_MS);
  await failed;
  expect(health).toHaveBeenCalledOnce();
  expect(tools).toHaveBeenCalledOnce();
  expect(vi.getTimerCount()).toBe(0);
});
