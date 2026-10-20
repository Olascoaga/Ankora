# Redocking workflow correction — 2026-10-20

## Diagnosis

The desktop validation workspace could list existing records but never called
the implemented creation endpoint. Navigation/rendering also required current
session structure/receptor/site state, making saved validations inaccessible
after restart. A failed history request left an indefinite loading indicator.
This was a workflow gap, not evidence that installer compression removed the
RMSD implementation.

## Backend acceptance

- Completed individual Vina, AutoDock4 CPU and AutoDock-GPU outputs are supported;
  validation does not invoke any docking executable.
- A paginated project-scoped reference endpoint selects preserved original 3D
  crystal extractions in the receptor's source coordinate frame. Byte-identical
  original reimports are accepted, unrelated sources and prepared/local
  references are rejected.
- Size/SHA-256 verification precedes measurement for the reference and each
  preserved pose. Molecular mapping requires equal heavy-atom counts. No
  validation is written on input admission/integrity failure.
- Existing symmetry-aware in-place RMSD and separate sampling/ranking verdicts
  are retained. The record stores RDKit version and the input pose hashes.
- Historical/frozen evidence is unchanged; this is not a new docking benchmark.

Tests: `test_redocking_validation.py` plus `test_redocking_workflow.py`, **30
passing** on Windows/Python 3.12.13. Real retained 7AQF/RV2 SDF/PDBQT fixtures
exercise RDKit; service-routing metadata is explicitly synthetic. The same
top-ranked pose remains over 10 Å away in place, while the recovering fixture
remains between 1.0 and 1.6 Å. API tests create/list/reopen independent temporary
records, validate thresholds, and check route dispatch before identifier lookup.
No frozen execution or protocol is rerun or retuned.

## Desktop acceptance

The implementation provides result/reference selection, explicit threshold and
acknowledgement, one guarded POST, immediate saved-record display, paginated
options and independent recoverable errors. Validation is reachable from an
empty session. Existing result/history data is not recomputed in the frontend.

`scripts/smoke_redocking_frontend.mjs` tests the production bundle under the
shipping restrictive CSP with **synthetic API replies**, never as scientific
evidence: three source kinds, three explicit POSTs, history reopening without
inputs and without another POST. Edge 155 passes at **960×680, 1280×800 and
1366×768** with vertical scroll, reachable controls/table, no workspace horizontal
clipping, no JavaScript errors and no CSP violations. Screenshots are local
private test artifacts, not fabricated experimental results.

This source correction does not rebuild, replace or validate a new installer.
The existing distributed beta must be rebuilt separately after scientist testing.

## Regression gates and limits

- Full backend suite: **881 passed** in 299.14 s at its collection snapshot;
  four additional negative admission cases were subsequently added and the
  final focused suite of **30 tests passed**. No frozen campaign was rerun.
- Full frontend suite: **317 passed / 41 files**; TypeScript and production
  build passed. Strict mypy passed over **141 source files**.
- Ruff passed for all files in this correction. Whole-workspace Ruff also
  reports three pre-existing findings in the uncommitted slim-installer test;
  those unrelated changes were preserved, not silently edited or committed.
- Existing Starlette/httpx deprecation and Vite bundle-size advisories remain;
  neither is a new redocking failure. No native-shell code changed.
