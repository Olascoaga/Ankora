# Platform and engine capability status

<!-- Generated from PLATFORM_STATUS.json by scripts/check_platform_docs.py; checked by CI. -->

Last synchronized: `2026-11-12`

Ankora separates **implementation**, **offline packaging**, **engineering evidence**, and
**distribution status** so capabilities implemented in source are neither hidden behind
outdated prose nor overstated as bare-metal public releases before their final gates close.
Frozen scientific benchmark boundaries remain governed separately by
[`VALIDATION_STATUS.md`](../validation/VALIDATION_STATUS.md).

## Platform matrix

| Platform | Distribution status | Desktop shell & CI | Implemented workflow | Offline packaging | Engineering evidence | Pending release gates |
| --- | --- | --- | --- | --- | --- | --- |
| **Windows 11 x64** | `private_beta` | Tauri v2 · WebView2 (Chromium) · CI: `verify (windows-latest)` | M1-M9 complete (Structure, Receptor, Ligands, Binding Site, Docking, Results, Validation, Export, Pose Interactions) | Slim offline NSIS installer (Ankora_0.1.0_x64-setup.exe, 407.16 MiB) + corresponding-sources companion ZIP (232.45 MiB) | Automated Windows CI on windows-latest; 10/10 native scientific adapter smoke matrix; strict-CSP production WebView2 viewer and guided-receptor smoke | User-controlled timestamped Authenticode code signing; Clean-machine installed acceptance on the latest slim installer build; Explicit public release authorization |
| **Linux x86_64 (Ubuntu 24.04 LTS reference)** | `release_candidate` | Tauri v2 · WebKitGTK 4.1 · CI: `verify-linux (ubuntu-24.04)` | M1-M9 complete plus Linux-only GNINA 1.3.3 single-ligand and virtual-screening workflows (ADR-026, ADR-027, ADR-028, ADR-029) | Core double-click .deb (Ankora_0.1.0_amd64.deb, 272.34 MiB) + zero-sudo portable .tar.zst (313.97 MiB) + 1-click GUI-imported offline GNINA CUDA 12.8 pack (2.55 GiB / 2,610.34 MiB, split into < 2 GiB .part01 + .part02 for GitHub Releases) + corresponding-sources companion ZIP (390.77 MiB) | Automated Ubuntu 24.04 CI lane; 10/10 Core + 11/11 post-import clean-room package smoke under WSL2/WSLg with RTX 5050 CUDA execution (ADR-029 Gate D4) | Bare-metal physical Linux x86_64 workstation attestation (ADR-026 Gate 4 / ADR-029 Gate D6); Explicit public release authorization |
| **macOS** | `out_of_scope` | Not implemented · CI: `None` | Out of scope for v0.1 | None | None | Out of scope for v0.1 |

### Primary platform evidence

- **Windows 11 x64 (`private_beta`):** [`PRIVATE_BETA_SLIM_INSTALLER_2026-10-20.md`](../validation/PRIVATE_BETA_SLIM_INSTALLER_2026-10-20.md), [`PRIVATE_BETA_INSTALLER_2026-10-15.md`](../validation/PRIVATE_BETA_INSTALLER_2026-10-15.md)
- **Linux x86_64 (Ubuntu 24.04 LTS reference) (`release_candidate`):** [`LINUX_OFFLINE_PACKAGE_SMOKE.md`](../validation/LINUX_OFFLINE_PACKAGE_SMOKE.md), [`LINUX_NATIVE_WORKSTATION_PROTOCOL.md`](../validation/LINUX_NATIVE_WORKSTATION_PROTOCOL.md)

## Docking engines and scoring boundaries

| Engine | Platforms | Execution modes | Primary ranking metric | Result model | Cross-engine comparison boundary |
| --- | --- | --- | --- | --- | --- |
| **AutoDock Vina `1.2.7`** | Windows 11 x64, Linux x86_64 (Ubuntu 24.04 LTS reference) | CPU · single ligand<br>CPU · library virtual screening | Empirical Vina score (kcal/mol, ascending / more negative) | Pose-native modes with inter-mode RMSD lower and upper bounds | Supported against AutoDock4 CPU library campaigns sharing exact receptor, finalized binding site, and applied selection manifest (Spearman rank correlation and Top-N overlap; zero merged score) |
| **AutoDock4 (CPU) `4.2.6`** | Windows 11 x64, Linux x86_64 (Ubuntu 24.04 LTS reference) | CPU · single ligand<br>CPU · library virtual screening | Estimated free energy of binding (kcal/mol, ascending / more negative) | Cluster/run-native DLG hierarchy over immutable AutoGrid4 4.2.6 affinity maps | Supported against AutoDock Vina library campaigns sharing exact receptor, finalized binding site, and applied selection manifest (Spearman rank correlation and Top-N overlap; zero merged score) |
| **AutoDock-GPU `1.6`** | Windows 11 x64, Linux x86_64 (Ubuntu 24.04 LTS reference) | OpenCL GPU (Windows) / CUDA 12 GPU (Linux) · single ligand<br>OpenCL / CUDA --filelist library virtual screening | AutoDock4 scoring-family energy (kcal/mol, ascending / more negative) | Cluster/run-native DLG hierarchy over shared immutable AutoGrid4 4.2.6 affinity maps | Shares the AutoDock4 scoring family (not an independent scoring vote from AutoDock4 CPU); not directly loaded by the Vina/AutoDock4 CPU comparison service |
| **GNINA `1.3.3`** | Linux x86_64 (Ubuntu 24.04 LTS reference) | CPU or CUDA 12.8 GPU · single ligand or sequential library screening (rescore)<br>CUDA 12.8 GPU only · single ligand or sequential library screening (refinement, timeout >= 10 min) | Within-ligand: CNNscore [0, 1] descending; Screening hit prioritization: cnn_score or cnn_vs (CNNscore * CNNaffinity) descending | CNN-ordered poses preserving separate CNNscore (dimensionless), CNNaffinity (pK), CNN_VS, optional CNNaffinity_variance (only when emitted), and minimizedAffinity (kcal/mol) | Maintained as a distinct CNN scoring family; never pooled or Spearman-merged with Vina or AutoDock4 scores |

### Scientific notes per engine

- **AutoDock Vina `1.2.7`:** Empirical Vina score is not experimental binding free energy; inter-mode RMSD bounds are not crystallographic reference RMSD.
- **AutoDock4 (CPU) `4.2.6`:** Stock AutoGrid4 4.2.6 enforces 14 ligand and 20 receptor atom-type ceilings; Meeko macrocycle glue types (CG0/G0) fail preflight explicitly without coercion.
- **AutoDock-GPU `1.6`:** Parallel GPU search uses its own Solis-Wets/ADADELTA protocol and is not assumed bitwise reproducible (DOCKING_GPU_REPRODUCIBILITY_UNVERIFIED); requires compatible host vendor GPU driver.
- **GNINA `1.3.3`:** Built-in models pinned to verified GNINA 1.3.3 SHA-256: dense_1_3 (1 model, default), default_1_3_ensemble (3 KD models, CLI omits --cnn), and default1.0 (5 models). Under refinement, minimizedAffinity is evaluated on CNN-refined geometry and is not an independent empirical energy check. Deferred on Windows.
