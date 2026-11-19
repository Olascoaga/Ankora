# Ankora v0.2 `M2` Out-of-Sample Protocol Calibration & Cross-Engine `--score_only` — Dual-OS Engineering Verification

- **Date:** 2026-11-19
- **Branch:** `codex/v0.2-dev` (isolated from `main` and frozen tag `v0.1.0-beta.2` at `36f1c0e`)
- **Governance:** `ADR-030` (v0.2 Roadmap & Quality Contract), `ADR-031` §3 (Out-of-Sample Protocol Calibration, `BEDROC20`, Parent + Bemis-Murcko Scaffold Split, Paired Parent Bootstrap, `1-SE` Parsimony Rule, Decoy Property Bias Audit), `ADR-032` & Gate 0 Finding `F4` (`FlexRes` `--score_only` Unbound Reference Shift)
- **Preceding Record:** [`V02_M1_EXPLICIT_FLEXIBILITY.md`](V02_M1_EXPLICIT_FLEXIBILITY.md)
- **Scope Boundary:** Software engineering, cross-OS scientific-tool `--score_only` integration, statistical calibration engine, HTTP API, `MethodsReport`, Desktop UI, and provenance verification on labelled synthetic fixtures and single-peptide/model complexes. This record does **not** alter or extend the frozen `v0.1` scientific benchmark claims in [`VALIDATION_STATUS.md`](VALIDATION_STATUS.md) or the frozen `LIT_PCBA_ANKORA_VS_V1` manifests.

---

## 1. Delivered `M2` Capabilities

| Sub-Milestone | Scope | Key Modules |
| --- | --- | --- |
| **`M2a`** | Cross-engine `--score_only` rescoring adapters across **AutoDock Vina `1.2.7`** (`vina`, `vinardo`, `ad4 --maps`), canonical **AutoDock4 `4.2.6` `epdb`** (rigid & `flexres`), and Linux **GNINA `1.3.3`** (`CNNscore`, `CNNaffinity`, `CNN_VS`, `minimizedAffinity`, optional `CNNvariance`), plus `PoseRescoringService` enforcing `E4` shared-context verification, `E7` map coverage, immutable staging-copy sanitization, and Gate 0 `F4` `unbound_reference_shifted` provenance | `adapters/engines/vina_v02.py`, `adapters/engines/autodock4_job.py`, `adapters/engines/gnina.py`, `schemas/rescoring.py`, `services/pose_rescoring.py`, `tests/test_v02_m2a_score_only.py` |
| **`M2b`** | Out-of-sample protocol calibration engine (`ADR-031` §3): parent + Bemis–Murcko scaffold grouped split (rejecting infeasible layouts without leaking scaffolds), 6-property physicochemical decoy bias audit (`MW`, `cLogP`, `HBD`, `HBA`, `RotBonds`, `formal_charge`; SMD + two-sample KS), tie-aware `BEDROC20` (primary), `EF1%` (with small-sample caution), `ROC-AUC`, `PR-AUC`, denominator-invariant active-vs-inactive failure census, paired parent bootstrap (`2,000` replicates, `candidate - reference`), deterministic `1-SE` parsimony rule favoring simpler/rigid protocols, single-use create-only filesystem locking (`split.json`, `selection.json`, `confirmation.json`), and verbatim null verdict `"Insufficient evidence to prefer over baseline"` | `schemas/warnings.py`, `schemas/calibration.py`, `persistence/calibration_store.py`, `services/protocol_calibration.py`, `tests/test_v02_m2b_protocol_calibration.py` |
| **`M2c`** | 6 localhost HTTP routes (`/api/v1/calibrations`, `/calibrations/{id}`, `/calibrations/splits`, `/calibrations/{id}/select`, `/calibrations/{id}/confirm`, `/rescoring/score-only`), saved-pose ID-only resolution across all 4 engines, `render_calibration_methods(...)` in `MethodsReportService` (preserving all `v0.1` `render(catalog_id)` prose untouched), and Desktop React/TypeScript UI (`ProtocolCalibrationWorkspace.tsx`, `RedockingWorkspace.tsx` view switch, opt-in `--score_only` cross-scoring panel with native-unit separation & Gate 0 `F4` disclosure in `PoseInteractionPanel.tsx`) | `api/routes.py`, `services/methods_report.py`, `tests/test_v02_m2c_api_and_methods.py`, `apps/desktop/src/types/api.ts`, `apps/desktop/src/api/client.ts`, `apps/desktop/src/features/validation/ProtocolCalibrationWorkspace.tsx`, `apps/desktop/src/features/validation/RedockingWorkspace.tsx`, `apps/desktop/src/features/results/PoseInteractionPanel.tsx`, `apps/desktop/src/tests/ProtocolCalibrationM2c.test.tsx` |

---

## 2. Empirical Cross-OS Findings Discharged in `M2`

1. **`vina 1.2.7 --scoring ad4 --maps <prefix> --score_only` Output Format:**
   - Live cross-OS probing confirmed that `--scoring ad4` formats term (4) as `(4) Unbound System's Energy [=(2)] : -0.249 (kcal/mol)` (distinct from standard Vina/Vinardo output) and supports scientific notation on steric clashes. `parse_vina_score_only_output` handles both variants strictly while preserving frozen `adapters/engines/vina.py` byte-identical to `v0.1.0-beta.2` (`7,120` bytes, SHA-256 `e13e32f5b6c401966debe80fe0049f4ae87f1cc3c8eb31f4566c57c1acc50993`).
