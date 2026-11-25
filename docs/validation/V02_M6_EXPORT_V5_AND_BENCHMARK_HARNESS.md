# Ankora v0.2 `M6` `Export v5`, `ADR-031` Installer-Size CI Guard & External Two-Axis Benchmark Harness — Dual-OS Engineering Verification

- **Date:** 2026-11-20
- **Branch:** `codex/v0.2-dev` (isolated from `main` and frozen tag `v0.1.0-beta.2` at `36f1c0e`)
- **Governance:** [`ADR-030`](../architecture/ADR/ADR-030-rank-space-consensus-prioritization.md), [`ADR-031`](../architecture/ADR/ADR-031-external-benchmark-boundary.md) (Hard Benchmark Separation, Mandatory Two-Axis Evaluation, Out-of-Sample Discipline & CI Installer-Size Budget Guard), [`ADR-032`](../architecture/ADR/ADR-032-explicit-flexibility-and-pose-complex-identity.md)
- **Preceding Records:** [`V02_M5_PCQ_CONSENSUS.md`](V02_M5_PCQ_CONSENSUS.md), [`V02_EXTERNAL_BENCHMARK_PROTOCOL.md`](V02_EXTERNAL_BENCHMARK_PROTOCOL.md)
- **Scope Boundary:** Software engineering, `Export v5` full `M1`–`M5` provenance packaging and `Export v4` backward compatibility, zero-dependency `scripts/verify_export_bundle.py` (`v2`–`v5` under `python -S`), CI installer-size and hard separation guard (`scripts/check_v02_installer_budget.py` wired into `.github/workflows/ci.yml`), strictly external two-axis comparison harness (`benchmarks/external_comparison/`), and Desktop `Export v5` UI verification on labelled synthetic fixtures. This record does **not** alter or extend the frozen `v0.1` scientific benchmark claims in [`VALIDATION_STATUS.md`](VALIDATION_STATUS.md), does **not** record live empirical `DockM8` results yet, and does **not** replace bare-metal Linux workstation sign-off (`ADR-029` Gate `D6`).

---

## 1. Installer-Size Budget & Hard Architectural Separation (`ADR-031 §1 & §4`)

| Metric | Recorded Measurement | Budget / Policy |
| --- | --- | --- |
| New Python packages / wheels in `M6` | **`0`** | `0` bytes declared for `M6` in [`environment/v02-installer-size-budget.json`](../../environment/v02-installer-size-budget.json) |
| Cumulative `M0`–`M6` measured wheel delta | **`567,794` B (`554.49 KiB`)** (`posebusters==0.6.5` MIT pure-Python wheel in `M3`) | `<= 1,048,576` B (`1.00 MiB`) cap enforced by `scripts/check_v02_installer_budget.py` |
| Backend Python AST + lockfile separation audit | **`184` modules audited, `0` forbidden imports/packages** | Zero `dockm8`, `docker`, `podman`, `streamlit`, `torch`, `dgl`, `benchmarks` coupling in `backend/src/` or `requirements/` |
| Environment locks (Windows & Linux) | Windows: `36` Conda, `75` Python, `7` packaging; Linux: `45` Conda, `76` pip (active runtime verified) | Unchanged from `M3` |

---

## 2. Delivered `M6` Capabilities

