import { ankoraApi, ApiError } from "../api/client";

export const BACKEND_STARTUP_TIMEOUT_MS = 120_000;
const HEALTH_ATTEMPT_TIMEOUT_MS = 3_000;
const RETRY_INTERVAL_MS = 750;

function pause(signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    signal.throwIfAborted();
    const abort = () => {
      clearTimeout(timer);
      reject(signal.reason);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, RETRY_INTERVAL_MS);
    signal.addEventListener("abort", abort, { once: true });
  });
}

/** Only read-only health probes retry; scientific operations never do. */
export async function loadBackend(signal: AbortSignal) {
  signal.throwIfAborted();
  const startup = new AbortController();
  const cancel = () => startup.abort(signal.reason);
  signal.addEventListener("abort", cancel, { once: true });
  const deadline = setTimeout(() => startup.abort(new Error(
    "The local backend did not finish starting within 120 seconds. Retry or inspect the startup logs.",
  )), BACKEND_STARTUP_TIMEOUT_MS);
  try {
    let health;
    while (!health) {
      startup.signal.throwIfAborted();
      const attempt = new AbortController();
      const abortAttempt = () => attempt.abort(startup.signal.reason);
      startup.signal.addEventListener("abort", abortAttempt, { once: true });
      const timeout = setTimeout(() => attempt.abort(), HEALTH_ATTEMPT_TIMEOUT_MS);
      try {
        health = await ankoraApi.health(attempt.signal);
        if (health.status !== "ok") throw new Error("The local backend returned an invalid health response.");
      } catch (error) {
        startup.signal.throwIfAborted();
        const transient = error instanceof TypeError || attempt.signal.aborted
          || (error instanceof ApiError && [502, 503, 504].includes(error.status));
        if (!transient) throw error;
      } finally {
        clearTimeout(timeout);
        startup.signal.removeEventListener("abort", abortAttempt);
      }
      if (!health) await pause(startup.signal);
    }
    const [system, tools] = await Promise.all([
      ankoraApi.system(startup.signal), ankoraApi.tools(startup.signal),
    ]);
    startup.signal.throwIfAborted();
    return { health, system, tools };
  } catch (error) {
    if (startup.signal.aborted) throw startup.signal.reason;
    throw error;
  } finally {
    clearTimeout(deadline);
    signal.removeEventListener("abort", cancel);
    startup.abort();
  }
}
