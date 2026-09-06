# ADR-021: Incremental state for large docking campaigns

- Status: Accepted
- Date: 2026-09-06

## Context

Vina, AutoDock4 CPU, and AutoDock-GPU screening campaigns originally stored
their mutable header and every ligand result in one `record.json`. Updating one
completed ligand therefore serialized and replaced the whole campaign. The
Results API also had to hydrate the complete entry list before returning a
small page. Both costs grow with the library even when only one row changes or
one page is requested.

The existing JSON and engine output files are scientific evidence. A storage
migration must not alter their bytes or hashes merely to improve access.

## Decision

Each library campaign owns a local `batch_state.sqlite3` sidecar. It stores the
small mutable campaign summary separately from independently addressable ligand
rows, including deterministic status, search, source-order, and best-result
indexes. Worker progress changes only the affected row and counters inside one
transaction. Results filtering, ranking, counting, and pagination execute in
SQLite and deserialize only the requested window.

`record.json` remains the portable human-readable campaign snapshot. Existing
campaigns are migrated lazily or through the explicit migration command by
adding a rebuildable sidecar; pre-existing files are hash-checked and never
rewritten. New active campaigns use the sidecar for progress and materialize
one complete atomic JSON snapshot when the campaign reaches a terminal state.

The sidecar has an explicit schema version and unknown versions fail closed.
It is an implementation index, not an independent source of scientific facts:
entry payloads still name the same artifacts, hashes, commands, and raw engine
evidence.

## Consequences

- One completed ligand produces one row update rather than a whole-library
  JSON rewrite.
- Polling can retrieve only entries newer than a known revision.
- A 10,000-entry result page is bounded by the requested limit rather than the
  complete serialized campaign.
- Terminal snapshots remain portable without requiring SQLite-aware export
  consumers.
- The sidecar adds a local schema and transaction boundary that must be tested
  across all supported engines and Windows filesystem behavior.