2. **Canonical `autodock4 4.2.6 epdb` Cross-OS Exponent Formatting:**
   - Live runs on Windows 11 and Linux WSL2 confirmed `epdb` executes identically on both rigid and `flexres` poses, while Windows MSVCRT formats 3-digit exponents (`+5.30e+005`) and Linux glibc formats 2-digit exponents (`+5.74e+05`). `parse_autodock4_epdb_dlg` parses both accurately and defaults `ScoringFamily.AUTODOCK4` to canonical `autodock4_epdb` (with `vina_ad4_maps` available as explicit opt-in).
3. **Gate 0 Finding `F4` (`--score_only --flex` Unbound Shift):**
   - `vina 1.2.7 --score_only --flex` recomputes the unbound reference energy from the moved side chains. Every flexible Vina `--score_only` record sets `unbound_reference_shifted=True` on `PoseRescoreFunctionEvidence`, surfaces an explicit alert in `PoseInteractionPanel.tsx`, and discloses the shift in `render_calibration_methods(...)`.
4. **Rigid vs. `FlexRes` Anti-Overfitting Proof (`M2b` Scenarios A, B, C):**
   - Verified deterministically in `test_v02_m2b_protocol_calibration.py`:
     - *Scenario A:* `1-SE` parsimony retains the simpler rigid baseline when `FlexRes` point `BEDROC20` lies within one paired bootstrap SE.
     - *Scenario B:* A `FlexRes` protocol that overfits Calibration fails on locked Confirmation and records the exact verbatim `ADR-031` verdict `"Insufficient evidence to prefer over baseline"`.
     - *Scenario C:* A genuine induced-fit gain whose locked Confirmation paired 95% CI excludes zero positively records `preferred_over_baseline`, while single-use filesystem locks reject any second Confirmation call with HTTP `409 Conflict` (`CALIBRATION_CONFIRMATION_ALREADY_CONSUMED`).

---

## 3. Dual-OS Verification Matrix (`codex/v0.2-dev` @ `48cf258`)

### 3.1 Windows 11 x64 (RTX 5050 Laptop GPU)

| Check | Result |
| --- | --- |
| `scripts/check_public_paths.py`, `check_platform_docs.py`, `check_public_validation_status.py` | Passed |
| `ruff check backend/src/ankora_backend backend/tests/test_v02_m2*.py` | `All checks passed!` |
| `mypy --config-file backend/pyproject.toml --strict backend/src/ankora_backend` | `Success: no issues found in 166 source files` |
| `adapters/engines/vina.py` frozen byte check | `7,120` bytes, SHA-256 `e13e32f5b6c401966debe80fe0049f4ae87f1cc3c8eb31f4566c57c1acc50993` |
| `pytest backend/tests/test_v02_m2a_score_only.py test_v02_m2b_protocol_calibration.py test_v02_m2c_api_and_methods.py` (live Windows `vina.exe 1.2.7`, `autogrid4.exe 4.2.6`, `autodock4.exe 4.2.6`) | **`41 passed, 0 skipped`** (`16.90s`) |
| Combined Windows `test_v02_*.py` + `test_autodock_gpu_docking.py` + `test_methods_report.py` + `test_screening_benchmark_protocol.py` + `test_screening_benchmark_vina_plan.py` + `test_third_party_notices.py` | **`475 passed, 1 skipped`** (sole skip is the Linux-only live GNINA test; all frozen `LIT_PCBA_ANKORA_VS_V1` manifests verified) |
| Desktop (`npm --workspace @ankora/desktop run typecheck`, `test`, `build:web`) | `tsc -b` 0 errors; **`45/45` test files, `386/386` tests passed** (including `ProtocolCalibrationM2c.test.tsx`); Vite production bundle built cleanly (`12.19s`) |
| Tauri Rust (`apps/desktop/src-tauri`: `cargo fmt --check`, `cargo test`) | Passed (`3/3` Rust unit tests) |

### 3.2 Linux x86\_64 (WSL2 Ubuntu 24.04, CUDA 12.8, GNINA 1.3.3)

| Check | Result |
| --- | --- |
| `scripts/check_public_paths.py`, `check_platform_docs.py`, `check_public_validation_status.py` | Passed |
| `ruff check backend/src/ankora_backend backend/tests/test_v02_*.py` | `All checks passed!` |
| `mypy --config-file backend/pyproject.toml --strict backend/src/ankora_backend` | `Success: no issues found in 166 source files` |
| `adapters/engines/vina.py` frozen byte check | `7,120` bytes, SHA-256 `e13e32f5b6c401966debe80fe0049f4ae87f1cc3c8eb31f4566c57c1acc50993` |
| `pytest -q backend/tests/test_v02_*.py` (live Linux `Meeko 0.7.1`, `Vina 1.2.7`, `AutoGrid4 4.2.6`, `AutoDock4 4.2.6`, `AutoDock-GPU 1.6 CUDA`, and `GNINA 1.3.3` rigid + `FlexRes` `--score_only`) | **`390 passed, 0 skipped`** (`349` M0–M1 + `41` M2a/M2b/M2c) |
| Desktop Linux Node `v24.19.0` (`npm run typecheck`, `npm test`, `npm run build:web`) | `tsc -b` 0 errors; **`45/45` test files, `386/386` tests passed**; Vite build succeeded (`7.74s`) |

---

## 4. Residual Scope & Next Milestone

- **Bare-Metal Linux Acceptance:** Final Linux release acceptance remains gated on a native Linux workstation (`ADR-029` Gate `D6`).
- **Deferred to `v0.3+`:** Multi-structure receptor ensemble docking (`apo`/`holo`) remains explicitly out of scope for `v0.2`.
- **Next Authorized Milestone:** **`M3`** — Coupled Pose-Plausibility & Quality Gate (`PoseBusters` + dual `MMFF94s` conformational strain on coupled `PoseComplex`, pure-Python wheel within the `< 1 MiB` installer budget in `environment/v02-installer-size-budget.json`).
