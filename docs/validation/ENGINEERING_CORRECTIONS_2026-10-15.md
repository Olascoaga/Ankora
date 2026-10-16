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
