# Ankora v0.2 Preregistered External Comparison Benchmark Protocol (`Ankora v0.2` vs. Pinned `DockM8`)

- **Date:** 2026-11-20 (external target identity pinned 2026-11-21; first two-axis execution archived 2026-11-23)
- **Status:** Preregistered Protocol & Pinned Target Identity (`DrugBud-Suite/DockM8` tag **`v1.1.1`**, commit **`3b765ea1122d01b6d3484ea25ec789f4456d8f8a`**, `2026-07-05T07:25:43Z`); First Two-Axis Execution Completed on `LIT-PCBA` `ESR_antago` (`5UFX`, WSL2/WSLg) in [`V02_EXTERNAL_BENCHMARK_ESR1_ANT_VS_DOCKM8.md`](V02_EXTERNAL_BENCHMARK_ESR1_ANT_VS_DOCKM8.md); Additional Multi-Target, Induced-Fit `FlexRes`, and Bare-Metal Linux `Gate D6` Runs Pending
- **Governance:** [`ADR-030`](../architecture/ADR/ADR-030-rank-space-consensus-prioritization.md), [`ADR-031`](../architecture/ADR/ADR-031-external-benchmark-boundary.md), [`ADR-032`](../architecture/ADR/ADR-032-explicit-flexibility-and-pose-complex-identity.md), [`ADR-033`](../architecture/ADR/ADR-033-hit-to-analog-expansion-and-pose-focused-screening.md), [`ADR-012`](../architecture/ADR/ADR-012-validation-by-reference-cases.md)
- **External Harness Location:** `benchmarks/external_comparison/` (strictly excluded from every Ankora installer, lockfile, and runtime per `ADR-031 §1`)
- **Scope Boundary:** This document preregisters the prospective scientific comparison protocol, pinned third-party commit identity, statistical hypotheses, admissibility rules, and bare-metal execution requirements. The first completed two-axis execution (`LIT-PCBA` `ESR_antago` / `5UFX`) is archived verbatim—including null primary verdicts—in [`V02_EXTERNAL_BENCHMARK_ESR1_ANT_VS_DOCKM8.md`](V02_EXTERNAL_BENCHMARK_ESR1_ANT_VS_DOCKM8.md) and does **not** alter the frozen `v0.1` claims in [`VALIDATION_STATUS.md`](VALIDATION_STATUS.md).

---

## 1. Hard Architectural Separation & Pinned Identities (`ADR-031 §1`)

1. **Product isolation:** `Ankora v0.2` runs 100% offline from its shipped Windows 11 x64 or Linux x86\_64 package without Docker, Streamlit, or any benchmark corpus. No dependency from `DockM8` enters `requirements/` or `backend/src/` (enforced in CI by `scripts/check_v02_installer_budget.py`).
2. **One-directional data consumption:** The external evaluator (`benchmarks/external_comparison/evaluate_comparison.py`, Python 3.12 stdlib only) consumes Ankora exclusively via SHA-256-verified **`Export v5`** (or `Export v4`) bundles validated first by `scripts/verify_export_bundle.py`.
3. **Pinned third-party identity:** `DockM8` (scientist-supplied reference `PMC13613745`) must be pinned to an exact release tag / commit SHA and container or environment digest inside `ComparisonProtocolManifest` before execution. Unpinned identifiers (`latest`, `main`, `head`) fail closed. Every raw `DockM8` output CSV, pose file, and log is preserved unmodified alongside its SHA-256 digest.

---

## 2. Mandatory Two-Axis Evaluation (`ADR-031 §2`)

Every comparison claim is admissible **only when both axes are executed and reported together** (`evaluate_comparison.py` rejects single-axis reports as `INCOMPLETE_SINGLE_AXIS_NOT_ADMISSIBLE`):

| Axis | Shared Inputs | What It Isolates |
| --- | --- | --- |
| **Axis A — Controlled Comparison** | Identical prepared receptor PDBQT/PDB, identical prepared ligand states (explicit protonation & tautomer set), identical search box coordinates, identical parent + Bemis–Murcko scaffold Confirmation split, identical compound denominator. | Isolates pose sampling, `--score_only` cross-evaluation, `PC-Q` / `PC-ECR` rank-space consensus, and `PoseBusters` physical validity from upstream chemistry preparation differences. |
| **Axis B — End-to-End Workflow Comparison** | Same starting crystallographic/experimental structure and same input compound library (SMILES + frozen activity labels). Each platform executes its own complete documented workflow (including preparation, protonation, pocket definition, and—for Ankora—explicit `FlexRes` / `LigandFlexibilitySpec` choices selected strictly on Calibration). | Measures real practitioner outcome, including preparation failure census, explicit chemistry guardrails, and induced-fit pocket handling (`1–4` `FlexRes` side chains where rigid-only receptors fail). |

