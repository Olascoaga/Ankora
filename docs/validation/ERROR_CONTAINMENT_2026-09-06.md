# Error-containment validation — 2026-09-06

## Scope

This record closes adversarial-audit remediation item 18. It validates React
render and lifecycle containment; it does not claim to catch asynchronous API,
event-handler, backend-process, or scientific-tool failures, which retain their
existing task-specific error paths.

## Contract

- The application root is protected by a last-resort error boundary, so a
  render failure produces a usable recovery screen instead of an empty WebView.
- The active scientific workspace is protected separately. A failure in a
  viewer or workflow screen leaves the top bar, workflow navigation, status bar,
  and activity center mounted.
- Workspace containment resets when project or workflow-step identity changes.
- `Try again` redraws React children only. It never invokes a scientific
  executable, resubmits an API request, or changes a recorded artifact.
- `Return to Structure` leaves a failed workspace without applying a scientific
  decision.
- Both recovery levels retain structured technical evidence: failure kind,
  project/workspace scope, error name and message, JavaScript stack, and React
  component stack. The exact JSON can be copied; a failed clipboard operation
  is reported without hiding the selectable evidence.
- Development stacks may contain local filesystem paths, so the panel states
  that caveat before a scientist shares the report.

## Automated evidence

The frontend boundary tests use explicitly synthetic render exceptions and
verify:

1. workspace failure containment while shell siblings remain usable;
2. exact evidence serialization and clipboard output;
3. display-only retry after the triggering condition is removed;
4. reset on workspace navigation; and
5. explicit exit from a failed workspace without retrying that screen; and
6. the application-level fallback and reload action.

Verified locally on the Windows-authoritative development machine:

- 494 backend tests;
- Ruff and strict mypy across 116 backend source files;
- 226 frontend tests across 31 files;
- strict TypeScript compilation;
- production Vite build;
- Rust formatting, strict Clippy, unit and documentation tests;
- optimized native Windows application build; and
- public-path sanitation.

The repository gate's fixed `backend/.pytest_tmp` path was still locked by
Windows from an earlier process, so its initial aggregate invocation reported
setup errors. Re-running the identical backend suite against a new isolated
temporary directory passed all 494 tests; the remaining gates were then run
unchanged. This is recorded as infrastructure evidence, not hidden as a product
failure.
