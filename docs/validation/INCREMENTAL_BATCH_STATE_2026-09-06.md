# Incremental batch-state validation — 2026-09-06

## Scope

This validation covers the rebuildable batch-state index used by Vina,
AutoDock4 CPU, and AutoDock-GPU virtual-screening campaigns.

## Synthetic 10,000-entry load contract

The explicitly synthetic test creates a 10,000-ligand Vina campaign, migrates
its legacy JSON record, and replaces the full-record loader with a deliberate
failure. The Results service still:

- returns a two-row best-score page in deterministic order;
- finds one named compound through indexed search;
- returns the final two rows through status filtering and a 9,998-row offset;
- reports the exact 10,000-row total;
- transfers less than 20 KB for the two-row response; and
- preserves the original `record.json` SHA-256.

The same generic persistence primitive is wired to all three campaign stores.
Focused service and recovery tests verify progress polling, cancellation,
startup reconciliation, pose lookup, and terminal materialization through the
new access paths.

## Existing-artifact migration

The explicit migration command is:

```powershell
python scripts/migrate_batch_state.py --data-root .ankora-data
```

It snapshots size and SHA-256 for every pre-existing file under the active
data root, adds only `batch_state.sqlite3` sidecars, and refuses to report
success if any prior file is missing or byte-different. Machine-specific paths
and campaign identifiers are intentionally excluded from this tracked record.

The Windows migration run completed successfully with:

- 4 Vina campaigns indexed;
- 4 AutoDock4 CPU campaigns indexed;
- 3 AutoDock-GPU campaigns indexed;
- 35,537 pre-existing files preserved; and
- 14,717,497,753 pre-existing bytes verified by SHA-256 before and after.

## Acceptance boundary

This validates incremental local persistence and server-side pagination. The
sidecar does not change scoring, ranking semantics, molecular preparation,
engine invocation, or any scientific artifact. Global scheduling across
simultaneous work is now governed separately by ADR-022 and the validation in
`GLOBAL_RESOURCE_ARBITER_2026-09-06.md`.
