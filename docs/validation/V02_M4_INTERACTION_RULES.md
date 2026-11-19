# Ankora v0.2 `M4` Declarative ProLIF Pharmacophoric Rules (`PIC`) & Tanimoto IFP — Dual-OS Engineering Verification

- **Date:** 2026-11-19
- **Branch:** `codex/v0.2-dev` (isolated from `main` and frozen tag `v0.1.0-beta.2` at `36f1c0e`)
- **Governance:** `ADR-030` (v0.2 Roadmap), `ADR-031` §4 (`M4` `0`-byte Dependency Budget Guard), `ADR-032` §4 (`E8` Coupled `PoseComplex` Evaluation), [`POSE_INTERACTION_POLICY.md`](../scientific/POSE_INTERACTION_POLICY.md)
- **Preceding Record:** [`V02_M3_POSE_QUALITY.md`](V02_M3_POSE_QUALITY.md)
- **Scope Boundary:** Software engineering, cross-OS `ProLIF 2.2.1` declarative rule evaluation (`REQUIRED`, `ALTERNATIVE_OR`, `FORBIDDEN`), canonical binary/counted IFP + Tanimoto similarity (including honest `0 / 0` `not_evaluable` empty-union handling), denominator-invariant `M2` Protocol Calibration gating, coupled `FlexRes` (`E8`) evaluation, create-only persistence, stale-dependency propagation, HTTP API, `MethodsReport`, and Desktop UI verification on labelled synthetic fixtures. This record does **not** alter or extend the frozen `v0.1` scientific benchmark claims in [`VALIDATION_STATUS.md`](VALIDATION_STATUS.md) or the frozen `LIT_PCBA_ANKORA_VS_V1` manifests.

---

## 1. Installer-Size Budget Verification (`ADR-031`)

| Metric | Recorded Measurement | Budget / Policy |
| --- | --- | --- |
| New Python packages / wheels | **`0`** | `0` bytes declared for `M4` in [`environment/v02-installer-size-budget.json`](../../environment/v02-installer-size-budget.json) |
| New native executables | **`0`** | Reuses already-locked `prolif==2.2.1`, `rdkit==2025.9.6`, and `meeko==0.7.1` |
| Environment lock status | `45` Conda artifacts, `76` pip wheels unchanged | Verified by `verify_linux_environment_lock.py --runtime` |

---

## 2. Delivered `M4` Capabilities

