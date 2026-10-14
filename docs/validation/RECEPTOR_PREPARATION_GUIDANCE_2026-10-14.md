# Receptor preparation guidance — 2026-10-14

## Scope and acceptance criteria

The scientist reported a new installed 7AQF preparation failure and excessive
trial-and-error. This unit fixes task guidance, not reconstructed chemistry.
The submitted scientific request and existing workers remain authoritative.

- Explain every unresolved structural prerequisite before calculation.
- After a residue-plan change, expose a reachable new pKa review action and
  keep final preparation blocked until that review exists for the exact plan.
- Grouped actions populate the draft only, do not overwrite existing Repair or
  Remove decisions, and neither remove residues nor launch scientific work.
- Filtering protonation proposals must retain hidden scientist overrides in
  the complete final request.
- Preserve failed-attempt evidence; distinguish it from the changed draft.
  After explicit removal choices, fold previous Meeko evidence rather than let
  it obscure the next action. The scientist can reopen it.
- Offer original-residue inspection and existing optional clash relief before
  deletion, with unchanged limitations. No repair or preparation is automatic.
- Keep decisions, next action and viewer reachable at 960×680 and 1280×800.

## Diagnosis of the reported scientific failure

The supplied failure identifies attempt `99871cbf-ad43-410e-a6b5-060966021c94`.
Its exact Meeko-input PQR SHA-256 is
`ce95eeb46d95d7b87e23c425befe7560dc1f7d5bba6864a59d218c91eaa0bcac`, independently
verified against the retained file. Meeko/RDKit reports carbon valence 6 in
LYS A:104 and valence 5 in GLN A:174 and ILE A:342. PDBFixer's structured output
reports 17 requested/matched repairs and no optional relaxation.

Read-only coordinate/topology inspection found:

| Residue | Retained-stage evidence |
| --- | --- |
| LYS A:104 | In the repaired PDB, reconstructed CD and CE lie 1.655 and 1.528 Å from observed CB despite not being its standard-template neighbors. These contacts persist through protonation; geometric connectivity assigns CB six neighbors. |
| GLN A:174 | Repaired NE2 lies 1.712 Å from OE1 and 1.775 Å from CG, producing extra inferred heavy-atom connections that persist through protonation. |
| ILE A:342 | The protonated coordinates place HB 0.874 Å from reconstructed CG2; connectivity assigns CG2 that hydrogen in addition to its normal neighbors. |

The read-only comparison used Gemmi 0.7.5, RDKit 2025.9.6 connectivity and
OpenMM 8.5.2 standard-residue topology; PDBFixer 1.12.0 and Meeko 0.7.1 were
installed in that diagnostic environment. It establishes malformed inferred geometry
in this attempt, not a universally applicable clash cutoff or preferred repair.
The three inspected PDB files were rehashed unchanged after inspection:

- Selected: `62987da61fe858e579a9dc85d1aac94258e9e13cee40117b681aac88f171cae6`.
- Repaired: `6a7572008e0230152844fce17d4aecb64be64a07a9d664f73cdf89c4540e23bb`.
- Protonated: `6ddcdcd415e0f3b7019c24c189a5513fb1dd58e8d469c521d2c0f031bd5cbb22`.

No failed artifact was overwritten or promoted; no receptor or docking was
rerun. Removing successive residues is not considered a validated chemical
repair. Reconstruction and post-hydrogen geometry need a separate, explicitly
validated correction before claiming this scientific failure resolved.

Code inspection also finds `fixer.addMissingAtoms()` called without a seed.
PDBFixer 1.12.0 exposes `seed=None` and seeds its Langevin integrator only when
one is supplied. Preview and final preparation independently reconstruct atoms.
This permits run-to-run variation; no paired repair execution was performed
here, so a deterministic-repair fix or successful paired outcome is not claimed.

## Verification

- Full frontend: 289 tests across 39 files pass, including four new synthetic
  guidance/grouping/filter/opt-in recovery regressions.
- Strict TypeScript and production build pass.
- Native Windows receptor backend regression subset: 49 tests pass; no backend
  source changed. This is not a new full-backend or native-installer acceptance.
- Public-path and frozen scientific-validation status checks pass.
- Production Edge 155 smoke with strict CSP passes startup/assets and genuine
  Mol* rendering of explicitly synthetic PDB/mmCIF UI fixtures. Recovery and
  guidance are checked at 960×680 and 1280×800: next action available, table
  reachable, no global horizontal overflow, stale review invalidated, focused
  proposal selection available, exactly two mocked preparation requests and two
  mocked reviews, no automatic retry, no viewer/CSP errors.
- The shared production smoke now accepts `--receptor-recovery
  --receptor-guidance`; CI invokes both. No new remote CI result is asserted.

All synthetic replies test interface behavior, not a successful 7AQF repair.
Raw browser evidence/screenshots and the read-only diagnostic helper remain
ignored locally. A sandbox-only backend test attempt stalled at a native
process boundary and was stopped; the same 49-test subset passed outside that
restriction. No owned test process remains. The existing unsigned installer
and scientific originals are untouched; a new installer requires separate
acceptance and authorization after the scientific correction.
