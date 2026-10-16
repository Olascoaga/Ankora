# Engineering corrections — 2026-10-15

## Ligand derivative project ownership

Confirmed four hardcoded `default` paths in ligand state, conformer, filter-run
and PDBQT persistence. All now use the project root captured when the store is
constructed, preserving the existing layout for the legitimate `default`
project. Preparation-status locks are keyed by their project-specific path.

Five synthetic storage regressions exercise all four derivative families with
the same identifiers in three different projects, project graph visibility,
cross-project read rejection and context capture. The focused storage/project/
ligand gate passed 16 tests. These are ownership tests, not chemical results.
Historical misplaced artifacts were not moved, rewritten or assigned guessed
ownership; any recovery requires explicit evidence and a separate migration.

## Directed dependencies and execution freshness

Confirmed reverse edges from library output snapshots and embedded initial
states. These no longer turn outputs into parents. Actual record IDs take
precedence over aliases. Initial imported states resolve to their owning
ligand; separately persisted states retain their own identity.

Effective stale-state admission now covers Vina, AutoGrid4, AutoDock4 and GPU,
single ligands and campaigns. Requests include exact selected preparation,
state/conformer and filter identities; cached map sets are checked separately.
Workers recheck after queue/resource waits. This is not automatic cancellation
of calculations that were already running when the scientist invalidates an
input. Evidence is never rewritten and inspection remains available.

The targeted engine/project gate passed 73 tests, including 17 freshness tests
for sibling independence, original/state aliases, project isolation, stale
receptor/site/map/PDBQT rejection before work creation and all three campaign
backends rejecting a selected stale preparation. Engine fixtures are synthetic
execution boundaries replaying recorded logs, not new GPU scientific results.

## GPU campaign terminal state and isolated collection

Confirmed unconditional Completed status after failed/timed-out file-list runs
and uncontained parsing of each molecule log. A cancellation remains Canceled;
timeout, failed exit/stdout verdict or zero successful molecules now yields
Failed with execution evidence. Valid partial results remain accessible. A
confirmed successful engine invocation with at least one valid molecule may
complete with explicit per-molecule failures/counts, consistent with the other
campaign backends; it does not claim every selected molecule succeeded.

Invalid/truncated logs fail only their molecule. Each collected entry is saved
incrementally, counters are updated without rescanning all molecules, and raw
logs are never overwritten. Progress counts parsed complete logs, not merely
filenames; the watcher is stopped when the process ends, including exceptions.
The GPU gate passed 24 tests, including zero-output timeout/nonzero/tool-failure,
truncated logs before/after valid molecules, explicit cancellation and retained
partial output after engine failure. Results are replayed from the existing real
captured DLG fixture; no new scientific scores are manufactured or asserted.
