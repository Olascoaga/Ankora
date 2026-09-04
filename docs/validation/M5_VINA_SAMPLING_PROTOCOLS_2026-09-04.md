# M5 Vina purpose-labelled sampling protocols - 2026-09-04

## Scope

This validation covers the request, interface, persistence, and Methods-report
contract introduced by ADR-019. It does not execute Vina, produce docking
scores, establish convergence, or claim that a fixed protocol is suitable for
publication.

## Contract verified

- New single-ligand and library setups default to the explicit `screening`
  purpose: exhaustiveness 8, 9 modes, 1.0 A minimum inter-mode RMSD, and a 3.0
  kcal/mol energy range.
- `pose_refinement` applies exhaustiveness 32, 20 modes, 1.0 A minimum
  inter-mode RMSD, and a 5.0 kcal/mol energy range.
- Selecting `custom` preserves the exact displayed numbers.
- Editing any sampling number relabels the setup as Custom and clears the
  scientist's prior exact-input acknowledgement.
- The backend rejects Screening or Pose refinement labels paired with values
  other than their recorded definitions.
- CPU/thread allocation, random seed, and timeout remain explicit controls
  outside the sampling-purpose preset.
- Historical records without a label remain readable and are never assigned an
  inferred purpose.
- Methods text records the selected purpose when present and explicitly states
  that it is not convergence or publication-suitability evidence.
- Batch execution receives the same retained purpose as the parent campaign.

## Evidence boundary

The automated fixtures are synthetic and validate software behavior only. A
scientific claim of adequate sampling still requires a separately recorded,
system-specific sensitivity or convergence study over the chosen binding site,
ligands, seeds, and sampling controls.

## Automated verification

The repository-wide Windows gate passed after the implementation:

- public-path check: no tracked absolute filesystem paths;
- backend: 453 pytest tests, Ruff, and strict mypy across 103 source files;
- frontend: 212 Vitest tests across 29 files, strict TypeScript, and production
  Vite build;
- native shell: rustfmt, strict Clippy, Rust unit/doc tests, and an optimized
  Tauri application build.

The existing frontend suite still emits its recorded non-fatal React `act()`
and synthetic `NaN` fixture warnings, and Vite still reports the known Mol*
bundle-size and browser-externalized optional encoder modules. None failed the
gate or originated in this sampling-protocol increment.
