# Ankora v0.2 `M6.5` Hit-to-Analog Structural Similarity Expansion, Pose-Focused Mini-Library Screening & `Export v6` — Dual-OS Engineering Verification

- **Date:** 2026-11-21
- **Branch:** `codex/v0.2-dev` (isolated from `main` and frozen tag `v0.1.0-beta.2` at `36f1c0e`)
- **Governance:** [`ADR-033`](../architecture/ADR/ADR-033-hit-to-analog-expansion-and-pose-focused-screening.md) (Hit-to-Analog Structural Similarity Expansion & Pose-Focused Mini-Library Virtual Screening), [`ADR-030`](../architecture/ADR/ADR-030-rank-space-consensus-prioritization.md) (`E1` panel-reuse hardening), [`ADR-031`](../architecture/ADR/ADR-031-external-benchmark-boundary.md) (`0`-byte installer-size budget guard), [`ADR-032`](../architecture/ADR/ADR-032-explicit-flexibility-and-pose-complex-identity.md) (`FlexRes` full-atom containment & coupled `PoseComplexIdentity`)
- **Preceding Record:** [`V02_M6_EXPORT_V5_AND_BENCHMARK_HARNESS.md`](V02_M6_EXPORT_V5_AND_BENCHMARK_HARNESS.md)
- **Scope Boundary:** Software engineering, `0`-dependency local RDKit Morgan similarity search and SQLite fingerprint caching, Gate 0 live empirical probe and opt-in PubChem PUG-REST / ChEMBL REST connectors behind a cryptographic IP disclosure consent gate (`consent_payload_sha256`), immutable `BindingSiteSource.POSE_FOCUSED` derivation with full-atom `FlexRes` interior containment and `ADR-018` volume warnings, receptor-frame in-place `MCS core RMSD` (`superposition_applied=false`), prerequisite `E1` consensus panel-reuse hardening (`k_max` + `executable_sha256s` + small/congeneric panel warning), derived `LigandSource.ANALOG_EXPANSION` mini-libraries with mandatory `seed_control`, acyclic stale-DAG lineage, `MethodsReport`, additive `Export v6` (preserving `Export v2`–`v5` byte compatibility) verified under `python -S`, and opt-in Desktop UI verification on labelled synthetic fixtures. This record does **not** alter or extend the frozen `v0.1` scientific benchmark claims in [`VALIDATION_STATUS.md`](VALIDATION_STATUS.md), does **not** establish prospective SAR enrichment, and does **not** replace bare-metal Linux workstation sign-off (`ADR-029` Gate `D6`).

---

## 1. Installer-Size Budget & Zero-Dependency Audit (`ADR-031` & `ADR-033`)

| Metric | Recorded Measurement | Budget / Policy |
| --- | --- | --- |
| New Python packages / wheels in `M6.5` | **`0`** | `0` bytes declared for `M6.5` in [`environment/v02-installer-size-budget.json`](../../environment/v02-installer-size-budget.json) |
| Cumulative `M0`–`M6.5` measured wheel delta | **`567,794` B (`554.49 KiB`)** (`posebusters==0.6.5` MIT pure-Python wheel in `M3`) | `<= 1,048,576` B (`1.00 MiB`) cap enforced by `scripts/check_v02_installer_budget.py` |
| Backend Python AST + lockfile separation audit | **`191` modules audited, `0` forbidden imports/packages** | Zero external harness/container/cloud-docking coupling in `backend/src/` or `requirements/` |
| Environment locks (Windows & Linux) | Windows: `36` Conda, `75` Python, `7` packaging; Linux: `45` Conda, `76` pip (active runtime verified) | Unchanged from `M3` |
| Frozen `v0.1` `adapters/engines/vina.py` | **`7,120` B**, SHA-256 `e13e32f5b6c401966debe80fe0049f4ae87f1cc3c8eb31f4566c57c1acc50993` | Byte-identical across Windows and Linux |

---

## 2. Gate 0 Live External Provider Schema Findings (`M6.5d`)

