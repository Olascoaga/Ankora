# GPU telemetry serialization validation — 2026-09-06

## Scope

This validation covers the short-lived NVIDIA telemetry cache used by the
shared resource display. It does not reserve GPU capacity, launch docking, or
change scientific results.

## Verified contracts

The cache now owns its state behind one lock. A cache lookup, an expired-reading
refresh through `nvidia-smi`, and publication of the complete result form one
serialized operation. Concurrent FastAPI worker threads therefore share one
driver probe instead of racing duplicate processes or unsafely replacing the
module-level tuple.

Automated regressions verify that:

- sequential reads within the two-second lifetime launch one probe;
- two concurrent readers launch exactly one probe and receive the same complete
  GPU reading;
- test invalidation follows the same lock as production reads; and
- missing, timed-out, malformed, and successful driver responses retain their
  prior explicit semantics.

## Acceptance boundary

The lock is intentionally held for the bounded driver probe, whose timeout
remains four seconds. Waiting resource-display requests reuse that answer once
it completes. The cache is process-local telemetry only; the global scientific
work scheduler remains the separate resource arbiter, and neither telemetry nor
its cache is scientific provenance.

## Verification

- 7 directed GPU/resource regressions passed;
- 494 backend tests passed, with Ruff and strict mypy clean over 116 source
  files;
- 220 frontend tests over 30 files, strict TypeScript, and the production Vite
  build passed;
- Rust formatting, strict Clippy, unit/doc tests, and the optimized native
  Windows build passed; and
- the tracked public-path sanitation check passed.
