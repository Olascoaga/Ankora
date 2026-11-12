# Validation and Engineering Evidence Index

This index catalogs all **128** immutable validation, benchmark, engineering-smoke, and protocol records under `docs/validation/`.

> **Scientific reading rule:** Every historical record preserves the exact state, hashes, and limitations that held on the date it was recorded. Engineering smokes (including WSL2/WSLg checks on synthetic or single-complex fixtures) verify software mechanics and provenance integrity; they do **not** extend the frozen scientific benchmark claims summarized in [`VALIDATION_STATUS.md`](VALIDATION_STATUS.md).

## Quick Summary by Category

| Section | Records | Scope |
| --- | ---: | --- |
| [1. Public Validation Status, Strategy & Frozen Reference Cases](#1-public-validation-status-strategy--frozen-reference-cases) | 8 | Start here to inspect Ankora's public validation boundaries and SHA-256-frozen crystallographic reference cases. |
| [2. Retrospective Virtual Screening Benchmark (`LIT-PCBA`)](#2-retrospective-virtual-screening-benchmark-lit-pcba) | 15 | Preregistered retrospective screening protocol, receptor/ligand freezes, primary AutoDock Vina campaign (`11,412` compounds across `ALDH1`, `ESR1_ant`, and `TP53`), and one-factor sensitivity design. |
| [3. Core Workspaces (`M1–M9`), Chemistry Guards & AutoDock Engines](#3-core-workspaces-m1m9-chemistry-guards--autodock-engines) | 26 | Acceptance and engineering records for structure intake, topology-guarded receptor preparation, ligand preparation, binding-site guardrails, Vina sampling, AutoGrid4/AutoDock4 CPU, AutoDock-GPU, resource arbitration, work recovery, and ProLIF interactions. |
| [4. Linux Port Foundation, Cross-OS Numeric Diagnostics & CUDA AutoDock-GPU (`ADR-026`)](#4-linux-port-foundation-cross-os-numeric-diagnostics--cuda-autodock-gpu-adr-026) | 22 | Engineering records for the Ubuntu 24. |
| [5. Linux `GNINA 1.3.3` Single-Ligand, Screening, Ensembles & `CNN_VS` (`ADR-027`, `ADR-028`)](#5-linux-gnina-133-single-ligand-screening-ensembles--cnn_vs-adr-027-adr-028) | 25 | Engineering and integration evidence for GNINA CPU/CUDA single jobs, sequential virtual screening, `CNNscore` / `CNNaffinity` / `CNN_VS` hit prioritization, CUDA `refinement`, built-in `dense_1_3` / `default_1_3_ensemble` / `default1. |
| [6. Offline Installers, Redistribution Compliance, Clean-Room Smoke & CI (`ADR-024`, `ADR-029`)](#6-offline-installers-redistribution-compliance-clean-room-smoke--ci-adr-024-adr-029) | 19 | Evidence for Windows NSIS installers, Linux `. |
| [7. Workbench Interface, Accessibility, Viewer CSP & Illustrated Guide](#7-workbench-interface-accessibility-viewer-csp--illustrated-guide) | 13 | Verification records for responsive layouts, accessible dialogs, strict-CSP Mol* viewer rendering, lossless 2D/3D contact presentation, and illustrated user-guide verification. |

## 1. Public Validation Status, Strategy & Frozen Reference Cases

Start here to inspect Ankora's public validation boundaries and SHA-256-frozen crystallographic reference cases.

| Record | Environment / Scope | Title |
| --- | --- | --- |
| [`PIK3CD_6OCO_M5V_EXECUTION.md`](PIK3CD_6OCO_M5V_EXECUTION.md) | `Windows (frozen benchmark)` | PIK3CD 6OCO/M5V independent execution |
| [`reference_cases/ADVERSARIAL_3UT3_EMJ.md`](reference_cases/ADVERSARIAL_3UT3_EMJ.md) | `Windows (frozen benchmark)` | Adversarial 3UT3 / EMJ reference placeholder |
| [`reference_cases/PIK3CD_6OCO_M5V.md`](reference_cases/PIK3CD_6OCO_M5V.md) | `Windows (frozen benchmark)` | PIK3CD 6OCO / M5V frozen pre-run validation protocol |
| [`reference_cases/PIK3CD_6OCO_M5V_RESULTS.md`](reference_cases/PIK3CD_6OCO_M5V_RESULTS.md) | `Windows (frozen benchmark)` | PIK3CD 6OCO / M5V completed frozen validation evidence |
| [`reference_cases/SERPINE1_7AQF_RV2.md`](reference_cases/SERPINE1_7AQF_RV2.md) | `Windows (frozen benchmark)` | SERPINE1 7AQF / RV2 frozen validation evidence |
| [`VALIDATION_STATUS.md`](VALIDATION_STATUS.md) | `Cross-platform policy` | Public validation status |
| [`VALIDATION_STRATEGY.md`](VALIDATION_STRATEGY.md) | `Cross-platform policy` | Validation strategy |
| [`VIRTUAL_SCREENING_BENCHMARK_PROTOCOL.md`](VIRTUAL_SCREENING_BENCHMARK_PROTOCOL.md) | `Cross-platform policy` | Virtual-screening benchmark protocol |

## 2. Retrospective Virtual Screening Benchmark (`LIT-PCBA`)

Preregistered retrospective screening protocol, receptor/ligand freezes, primary AutoDock Vina campaign (`11,412` compounds across `ALDH1`, `ESR1_ant`, and `TP53`), and one-factor sensitivity design.

| Record | Environment / Scope | Title |
| --- | --- | --- |
| [`LIT_PCBA_BOX_AND_SENTINEL_FREEZE_2026-09-15.md`](LIT_PCBA_BOX_AND_SENTINEL_FREEZE_2026-09-15.md) | `Windows (frozen benchmark)` | LIT-PCBA box and sentinel freeze — 2026-09-15 |
| [`LIT_PCBA_FINAL_RECEPTORS_2026-09-20.md`](LIT_PCBA_FINAL_RECEPTORS_2026-09-20.md) | `Windows (frozen benchmark)` | LIT-PCBA final receptor production record |
| [`LIT_PCBA_LIGAND_PREPARATION_PLAN_2026-09-21.md`](LIT_PCBA_LIGAND_PREPARATION_PLAN_2026-09-21.md) | `Windows (frozen benchmark)` | LIT-PCBA ligand-preparation plan freeze — 2026-09-21 |
| [`LIT_PCBA_LIGAND_PREPARATION_RESULTS_2026-09-23.md`](LIT_PCBA_LIGAND_PREPARATION_RESULTS_2026-09-23.md) | `Windows (frozen benchmark)` | LIT-PCBA ligand-preparation results — 2026-09-23 |
| [`LIT_PCBA_PROTONATION_PREVIEW_2026-09-17.md`](LIT_PCBA_PROTONATION_PREVIEW_2026-09-17.md) | `Windows (frozen benchmark)` | LIT-PCBA receptor protonation preview record |
| [`LIT_PCBA_RECEPTOR_PLAN_FREEZE_2026-09-17.md`](LIT_PCBA_RECEPTOR_PLAN_FREEZE_2026-09-17.md) | `Windows (frozen benchmark)` | LIT-PCBA receptor-plan freeze — 2026-09-17 |
| [`LIT_PCBA_SOURCE_ACQUISITION_2026-09-11.md`](LIT_PCBA_SOURCE_ACQUISITION_2026-09-11.md) | `Windows (frozen benchmark)` | LIT-PCBA source acquisition record — 2026-09-11 |
| [`LIT_PCBA_STRUCTURE_INTAKE_2026-09-15.md`](LIT_PCBA_STRUCTURE_INTAKE_2026-09-15.md) | `Windows (frozen benchmark)` | LIT-PCBA official-structure intake — 2026-09-15 |
| [`LIT_PCBA_TEMPLATE_SELECTION_2026-09-14.md`](LIT_PCBA_TEMPLATE_SELECTION_2026-09-14.md) | `Windows (frozen benchmark)` | LIT-PCBA holo-template selection — 2026-09-14 |
| [`LIT_PCBA_VINA_EXECUTOR_READINESS_2026-09-23.md`](LIT_PCBA_VINA_EXECUTOR_READINESS_2026-09-23.md) | `Windows (frozen benchmark)` | LIT-PCBA primary Vina executor readiness — 2026-09-23 |
| [`LIT_PCBA_VINA_PRIMARY_METRICS_2026-09-28.md`](LIT_PCBA_VINA_PRIMARY_METRICS_2026-09-28.md) | `Windows (frozen benchmark)` | LIT-PCBA primary Vina metrics — 2026-09-28 |
| [`LIT_PCBA_VINA_PRIMARY_PLAN_2026-09-23.md`](LIT_PCBA_VINA_PRIMARY_PLAN_2026-09-23.md) | `Windows (frozen benchmark)` | LIT-PCBA primary Vina campaign plan — 2026-09-23 |
| [`LIT_PCBA_VINA_PRIMARY_RESULTS_2026-09-28.md`](LIT_PCBA_VINA_PRIMARY_RESULTS_2026-09-28.md) | `Windows (frozen benchmark)` | LIT-PCBA primary Vina results — 2026-09-28 |
| [`LIT_PCBA_VINA_SENSITIVITY_PLAN_2026-09-28.md`](LIT_PCBA_VINA_SENSITIVITY_PLAN_2026-09-28.md) | `Windows (frozen benchmark)` | LIT-PCBA Vina sensitivity execution plan — 2026-09-28 |
| [`LIT_PCBA_VINA_WINDOWS_PATH_INCIDENT_2026-09-23.md`](LIT_PCBA_VINA_WINDOWS_PATH_INCIDENT_2026-09-23.md) | `Windows (frozen benchmark)` | LIT-PCBA Vina Windows path incident — 2026-09-23 |

## 3. Core Workspaces (`M1–M9`), Chemistry Guards & AutoDock Engines

Acceptance and engineering records for structure intake, topology-guarded receptor preparation, ligand preparation, binding-site guardrails, Vina sampling, AutoGrid4/AutoDock4 CPU, AutoDock-GPU, resource arbitration, work recovery, and ProLIF interactions.

| Record | Environment / Scope | Title |
| --- | --- | --- |
| [`AUTODOCK4_PHASE0_WINDOWS.md`](AUTODOCK4_PHASE0_WINDOWS.md) | `Windows / Core engine` | AutoDock4 Phase 0 native-Windows validation — 2026-08-24 |
| [`AUTODOCK4_PHASE1_MAPS.md`](AUTODOCK4_PHASE1_MAPS.md) | `Windows / Core engine` | AutoDock4 Phase 1 immutable map sets — 2026-08-24 |
| [`AUTODOCK_CPU_VS_GPU_BENCHMARK.md`](AUTODOCK_CPU_VS_GPU_BENCHMARK.md) | `Windows / Core engine` | AutoDock4 CPU vs AutoDock-GPU — benchmark (ADR-015 item 5) |
| [`AUTODOCK_GPU_PHASE5_PROBE.md`](AUTODOCK_GPU_PHASE5_PROBE.md) | `Windows / Core engine` | AutoDock-GPU — Phase 5 probe (ADR-015 item 5) |
| [`DISTINGUISHABLE_CAMPAIGN_BUNDLES_2026-09-07.md`](DISTINGUISHABLE_CAMPAIGN_BUNDLES_2026-09-07.md) | `Windows / Core engine` | Distinguishable campaign bundles — 2026-09-07 |
| [`ENGINEERING_CORRECTIONS_2026-10-15.md`](ENGINEERING_CORRECTIONS_2026-10-15.md) | `Windows / Core engine` | Engineering corrections — 2026-10-15 |
| [`GENERAL_RECEPTOR_WORKFLOW_2026-10-14.md`](GENERAL_RECEPTOR_WORKFLOW_2026-10-14.md) | `Windows / Core engine` | General receptor workflow validation — 2026-10-14 |
| [`GLOBAL_RESOURCE_ARBITER_2026-09-06.md`](GLOBAL_RESOURCE_ARBITER_2026-09-06.md) | `Windows / Core engine` | Global resource-arbiter validation — 2026-09-06 |
| [`GPU_EXECUTION_EVIDENCE.md`](GPU_EXECUTION_EVIDENCE.md) | `Windows / Core engine` | AutoDock-GPU execution evidence and repeatability |
| [`GPU_TELEMETRY_SERIALIZATION_2026-09-06.md`](GPU_TELEMETRY_SERIALIZATION_2026-09-06.md) | `Windows / Core engine` | GPU telemetry serialization validation — 2026-09-06 |
| [`GUIDED_RECEPTOR_WORKFLOW_2026-10-14.md`](GUIDED_RECEPTOR_WORKFLOW_2026-10-14.md) | `Windows / Core engine` | Three-step receptor workflow — 2026-10-14 |
| [`INCREMENTAL_BATCH_STATE_2026-09-06.md`](INCREMENTAL_BATCH_STATE_2026-09-06.md) | `Windows / Core engine` | Incremental batch-state validation — 2026-09-06 |
| [`M1_STRUCTURE_WORKSPACE.md`](M1_STRUCTURE_WORKSPACE.md) | `Windows / Core engine` | M1 Structure Workspace acceptance evidence |
| [`M2_RECEPTOR_PREPARATION.md`](M2_RECEPTOR_PREPARATION.md) | `Windows / Core engine` | M2 Receptor Preparation acceptance evidence |
| [`M3_LIGAND_PREPARATION.md`](M3_LIGAND_PREPARATION.md) | `Windows / Core engine` | M3 Ligand Preparation evidence |
| [`M4_BINDING_SITE.md`](M4_BINDING_SITE.md) | `Windows / Core engine` | M4 binding-site decision guardrails — 2026-09-04 |
| [`M5_VINA_SAMPLING_PROTOCOLS_2026-09-04.md`](M5_VINA_SAMPLING_PROTOCOLS_2026-09-04.md) | `Windows / Core engine` | M5 Vina purpose-labelled sampling protocols - 2026-09-04 |
| [`M5_VINA_WINDOWS_SMOKE_2026-08-23.md`](M5_VINA_WINDOWS_SMOKE_2026-08-23.md) | `Windows / Core engine` | M5 AutoDock Vina 1.2.7 Windows smoke — 2026-08-23 |
| [`M9_POSE_INTERACTIONS.md`](M9_POSE_INTERACTIONS.md) | `Windows / Core engine` | M9 Pose Interactions acceptance evidence |
| [`PROJECT_WORKSPACE_2026-09-06.md`](PROJECT_WORKSPACE_2026-09-06.md) | `Windows / Core engine` | Project Workspace validation — 2026-09-06 |
| [`RECEPTOR_PREPARATION_GUIDANCE_2026-10-14.md`](RECEPTOR_PREPARATION_GUIDANCE_2026-10-14.md) | `Windows / Core engine` | Receptor preparation guidance — 2026-10-14 |
| [`RECEPTOR_RELAXATION_RECOVERY_2026-10-13.md`](RECEPTOR_RELAXATION_RECOVERY_2026-10-13.md) | `Windows / Core engine` | Receptor relaxation recovery — 13 October 2026 |
| [`RECEPTOR_TERMINAL_OXYGEN_REVIEW.md`](RECEPTOR_TERMINAL_OXYGEN_REVIEW.md) | `Windows / Core engine` | Receptor terminal oxygen review |
| [`RECEPTOR_TOPOLOGY_GUARD_2026-10-14.md`](RECEPTOR_TOPOLOGY_GUARD_2026-10-14.md) | `Windows / Core engine` | Topology-guarded receptor repair — 2026-10-14 |
| [`REDOCKING_WORKFLOW_2026-10-20.md`](REDOCKING_WORKFLOW_2026-10-20.md) | `Windows / Core engine` | Redocking workflow correction — 2026-10-20 |
| [`WORK_RECOVERY_2026-09-04.md`](WORK_RECOVERY_2026-09-04.md) | `Windows / Core engine` | Durable work recovery validation - 2026-09-04 |

## 4. Linux Port Foundation, Cross-OS Numeric Diagnostics & CUDA AutoDock-GPU (`ADR-026`)

Engineering records for the Ubuntu 24.04 Linux runtime lock, process-tree lifetime, native P2Rank/Vina execution, `<= 4 ULP` glibc vs Windows UCRT BEDROC numeric diagnostic, and CUDA AutoDock-GPU execution/cancellation.

| Record | Environment / Scope | Title |
| --- | --- | --- |
| [`LINUX_API_PREPARATION_PLAN.md`](LINUX_API_PREPARATION_PLAN.md) | `Linux (WSL2/WSLg)` | Linux API preparation and Vina smoke — predeclared protocol |
| [`LINUX_AUTODOCK_GPU_BUILD2_PLAN.md`](LINUX_AUTODOCK_GPU_BUILD2_PLAN.md) | `Linux (WSL2/WSLg)` | Linux AutoDock-GPU CUDA build follow-up — predeclared |
| [`LINUX_AUTODOCK_GPU_BUILT_SMOKE.md`](LINUX_AUTODOCK_GPU_BUILT_SMOKE.md) | `Linux (WSL2/WSLg)` | Linux locally built AutoDock-GPU smoke — predeclared exploratory follow-up |
| [`LINUX_AUTODOCK_GPU_CAMPAIGN_AND_CANCEL.md`](LINUX_AUTODOCK_GPU_CAMPAIGN_AND_CANCEL.md) | `Linux (WSL2/WSLg)` | Linux AutoDock-GPU campaign and cancellation: declared engineering test |
| [`LINUX_AUTODOCK_GPU_LOCAL_BUILD_PLAN.md`](LINUX_AUTODOCK_GPU_LOCAL_BUILD_PLAN.md) | `Linux (WSL2/WSLg)` | Linux AutoDock-GPU targeted CUDA build — predeclared exploration |
| [`LINUX_AUTODOCK_GPU_NATIVE_SMOKE.md`](LINUX_AUTODOCK_GPU_NATIVE_SMOKE.md) | `Linux (WSL2/WSLg)` | Linux AutoDock-GPU 1.6 CUDA smoke — predeclared protocol |
| [`LINUX_AUTODOCK_GPU_SERVICE_SMOKE.md`](LINUX_AUTODOCK_GPU_SERVICE_SMOKE.md) | `Linux (WSL2/WSLg)` | Linux AutoDock-GPU service smoke — predeclared exploratory protocol |
| [`LINUX_BACKEND_BOOTSTRAP.md`](LINUX_BACKEND_BOOTSTRAP.md) | `Linux (WSL2/WSLg)` | Linux backend development launcher — 2026-10-28 |
| [`LINUX_CRYSTAL_REDOCKING_FOLLOWUP.md`](LINUX_CRYSTAL_REDOCKING_FOLLOWUP.md) | `Linux (WSL2/WSLg)` | Linux 1HSG/MK1 exploratory redocking follow-up — predeclared protocol |
| [`LINUX_CRYSTAL_REDOCKING_PLAN.md`](LINUX_CRYSTAL_REDOCKING_PLAN.md) | `Linux (WSL2/WSLg)` | Linux crystallographic redocking API smoke — predeclared protocol |
| [`LINUX_DESKTOP_BOOTSTRAP.md`](LINUX_DESKTOP_BOOTSTRAP.md) | `Linux (WSL2/WSLg)` | Linux desktop development bootstrap — 2026-10-28 |
| [`LINUX_P2RANK_EXECUTION.md`](LINUX_P2RANK_EXECUTION.md) | `Linux (WSL2/WSLg)` | Linux P2Rank execution — 2026-10-28 |
| [`LINUX_PORT_BOOTSTRAP_REVIEW.md`](LINUX_PORT_BOOTSTRAP_REVIEW.md) | `Linux (WSL2/WSLg)` | Linux bootstrap integration review — 2026-10-28 |
| [`LINUX_PORTABILITY_RECONCILIATION.md`](LINUX_PORTABILITY_RECONCILIATION.md) | `Linux (WSL2/WSLg)` | Linux Portability Reconciliation — 2026-10-28 |
| [`LINUX_PRIMARY_METRICS_NUMERIC_DIAGNOSTIC.md`](LINUX_PRIMARY_METRICS_NUMERIC_DIAGNOSTIC.md) | `Cross-platform (Windows vs Linux)` | Cross-platform diagnostic for the frozen primary Vina metrics — 2026-10-28 |
| [`LINUX_PROCESS_EXECUTION.md`](LINUX_PROCESS_EXECUTION.md) | `Linux (WSL2/WSLg)` | Linux Scientific Process Lifetime and Cancellation Validation |
| [`LINUX_SCIENTIFIC_FOUNDATION_REVIEW.md`](LINUX_SCIENTIFIC_FOUNDATION_REVIEW.md) | `Linux (WSL2/WSLg)` | Linux scientific foundation — coordinator review, 2026-10-28 |
| [`LINUX_SCIENTIFIC_RUNTIME.md`](LINUX_SCIENTIFIC_RUNTIME.md) | `Linux (WSL2/WSLg)` | Linux scientific runtime lock — 2026-10-28 |
| [`LINUX_SOURCE_BASELINE.md`](LINUX_SOURCE_BASELINE.md) | `Linux (WSL2/WSLg)` | Linux source baseline — 2026-10-28 |
| [`LINUX_TOOL_DISCOVERY.md`](LINUX_TOOL_DISCOVERY.md) | `Linux (WSL2/WSLg)` | Linux tool discovery — 2026-10-28 |
| [`LINUX_VINA_CPU_SMOKE_PLAN.md`](LINUX_VINA_CPU_SMOKE_PLAN.md) | `Linux (WSL2/WSLg)` | Linux CPU AutoDock Vina engineering smoke — plan (2026-10-28) |
| [`LINUX_VINA_SERVICE_PLAN.md`](LINUX_VINA_SERVICE_PLAN.md) | `Linux (WSL2/WSLg)` | Linux Vina service integration smoke — predeclared protocol |

## 5. Linux `GNINA 1.3.3` Single-Ligand, Screening, Ensembles & `CNN_VS` (`ADR-027`, `ADR-028`)

Engineering and integration evidence for GNINA CPU/CUDA single jobs, sequential virtual screening, `CNNscore` / `CNNaffinity` / `CNN_VS` hit prioritization, CUDA `refinement`, built-in `dense_1_3` / `default_1_3_ensemble` / `default1.0` models, redocking, ProLIF interactions, `Methods`, and Export v4.

| Record | Environment / Scope | Title |
| --- | --- | --- |
| [`GNINA_EXPORT.md`](GNINA_EXPORT.md) | `Linux (WSL2/WSLg)` | GNINA portable export (single job and screening campaign) |
| [`GNINA_METHODS.md`](GNINA_METHODS.md) | `Linux (WSL2/WSLg)` | GNINA Methods report |
| [`GNINA_REDOCKING.md`](GNINA_REDOCKING.md) | `Linux (WSL2/WSLg)` | GNINA single-job redocking validation |
| [`GNINA_SCREENING_PLAN.md`](GNINA_SCREENING_PLAN.md) | `Linux (WSL2/WSLg)` | GNINA virtual-screening implementation plan |
| [`GNINA_SINGLE_WORKSPACE.md`](GNINA_SINGLE_WORKSPACE.md) | `Linux (WSL2/WSLg)` | GNINA single-ligand workspace |
| [`LINUX_GNINA_API_CPU.md`](LINUX_GNINA_API_CPU.md) | `Linux (WSL2/WSLg)` | GNINA CPU API engineering check |
| [`LINUX_GNINA_API_CUDA.md`](LINUX_GNINA_API_CUDA.md) | `Linux (WSL2/WSLg)` | GNINA CUDA API engineering check |
| [`LINUX_GNINA_CANCEL_CUDA.md`](LINUX_GNINA_CANCEL_CUDA.md) | `Linux (WSL2/WSLg)` | GNINA CUDA cancellation engineering check |
| [`LINUX_GNINA_CATALOG.md`](LINUX_GNINA_CATALOG.md) | `Linux (WSL2/WSLg)` | GNINA result catalog engineering check |
| [`LINUX_GNINA_CNN_MODES.md`](LINUX_GNINA_CNN_MODES.md) | `Linux (WSL2/WSLg)` | GNINA 1.3.3 CNN scoring modes, ensemble identities, and memory probe — predeclared |
| [`LINUX_GNINA_CUDA_IDENTITY.md`](LINUX_GNINA_CUDA_IDENTITY.md) | `Linux (WSL2/WSLg)` | GNINA CUDA device identity engineering check |
| [`LINUX_GNINA_EXPORT.md`](LINUX_GNINA_EXPORT.md) | `Linux (WSL2/WSLg)` | Linux GNINA single-job export integration check |
| [`LINUX_GNINA_EXPORT_REFERENCE.md`](LINUX_GNINA_EXPORT_REFERENCE.md) | `Linux (WSL2/WSLg)` | GNINA exported redocking reference check |
| [`LINUX_GNINA_INITIAL_SMOKE.md`](LINUX_GNINA_INITIAL_SMOKE.md) | `Linux (WSL2/WSLg)` | GNINA Linux initial exploratory smoke — predeclared |
| [`LINUX_GNINA_INTERACTIONS.md`](LINUX_GNINA_INTERACTIONS.md) | `Linux (WSL2/WSLg)` | Linux GNINA pose interaction integration check |
| [`LINUX_GNINA_METHODS.md`](LINUX_GNINA_METHODS.md) | `Linux (WSL2/WSLg)` | Linux GNINA Methods integration check |
| [`LINUX_GNINA_REDOCKING.md`](LINUX_GNINA_REDOCKING.md) | `Linux (WSL2/WSLg)` | Linux GNINA redocking integration check |
| [`LINUX_GNINA_REFINEMENT_CUDA.md`](LINUX_GNINA_REFINEMENT_CUDA.md) | `Linux (WSL2/WSLg)` | GNINA CUDA `refinement` mode, built-in `default_1_3_ensemble`, and VRAM arbiter check — predeclared |
| [`LINUX_GNINA_SCREENING_CNN_VS.md`](LINUX_GNINA_SCREENING_CNN_VS.md) | `Linux (WSL2/WSLg)` | GNINA CUDA `CNN_VS` + `default_1_3_ensemble` screening and frozen legacy compatibility check — predeclared |
| [`LINUX_GNINA_SCREENING_CUDA.md`](LINUX_GNINA_SCREENING_CUDA.md) | `Linux (WSL2/WSLg)` | GNINA CUDA virtual-screening and mid-campaign cancellation checks — predeclared |
| [`LINUX_GNINA_SCREENING_SMOKE.md`](LINUX_GNINA_SCREENING_SMOKE.md) | `Linux (WSL2/WSLg)` | GNINA screening CPU API check — predeclared |
| [`LINUX_GNINA_SCREENING_WSLG.md`](LINUX_GNINA_SCREENING_WSLG.md) | `Linux (WSL2/WSLg)` | GNINA WSLg native desktop screening check — completed |
| [`LINUX_GNINA_SERVICE_CPU.md`](LINUX_GNINA_SERVICE_CPU.md) | `Linux (WSL2/WSLg)` | GNINA CPU service engineering check |
| [`LINUX_GNINA_SERVICE_CUDA.md`](LINUX_GNINA_SERVICE_CUDA.md) | `Linux (WSL2/WSLg)` | Experimental GNINA CUDA service engineering check |
| [`LINUX_GNINA_TOPOLOGY_SMOKE.md`](LINUX_GNINA_TOPOLOGY_SMOKE.md) | `Linux (WSL2/WSLg)` | GNINA 1.3.3 PDBQT topology check — predeclared |

## 6. Offline Installers, Redistribution Compliance, Clean-Room Smoke & CI (`ADR-024`, `ADR-029`)

Evidence for Windows NSIS installers, Linux `.deb` and zero-`sudo` `.tar.zst` Core bundles, the 1-click offline GNINA CUDA 12.8 pack (`D4`), the bare-metal Linux workstation protocol (`D6`), hash-locked environments, third-party legal inventories, and isolated CI.

| Record | Environment / Scope | Title |
| --- | --- | --- |
| [`COMPACT_WINDOWS_INSTALLER_2026-10-09.md`](COMPACT_WINDOWS_INSTALLER_2026-10-09.md) | `Windows` | Complete compact Windows candidate — 2026-10-09 |
| [`COMPLETE_WINDOWS_INSTALLER_2026-10-08.md`](COMPLETE_WINDOWS_INSTALLER_2026-10-08.md) | `Windows` | Complete Windows installer candidate — 2026-10-08 |
| [`COMPLETE_WINDOWS_PAYLOAD_2026-10-06.md`](COMPLETE_WINDOWS_PAYLOAD_2026-10-06.md) | `Windows` | Complete Windows payload — implementation evidence |
| [`DEV_DEPENDENCY_PEFILE_2026-10-28.md`](DEV_DEPENDENCY_PEFILE_2026-10-28.md) | `Cross-platform` | Development dependency: pefile — 2026-10-28 |
| [`LINUX_NATIVE_WORKSTATION_PROTOCOL.md`](LINUX_NATIVE_WORKSTATION_PROTOCOL.md) | `Bare-metal Linux protocol` | Native Linux Workstation Verification Protocol (`ADR-029` Gate `D6`) |
| [`LINUX_OFFLINE_PACKAGE_SMOKE.md`](LINUX_OFFLINE_PACKAGE_SMOKE.md) | `Linux (WSL2/WSLg clean-room)` | Linux Offline Package & One-Click GNINA Pack Clean-Room Smoke (`ADR-029` Gate `D4`) |
| [`LOCKED_WINDOWS_ENVIRONMENT_2026-09-08.md`](LOCKED_WINDOWS_ENVIRONMENT_2026-09-08.md) | `Windows` | Locked Windows scientific environment — 2026-09-08 |
| [`NATIVE_SMOKE_FIXTURE_IDENTITY_2026-10-28.md`](NATIVE_SMOKE_FIXTURE_IDENTITY_2026-10-28.md) | `Cross-platform` | Native-smoke evidence writer: fixture identity across hosts — 2026-10-28 |
| [`NATIVE_TOOL_SMOKE_MATRIX_2026-09-08.md`](NATIVE_TOOL_SMOKE_MATRIX_2026-09-08.md) | `Windows` | Native scientific-tool smoke matrix — 2026-09-08 |
| [`P2RANK_SMOKE_IDENTITY.md`](P2RANK_SMOKE_IDENTITY.md) | `Cross-platform` | P2Rank Smoke Executable Identity Fix — 2026-10-28 |
| [`PRIVATE_BETA_INSTALLER_2026-10-15.md`](PRIVATE_BETA_INSTALLER_2026-10-15.md) | `Windows` | Complete private-beta installer — 15 October 2026 |
| [`PRIVATE_BETA_INTERACTIONS_INSTALLER_2026-10-09.md`](PRIVATE_BETA_INTERACTIONS_INSTALLER_2026-10-09.md) | `Windows` | Updated private-beta Windows installer — 2026-10-09 |
| [`PRIVATE_BETA_RECEPTOR_RECOVERY_INSTALLER_2026-10-13.md`](PRIVATE_BETA_RECEPTOR_RECOVERY_INSTALLER_2026-10-13.md) | `Windows` | Private-beta receptor recovery installer — 13 October 2026 |
| [`PRIVATE_BETA_SLIM_INSTALLER_2026-10-20.md`](PRIVATE_BETA_SLIM_INSTALLER_2026-10-20.md) | `Windows` | Slim private-beta installer (Option A) — 20 October 2026 |
| [`THIRD_PARTY_REDISTRIBUTION_2026-09-08.md`](THIRD_PARTY_REDISTRIBUTION_2026-09-08.md) | `Windows` | Third-party redistribution validation — 2026-09-08 |
| [`WINDOWS_CI_ISOLATED_PYTHON.md`](WINDOWS_CI_ISOLATED_PYTHON.md) | `Windows` | Windows CI: isolated Python environment — 2026-10-28 |
| [`WINDOWS_CI_LOCKED_ENVIRONMENT.md`](WINDOWS_CI_LOCKED_ENVIRONMENT.md) | `Windows` | Windows CI on the hash-locked Python environment — 2026-10-28 |
| [`WINDOWS_INSTALLER_RUNTIME_2026-09-08.md`](WINDOWS_INSTALLER_RUNTIME_2026-09-08.md) | `Windows` | Windows installer and bundled runtime validation — 2026-09-08 |
| [`WINDOWS_RELEASE_ARTIFACTS_2026-09-10.md`](WINDOWS_RELEASE_ARTIFACTS_2026-09-10.md) | `Windows` | Windows release artifact contract |

## 7. Workbench Interface, Accessibility, Viewer CSP & Illustrated Guide

Verification records for responsive layouts, accessible dialogs, strict-CSP Mol* viewer rendering, lossless 2D/3D contact presentation, and illustrated user-guide verification.

| Record | Environment / Scope | Title |
| --- | --- | --- |
| [`ACCESSIBLE_DIALOGS_2026-09-06.md`](ACCESSIBLE_DIALOGS_2026-09-06.md) | `Windows / Web UI` | Accessible-dialog validation — 2026-09-06 |
| [`CONSISTENT_FORMATTING_2026-09-07.md`](CONSISTENT_FORMATTING_2026-09-07.md) | `Windows / Web UI` | Consistent scientific and date formatting acceptance |
| [`DEVELOPMENT_VIEWER_INTEROP_2026-10-09.md`](DEVELOPMENT_VIEWER_INTEROP_2026-10-09.md) | `Windows / Web UI` | Development molecular viewer interoperability — 2026-10-09 |
| [`ERROR_CONTAINMENT_2026-09-06.md`](ERROR_CONTAINMENT_2026-09-06.md) | `Windows / Web UI` | Error-containment validation — 2026-09-06 |
| [`INTERACTION_PRESENTATION_2026-10-09.md`](INTERACTION_PRESENTATION_2026-10-09.md) | `Windows / Web UI` | Lossless interaction presentation — 2026-10-09 |
| [`MIDNIGHT_LABORATORY_VISUAL_IDENTITY_2026-10-05.md`](MIDNIGHT_LABORATORY_VISUAL_IDENTITY_2026-10-05.md) | `Windows / Web UI` | Midnight Laboratory visual identity validation |
| [`PACKAGED_UI_REPAIR_2026-10-08.md`](PACKAGED_UI_REPAIR_2026-10-08.md) | `Windows / Web UI` | Packaged UI regression repair — 2026-10-08 |
| [`POSE_INTERACTION_SCROLL_2026-10-06.md`](POSE_INTERACTION_SCROLL_2026-10-06.md) | `Windows / Web UI` | Pose-interaction scroll regression — 2026-10-06 |
| [`README_PRESENTATION_2026-10-11.md`](README_PRESENTATION_2026-10-11.md) | `Windows / Web UI` | Private-beta README presentation — 11 October 2026 |
| [`RESPONSIVE_WORKBENCH_LAYOUTS_2026-09-07.md`](RESPONSIVE_WORKBENCH_LAYOUTS_2026-09-07.md) | `Windows / Web UI` | Responsive workbench layout validation — 2026-09-07 |
| [`RESULTS_METHODS_ACCESS_2026-09-07.md`](RESULTS_METHODS_ACCESS_2026-09-07.md) | `Windows / Web UI` | Results-local Methods access — 2026-09-07 |
| [`USER_GUIDE_7AQF_2026-10-09.md`](USER_GUIDE_7AQF_2026-10-09.md) | `Windows / Web UI` | Illustrated user-guide verification: 7AQF / RV2 |
| [`USER_GUIDE_REVIEW_2026-10-06.md`](USER_GUIDE_REVIEW_2026-10-06.md) | `Windows / Web UI` | Illustrated user-guide review - 2026-10-06 |