| Sub-Milestone | Scope | Key Modules |
| --- | --- | --- |
| **`M4a`** | Frozen declarative rule & IFP contracts (`InteractionRuleSetRecord`, `InteractionRuleClause` supporting `REQUIRED` / `ALTERNATIVE_OR` / `FORBIDDEN`, `InteractionTarget` with optional `max_distance_angstrom`, `InteractionFingerprint`, `IfpTanimotoResult`, `InteractionRuleEvaluationRecord`); order-invariant canonical `rule_set_identity_sha256` (plugging directly into `ProtocolSpec.interaction_rule_set_sha256`) and `fingerprint_sha256`; PDB residue validator rejecting typos/mismatches fail-closed (`422`); pure Tanimoto IFP evaluator reporting empty unions (`0 / 0`) honestly as `similarity = None` + `not_evaluable` + `INTERACTION_IFP_EMPTY_UNION`; and `apply_interaction_rule_gate_to_observations(...)` preserving an invariant denominator inside `M2` `ProtocolCalibrationService` (`INTERACTION_RULE_SET_FAILED` / `INTERACTION_RULE_NOT_EVALUABLE`) | `schemas/warnings.py`, `schemas/interaction_rules.py`, `adapters/interactions/pharmacophore_rules.py`, `tests/test_v02_m4a_interaction_rules_engine.py` |
| **`M4b`** | Create-only stores (`analysis/interaction_rule_sets/` and `analysis/interaction_rule_evaluations/`) wired into `ProjectDependencyService` (`rule_set_id` reference tracking and `POSE_ANALYSIS` classification so receptor/rule-set staleness propagates automatically); `InteractionRulesService` resolving poses across all 8 catalog sources via `resolve_verified_pose_inputs`, validating cross-receptor identity, running live `ProLIF 2.2.1` directly on the deterministically materialized coupled receptor PDB (`E8`) when `sidechain_flex` is active (or reusing a hash-verified matching `InteractionAnalysisRecord`), verifying byte-level pose immutability (`mutated_original_pose = false`); 5 localhost REST endpoints (`/api/v1/interactions/rule-sets*` and `/api/v1/results/campaigns/{engine}/{record_id}/compounds/{ligand_id}/poses/{pose_artifact_id}/interaction-rules`); and `render_interaction_rules_methods(...)` citing Crossref-verified `Bouysset & Fiorucci, J. Cheminform. 2021, 13, 72 (DOI: 10.1186/s13321-021-00548-6)` without modifying `v0.1` prose | `persistence/interaction_rules_store.py`, `services/interaction_rules.py`, `services/project_dependencies.py`, `api/routes.py`, `services/methods_report.py`, `tests/test_v02_m4b_interaction_rules_service_and_api.py` |
| **`M4c`** | Strictly opt-in Desktop UI (`InteractionRulesSection.tsx` inside `PoseInteractionPanel.tsx`, zero unsolicited API calls on mount): declarative `REQUIRED` / `ALTERNATIVE_OR` / `FORBIDDEN` builder with 1-click quick-add from detected contacts, optional current-pose Tanimoto IFP reference + threshold, sealed `rule_set_identity_sha256` display, coupled `FlexRes` (`E8`) banner, warning alerts, Tanimoto bit-diff card (`Shared` / `Missing` / `Pose-only` + `0 / 0` `not_evaluable`), and clickable contact pills focusing the exact contact simultaneously in the 2D SVG diagram and 3D `Mol*` viewer | `apps/desktop/src/types/api.ts`, `apps/desktop/src/api/client.ts`, `apps/desktop/src/features/results/InteractionRulesSection.tsx`, `apps/desktop/src/features/results/PoseInteractionPanel.tsx`, `apps/desktop/src/styles.css`, `apps/desktop/src/tests/InteractionRulesM4.test.tsx` |

---

## 3. Live Coupled `FlexRes` (`E8`) & Anti-Leakage Proofs

1. **Induced `SER A:5` Hydrogen Bond on Coupled `FlexRes` (`test_v02_m4b_interaction_rules_service_and_api.py`):**
   - Two poses hold identical synthetic ethanol coordinates while `SER A:5` is configured as `sidechain_flex` (crystal rotamer points in `+Y`, `> 5.4 Å` from the ligand).
   - **Pose 1** (moved `SER A:5` `OG`/`HG` rotated into `-Y` at `2.80 Å` from ethanol `O`) passes `REQUIRED SER A:5 [HBDonor/HBAcceptor] <= 3.5 Å` and yields `Tanimoto IFP = 1.000` against Pose 1's sealed reference IFP under live `ProLIF 2.2.1`.
   - **Pose 2** (identical ligand, moved `SER A:5` in crystal `+Y` rotamer) fails `REQUIRED SER A:5`, triggers `INTERACTION_RULE_CLAUSES_FAILED` and `INTERACTION_IFP_TANIMOTO_BELOW_THRESHOLD`, and records a distinct `materialized_coupled_receptor_sha256` — proving evaluation operates strictly on per-pose moved side chains rather than static crystal coordinates.
2. **Leakage Prevention & Invariant Denominator in `M2` Calibration (`test_v02_m4a_interaction_rules_engine.py`):**
   - Pinning `ProtocolSpec(interaction_rule_set_sha256=...)` during Calibration retains non-passing parents in `FailureCensusBreakdown` with `INTERACTION_RULE_SET_FAILED` (worst-ranked tie, never dropped from the denominator), and attempting to supply Confirmation observations tagged with a modified rule-set hash fails closed (`422`).
3. **Fail-Closed Integrity Guards:**
   - Unknown/mismatched receptor residue (`INTERACTION_RULE_RESIDUE_NOT_FOUND`, `422`), cross-receptor rule evaluation (`INTERACTION_RULE_RECEPTOR_MISMATCH`, `422`), mismatched cached `analysis_id` reuse (`INTERACTION_RULE_ANALYSIS_MISMATCH`, `422`), and stale propagation from receptor → rule set → pose evaluation are all verified.

