# Ankora v0.2 `M5` Pose-Concordant Quantile Consensus (`PC-Q`, `PC-ECR`, Gated `PC-L2`) — Dual-OS Engineering Verification

- **Date:** 2026-11-19
- **Branch:** `codex/v0.2-dev` (isolated from `main` and frozen tag `v0.1.0-beta.2` at `36f1c0e`)
- **Governance:** [`ADR-030`](../architecture/ADR/ADR-030-rank-space-consensus-prioritization.md) (Rank-Space Consensus Prioritization `PC-Q` / `PC-ECR` / `PC-L2`), [`ADR-031`](../architecture/ADR/ADR-031-external-benchmark-boundary.md) §4 (`M5` `0`-byte Dependency Budget Guard), [`ADR-032`](../architecture/ADR/ADR-032-explicit-flexibility-and-pose-complex-identity.md) (`E7`/`E8` Coupled `PoseComplexIdentity`)
- **Preceding Record:** [`V02_M4_INTERACTION_RULES.md`](V02_M4_INTERACTION_RULES.md)
- **Scope Boundary:** Software engineering, deterministic complete-linkage joint `(ligand, flex)` pose clustering (`<= 2.0 Å` with explicit `K_max` cap and `E3` medoid tie-break), parent-weighted empirical midrank quantile consensus (`pcq-core-v1`, `pcq-neural-v1` always accompanied by `pcq-core-v1`), inter-family disagreement (`D_ic`), separate-scale `PC-ECR` (`tau = 0.05`, `1/sigma` scale per Palacio-Rodríguez et al. `doi:10.1038/s41598-019-41594-3`), Confirmation-gated strictly convex non-negative `PC-L2` (`scipy.optimize.L-BFGS-B`), live cross-engine `--score_only` campaign orchestration, two-tier `RankingArtifact` (`E6`), create-only persistence, stale-dependency propagation, HTTP API, `MethodsReport`, and opt-in Desktop UI verification on labelled synthetic fixtures. This record does **not** alter or extend the frozen `v0.1` scientific benchmark claims in [`VALIDATION_STATUS.md`](VALIDATION_STATUS.md) or the frozen `LIT_PCBA_ANKORA_VS_V1` manifests.

---

## 1. Installer-Size Budget Verification (`ADR-031`)

| Metric | Recorded Measurement | Budget / Policy |
| --- | --- | --- |
| New Python packages / wheels | **`0`** | `0` bytes declared for `M5` in [`environment/v02-installer-size-budget.json`](../../environment/v02-installer-size-budget.json) |
| New native executables | **`0`** | Reuses already-locked `scipy`, `rdkit==2025.9.6`, `meeko==0.7.1`, AutoDock Vina `1.2.7`, AutoGrid4/AutoDock4 `4.2.6`, AutoDock-GPU `1.6`, and Linux GNINA `1.3.3` |
| Environment lock status | `45` Conda artifacts, `76` pip wheels unchanged | Verified by `verify_linux_environment_lock.py --runtime` |

---

## 2. Delivered `M5` Capabilities

