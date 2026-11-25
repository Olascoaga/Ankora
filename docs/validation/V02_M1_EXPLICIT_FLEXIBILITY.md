# Ankora v0.2 `M1` Explicit Ligand & Receptor Side-Chain Flexibility — Dual-OS Engineering Verification

- **Date:** 2026-11-19
- **Branch:** `codex/v0.2-dev` (isolated from `main` and frozen tag `v0.1.0-beta.2` at `36f1c0e`)
- **Governance:** `ADR-030` (v0.2 Roadmap & Quality Contract), `ADR-031` (Explicit-First Scientific Architecture), `ADR-032` & Addendum `A1`–`A6` (Explicit Ligand & Bounded Receptor Side-Chain Flexibility)
- **Prerequisite Gate:** [`V02_M1_FLEXIBILITY_GATE0_PROBE.md`](V02_M1_FLEXIBILITY_GATE0_PROBE.md)
- **Scope Boundary:** Software engineering, cross-OS scientific-tool integration, contract, UI, and provenance verification on labelled synthetic fixtures and single-peptide/model complexes. This record does **not** alter or extend the frozen `v0.1` scientific benchmark claims in [`VALIDATION_STATUS.md`](VALIDATION_STATUS.md) or the frozen `LIT_PCBA_ANKORA_VS_V1` manifests.

---

## 1. Delivered `M1` Capabilities

| Sub-Milestone | Scope | Key Modules |
| --- | --- | --- |
| **`M0`** | Frozen Pydantic v2 contracts & warning taxonomy (`ADR-030`–`ADR-032`) | `schemas/flexibility.py`, `schemas/docking.py`, `schemas/receptors.py`, `schemas/ligands.py` |
| **`M1 Gate 0`** | Live cross-OS CLI/format probe across Meeko `0.7.1`, Vina `1.2.7`, AutoGrid4 `4.2.6`, AutoDock4 `4.2.6`, AutoDock-GPU `1.6`, GNINA `1.3.3` | `docs/validation/V02_M1_FLEXIBILITY_GATE0_PROBE.md`, `ADR-032` Addendum `A1`–`A6` |
| **`M1a`** | Explicit semi-flexible ligand control (`macrocycle_policy`, `flexible_amides`, SMARTS bond rigidification with `LIG_RIGIDIFY_SMARTS_NO_MATCH` detection, `effective_torsdof`, Meeko macrocycle `CG0`/`G0` AutoDock4 atom-type guard) | `adapters/chemistry/meeko.py`, `services/ligand_preparation.py`, `services/ligand_library_preparation.py` |
| **`M1b`** | Bounded receptor side-chain split (`mk_prepare_receptor -f`), immutable `PDBQT_RIGID` + `PDBQT_FLEX` outputs, hard rejection of `GLY`/`ALA`/`PRO`/`CYX` & duplicate residues, `DOCKING_FLEXRES_DOF_HIGH` (>4 residues or >12 added chi torsions), `AutoGrid4` `E7` union atom-type guard | `adapters/chemistry/meeko_receptor.py`, `services/receptor_preparation.py`, `services/autogrid.py` |
| **`M1c-1`** | Deterministic `E8` coupled `PoseComplex` materialization (`PoseComplexIdentity`), Windows Vina NUL-line sanitization, coupled `MODEL`/`BEGIN_RES` splitting, GNINA 0-based ordinal pairing + Meeko-template re-injection | `adapters/chemistry/flex_pose_complex.py` |
| **`M1c-2`** | `AutoDock Vina 1.2.7` (`--flex`, `--scoring vinardo`, create-only `--local_only` derivative with authoritative stdout breakdown) + coupled `E8` `PoseInteractionService` | `adapters/engines/vina_v02.py`, `services/vina_docking.py`, `services/pose_interactions.py` |
| **`M1c-3`** | `AutoDock4 4.2.6` CPU (`flexres`) + `AutoDock-GPU 1.6` (`--flexres`) + `E7` map-union enforcement + coupled `E8` pose storage & `PoseInteractionService` | `adapters/engines/autodock4.py`, `adapters/engines/autodock_gpu.py`, `services/autodock4_docking.py`, `services/autodock_gpu_docking.py` |
| **`M1c-4`** | Linux `GNINA 1.3.3` `FlexRes` (`--flex` + `--out_flex .pdb` guard refusing `.pdbqt` + ordinal pairing + Meeko re-injection + create-only `--local_only`), 7 `/flex` + Vina/GNINA refinement API routes, `MethodsReportService` & `CampaignExportService` (v4-compatible) | `adapters/engines/gnina.py`, `services/gnina_docking.py`, `api/routes.py`, `services/methods_report.py`, `services/campaign_export.py` |
| **`M1d`** | Desktop React/TypeScript/Mol* UI: explicit ligand flexibility panel, receptor `FlexRes` picker + DOF badge, Vina `Vinardo` / `ActiveFlexResBanner` engine disclosures, coupled `PoseComplex` default view + translucent crystal-rotamer overlay toggle, create-only `--local_only` derivative trigger | `apps/desktop/src/features/ligand/LigandFlexibilityControls.tsx`, `apps/desktop/src/features/receptor/flexResidues.ts`, `apps/desktop/src/features/docking/ActiveFlexResBanner.tsx`, `apps/desktop/src/features/results/PoseInteractionPanel.tsx`, `apps/desktop/src/viewer/molstarAdapter.ts` |