Before coding the opt-in Phase 2 connectors (`adapters/external/analog_providers.py`), live HTTP probes against PubChem PUG-REST and ChEMBL REST documented two upstream response contracts that would otherwise have caused silent parsing or chemical-integrity defects:

1. **PubChem PUG-REST modern property schema:** `POST /rest/pug/compound/fastsimilarity_2d/smiles/property/SMILES,ConnectivitySMILES,Title/JSON` returns `"SMILES"` and `"ConnectivitySMILES"` (not legacy `"CanonicalSMILES"`/`"IsomericSMILES"`). The adapter validates both modern keys and explicitly retains stereo-preserving SMILES.
2. **ChEMBL REST salt retention & string similarity:** `GET /chembl/api/data/similarity/{encoded}/{threshold}.json` searches on parent structures while returning full salt `canonical_smiles` (e.g., `CHEMBL2296002` with string `"similarity": "100"` and `had_multiple_fragments=True`). Ankora therefore **never** trusts provider similarity as local similarity: `provider_similarity` is kept strictly separate from mandatory local RDKit `MorganGenerator(radius=2, fpSize=2048, includeChirality=True)` `local_rdkit_tanimoto`, raw HTTP responses are archived verbatim, and multi-fragment records are flagged for downstream `ADR-016` preparation review.

---

## 3. Delivered `M6.5` Capabilities (`codex/v0.2-dev` `103381e..baceb19`)

