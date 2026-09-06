# Project Workspace validation — 2026-09-06

## Scope

This record closes adversarial-audit remediation item 16: explicit project
identity plus the ADR-011 dependency/stale graph. It validates ownership and
lineage behavior; it does not recompute or reinterpret a docking result.

## Verified contracts

Automated backend coverage verifies that:

- an existing `projects/default` tree is registered as a legitimate migrated
  project without changing an evidence file's bytes or modification time;
- project catalog metadata is written outside project evidence;
- creating and switching projects isolates structure lookup in both directions;
- an unregistered project is rejected before a directory or project-bound
  service can be created;
- switching is rejected while scientific work is active;
- a synthetic structure → receptor → binding site → docking → pose analysis →
  export chain is recovered from immutable records;
- marking the receptor stale requires a reason and propagates to every recorded
  descendant, but not to its source structure; and
- every synthetic evidence file retains its original SHA-256 after stale-state
  propagation.

Frontend coverage verifies explicit project switching and creation, the
required stale-state reason, visible retained stale evidence, and bounded graph
continuation. The active project is available from both the File menu and the
top-bar project context. A completed switch clears the previous project's
visible structure, receptor, ligand, binding-site, activity, and recovery state
before loading history from the new project.

## Authoritative gate

- Backend: 493 collected tests pass; Ruff passes; strict mypy passes over 116
  source files.
- Frontend: 220 tests pass across 30 files; strict TypeScript and the production
  Vite build pass.
- Native shell: rustfmt, strict Clippy, Rust unit tests, and Rust doc tests pass.
- Publication hygiene: the tracked-file absolute-path check passes.

The frontend suite retains two pre-existing non-failing test diagnostics: a
React `NaN` warning in `LibraryShelf.test.tsx` and asynchronous `act(...)`
warnings in `AutoDock4LibraryWorkspace.test.tsx`. They are not introduced by
Project Workspace and remain visible for later test-harness cleanup.

## Acceptance boundary

The catalog and explicit stale markers are mutable workspace metadata; molecular
artifacts and scientific records remain immutable. Graph references are derived
only from identifiers already present in those records. An unresolved reference
is diagnostic and never silently makes a result stale. Alternative or newer
branches remain valid evidence until the scientist explicitly marks an upstream
record stale. Project switching is supported by one local desktop backend;
simultaneous multi-process catalog writers are not claimed.
