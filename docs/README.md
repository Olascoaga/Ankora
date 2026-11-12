# Ankora Documentation Portal

Ankora is a local-first scientific desktop workbench for step-by-step molecular docking and virtual screening. Every document in this tree separates **what is implemented in code**, **how offline distributions are packaged**, **what engineering checks have run**, and **what frozen scientific benchmarks do or do not establish**.

---

## 1. Start Here: Guided Walkthrough & Platform Status

| Document | Audience | What you will find |
| --- | --- | --- |
| [Repository README](../README.md) | Everyone | Overview of the `M1–M9` workflow, the 4 supported docking engines, installation paths, and citation details. |
| [Illustrated User Guide](USER_GUIDE.md) · [Printable PDF](Ankora-User-Guide.pdf) | Scientists & students | End-to-end illustrated campaign on **SERPINE1 / PAI-1 (`PDB 7AQF` · `RV2`)**, plus Linux `GNINA 1.3.3` CNN scoring, redocking validation, and virtual screening. |
| [Platform & Engine Status](product/PLATFORM_STATUS.md) · [`JSON`](product/PLATFORM_STATUS.json) | Everyone | Canonical matrix comparing **Windows 11 x64 (`private_beta`)**, **Linux x86\_64 (`release_candidate`)**, and **macOS (`out_of_scope`)**, alongside all four docking engines. |
| [User Workflow](product/USER_WORKFLOW.md) | Scientists | Step-by-step ordering and prerequisites across Structure, Receptor, Ligands, Binding Site, Docking, Results, Validation, and Export. |

---

## 2. Scientific Policies & Score Interpretation

Read these contracts before comparing campaigns, interpreting scores, or citing generated reports:

| Policy | Scientific contract |
| --- | --- |
| [Receptor Preparation Policy](scientific/RECEPTOR_PREPARATION_POLICY.md) | Read-only Gemmi inspection, explicit chain/water/heterogen choices, selective PDBFixer reconstruction (`topology_guard_v3`), PROPKA/PDB2PQR protonation review, and Meeko PDBQT creation. |
| [Ligand Preparation Policy](scientific/LIGAND_PREPARATION_POLICY.md) | Immutable compound/library intake, explicit stereochemistry and physiological-pH microstate selection (`ADR-016`), rule/alert evaluation, ETKDGv3/MMFF94s minimization, and Meeko PDBQT output. |
| [Docking Policy](scientific/DOCKING_POLICY.md) | Independent execution and scoring boundaries for **AutoDock Vina `1.2.7`**, **AutoDock4 `4.2.6` (CPU)**, **AutoDock-GPU `1.6`**, and Linux **GNINA `1.3.3`** (`CNNscore`, `CNNaffinity` pK, `CNN_VS`, `rescore` vs CUDA `refinement`, built-in CNN ensembles, and Spearman rank comparison between Vina and AutoDock4 CPU). |
| [Redocking Validation Policy](scientific/REDOCKING_VALIDATION.md) | Post-hoc symmetry-aware heavy-atom RMSD computed **in place** (never superposed) against an immutable crystallographic extraction, separating `sampling_success` from `ranking_success`. |
| [Pose Interaction Policy](scientific/POSE_INTERACTION_POLICY.md) | Create-only ProLIF `2.2.1` contact detection on hash-verified receptor/conformer/pose triples, lossless residue summary vs all-atomic-contact views, and geometric interpretation limits. |
| [Methods Report Policy](scientific/METHODS_REPORT_POLICY.md) | Record-derived `Methods` section generation with tool versions, SHA-256 identities, DOI-verified citations, and explicit `[not recorded: ...]` gap markers instead of invented prose. |

---

## 3. Validation Status, Frozen Reference Cases & Evidence Index

| Resource | Purpose |
| --- | --- |
| [Public Validation Status](validation/VALIDATION_STATUS.md) · [`JSON`](validation/VALIDATION_STATUS.json) | CI-enforced summary of frozen reference cases (`PIK3CD 6OCO / M5V` completed; `SERPINE1 7AQF / RV2` frozen with documented gaps) and claims not yet established. |
| [**Complete Validation & Evidence Index**](validation/INDEX.md) | Categorized index of all **128** scientific, benchmark, cross-platform numeric, Linux/GNINA, and offline-packaging validation records under `docs/validation/`. |
| [Validation Strategy](validation/VALIDATION_STRATEGY.md) | Methodology separating engineering smoke checks, retrospective reference cases, and prospective biological claims. |
| [Virtual Screening Benchmark Protocol](validation/VIRTUAL_SCREENING_BENCHMARK_PROTOCOL.md) | Preregistered retrospective LIT-PCBA benchmark design, receptor/ligand freezes, primary Vina metrics, and sensitivity plan. |

---

## 4. Product Scope & Interface Design