| Sub-Milestone | Commit | Scope | Key Modules |
| --- | --- | --- | --- |
| **`M6.5a`** | `103381e` | **Governance (`ADR-033`), `M6.5` `0`-byte budget & `E1` panel-reuse hardening:** authored `ADR-033`, registered `M6.5` (`0` B) in `v02-installer-size-budget.json`, added 5 `WarningCode`s and 3 `DependencyNodeKind`s (`ANALOG_CATALOG`, `ANALOG_SEARCH`, `ANALOG_SELECTION`), enforced `k_max` + `executable_sha256s` in `PoseConsensusService._verify_reused_panel_context`, recorded `frozen_panel_parent_count` vs `scored_target_parent_count`, and added `CONSENSUS_SMALL_OR_CONGENERIC_PANEL` (`< 50` parents or monoscaffold) | `docs/architecture/ADR/ADR-033-*.md`, `environment/v02-installer-size-budget.json`, `scripts/check_v02_installer_budget.py`, `schemas/{warnings,projects}.py`, `adapters/consensus/pcq_math.py`, `services/pose_consensus.py`, `tests/test_v02_m65a_e1_guard_and_contracts.py` |
| **`M6.5b`** | `7c106de` | **Immutable `BindingSiteSource.POSE_FOCUSED` + full-atom `FlexRes` containment:** added `BindingSiteSource.POSE_FOCUSED`, `PoseFocusedOrigin`, and `PoseFocusedEvidence`; extracted heavy atoms from docked pose PDBQT (excluding H and Meeko macrocycle glue pseudoatoms `G0..G9`/`CG0..CG9`), derived deterministic padded boxes with optional `box_override`, enforced full-atom `FlexRes` interior-margin containment failing closed (`422 BINDING_SITE_FLEXRES_OUTSIDE_BOX`), preserved `ADR-018` `27,000 Å³` warnings, and blocked stale source artifacts (`409`) | `schemas/binding_sites.py`, `services/binding_site_definition.py`, `services/project_dependencies.py`, `api/routes.py`, `tests/test_v02_m65b_pose_focused_site.py` |
| **`M6.5c`** | `1406d99` | **100% offline RDKit analog search, SQLite FP cache & in-place `MCS core RMSD`:** implemented bounded SDF/SMI/CSV catalog ingestion, stereochemistry-preserving dedup, ephemeral search-only largest-fragment salt stripping, `MorganGenerator(r=2, 2048, includeChirality=True)` Tanimoto + graph-verified SMARTS filtering, deterministic tie-breaking, `SqliteFingerprintCache`, create-only `AnalogExpansionArtifactStore`, and receptor-frame in-place heavy-atom `MCS core RMSD` (`superposition_applied=False`, bounded timeout disclosure), verified with `socket.socket` monkeypatch-blocked | `schemas/analog_expansion.py`, `adapters/chemistry/analog_similarity.py`, `adapters/chemistry/mcs_core_rmsd.py`, `persistence/analog_expansion_store.py`, `tests/test_v02_m65c_offline_similarity_and_mcs_rmsd.py` |
| **`M6.5d`** | `0fe770c` | **Opt-in PubChem PUG-REST & ChEMBL REST connectors behind IP consent gate:** enforced hard cryptographic `consent_payload_sha256` verification before HTTP client creation, `1` concurrent request, `<= 1 req/s`, `<= 500` candidates, `<= 10 MiB`, `<= 2` retries honoring `Retry-After`, verbatim raw response archiving, and mandatory local RDKit recalculation | `adapters/external/{__init__,analog_providers}.py`, `tests/test_v02_m65d_online_providers_and_ip_gate.py` |
| **`M6.5e`** | `fca070b` | **`AnalogExpansionService`, derived mini-library, acyclic DAG, REST API, `MethodsReport` & `Export v6`:** added `LigandSource.ANALOG_EXPANSION`, mandatory `seed_control` injection into standard immutable `LigandLibraryRecord` (`ADR-016`), Meeko glue-atom stripping in `mcs_core_rmsd.py`, acyclic upstream-only DAG tracking, `/api/v1/analog-expansion/*` endpoints, `render_analog_expansion_methods`, additive `Export v6` in `campaign_export.py` & `consensus_export.py` (preserving `Export v2`–`v5` untouched), and upgraded zero-dependency `scripts/verify_export_bundle.py` (`v2`–`v6`) verified under `python -S` | `schemas/ligands.py`, `services/{ligand_import,analog_expansion,project_dependencies,methods_report,campaign_export,consensus_export}.py`, `api/routes.py`, `scripts/verify_export_bundle.py`, `tests/test_v02_m65e_service_api_dag_export.py` |
| **`M6.5f`** | `baceb19` | **Opt-in Desktop UI & `Export v6` badge:** added `AnalogExpansionPanel.tsx` (Offline local catalog/project-library snapshot vs Opt-in PubChem/ChEMBL with IP consent preview & mandatory checkbox, curation table with separate local RDKit vs provider Tanimoto and mandatory `seed_control`, `POSE_FOCUSED` preview & save), opt-in triggers inside `PoseInteractionPanel.tsx` and `ConsensusWorkspace.tsx` (`MedoidDrawer`), `pose_focused` support in `BindingSiteWorkspace.tsx`, `Export v6` badge in `ExportWorkspace.tsx`, and `AnalogExpansionM65.test.tsx` | `apps/desktop/src/types/api.ts`, `apps/desktop/src/api/client.ts`, `apps/desktop/src/features/expansion/AnalogExpansionPanel.tsx`, `apps/desktop/src/features/binding-site/BindingSiteWorkspace.tsx`, `apps/desktop/src/features/results/{PoseInteractionPanel,ConsensusWorkspace}.tsx`, `apps/desktop/src/features/export/ExportWorkspace.tsx`, `apps/desktop/src/styles.css`, `apps/desktop/src/tests/AnalogExpansionM65.test.tsx` |

---

## 4. Dual-OS Verification Matrix (`codex/v0.2-dev` @ `baceb19`)

### 4.1 Windows 11 x64 (`RTX 5050` Laptop GPU, locked `.venv`)