---

## 3. Out-of-Sample Statistical Discipline (`ADR-031 §3`)

1. **Grouped Calibration / Confirmation split:** All compounds are split prior to scoring by `M2` `ProtocolCalibrationService` (`grouping_strategy = "parent_and_murcko_scaffold"`), sealing `split_identity_sha256` before any docking run begins.
2. **Calibration-only selection:** All protocol choices—including whether to enable `FlexRes` (`1–4` residues), whether to activate `Vinardo` or `PC-Q Core` vs. `PC-Q Neural`, whether to seal `M4` pharmacophoric rules (`rule_set_identity_sha256`), and whether to fit gated `PC-L2`—are locked on **Calibration** under the `1-SE` parsimony rule before unlocking **Confirmation** exactly once.
3. **Primary and secondary metrics (fixed in advance, no post-hoc substitution):**
   - **Primary metric:** Tie-aware **`BEDROC_20`** (`alpha = 20.0`) on the locked Confirmation split, retaining every failed, excluded, or `partial_or_unscored` parent compound as a worst-ranked tie in the invariant denominator (`ADR-030 E6`).
   - **Primary comparison statistic:** Paired parent-compound bootstrap `Δ BEDROC_20 = BEDROC_20(Ankora) − BEDROC_20(External)` (`2,000` replicates, `95% CI`, bootstrap `SE`, fixed seed `20261120`).
   - **Secondary metrics (labelled secondary):** `EF_1%`, `ROC-AUC`, `PR-AUC`, active-vs-inactive failure census, and **`PoseBusters`-stratified `BEDROC_20`** (re-evaluating enrichment after failing physically implausible poses, directly exposing score-only inflation vs. physical plausibility).
4. **Explicit null and negative verdicts:**
   - If the `95% CI` for `Δ BEDROC_20` includes zero, the mandatory verdict is verbatim: **`"Insufficient evidence to prefer over baseline"`**.
   - If the `95% CI` is strictly negative (`ci_upper < 0`), the external platform is recorded as preferred on that axis.
   - **Mandatory publication:** Every completed two-axis run—positive, null, or negative—must be archived verbatim under `docs/validation/` without selective omission.

---

## 4. Target Composition & Induced-Fit Sensitivity Case

1. **Retrospective virtual screening targets:** Drawn from public, non-redistributed benchmark corpora (e.g., unbiased `LIT-PCBA` targets with locked Bemis–Murcko Confirmation splits and documented 6-property decoy bias audits from `M2`).
2. **Induced-fit gatekeeper side-chain case (`ADR-032`):** Includes at least one well-characterized `apo` / gatekeeper-rotamer target where a pocket side chain occludes the bound ligand conformation in rigid coordinates, explicitly testing whether `M1` `FlexRes` (`1–4` residues) + `M2` `1-SE` Calibration + `M3` coupled `PoseBusters` + `M5` joint `(ligand, flex)` `PC-Q` recovers physically valid actives on Axis B without inflating false positives on rigid-optimal targets.

---

## 5. Bare-Metal Linux Workstation Execution (`ADR-029` Gate `D6`)

Final Linux release acceptance and external benchmark execution (requiring native Linux CUDA 12.8 for both `GNINA 1.3.3` / `AutoDock-GPU 1.6` and container-isolated `DockM8`) must be conducted on a physical bare-metal `x86_64` Linux workstation following [`LINUX_NATIVE_WORKSTATION_PROTOCOL.md`](LINUX_NATIVE_WORKSTATION_PROTOCOL.md):

1. Execute `scripts/smoke_linux_package.py` on the physical Linux workstation to record `native-workstation-attestation.json` (`Gate D6`).
2. Verify packaged installer byte deltas against `environment/v02-installer-size-budget.json` using `python -S scripts/check_v02_installer_budget.py --windows-installer ... --linux-deb ... --linux-tar-zst ...`.
3. Export Ankora's Confirmation campaigns and consensus rankings as **`Export v5`** bundles (`POST /api/v1/consensus/runs/{id}/export`) and verify every bundle with `python -S scripts/verify_export_bundle.py --require-format 5`.
4. Run `python -S benchmarks/external_comparison/evaluate_comparison.py` against the sealed `ComparisonProtocolManifest` and commit the resulting immutable JSON + Markdown comparison record under `docs/validation/`.