| Document | Scope |
| --- | --- |
| [Product Definition](product/PRODUCT_DEFINITION.md) & [Scope](product/SCOPE.md) | Target practitioner profile, in-scope capabilities on Windows and Linux, and explicit non-goals (no cloud execution, no merged consensus score, no silent chemical choices). |
| [M6 Results Workspace](product/M6_RESULTS.md) | Rebuildable multi-engine campaign catalog, SQLite incremental screening sidecar, Vina/AutoDock4 CPU rank comparison, GNINA CNN projection, and recoverable Trash. |
| [M9 Pose Interactions](product/M9_POSE_INTERACTIONS.md) | Linked 3D Mol\* + skeletal 2D SVG diagram + atomic contact table, publication figure export (`SVG`/`PNG`/`TIFF`/`PDF`), and exact-pose complex PDB export. |
| [UI Principles](product/UI_PRINCIPLES.md), [UX Foundation](design/UX_FOUNDATION.md) & [Startup Screen](design/STARTUP_SCREEN.md) | Fixed-viewport workbench layout (`ADR-014`), semantic design tokens, accessibility rules, and the live 5-check *Anchoring* startup record. |
| [Image Provenance](images/README.md) | Exact SHA-256 source records and read-only capture conditions for repository and user-guide screenshots. |

---

## 5. Architecture & Key Decision Records (`ADR-001`–`ADR-029`)

Start with [System Architecture](architecture/ARCHITECTURE.md) for the end-to-end Tauri v2 (`WebView2` on Windows, `WebKitGTK` on Linux) + React/TypeScript + localhost FastAPI/Python 3.12 design, resource arbitration, and isolated toolchains. Full decision records live in [`docs/architecture/ADR/`](architecture/ADR):

| ADR group | Key records |
| --- | --- |
| **Workbench & Artifact Integrity** | [ADR-002](architecture/ADR/ADR-002-guided-manual-workflow.md) (guided manual workflow), [ADR-004](architecture/ADR/ADR-004-immutable-original-inputs.md) (immutable inputs), [ADR-005](architecture/ADR/ADR-005-traceable-scientific-transformations.md) (traceable derivatives), [ADR-011](architecture/ADR/ADR-011-stale-artifact-propagation.md) (stale propagation), [ADR-014](architecture/ADR/ADR-014-scientific-workbench-interface.md) (fixed-viewport workbench), [ADR-023](architecture/ADR/ADR-023-project-workspace-identity.md) (project workspaces). |
| **Chemistry & Sampling Rigor** | [ADR-012](architecture/ADR/ADR-012-validation-by-reference-cases.md) (reference-case validation), [ADR-015](architecture/ADR/ADR-015-autodock4-engine.md) (AutoDock4 & AutoGrid4), [ADR-016](architecture/ADR/ADR-016-explicit-screening-microstates.md) (explicit screening microstates), [ADR-017](architecture/ADR/ADR-017-explicit-receptor-protonation-decisions.md) (receptor protonation review), [ADR-018](architecture/ADR/ADR-018-exploratory-search-space-and-vina-sampling.md) & [ADR-019](architecture/ADR/ADR-019-purpose-labelled-vina-sampling-protocols.md) (box volume & Vina sampling), [ADR-025](architecture/ADR/ADR-025-topology-guarded-receptor-repair.md) (`topology_guard_v3` receptor reconstruction). |
| **Execution Reliability & Windows Packaging** | [ADR-020](architecture/ADR/ADR-020-durable-work-recovery.md) (durable work leases & startup reconciliation), [ADR-021](architecture/ADR/ADR-021-incremental-batch-state.md) (incremental SQLite batch state), [ADR-022](architecture/ADR/ADR-022-global-resource-arbitration.md) (`ResourceArbiter` CPU/GPU/RAM/VRAM/disk), [ADR-024](architecture/ADR/ADR-024-complete-scientific-installer.md) (self-contained offline scientific installer). |
| **Linux Port, GNINA & Modular Distribution** | [ADR-026](architecture/ADR/ADR-026-linux-port-and-native-acceptance.md) (Linux port & bare-metal workstation gate, superseding [ADR-001](architecture/ADR/ADR-001-windows-only-personal-workbench.md)), [ADR-027](architecture/ADR/ADR-027-linux-gnina.md) (Linux `GNINA 1.3.3` engine, superseding [ADR-008](architecture/ADR/ADR-008-vina-and-gnina.md) deferral on Linux), [ADR-028](architecture/ADR/ADR-028-gnina-cnn-vs-refinement-ensemble.md) (`CNN_VS`, CUDA `refinement`, built-in CNN ensembles & VRAM arbitration), [ADR-029](architecture/ADR/ADR-029-linux-offline-distribution.md) (modular `.deb`/`.tar.zst` Core installer + 1-click offline GNINA CUDA 12.8 pack). |

---

## 6. Development, Locked Environments & Packaging

| Guide | Platform | Contents |
| --- | --- | --- |
| [Windows Development & Packaging](DEVELOPMENT.md) | Windows 11 x64 | Conda + hash-locked pip setup, external tool discovery, test/lint/typecheck gates, and NSIS installer assembly. |
| [Linux Development & Offline Packaging](DEVELOPMENT_LINUX.md) | Linux x86\_64 (Ubuntu 24.04 LTS) | Locked Conda/pip setup, `dev_linux.py` & Tauri/WebKitGTK launch, AutoDock-GPU CUDA & GNINA `1.3.3` setup, `.deb`/`.tar.zst`/GNINA-pack builders, clean-room smoke (`D4`), bare-metal attestation (`D6`), and `verify-linux` CI. |
| [Changelog](../CHANGELOG.md) & [Citation Metadata](../CITATION.cff) | Cross-platform | Chronological record of verified engineering/scientific increments and Citation File Format `1.2.0` metadata. |