| Sub-Milestone | Scope | Key Modules |
| --- | --- | --- |
| **`M6a`** | **`Export v5` full `M1`–`M5` provenance & zero-dependency verifier:** extended `RecordedEvidence` / `collect_v02_recorded_evidence` in `campaign_export.py` so legacy rigid `v0.1` campaigns stay byte-compatible at `ankora_export_format: 4` while campaigns carrying `sidechain_flex`, `M3` `PoseQualityRecord`, or `M4` `InteractionRuleEvaluationRecord`/`InteractionRuleSetRecord` auto-upgrade to `ankora_export_format: 5` with `v02_provenance`; added `ConsensusExportService` (`POST /api/v1/consensus/runs/{consensus_id}/export`) emitting two-tier `E6` `results.csv` (`row: "consensus_parent"`), `methods.md` (`10.1038/s41598-019-41594-3`), verbatim SHA-256-verified copies of `consensus`, `consensus_panels`, optional `calibrations` (+ `split.json`/`selection.json`/`confirmation.json`), and attached `M3`/`M4` evidence; integrated `ExportKind.CONSENSUS` & `ankora_export_format` into `ExportCatalogService`; upgraded stdlib-only `scripts/verify_export_bundle.py` (`v2`–`v5`) with `E6` anti-imputation and `v0.2` blob SHA-256 verification under `python -S` | `schemas/exports.py`, `services/campaign_export.py`, `services/consensus_export.py`, `services/export_catalog.py`, `api/routes.py`, `scripts/verify_export_bundle.py`, `tests/test_v02_m6a_export_v5.py` |
| **`M6b`** | **`ADR-031` CI budget guard & strictly external two-axis benchmark harness:** added stdlib-only `scripts/check_v02_installer_budget.py` (manifest reconciliation, AST + lockfile forbidden-dependency scan, fail-closed packaged installer byte check) wired into both Windows `verify` and Ubuntu `verify-linux` jobs in `.github/workflows/ci.yml`; created strictly external, zero-product-import `benchmarks/external_comparison/` (`protocol_manifest.py` rejecting `"latest"` unpinned versions and requiring both `"controlled"` + `"end_to_end"` axes; `evaluate_comparison.py` consuming Ankora exclusively through verified `Export v4`/`v5` bundles, enforcing mandatory two-axis admissibility, tie-aware `BEDROC_20` / `EF_1%` / `ROC-AUC` / `PR-AUC`, denominator-invariant active/inactive failure census, `PoseBusters` physical-validity stratification, paired parent-compound bootstrap `95% CI`, verbatim `"Insufficient evidence to prefer over baseline"` null verdict, and unbiased publication of negative outcomes); preregistered protocol recorded in [`V02_EXTERNAL_BENCHMARK_PROTOCOL.md`](V02_EXTERNAL_BENCHMARK_PROTOCOL.md) | `scripts/check_v02_installer_budget.py`, `.github/workflows/ci.yml`, `benchmarks/external_comparison/{README.md,protocol_manifest.py,evaluate_comparison.py}`, `docs/validation/V02_EXTERNAL_BENCHMARK_PROTOCOL.md`, `tests/test_v02_m6b_external_benchmark_and_budget.py` |
| **`M6c`** | **Desktop `Export v5` UI:** added opt-in `Export v5 bundle` trigger inside `ConsensusWorkspace.tsx` surfacing verified `input_identity_sha256`, `bundle_identity_sha256`, and direct download links (`_bundle.zip`, `results.csv`, `manifest.json`, `methods.md`); added `Consensus bundles` filter and `Export v5` format badge to `ExportWorkspace.tsx` without altering existing `Campaign bundle` behavior; verified via `ExportV5M6.test.tsx` | `apps/desktop/src/types/api.ts`, `apps/desktop/src/api/client.ts`, `apps/desktop/src/features/results/ConsensusWorkspace.tsx`, `apps/desktop/src/features/export/ExportWorkspace.tsx`, `apps/desktop/src/tests/ExportV5M6.test.tsx` |

---

## 3. Dual-OS Verification Matrix (`codex/v0.2-dev` @ `d5ed401`)

### 3.1 Windows 11 x64 (`RTX 5050` Laptop GPU)

