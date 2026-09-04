# M4 binding-site decision guardrails — 2026-09-04

## Scope

This record validates the scientific-control boundary for the universally
available full-protein preview. It is implementation evidence, not evidence
that blind docking identifies a biological binding site.

## Verified behavior

- Binding Site still opens on a full-protein box computed through the
  non-persistent preview endpoint.
- Previewing the box without acknowledgement creates no binding-site artifact.
- The final action is disabled in the interface until the scientist explicitly
  acknowledges that the whole-receptor box is exploratory.
- The backend independently rejects an unacknowledged full-protein create with
  `BINDING_SITE_FULL_PROTEIN_ACKNOWLEDGEMENT_REQUIRED` and writes no directory.
- An acknowledged request records
  `acknowledge_exploratory_full_protein: true` in the immutable decisions and
  proceeds through the existing source-record and optional manual-derivative
  lineage.
- A displayed box above 27,000 A^3 shows Vina's large-search-space warning
  before finalization.

## Automated evidence

Synthetic, explicitly labelled backend coverage resolves the real atoms in the
existing gemmi-readable fixture, checks non-persistence on rejection, and
checks acknowledged default/custom-margin geometry. Frontend coverage verifies
the automatic preview, disabled final action, explicit checkbox, recorded
request, and visible 102,600 A^3 warning.

The focused gate passed on 2026-09-04: 27 backend tests and 34 frontend tests
covering Binding Site, Vina setup, campaign history, and the volume-guidance
component. The authoritative repository gate then passed 441 backend tests,
Ruff, strict mypy over 103 source files, 209 frontend tests over 28 files,
strict TypeScript, the production Vite build, Rust formatting, strict Clippy,
unit/doc tests, and the optimized native Windows build.
