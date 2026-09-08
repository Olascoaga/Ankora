# Consistent scientific and date formatting acceptance

Date: 2026-09-07

Scope: adversarial-audit remediation Gate D, item 20.

## Accepted contract

- Scientific quantities are rendered through one shared formatter regardless
  of the Windows display language.
- The decimal mark is always a period. Large values use U+202F NARROW NO-BREAK
  SPACE for grouping, for example `5 620.9 Å³` and `102 600` evaluations.
- Each caller still declares its scientifically meaningful precision. Values
  that round to zero never retain a misleading negative sign or positive sign.
- Missing or non-finite scientific values render as an explicit em dash.
- User-interface dates are English, day first, and use local 24-hour time.
  Ankora does not rewrite stored timestamps or silently replace an invalid
  historical timestamp.

The contract covers shell metadata, receptor inspection, ligand descriptors
and minimization evidence, binding boxes and search volumes, Vina and AutoDock4
setup/results, interaction distances and angles, redocking RMSD, campaign
history, Results, and Export. File-size and live machine-utilization displays
remain operational telemetry rather than scientific quantities.

## Automated evidence

Dedicated formatter regressions exercise dot decimals, narrow-space grouping,
fixed precision, signed values, negative-zero normalization, missing values,
English local dates, 24-hour time, and invalid-timestamp preservation. The
Vina search-volume regression verifies the actual scientific warning text uses
the same grouping contract. Existing workflow regressions protect all migrated
screens and ensure their recorded numeric values and units remain visible.

## Acceptance gate

The authoritative local gate for the exact committed tree includes:

- complete backend pytest, Ruff, and strict mypy;
- complete frontend tests, strict TypeScript, and production Vite build;
- Rust formatting, strict Clippy, unit/doc tests, and the optimized native
  Windows build;
- public-path sanitation and a clean diff check.

Final counts and commit identity are recorded in the changelog, private local
continuity memory, and Git history after the gate completes.
