# Ankora v0.2 `M3` Coupled Physical Pose Plausibility (`PoseBusters 0.6.5`) & Dual `MMFF94s` Conformational Strain — Dual-OS Engineering Verification

- **Date:** 2026-11-19
- **Branch:** `codex/v0.2-dev` (isolated from `main` and frozen tag `v0.1.0-beta.2` at `36f1c0e`)
- **Governance:** `ADR-030` (v0.2 Roadmap & Quality Contract), `ADR-031` §4 (`M3` `< 1 MiB` Pure-Python Wheel Budget Guard), `ADR-032` §4 (`E8` Coupled `PoseComplex` Evaluation)
- **Preceding Record:** [`V02_M2_PROTOCOL_CALIBRATION.md`](V02_M2_PROTOCOL_CALIBRATION.md)
- **Scope Boundary:** Software engineering, cross-OS `PoseBusters 0.6.5` integration, dual `MMFF94s` conformational strain evaluation, flexible side-chain covalent geometry auditing, create-only persistence, HTTP API, `MethodsReport`, Desktop UI, and stale-dependency verification on labelled synthetic fixtures. This record does **not** alter or extend the frozen `v0.1` scientific benchmark claims in [`VALIDATION_STATUS.md`](VALIDATION_STATUS.md) or the frozen `LIT_PCBA_ANKORA_VS_V1` manifests.

---

## 1. Installer-Size Budget & License Verification (`ADR-031`)

| Metric | Recorded Measurement | Budget / Policy |
| --- | --- | --- |
| Distribution | `posebusters==0.6.5` (`posebusters-0.6.5-py3-none-any.whl`) | Pure-Python wheel only (`0` compiled extensions) |
| Wheel size | **`567,794` bytes (`554.49 KiB`)** | `< 1,048,576` bytes (`< 1 MiB` in `environment/v02-installer-size-budget.json`) |
| Wheel SHA-256 | `3e0cbca6481079d5ab7d1989a8a8f184dbba27366613c4b515658ea52fb95ea3` | Locked in `requirements/windows-py312.lock` & `requirements/linux-py312.lock` |
| New transitive dependencies | **`0`** (`rdkit==2025.9.6`, `pandas==3.0.5`, `numpy==2.5.2`, `PyYAML==6.0.3` already locked) | Verified via `--no-deps` install & `verify_linux_environment_lock.py --runtime` |
| License | **MIT** (`posebusters-0.6.5.dist-info/licenses/LICENSE`, SPDX override `"MIT"` in `scripts/generate_third_party_notices.py`) | Permissive, compatible with Ankora MIT |

---

## 2. Delivered `M3` Capabilities

| Sub-Milestone | Scope | Key Modules |
| --- | --- | --- |
| **`M3a`** | Pure-Python `posebusters==0.6.5` lock alignment (`windows`/`linux` locks + `pyproject.toml` + budget manifest + legal override); `PoseBusters` `config="dock"` adapter with honest 4-state mapping (`pass`, `fail`, `not_applicable` for absent rings/double-bonds/waters/cofactors, `not_evaluable` for non-finite metrics) and 3D-stereochemistry canonical topology validation; dual `MMFF94s` conformational strain evaluator (`E_MMFF94s(locally relaxed pose, 100 kcal/mol/A^2 heavy-atom tether during relaxation only) - min_k E_MMFF94s(ETKDGv3 free conformer k)`) refusing silent UFF fallback on unparameterized elements (e.g., boron); and coupled `FlexRes` side-chain covalent geometry auditor (`flex_sidechain_bond_lengths`, `flex_sidechain_chirality`, `flex_sidechain_receptor_clash`) | `adapters/quality/posebusters_adapter.py`, `adapters/quality/conformational_strain.py`, `adapters/quality/flex_sidechain_geometry.py`, `schemas/warnings.py`, `tests/test_v02_m3a_pose_quality_adapters.py` |
| **`M3b`** | Create-only persistence (`analysis/pose_quality/<assessment_id>/record.json`, participating in `ProjectDependencyService` stale propagation without mutating records), `PoseQualityService` resolving any saved pose across all 8 catalog engines via shared `resolve_verified_pose_inputs`, evaluating `PoseBusters` + `FlexComplexGeometry` directly against the deterministically materialized coupled receptor PDB (`E8`) under `sidechain_flex`, verifying byte-level pose immutability (`mutated_original_pose = false`), 2 localhost REST routes (`GET`/`POST /api/v1/results/campaigns/{engine}/{record_id}/compounds/{ligand_id}/poses/{pose_artifact_id}/quality`), and `render_pose_quality_methods(...)` citing `Buttenschoen et al., Chem. Sci. 2024, 15, 3130-3139 (DOI: 10.1039/D3SC04185A)` | `schemas/pose_quality.py`, `persistence/pose_quality_store.py`, `services/pose_quality.py`, `services/pose_interactions.py`, `api/routes.py`, `services/methods_report.py`, `tests/test_v02_m3b_pose_quality_service_and_api.py` |
| **`M3c`** | Opt-in Desktop UI (`PoseQualitySection.tsx` inside `PoseInteractionPanel.tsx`): zero unsolicited fetches on mount, explicit 4-state summary pills & status filter, coupled `FlexRes` complex SHA-256 banner (`E8`), structured warning alerts, dedicated dual `MMFF94s` strain readout with explicit disclaimer that strain is a diagnostic flag never added to or subtracted from docking scores, plus `useLayoutEffect` pose-toggle reset fix eliminating first-frame interaction races | `apps/desktop/src/types/api.ts`, `apps/desktop/src/api/client.ts`, `apps/desktop/src/features/results/PoseQualitySection.tsx`, `apps/desktop/src/features/results/PoseInteractionPanel.tsx`, `apps/desktop/src/styles.css`, `apps/desktop/src/tests/PoseQualityM3.test.tsx` |

