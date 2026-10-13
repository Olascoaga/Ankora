# Receptor relaxation recovery — 13 October 2026

## Report and scope

The scientist reported a private-beta 7AQF preparation failure with
`RECEPTOR_RELAXATION_TOLERANCE_EXCEEDED`. The screenshot also showed enabled
relaxation with no remaining Repair decisions, a disabled checkbox, and blocked
Apply. Source correction is accepted for implementation; the delivered installer
is not rebuilt in this unit.

This unit fixes recovery and diagnostic presentation, not the molecular
relaxation method. It does not claim to resolve the reported structure's clash
or identify its particular residue without that attempt's technical evidence.

## Implemented boundary

- A checked relaxation option can always be turned off, including after a
  selected chain or its last missing-atom repair is removed from the draft.
  Alternate-conformation selection is not counted as PDBFixer atom repair.
  Manual-review/incomplete decisions still block Apply.
- Tolerance failures add every exceeded observed heavy atom's exact residue,
  atom name, displacement and coordinates before/after. Descending displacement
  and identity tie-breaking are deterministic; residue locators are deduplicated.
  Existing scalar fields and stable error code remain compatible.
- The UI lists up to twelve atoms and preserves the complete evidence below.
  Inspection selects the original residue in Mol*, not an inferred bad atom or
  a new calculation. Disabling relaxation edits only the visible draft and
  explicitly does not certify reconstructed geometry or delete residues.
- An attempted decision snapshot distinguishes current errors from failures of
  a previous plan. Old scalar-only failures remain usable without guessed atoms.
  Changing the distance reference preserves previous preparation evidence even
  when the inspection report refreshes.
  Force/iteration controls remain accessible in folded advanced settings.
- Copy describes elastic positional restraints accurately. Displacement alone
  no longer asserts an irreparable clash or recommends residue deletion.

The OpenMM worker, repulsive potential, bond tethers, default parameters,
0.5 Å threshold and original coordinate acceptance computation are unchanged.
Accepted historical records and raw worker files are never rewritten.

## Verification

- Full backend in the existing `ankora-dev` scientific environment:
  **741 tests passed**. No dependency was installed or updated.
- Full frontend: **285 tests passed across 39 files**, including six new
  receptor component regressions. TypeScript and production build pass.
- Ruff over backend source/tests and strict mypy over **138 source files** pass
  with the backend project's configuration. Public-path and generated
  scientific-status checks pass before commit.
- Synthetic coordinate tests cover within/exact/over-threshold displacement,
  complete ordered diagnosis, new-atom exclusion and immutable input bytes.
  A synthetic worker regression verifies retained failure JSON, raw stdout/
  stderr and all three stage PDBs, with no successful record on rejected output.
- Opt-in production smoke:
  `node scripts/smoke_packaged_frontend.mjs --ready-immediately --receptor-recovery`
  passed in headless Edge **155.0.4283.45** under the actual restrictive CSP.
  Real Mol* renders the explicit synthetic PDB/mmCIF fixtures. The recovery
  case verifies atom inspection without viewer errors, no horizontal page
  overflow at **1280×800** and **960×680**, folded settings, old-plan labeling,
  an escapable checkbox and exactly **one** mocked preparation request.
  Error-panel captures were visually inspected. This is browser-rendered
  Windows UI evidence, not newly installed Tauri acceptance or real relaxation.

### Read-only historical coordinate replay

Retained failed receptor `7962567b-6a2a-4cc5-afa8-459d043075cd` still rejects with
the exact previous maximum of **0.6049247887134421 Å**. The new diagnosis identifies
the observed **ARG A:271 CB** atom: `(43.887, -46.196, 26.505)` →
`(44.252, -46.674, 26.440)` Å. All six source files retain their SHA-256 values.
No PDBFixer, OpenMM, PDB2PQR, Meeko or docking tool was rerun for this replay.
This historical identity is not assumed to be the scientist's new failed attempt.

Private coordinate replay/test outputs remain under ignored
`build/user-guide-receptor-recovery-20261013/`; browser evidence is retained under
ignored `build/windows-runtime/frontend-smoke-1791916433702/`.

## Limitations and next acceptance

The basic `.venv` could run focused receptor tests but could not collect the full
packaging suite because `pefile` is absent. The unchanged existing `ankora-dev`
environment supplied the complete authoritative backend gate. A sandbox-only
API test run stalled and was stopped; the isolated unsandboxed Windows execution
passed. Existing Starlette test-client and frontend fixture warnings are retained,
as is the known large Mol* bundle notice; none was silenced by changing settings.

No Rust/application installer build or native installed-app acceptance is claimed.
The scientist should test the development source with their exact preparation
plan and inspect any remaining error evidence before authorizing a new separate
installer. A tolerance failure still rejects the geometry; turning off relaxation
is not a shortcut to scientific acceptance.