---

## 2. Notable Empirical Findings & Integrity Safeguards

1. **Frozen `v0.1` `LIT_PCBA_ANKORA_VS_V1` Vina Parser Preservation:**
   - The frozen `v0.1` screening benchmark manifests (`LIT_PCBA_ANKORA_VS_V1.vina-primary-plan.json` and `LIT_PCBA_ANKORA_VS_V1.vina-executor-readiness.json`) cryptographically hash-pin `backend/src/ankora_backend/adapters/engines/vina.py` (`7,120` bytes, SHA-256 `e13e32f5b6c401966debe80fe0049f4ae87f1cc3c8eb31f4566c57c1acc50993`).
   - All `v0.2` Vina extensions (`--flex`, `--scoring vinardo`, `--local_only`, stdout energy parsing) were isolated in `backend/src/ankora_backend/adapters/engines/vina_v02.py`, keeping `adapters/engines/vina.py` byte-identical to `v0.1.0-beta.2` (`36f1c0e`) so historical benchmark verification passes with zero relaxed assertions.
2. **Live `GNINA 1.3.3` `--local_only` Echoed Score-REMARK Discovery:**
   - During live Linux `GNINA 1.3.3` CPU testing (`test_v02_m1c_gnina_flex_and_methods.py`), invoking `gnina --local_only --ligand <parent_pose.pdbqt>` echoed prior `REMARK minimizedAffinity / CNNscore / CNNaffinity` headers from the parent pose verbatim into `--out`, producing duplicate score REMARK records rejected by strict parsing (`GNINA_OUTPUT_INVALID`).
   - Fixed in `services/gnina_docking.py:refine_pose_local_only` by stripping `MODEL`/`ENDMDL` and stale parent GNINA score `REMARK` headers solely on the ephemeral staging copy while preserving the parent pose artifact bytes immutably.
3. **Export v4 & v0.1 Rigid Compatibility:**
   - For rigid `v0.1` campaigns, `MethodsReportService` prose, Export v4 CSV column headers, and `input_identity_sha256` remain unchanged. Optional `sidechain_flex` provenance fields and `inputs/receptor_flex.pdbqt` / `raw/raw_flex.pdb` / `poses/*_flex.pdbqt` bundle entries are emitted strictly for `sidechain_flex` runs.

---

## 3. Dual-OS Verification Matrix

### 3.1 Windows 11 x64 (RTX 5050 Laptop GPU)

