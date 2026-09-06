# Durable work recovery validation - 2026-09-04

## Scope

This record validates software behavior when the Ankora backend or host exits
before long-running work reaches a terminal state. It covers Vina, AutoGrid,
AutoDock4 CPU, and AutoDock-GPU single jobs and library campaigns. It does not
claim recovery of engine computation from a checkpoint and produces no new
scientific scores.

## Contract verified

- Active workers write a durable owner lease and heartbeat; normal exit marks
  that lease released.
- Startup reconciles `queued`, `running`, and `cancel_requested` records to an
  explicit engine-specific interrupted failure.
- Reconciliation records the previous state and, when present, the former
  backend instance and last heartbeat.
- A completed library entry remains unchanged when another entry in the same
  campaign was interrupted.
- Only active entries become interrupted failures; campaign terminal counts
  are recomputed from the resulting entries.
- Active leases are marked reconciled, and the typed local API reports every
  item handled during that startup.
- Partial directories and raw engine output are retained and are not reused as
  successful work.
- The activity center opens when startup recovered interruptions and reports
  their prior state plus completed and interrupted molecule counts.
- Retry is disabled until the scientist acknowledges that it creates a new
  immutable attempt. The API enforces the same acknowledgement independently.
- All seven Vina/AutoGrid/AutoDock4 CPU/AutoDock-GPU job and campaign kinds
  revalidate the exact recorded request through their normal execution service
  and return a distinct job or campaign identifier.
- Only engine-specific startup-interruption codes are retryable through this
  interface. Ordinary tool or scientific failures remain failures and require
  their own diagnosis rather than being presented as resumable work.

## Evidence boundary

The automated recovery fixtures are explicitly synthetic lifecycle records.
They verify durable state transitions and retry dispatch, not docking chemistry
or engine checkpoint compatibility. The interface deliberately performs no
automatic retry, and “retry” never claims checkpoint resume: it is a new run of
the preserved request against inputs and tools revalidated at that moment.

## Automated verification

The repository-wide Windows gate passed after the implementation:

- public-path check: no tracked absolute filesystem paths;
- backend: 466 pytest tests, Ruff, and strict mypy across 108 source files;
- frontend: 213 Vitest tests across 29 files, strict TypeScript, and production
  Vite build;
- native shell: rustfmt, strict Clippy, Rust unit/doc tests, and an optimized
  Tauri application build.

The existing frontend suite still emits its recorded non-fatal React `act()`
and synthetic `NaN` fixture warnings, and Vite still reports the known Mol*
bundle-size and browser-externalized optional encoder modules. The Windows
linker also emits its existing informational import-library message. None
failed the gate or originated in this recovery increment.