| Sub-Milestone | Scope | Key Modules |
| --- | --- | --- |
| **`M5a`** | Frozen ADR-030 consensus contracts (`ConsensusVariantId`, `PoseClusterSummary`, `ReferencePanelArtifact` with order-invariant `compute_reference_panel_sha256` (`E1`), `MedoidConsensusBreakdown`, `PcL2ModelArtifact`, `ConsensusParentDetail`, `ConsensusRunRecord`) + 3 warning codes (`CONSENSUS_PARTIAL_PROFILE_RETAINED`, `CONSENSUS_HIGH_INTER_FAMILY_DISAGREEMENT`, `CONSENSUS_PCL2_UNPROMOTED`); deterministic complete-linkage joint `(ligand, flex)` pose clustering (`d_joint = max(RMSD_lig, RMSD_flex)` reusing symmetry-aware `CalcRMS` plus per-residue symmetric side-chain RMSD for `PHE`/`TYR`/`ASP`/`GLU`/`ARG`/`VAL`/`LEU`), explicit required `k_max` (`E2`), bitwise input-order-invariant `E3` medoid tie-break (`canonical_pose_coordinate_sha256`), and independent `search_engines_present` tracking; pure rank-space consensus math (`pcq-core-v1` `0.50/0.50`, `pcq-neural-v1` `1/3,1/3,1/3` always computing `core_ranking` alongside, within-block `vina`+`vinardo` `0.50/0.50` preventing double-voting, parent-weighted midrank quantiles invariant to medoid duplication, exact `D_ic`, separate-scale `PC-ECR` at `tau = 0.05` (`E5`), two-tier `E6` `RankingArtifact` without imputation, and bounded strictly convex `scipy.optimize.L-BFGS-B` non-negative `PC-L2` gated on locked Confirmation via `paired_parent_bootstrap_delta` emitting verbatim `"Insufficient evidence to prefer over baseline"` when unpromoted) | `schemas/warnings.py`, `schemas/consensus.py`, `adapters/chemistry/pose_clustering.py`, `adapters/consensus/pcq_math.py`, `tests/test_v02_m5a_clustering_and_pcq_math.py` |
| **`M5b`** | Create-only `ConsensusArtifactStore` (`analysis/consensus/` and `analysis/consensus_panels/`) wired into `ProjectDependencyService` (`consensus_id`, `panel_id`, `calibration_id` -> `POSE_ANALYSIS` stale propagation); `PoseConsensusService` enforcing fail-closed `E4`/`E7` shared receptor, flex-spec, binding-box, and AutoGrid4 map-set identity, clustering all saved campaign poses per parent, cross-scoring every retained medoid in place via live `PoseRescoringService` (`--score_only`, never mutating pose bytes), locking or reusing `ReferencePanelArtifact` (`E1`), and creating immutable `PC-L2` derivative runs; 5 localhost REST routes (`GET /api/v1/consensus/runs`, `GET /api/v1/consensus/runs/{consensus_id}`, `POST /api/v1/consensus/runs/structured`, `POST /api/v1/consensus/runs/campaigns`, `POST /api/v1/consensus/runs/{consensus_id}/pc-l2`); DOI-verified citation `_ECR_PALACIO_RODRIGUEZ` (`Palacio-Rodríguez K, Lans I, Cavasotto CN, Cossio P. Scientific Reports. 2019;9:5142. doi:10.1038/s41598-019-41594-3`) and standalone `render_consensus_methods(...)` leaving `v0.1` `MethodsReport` untouched | `persistence/consensus_store.py`, `services/pose_consensus.py`, `services/project_dependencies.py`, `services/tool_citations.py`, `services/methods_report.py`, `api/routes.py`, `tests/test_v02_m5b_consensus_service_and_api.py` |
| **`M5c`** | Strictly opt-in Desktop UI (`ConsensusWorkspace.tsx` mounted via `Campaigns` \| `PC-Q Consensus` switch inside `ResultsWorkspace.tsx`, issuing zero unsolicited `/consensus/*` fetches on mount): create-consensus builder enforcing explicit required `K_max` (`E2`) with fixed published weights (zero user weight sliders), saved run selector & provenance header (`variant_id`, `ReferencePanel SHA-256`, `FlexRes E8` badge, denominator, warnings), two-tier `E6` ranking table showing `PC-Q (0–100)`, `PC-Q Core (0–100)` whenever `pcq-neural-v1` is active, separate `PC-ECR (τ=0.05, 1/σ scale)` column (`E5`), `D_ic`, family block quantile bars (`Q_icb`), independent `Search convergence` badge, `RotBonds`, expandable per-medoid native-unit score drawer, explicit Tier 2 `partial_or_unscored` unranked retention table, and optional Confirmation-gated `PC-L2` calibration & audit card rendering both promoted and verbatim unpromoted verdicts | `apps/desktop/src/types/api.ts`, `apps/desktop/src/api/client.ts`, `apps/desktop/src/features/results/ConsensusWorkspace.tsx`, `apps/desktop/src/features/results/ResultsWorkspace.tsx`, `apps/desktop/src/styles.css`, `apps/desktop/src/tests/ConsensusM5c.test.tsx` |

---

## 3. Verified Scientific & Engineering Invariants (`ADR-030` `E1`–`E8`)

1. **Joint `(ligand, flex)` Complete-Linkage Clustering & Anti-Chaining (`test_v02_m5a_clustering_and_pcq_math.py`):**
   - Verified 7 Å flipped poses never merge, intermediate bridge poses cannot chain distant conformations (`complete-linkage`), input-permutation invariance holds bitwise via `E3` canonical coordinate SHA-256 tie-break, divergent `MET A:5` side-chain rotamers split clusters even on identical ligand coordinates, and symmetric `ASP` `OD1/OD2` swaps yield `0.0 Å` RMSD.
2. **Parent-Weighted Midrank Quantiles, Exact `D_ic`, Separate `PC-ECR` Scale, & Two-Tier `E6` (`test_v02_m5a_clustering_and_pcq_math.py`):**
   - Verified parent-weighted midrank `q = 0.375` remains strictly invariant under 4× medoid duplication, exact `D_ic = 37.5 / 12.5`, exact `PC-ECR` on `1/sigma` scale (`tau = 0.05`), `pcq-neural-v1` always recording `pcq-core-v1` alongside, `E6` unranked retention of partial/unscored parents without imputation, and `PC-L2` gating passing on orthogonal complementary features (`promoted = True`) while rejecting collinear/non-improving features (`promoted = False` + verbatim `"Insufficient evidence to prefer over baseline"`).