---

## 3. Empirical Findings Discharged in `M3`

1. **Honest 4-State Separation vs. Raw `PoseBusters` Booleans:**
   - Raw `PoseBusters 0.6.5` (`config="dock"`) returns `True` even when `0` waters, `0` cofactors, or `0` double bonds exist in the complex (`smallest_distance_* = NaN`, `number_*_checked = 0`). Ankora explicitly maps absent species/motifs to `DiagnosticStatus.NOT_APPLICABLE` instead of presenting a misleading green pass.
2. **Strict `MMFF94s` Parameter Gate Without Silent UFF Downgrade:**
   - Live probing proved `PoseBusters 0.6.5` `internal_energy` falls back to `UFF` on phenylboronic acid (`c1ccccc1B(O)O`), whereas Ankora's dual `MMFF94s` strain evaluator checks `AllChem.MMFFHasAllMoleculeParams(...)` up front and emits `strain = None`, `DiagnosticStatus.NOT_EVALUABLE`, and `POSE_QUALITY_MMFF94S_UNPARAMETERIZED` rather than silently changing force fields.
3. **Coupled `E8` Clash Detection on Moved `FlexRes` Side Chains:**
   - `test_v02_m3b_pose_quality_service_and_api.py` verifies two poses with identical ligand coordinates against a `sidechain_flex` `MET A:5` receptor: Pose 1 (clear moved rotamer) passes all checks (`overall_status = pass`), while Pose 2 (moved `MET A:5` side chain overlapping the ligand while the crystal rotamer stayed > 4 Å away) fails `pb_minimum_distance_to_protein` and `pb_volume_overlap_with_protein` (`overall_status = fail`, `POSE_QUALITY_CHECKS_FAILED`), proving evaluation runs on the coupled `PoseComplex` rather than stale crystal coordinates.

---

## 4. Dual-OS Verification Matrix (`codex/v0.2-dev` @ `d147b7f`)

### 4.1 Windows 11 x64 (RTX 5050 Laptop GPU)

| Check | Result |
| --- | --- |
| `scripts/check_public_paths.py`, `check_platform_docs.py`, `check_public_validation_status.py`, `verify_linux_environment_lock.py` | Passed (`45` Conda, `76` pip wheels) |
| `ruff check backend/src/ankora_backend backend/tests/test_v02_m3*.py` | `All checks passed!` |
| `mypy --config-file backend/pyproject.toml --strict backend/src/ankora_backend` | `Success: no issues found in 173 source files` |
| `adapters/engines/vina.py` frozen byte check | `7,120` bytes, SHA-256 `e13e32f5b6c401966debe80fe0049f4ae87f1cc3c8eb31f4566c57c1acc50993` |
| Combined Windows `test_v02_*.py` (`M0`–`M3`) + `test_autodock_gpu_docking.py` + `test_methods_report.py` + `test_pose_interactions.py` + `test_screening_benchmark_protocol.py` + `test_screening_benchmark_vina_plan.py` + `test_third_party_notices.py` | **`496 passed, 1 skipped`** (`188.25s`; sole skip is the Linux-only live `GNINA` test) |
| Desktop (`npm --workspace @ankora/desktop run typecheck`, `test`, `build:web`) | `tsc -b` 0 errors; **`46/46` test files, `388/388` tests passed** (including `PoseQualityM3.test.tsx`); Vite production bundle built cleanly (`12.80s`) |

### 4.2 Linux x86\_64 (WSL2 Ubuntu 24.04, CUDA 12.8, GNINA 1.3.3)

| Check | Result |
| --- | --- |
| `scripts/check_public_paths.py`, `check_platform_docs.py`, `check_public_validation_status.py`, `verify_linux_environment_lock.py --runtime` | Passed (`45` Conda artifacts, `76` pip wheels including `posebusters==0.6.5` verified on active runtime) |
| `ruff check backend/src/ankora_backend backend/tests/test_v02_*.py` | `All checks passed!` |
| `mypy --config-file backend/pyproject.toml --strict backend/src/ankora_backend` | `Success: no issues found in 173 source files` |
| `adapters/engines/vina.py` frozen byte check | `7,120` bytes, SHA-256 `e13e32f5b6c401966debe80fe0049f4ae87f1cc3c8eb31f4566c57c1acc50993` |
| `pytest -rs backend/tests/test_v02_*.py` (live Linux `PoseBusters 0.6.5`, `RDKit MMFF94s`, `Meeko 0.7.1`, `Vina 1.2.7`, `AutoGrid4/AD4 4.2.6`, `AutoDock-GPU 1.6 CUDA`, `GNINA 1.3.3`) | **`397 passed, 0 skipped`** (`86.66s`) |
| Desktop Linux Node `v24.19.0` (`npm run typecheck`, `npm test`, `npm run build:web`) | `tsc -b` 0 errors; **`46/46` test files, `388/388` tests passed**; Vite build succeeded (`9.95s`) |

---

## 5. Residual Scope & Next Milestone

- **Bare-Metal Linux Acceptance:** Final Linux release acceptance remains gated on a native Linux workstation (`ADR-029` Gate `D6`).
- **Deferred to `v0.3+`:** Multi-structure receptor ensemble docking (`apo`/`holo`) remains explicitly out of scope for `v0.2`.
- **Next Authorized Milestone:** **`M4`** — Declarative Pharmacophoric Rules (`ProLIF 2.2.1` `InteractionRuleSet`: `REQUIRED` / `ALTERNATIVE_OR` / `FORBIDDEN` + Tanimoto IFP similarity over coupled `PoseComplex`, `0` new dependencies).
