# Results-local Methods access — 2026-09-07

## Problem

The Methods generator already supported every stored Vina and AutoDock4
single/library record, but the interface exposed it only from Export after a
completed library campaign was chosen. A scientist reviewing an exact result —
especially a single-ligand job that has no campaign-bundle action — had to leave
the record context to find the prose. Copy success also permanently replaced
the action label, making a repeat copy look like a status rather than an action.

## Accepted behavior

- Opening any Results campaign exposes `Write the Methods section` in that
  record's right-hand evidence inspector.
- The existing service receives the selected campaign's exact `catalog_id`;
  Results does not create a template, infer another record, or recompute work.
- The shared accessible Methods dialog and its gap-first review remain the one
  rendering/copy boundary used by both Results and Export.
- `Copy to clipboard` remains an action before and after a successful copy.
  Success appears separately as a polite live status for 2.4 seconds. Repeated
  clicks write the complete Markdown again and restart the confirmation timer.
- Closing the dialog cancels the pending timer; no late confirmation updates an
  unmounted view. Clipboard denial still produces no false success claim.

## Verification

- A Results regression opens Vina campaign Methods from the selected result and
  verifies the exact engine/record route.
- The shared Methods regression copies twice, confirms the Markdown bytes each
  time, and proves the transient status clears while the action label remains.
- The complete frontend gate passes 236 tests over 33 files, strict TypeScript,
  and the production Vite build. Backend behavior did not change; the preceding
  498-test/Ruff/strict-mypy gate remains authoritative. Rust formatting, strict
  Clippy, native tests/build, and the public-path check close this unit.