| Check | Result |
| --- | --- |
| `check_platform_docs.py`, `check_public_paths.py`, `check_public_validation_status.py`, `python -S scripts/check_v02_installer_budget.py`, `verify_linux_environment_lock.py`, `verify_windows_environment_lock.py` | Passed (`191` backend Python modules audited, `0` forbidden hits; `M6.5` `0` B delta; Windows `36` Conda / `75` Python / `7` packaging; Linux `45` Conda / `76` pip) |
| `ruff check` (22 `M6.5` backend/script modules + 5 `test_v02_m65*.py` suites) & `mypy --strict` (17 `M6.5` modules) | `All checks passed!`; `Success: no issues found in 17 source files` |
| `adapters/engines/vina.py` frozen byte check | `7,120` bytes, SHA-256 `e13e32f5b6c401966debe80fe0049f4ae87f1cc3c8eb31f4566c57c1acc50993` |
| Combined locked `.venv` `pytest` (`test_v02_*.py` `M0`–`M6.5` + `test_binding_site_definition.py` + `test_verify_export_bundle.py` + `test_campaign_export.py` + `test_export_catalog.py` + `test_autodock_gpu_docking.py` + `test_methods_report.py` + `test_pose_interactions.py` + `test_screening_benchmark_protocol.py` + `test_screening_benchmark_vina_plan.py` + `test_third_party_notices.py`) | **`583 passed, 1 skipped`** (`110.63s`; sole skip is Linux-only live `GNINA 1.3.3`) |
| Desktop (`npx tsc -b --noEmit`, `npx vitest run`, `npm run build:web`) | `tsc -b` 0 errors; **`50/50` test files, `398/398` tests passed** (including `AnalogExpansionM65.test.tsx`); Vite production build cleanly (`9.60s`, `1815` modules) |

### 4.2 Linux x86\_64 (WSL2 Ubuntu 24.04, CUDA 12.8, live `GNINA 1.3.3` `SHA-256 3340c1f4...`)

| Check | Result |
| --- | --- |
| `check_platform_docs.py`, `check_public_paths.py`, `check_public_validation_status.py`, `python -S scripts/check_v02_installer_budget.py`, `verify_linux_environment_lock.py --runtime` | Passed (`45` Conda artifacts, `76` pip wheels verified on active runtime; `191` backend modules audited) |
| `ruff check` & `mypy --config-file backend/pyproject.toml --strict` (17 `M6.5` modules) | `All checks passed!`; `Success: no issues found in 17 source files` |
| `adapters/engines/vina.py` frozen byte check | `7,120` bytes, SHA-256 `e13e32f5b6c401966debe80fe0049f4ae87f1cc3c8eb31f4566c57c1acc50993` |
| `pytest -p no:cacheprovider -rs backend/tests/test_v02_*.py backend/tests/test_binding_site_definition.py backend/tests/test_verify_export_bundle.py backend/tests/test_campaign_export.py backend/tests/test_export_catalog.py` (with live `GNINA 1.3.3 CUDA`, `Vina 1.2.7`, `AutoGrid4/AD4 4.2.6`, `AutoDock-GPU 1.6`, `Meeko 0.7.1`, `PoseBusters 0.6.5`, `ProLIF 2.2.1`, `RDKit 2025.9.6`, `Export v6` & `python -S` verifier) | **`484 passed, 0 skipped`** (`56.58s`) |
| Desktop Linux Node `v24.19.0` (`npx tsc -b --noEmit`, `npx vitest run`, `npm run build:web`) | `tsc -b` 0 errors; **`50/50` test files, `398/398` tests passed** (`12.49s`); Vite production build cleanly (`8.17s`, `1815` modules) |

---

## 5. Residual Gates Before `v0.2.0` Public Release

1. **Bare-Metal Linux Workstation Acceptance (`ADR-029` Gate `D6`):** Requires running `scripts/smoke_linux_package.py` on a physical Linux workstation with native NVIDIA driver and native X11/Wayland session (`LINUX_NATIVE_WORKSTATION_PROTOCOL.md`).
2. **Live External Benchmark Execution (`V02_EXTERNAL_BENCHMARK_PROTOCOL.md`):** Running pinned `DockM8` alongside Ankora `v0.2` on public targets over both Axis A (`controlled`) and Axis B (`end_to_end`) and archiving the sealed JSON/Markdown verdict.
3. **Packaged `v0.2` Installer Builds & Byte Attestation:** Running `scripts/check_v02_installer_budget.py` against freshly built Windows `.exe`, Linux `.deb`, and Linux `.tar.zst` installers once `v0.2` release packaging is authorized.
4. **Conditional `M7` (`OpenMM` offline parameterization spike):** Remains explicitly separate from the `v0.2` critical path and gated behind a zero-network ligand parameterization spike on both Windows and Linux.