3. **Live Cross-Engine `--score_only` Campaign Consensus & Fail-Closed Context Guards (`test_v02_m5b_consensus_service_and_api.py`):**
   - Executed **live** `AutoGrid4 4.2.6`, `AutoDock Vina 1.2.7` (`vina` + `vinardo` `--score_only`), and `AutoDock4 4.2.6` (`epdb` `--score_only`) end-to-end via `POST /api/v1/consensus/runs/campaigns`, verified `E4` binding-box mismatch rejection (`422` `CONSENSUS_SHARED_CONTEXT_MISMATCH`), `E1` hash-locked `ReferencePanelArtifact` reuse across runs, stale DAG propagation from receptor -> panel -> consensus run, `MethodsReport` generation citing `10.1038/s41598-019-41594-3`, structured `pcq-neural-v1` persistence, and create-only `POST /api/v1/consensus/runs/{consensus_id}/pc-l2` derivatives.

---

## 4. Dual-OS Verification Matrix (`codex/v0.2-dev` @ `a038cda`)

### 4.1 Windows 11 x64 (`RTX 5050` Laptop GPU)

| Check | Result |
| --- | --- |
| `scripts/check_public_paths.py`, `check_platform_docs.py`, `check_public_validation_status.py`, `verify_linux_environment_lock.py` | Passed (`45` Conda, `76` pip wheels unchanged) |
| `ruff check backend/src/ankora_backend backend/tests/test_v02_m5*.py` | `All checks passed!` |
| `mypy --config-file backend/pyproject.toml --strict` (all 10 `M5` modules) | `Success: no issues found in 10 source files` |
| `adapters/engines/vina.py` frozen byte check | `7,120` bytes, SHA-256 `e13e32f5b6c401966debe80fe0049f4ae87f1cc3c8eb31f4566c57c1acc50993` |
| Combined Windows `test_v02_*.py` (`M0`–`M5`) + `test_autodock_gpu_docking.py` + `test_methods_report.py` + `test_pose_interactions.py` + `test_screening_benchmark_protocol.py` + `test_screening_benchmark_vina_plan.py` + `test_third_party_notices.py` | **`511 passed, 1 skipped`** (`127.94s`; sole skip is the Linux-only live `GNINA` test) |
| Desktop (`npx tsc -b`, `npx vitest run`, `npx vite build`) | `tsc -b` 0 errors; **`48/48` test files, `393/393` tests passed** (including `ConsensusM5c.test.tsx` and untouched `ResultsWorkspace.test.tsx`); Vite production bundle built cleanly (`12.36s`) |

### 4.2 Linux x86\_64 (WSL2 Ubuntu 24.04, CUDA 12.8, GNINA 1.3.3)

| Check | Result |
| --- | --- |
| `scripts/check_public_paths.py`, `check_platform_docs.py`, `check_public_validation_status.py`, `verify_linux_environment_lock.py --runtime` | Passed (`45` Conda artifacts, `76` pip wheels verified on active runtime) |
| `ruff check backend/src/ankora_backend backend/tests/test_v02_m5*.py` | `All checks passed!` |
| `mypy --config-file backend/pyproject.toml --strict` (all 10 `M5` modules) | `Success: no issues found in 10 source files` |
| `adapters/engines/vina.py` frozen byte check | `7,120` bytes, SHA-256 `e13e32f5b6c401966debe80fe0049f4ae87f1cc3c8eb31f4566c57c1acc50993` |
| `pytest -p no:cacheprovider -rs backend/tests/test_v02_*.py` (live Linux `Vina 1.2.7`, `AutoGrid4/AD4 4.2.6`, `AutoDock-GPU 1.6 CUDA`, `GNINA 1.3.3`, `Meeko 0.7.1`, `PoseBusters 0.6.5`, `ProLIF 2.2.1`) | **`412 passed, 0 skipped`** (`64.41s`) |
| Desktop Linux Node `v24.19.0` (`npx tsc -b`, `npx vitest run`, `npx vite build`) | `tsc -b` 0 errors; **`48/48` test files, `393/393` tests passed**; Vite build succeeded (`7.22s`) |

---

## 5. Residual Scope & Next Milestone

- **Bare-Metal Linux Acceptance:** Final Linux release acceptance remains gated on a native Linux workstation (`ADR-029` Gate `D6`).
- **Deferred to `v0.3+`:** Multi-structure receptor ensemble docking (`apo`/`holo`) remains explicitly out of scope for `v0.2`.
- **Next Authorized Milestone:** **`M6`** — Preregistered external comparison benchmark vs `DockM8` (`ADR-031`), `Export v5` bundle packaging `M1`–`M5` provenance, and bare-metal Linux workstation acceptance (`Gate D6`).