| Check | Result |
| --- | --- |
| `scripts/check_public_paths.py`, `check_platform_docs.py`, `check_public_validation_status.py` | Passed |
| `ruff check backend/src/ankora_backend backend/tests/test_v02_*.py` | `All checks passed!` |
| `mypy --config-file backend/pyproject.toml --strict backend/src/ankora_backend` | `Success: no issues found in 161 source files` |
| `adapters/engines/vina.py` frozen byte check | `7,120` bytes, SHA-256 `e13e32f5b6c401966debe80fe0049f4ae87f1cc3c8eb31f4566c57c1acc50993` |
| `pytest backend/tests/test_v02_*.py` (live Windows `Meeko 0.7.1`, `vina.exe 1.2.7`, `autogrid4.exe 4.2.6`, `autodock4.exe 4.2.6`, `AutoDock-GPU.exe 1.6` CUDA) | `348 passed, 1 skipped` (Linux-only live GNINA test skipped on Windows; synthetic GNINA/API/Methods/Export tests passed) |
| Full Windows backend suite (`pytest backend/tests --ignore=backend/tests/test_gpu_payload_builder.py` + `test_gnina_screening_api.py`) | Passed (including all frozen `LIT_PCBA_ANKORA_VS_V1` manifests & `test_third_party_notices.py`) |
| Desktop (`npm --workspace @ankora/desktop run typecheck`, `test`, `build:web`) | `tsc -b` 0 errors; `44/44` test files, `380/380` tests passed (including `FlexUiM1d.test.tsx`); Vite production bundle built cleanly |
| Tauri Rust (`apps/desktop/src-tauri`: `cargo fmt --check`, `cargo test`) | Passed (`3/3` Rust unit tests) |

### 3.2 Linux x86_64 (WSL2 Ubuntu 24.04, CUDA 12.8, GNINA 1.3.3)

| Check | Result |
| --- | --- |
| `scripts/check_public_paths.py`, `check_platform_docs.py`, `check_public_validation_status.py` | Passed |
| `ruff check backend/src/ankora_backend backend/tests/test_v02_*.py` | `All checks passed!` |
| `mypy --config-file backend/pyproject.toml --strict backend/src/ankora_backend` | `Success: no issues found in 161 source files` |
| `pytest -q backend/tests/test_v02_*.py` (live Linux `Meeko 0.7.1`, `Vina 1.2.7`, `AutoGrid4 4.2.6`, `AutoDock4 4.2.6`, `AutoDock-GPU 1.6 CUDA`, and `GNINA 1.3.3` CPU FlexRes + `--local_only`, binary SHA-256 `3340c1f49cd3c7c84d8699182a1c6af13c7fa2a22448d1204640446106f72172`) | **`349 passed, 0 skipped`** |
| `pytest backend/tests/test_autodock_gpu_docking.py test_screening_benchmark_vina_plan.py test_screening_benchmark_protocol.py` | `47/47` passed (`vina.py` frozen hash & OpenAPI paths verified; sole pre-existing Linux-only failure is the documented `v0.1` `1 ULP` glibc vs Windows UCRT `math.exp` BEDROC float-equality check in `test_primary_vina_metrics_reproduce_from_the_closed_campaign`) |
| Desktop Linux Node `v24.19.0` (`npm run typecheck`, `npm test`, `npm run build:web`) | `tsc -b` 0 errors; `44/44` test files, `380/380` tests passed; Vite build passed |
| Tauri Rust Linux (`apps/desktop/src-tauri`: `cargo fmt --check`, `cargo test`) | Passed (`5/5` Rust unit tests including POSIX child termination) |

---

## 4. Residual Scope & Next Milestone

- **Bare-Metal Linux Acceptance:** Final Linux release acceptance remains gated on a native Linux workstation (`ADR-029` Gate `D6`).
- **Deferred to `v0.3+`:** Multi-structure receptor ensemble docking (`apo`/`holo`) remains explicitly out of scope for `v0.2`.
- **Next Authorized Milestone:** **`M2`** — Out-of-Sample Protocol Calibration & Rescoring (`BEDROC20`, parent + Bemis-Murcko scaffold split, `1-SE` parsimony rule, `--score_only` cross-scoring).