| Check | Result |
| --- | --- |
| `check_public_paths.py`, `check_public_validation_status.py`, `python -S scripts/check_v02_installer_budget.py`, `verify_linux_environment_lock.py`, `verify_windows_environment_lock.py` | Passed (`184` backend Python modules audited, `0` forbidden hits; Windows `36` Conda / `75` Python / `7` packaging; Linux `45` Conda / `76` pip) |
| `ruff check` & `mypy --strict` (all 9 `M6` backend/script/harness modules) | `All checks passed!`; `Success: no issues found in 9 source files` |
| `adapters/engines/vina.py` frozen byte check | `7,120` bytes, SHA-256 `e13e32f5b6c401966debe80fe0049f4ae87f1cc3c8eb31f4566c57c1acc50993` |
| Combined Windows `test_v02_*.py` (`M0`–`M6`) + `test_verify_export_bundle.py` + `test_campaign_export.py` + `test_export_catalog.py` + `test_autodock_gpu_docking.py` + `test_methods_report.py` + `test_pose_interactions.py` + `test_screening_benchmark_protocol.py` + `test_screening_benchmark_vina_plan.py` + `test_third_party_notices.py` | **`554 passed, 1 skipped`** (`142.08s`; sole skip is the Linux-only live `GNINA` test) |
| Desktop (`npx tsc -b`, `npx vitest run`, `npx vite build`) | `tsc -b` 0 errors; **`49/49` test files, `395/395` tests passed** (including `ExportV5M6.test.tsx` and untouched `ExportWorkspace.test.tsx`); Vite production bundle built cleanly (`9.43s`) |

### 3.2 Linux x86\_64 (WSL2 Ubuntu 24.04, CUDA 12.8, GNINA 1.3.3)

| Check | Result |
| --- | --- |
| `check_platform_docs.py`, `check_public_paths.py`, `check_public_validation_status.py`, `python -S scripts/check_v02_installer_budget.py`, `verify_linux_environment_lock.py --runtime` | Passed (`45` Conda artifacts, `76` pip wheels verified on active runtime; `184` backend modules audited) |
| `ruff check` & `mypy --strict` (all 9 `M6` modules) | `All checks passed!`; `Success: no issues found in 9 source files` |
| `adapters/engines/vina.py` frozen byte check | `7,120` bytes, SHA-256 `e13e32f5b6c401966debe80fe0049f4ae87f1cc3c8eb31f4566c57c1acc50993` |
| `pytest -p no:cacheprovider -rs backend/tests/test_v02_*.py backend/tests/test_verify_export_bundle.py backend/tests/test_export_catalog.py` (live Linux `Vina`, `AutoGrid4/AD4`, `AutoDock-GPU CUDA`, `GNINA 1.3.3`, `Meeko`, `PoseBusters`, `ProLIF`, `Export v5`, `python -S` verifier & external harness) | **`433 passed, 0 skipped`** (`77.44s`) |
| Desktop Linux Node `v24.19.0` (`npx tsc -b`, `npx vitest run`, `npx vite build`) | `tsc -b` 0 errors; **`49/49` test files, `395/395` tests passed**; Vite build succeeded (`6.96s`) |

---

## 4. Residual Gates Before `v0.2.0` Public Release

1. **Bare-Metal Linux Workstation Acceptance (`ADR-029` Gate `D6`):** Requires running `scripts/smoke_linux_package.py` on a physical Linux workstation with native NVIDIA driver and native X11/Wayland session (`LINUX_NATIVE_WORKSTATION_PROTOCOL.md`).
2. **Live External Benchmark Execution (`V02_EXTERNAL_BENCHMARK_PROTOCOL.md`):** Running pinned `DockM8` alongside Ankora `v0.2` on public targets over both Axis A (`controlled`) and Axis B (`end_to_end`) and archiving the sealed JSON/Markdown verdict (positive, null, or negative).
3. **Packaged `v0.2` Installer Builds & Byte Attestation:** Running `scripts/check_v02_installer_budget.py` against freshly built Windows `.exe`, Linux `.deb`, and Linux `.tar.zst` installers once `v0.2` release packaging is authorized.
4. **Conditional `M7` (`OpenMM` offline parameterization spike):** Remains explicitly separate from the `v0.2` critical path and gated behind a zero-network ligand parameterization spike on both Windows and Linux.