---

## 4. Dual-OS Verification Matrix (`codex/v0.2-dev` @ `8fc447e`)

### 4.1 Windows 11 x64 (`RTX 5050` Laptop GPU)

| Check | Result |
| --- | --- |
| `scripts/check_public_paths.py`, `check_platform_docs.py`, `check_public_validation_status.py`, `verify_linux_environment_lock.py` | Passed (`45` Conda, `76` pip wheels) |
| `ruff check backend/src/ankora_backend backend/tests/test_v02_m4*.py` | `All checks passed!` |
| `mypy --config-file backend/pyproject.toml --strict backend/src/ankora_backend` | `Success: no issues found in 177 source files` |
| `adapters/engines/vina.py` frozen byte check | `7,120` bytes, SHA-256 `e13e32f5b6c401966debe80fe0049f4ae87f1cc3c8eb31f4566c57c1acc50993` |
| Combined Windows `test_v02_*.py` (`M0`–`M4`) + `test_autodock_gpu_docking.py` + `test_methods_report.py` + `test_pose_interactions.py` + `test_screening_benchmark_protocol.py` + `test_screening_benchmark_vina_plan.py` + `test_third_party_notices.py` | **`503 passed, 1 skipped`** (`144.33s`; sole skip is the Linux-only live `GNINA` test) |
| Desktop (`npm --workspace @ankora/desktop run typecheck`, `test`, `build:web`) | `tsc -b` 0 errors; **`47/47` test files, `390/390` tests passed** (including `InteractionRulesM4.test.tsx`); Vite production bundle built cleanly (`14.15s`) |

### 4.2 Linux x86\_64 (WSL2 Ubuntu 24.04, CUDA 12.8, GNINA 1.3.3)

| Check | Result |
| --- | --- |
| `scripts/check_public_paths.py`, `check_platform_docs.py`, `check_public_validation_status.py`, `verify_linux_environment_lock.py --runtime` | Passed (`45` Conda artifacts, `76` pip wheels verified on active runtime) |
| `ruff check backend/src/ankora_backend backend/tests/test_v02_*.py` | `All checks passed!` |
| `mypy --config-file backend/pyproject.toml --strict backend/src/ankora_backend` | `Success: no issues found in 177 source files` |
| `adapters/engines/vina.py` frozen byte check | `7,120` bytes, SHA-256 `e13e32f5b6c401966debe80fe0049f4ae87f1cc3c8eb31f4566c57c1acc50993` |
| `pytest -p no:cacheprovider -rs backend/tests/test_v02_*.py` (live Linux `ProLIF 2.2.1`, `PoseBusters 0.6.5`, `RDKit MMFF94s`, `Meeko 0.7.1`, `Vina 1.2.7`, `AutoGrid4/AD4 4.2.6`, `AutoDock-GPU 1.6 CUDA`, `GNINA 1.3.3`) | **`404 passed, 0 skipped`** (`85.22s`) |
| Desktop Linux Node `v24.19.0` (`npm run typecheck`, `npm test`, `npm run build:web`) | `tsc -b` 0 errors; **`47/47` test files, `390/390` tests passed**; Vite build succeeded (`8.24s`) |

---

## 5. Residual Scope & Next Milestone

- **Bare-Metal Linux Acceptance:** Final Linux release acceptance remains gated on a native Linux workstation (`ADR-029` Gate `D6`).
- **Deferred to `v0.3+`:** Multi-structure receptor ensemble docking (`apo`/`holo`) remains explicitly out of scope for `v0.2`.
- **Next Authorized Milestone:** **`M5`** — Pose-Concordant Quantile Consensus Engine (`PC-Q` `pcq-core-v1` / `pcq-neural-v1`, `PC-ECR`, gated convex `PC-L2`, complete-linkage joint `(ligand, flex)` clustering `<= 2.0 Å` with `K_max` cap, deterministic medoid tie-break `E3`, and two-tier ranking table `E6`; `0` new dependencies).
