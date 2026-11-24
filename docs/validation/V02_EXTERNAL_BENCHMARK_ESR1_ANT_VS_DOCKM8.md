# Ankora `v0.2` External Comparison Benchmark — `LIT-PCBA` `ESR_antago` (`5UFX`) vs. Pinned `DockM8 v1.1.1` (`ADR-031`)

- **Date:** 2026-11-23
- **Status:** Completed Two-Axis External Comparison on First Public Target (`ADMISSIBLE_TWO_AXIS_COMPARISON`); WSL2/WSLg Execution (`Ubuntu 24.04`, `RTX 5050 Laptop GPU CUDA 12.8`) — Single-Target Evidence Only (Does Not Extend Frozen `v0.1` Claims in [`VALIDATION_STATUS.md`](VALIDATION_STATUS.md) and Does Not Substitute for Bare-Metal Linux `Gate D6` or Multi-Target / Induced-Fit `FlexRes` Evaluation)
- **Governance:** [`ADR-030`](../architecture/ADR/ADR-030-rank-space-consensus-prioritization.md), [`ADR-031`](../architecture/ADR/ADR-031-external-benchmark-boundary.md), [`ADR-032`](../architecture/ADR/ADR-032-explicit-flexibility-and-pose-complex-identity.md), [`V02_EXTERNAL_BENCHMARK_PROTOCOL.md`](V02_EXTERNAL_BENCHMARK_PROTOCOL.md)
- **Primary Verdicts (Verbatim per `ADR-031 §3`, `PC-Q Neural` vs. `DockM8 ECR`, `N = 300` Locked Confirmation):**
  - **Axis A (`controlled`):** **`Insufficient evidence to prefer over baseline`** (`Ankora BEDROC_20 = 0.2659` vs. `DockM8 ECR BEDROC_20 = 0.3040`, paired `Δ = -0.0381`, `95% CI [-0.2044, +0.1184]`, `SE = 0.0827`).
  - **Axis B (`end_to_end`):** **`Insufficient evidence to prefer over baseline`** (`Ankora BEDROC_20 = 0.2707` vs. `DockM8 ECR BEDROC_20 = 0.1366`, paired `Δ = +0.1341`, `95% CI [-0.0582, +0.3339]`, `SE = 0.1015`; `ROC-AUC 0.6707` vs. `0.4703`).
- **Physical Pose Validity (`PoseBusters 0.6.5`, `config="dock"`):**
  - **Axis A (`controlled`):** Ankora **`274/287` (`95.47%`)** vs. DockM8 **`268/297` (`90.24%`)** (`+5.23 pp`; `PoseBusters`-stratified `Δ BEDROC_20 = -0.0335`, `95% CI [-0.2062, +0.1372]`, null verdict).
  - **Axis B (`end_to_end`):** Ankora **`289/296` (`97.64%`)** vs. DockM8 **`264/298` (`88.59%`)** (`+9.05 pp`; `4.9×` fewer failing poses on Ankora; `PoseBusters`-stratified `Δ BEDROC_20 = +0.1078`, `95% CI [-0.0981, +0.3206]`, null verdict).

---

## 1. Hard Architectural Separation & Pinned Identities (`ADR-031 §1`)

All external tooling (`DockM8 v1.1.1` clone, external Python `3.10` Conda environment `dockm8-external`, and raw benchmark artifacts under `<external-benchmark-root>/esr1-ant-v02-vs-dockm8/`) remained strictly outside the Ankora repository, lockfiles, `ankora-dev` runtime, and packaged installers. The one-directional evaluator (`python -S benchmarks/external_comparison/evaluate_comparison.py`) consumed Ankora exclusively via SHA-256-verified **`Export v5`** consensus ZIP bundles pre-checked by `scripts/verify_export_bundle.py --require-format 5`.

| Platform / Component | Version / Ref | Exact Commit / Executable SHA-256 | Notes |
| --- | --- | --- | --- |
| **Ankora `v0.2` (Docking / Export)** | `0.2.0-dev` (`codex/v0.2-dev`) | `24743342aa4a217d47d5701d5a1f6ba635ffb0a2` | Includes live multi-engine fixes `4a07c19` and `2474334` (Section 7). |
| **Ankora External Evaluator** | `codex/v0.2-dev` | `6672b98acd7ca8c089cf053eae131a2f2089963f` | Includes discrete Truchon & Bayly (2007) `BEDROC` normalization fix (`<= 1e-12` parity with `screening_benchmark._bedroc`, Section 7). |
| `Ankora` AutoDock Vina | `1.2.7` | `f31f774f723bba7bbe6e9d1c47577020eea9a8da16424284c043d22593570644` | Linux `x86_64` CPU |
| `Ankora` AutoGrid4 | `4.2.6` | `91621b89d13410efde31aed2a0934b15837172ef167d783bec0b3a94d384dc72` | Linux `x86_64` CPU |
| `Ankora` AutoDock4 | `4.2.6` | `15ac656b45db209655b1aae908ed1e06e743c7be4abb55b039f0bf38a6fd9fc9` | Canonical `epdb` cross-scoring |
| `Ankora` AutoDock-GPU | `1.6` (`128wi`) | `3e1bba7691983c97e1d64fef6cc45dd8306d54d10e5f81f50185694f06e8be78` | Native CUDA on `NVIDIA GeForce RTX 5050 Laptop GPU` |
| `Ankora` GNINA | `1.3.3` (`cuda12.8.static`) | `3340c1f49cd3c7c84d8699182a1c6af13c7fa2a22448d1204640446106f72172` | Native CUDA 12.8 on `RTX 5050` (`sm_120`) |
| `Ankora` PoseBusters | `0.6.5` (`config="dock"`) | Locked wheel `3e0cbca6481079d5ab7d1989a8a8f184dbba27366613c4b515658ea52fb95ea3` | Shared physical-validity evaluator across both platforms |
| **DrugBud-Suite / DockM8** | **`v1.1.1`** | **`3b765ea1122d01b6d3484ea25ec789f4456d8f8a`** | Isolated external Python `3.10` Conda env (`dockm8-external`) |
| `DockM8` bundled `gnina` (`SMINA` & `GNINA-All`/`Vinardo`/`AD4`) | `v1.1` (Dec 2023) | `cd5f12d88f63bef2f637ef183beb24f1620ba97944d88173b76fbd373e46d84f` | Aborts with `SIGABRT` on Blackwell `sm_120` CUDA; executed CPU-only (`CUDA_VISIBLE_DEVICES=""`, `14` CPUs). `smina_docking.py` invokes this binary. |
| `DockM8` bundled `KORP-PL` | `v1.1.1` asset | `cd1776c362005eb697ff4956dc8c872ef5431dda2f8cf8d0c2df78375ec24d8b` | CPU rescorer |
| `DockM8` bundled `LinF9` | `v1.1.1` asset | `01aa01529b1bef4141eac8420762d556f669fe635b59db23c2a2143b59dd0420` | CPU rescorer |

### Verified Bundle & Raw External Output Digests

| Artifact | Axis | SHA-256 |
| --- | --- | --- |
| `Ankora` Export v5 ZIP (`Ankora_ESR1_ant_AxisA_Controlled_PCQ_consensus-run-f86176a1_..._export-cfc8d01b_bundle.zip`) | `controlled` | `f83fc1fae045902055a809b6ab8f57fd1e24cce17158c77dba32924b4862f6cf` (`format=5`, `289` verified evidence files) |
| `Ankora` Export v5 ZIP (`Ankora_ESR1_ant_AxisB_EndToEnd_PCQ_consensus-run-1c9cff06_..._export-30c67ff7_bundle.zip`) | `end_to_end` | `fc6561609c9e77dc8c6306136837ed79a58f15ebf887eb95ece9c2c217de32d0` (`format=5`, `298` verified evidence files) |
| `DockM8` raw `ecr_consensus.csv` | `controlled` | `fe95180a9f43fa1f262e9b7820d0c3c080f7e70ceb084cb138b40fdd5bb11b77` |
| `DockM8` raw `rbr_consensus.csv` | `controlled` | `9ab1ca455c0a5e07f9d2a87e525c91c2661858a0be75e25abdb4463d8cea30e7` |
| `DockM8` raw `rescored_poses.csv` | `controlled` | `9b92cafb0297814e2a088d75ecf6012efeaf0e72da299b693c3e92c1570229b8` |
| `DockM8` raw `bestpose_selected.sdf` | `controlled` | `ad03db76ec6de7b18e257b2796144619b6b9a1035d6719a038c2c9eb6fc9004e` |
| `DockM8` raw `ecr_consensus.csv` | `end_to_end` | `195c683283c5e02d9ea6c12a703f7acfdf6ddf060590cfb0c6743cfd08db05fa` |
| `DockM8` raw `rbr_consensus.csv` | `end_to_end` | `0a19a1e78b0e79244dc20e72dd6397fbaa1d5a070b4282cc2448233d5097bfcc` |
| `DockM8` raw `rescored_poses.csv` | `end_to_end` | `6bcce5c69c95a0442af250329615fb869c3800204544e4c2e59c89ede7c10` |
| `DockM8` raw `bestpose_selected.sdf` | `end_to_end` | `45aa3b5235326462be928510375835067e321f795cbbd87721a610bfb87a7611` |
| Official Primary Report (`primary_pcq_neural_vs_dockm8_ecr_report.json`) | Both | Protocol `ee2754a3a94e759946b61f0feb000eb4db6aead41c408cc3f63b308103750767` / Report `d3720c441b479d395d5cf2edaf1b6679a6003f94f18f36c7a6979a351d917ba7` |

---

## 2. Frozen Cohort, Grouped Scaffold Split & Decoy Bias Audit (`ADR-031 §3`)

- **Target:** Public `LIT-PCBA` **`ESR_antago`** (`ESR1` antagonist, crystal template **`PDB 5UFX`**).
- **Deterministic data-independent cohort (`500` parent compounds):** All `88` actives + `412` SHA-256-deterministically sampled inactives from the locally frozen `LIT_PCBA_ANKORA_VS_V1` source files.
- **Sealed grouped split (`M2 ProtocolCalibrationService`):**
  - `calibration_id`: `8efacae2-8e8c-4204-8304-a69462262fee`
  - `grouping_strategy`: `parent_and_murcko_scaffold` (zero scaffold leakage between splits)
  - `split_identity_sha256`: **`33cb058cfaa44733f310a124d7d5ad5952219968514f5cdabdc444cea1797127`** (sealed prior to any docking execution)
  - **Calibration (`200` parents):** `35` actives, `165` inactives, `58` Murcko scaffolds (`200/200` prepared on Axis A controlled inputs).
  - **Locked Confirmation (`300` parents):** `53` actives, `247` inactives, `292` disjoint Murcko scaffolds (`297/300` prepared + `3` explicit `STEREOCHEMISTRY_REQUIRES_DECISION` failures retained as worst ties on Axis A).
- **Controlled Axis A search box (frozen `LIT-PCBA 5UFX` primary box):** `center = (-2.1045, -30.917, 21.770) Å`, `size = (17.181, 20.268, 22.648) Å`.
- **End-to-End Axis B search boxes (each platform independently from raw `5UFX` + co-crystal ligand):**
  - `Ankora`: `center = (-2.1045, -30.917, 21.770) Å`, `size = (17.181, 20.268, 22.648) Å` (Chain A, `topology_guard_v3`, `OXT` added on Chain A).
  - `DockM8`: `center = (-2.85, -31.43, 23.57) Å`, `size = (20.0, 20.0, 20.0) Å` (`--pocket_method Reference`, `PDBFixer` over Chains A+B).
- **`M2` 6-Property Decoy Bias Audit (recorded transparently per `ADR-031`):** `CALIBRATION_DECOY_PROPERTY_BIAS` flagged **`molecular_weight`** (`active median 315.72 Da` vs. `inactive 240.97 Da`, `SMD = +0.640`, `KS = 0.418`, `p = 5.93e-12`) and **`clogp`** (`3.34` vs. `1.85`, `SMD = +0.637`, `KS = 0.425`, `p = 2.38e-12`); `HBD`, `HBA`, `rotatable_bonds`, and `formal_charge` were unflagged. Enrichment on `ESR_antago` therefore partly reflects property discrimination alongside pose-specific recognition.

---

## 3. Stage 1 — Ankora `M2` Calibration (`N = 200`, `35` Actives / `165` Inactives)

Ankora docked all `200` Calibration parents across `Vina 1.2.7` (`200/200`, `410.6 s`), `AutoDock-GPU 1.6 CUDA` (`195/200`, `147.7 s`; `5` `CG0`/`G0` macrocycles), and `GNINA 1.3.3 CUDA` (`195/200`, `686.2 s`), clustered poses (`<= 2.0 Å`, `K_max = 3`, `598` medoids), cross-scored in place (`--score_only`, `704.2 s`), and sealed `ReferencePanelArtifact` `9c92e0b4-eb42-4daf-b10d-d7ccb0b576a6` (`SHA-256 a0448f0bf3c264f1afed19248151c7be94a6300e490eca60d17d46245a1248b9`).

| Ankora Calibration Protocol | `BEDROC_20` | `EF_1%` | `ROC-AUC` | `PR-AUC` | Scored / Total | Within `1-SE` of Best |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| **`autodock_gpu_only`** (`M2` selected) | **0.7570** | 5.71 | 0.7134 | 0.5673 | 195/200 | Yes (`best`) |
| **`vina_only`** | 0.6923 | 5.71 | **0.7688** | 0.5535 | 200/200 | **Yes** (`Δ = -0.0648`, `SE = 0.1073`) |
| `gnina_cnn_affinity_only` | 0.6255 | 2.86 | 0.7202 | 0.4763 | 195/200 | No |
| `gnina_cnn_vs_only` | 0.5475 | 5.71 | 0.5778 | 0.3692 | 195/200 | No |
| `pcq_core_v1` | 0.5167 | 2.86 | 0.6909 | 0.4031 | 195/200 | No |
| `pcq_neural_v1` | 0.5137 | 5.71 | 0.6221 | 0.3784 | 195/200 | No |
| `pc_ecr_v1` | 0.4721 | 5.71 | 0.6601 | 0.3775 | 195/200 | No |
| `gnina_cnn_score_only` | 0.2406 | 2.86 | 0.4461 | 0.1972 | 195/200 | No |

- **Scientific finding on Calibration:** `M2`'s `1-SE` parsimony gate selected `autodock_gpu_only` (`selection_identity_sha256 = 69b54f6fdcecbc440ace33e0811cfee61371563c015facd1add578bde343171e`) with `vina_only` within `1-SE`, **refusing to promote multi-engine `PC-Q` over the simpler single-engine empirical baseline on `5UFX`**. Inspection of Calibration medoid logs identified two physical causes: (1) evaluating Vina/GNINA-docked geometries in place on AutoDock4's rigid `0.375 Å` 12–6 Lennard-Jones grid without local minimization creates severe repulsive steric spikes (`+289` to `+127,000 kcal/mol`) on ~10% of cross-engine medoids, and (2) `GNINA CNNscore` (`0.2406`) acted as a weak early-enrichment ranker on `5UFX`. On single-use internal `M2` Confirmation (`confirmation_identity_sha256 = 8f34dd5f...`), `autodock_gpu_only` vs. `vina_only` yielded paired `Δ = -0.1333` (`95% CI [-0.2902, +0.0307]`), emitting verbatim **`"Insufficient evidence to prefer over baseline"`**.

---

## 4. Stage 2 — Official Two-Axis Comparison (`N = 300` Locked Confirmation: `53` Actives / `247` Inactives)

All official reports below were produced strictly via `python -S benchmarks/external_comparison/evaluate_comparison.py` (`2,000` paired parent-bootstrap replicates, `seed = 20261120`, `alpha = 20.0`, `top_fraction = 0.01`, failed/excluded/partial parents retained as worst ties in the invariant `300`-parent denominator).

### 4.1 Primary Pre-Declared Endpoint: `Ankora v0.2 PC-Q Neural` (`Export v5`) vs. `DockM8 v1.1.1 ECR`

| Axis | Platform | `BEDROC_20` | `EF_1%` | `ROC-AUC` | `PR-AUC` | Scored / Total | Failed Actives / Inactives | Paired `Δ BEDROC_20` (`95% CI`, `SE`) | Verbatim Verdict |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| **Axis A (`controlled`)** | **Ankora `PC-Q Neural`** | 0.2659 | 1.89 | 0.6032 | 0.2471 | 287/300 | **6 / 7** | `-0.0381` (`[-0.2044, +0.1184]`, `SE 0.0827`) | **Insufficient evidence to prefer over baseline** |
| **Axis A (`controlled`)** | **DockM8 `ECR`** | 0.3040 | 1.89 | 0.6448 | 0.2582 | 297/300 | 0 / 3 | — | — |
| **Axis B (`end_to_end`)** | **Ankora `PC-Q Neural`** | 0.2707 | 0.00 | **0.6707** | **0.2714** | 296/300 | **0 / 4** | `+0.1341` (`[-0.0582, +0.3339]`, `SE 0.1015`) | **Insufficient evidence to prefer over baseline** |
| **Axis B (`end_to_end`)** | **DockM8 `ECR`** | 0.1366 | 1.89 | 0.4703 | 0.1674 | 298/300 | 0 / 2 | — | — |

> **Critical Axis A vs. Axis B Mechanistic Diagnosis (Macrocycle Recovery & Preparation Collapse):**
> 1. On **Axis A (`controlled`)**, all **`6`** failed Ankora actives (`ESR144204375`, `ESR144204498`, `ESR144204524`, `ESR144205477`, `ESR144205501`, `ESR144213818`) plus `4` inactives were frozen `v0.1` Meeko PDBQT macrocycles containing `CG0`/`G0` ring-closure glue atoms unsupported by `AutoGrid4`/`AutoDock-GPU`, honestly retained as worst ties in Tier 2 (`partial_or_unscored`) per `ADR-030 E6`.
> 2. On **Axis B (`end_to_end`)**, Ankora `v0.2`'s **`M1` `MacrocyclePolicy.RIGID_INPUT_CONFORMATION` (`ADR-032`)** unlocked **`10/10`** macrocycles (`6/6` actives + `4/4` inactives, `0` failed actives; only `4` inactives were explicitly refused under `ADR-016` `LIG_STEREOCHEMISTRY_UNDEFINED`). Simultaneously, `DockM8 v1.1.1`'s own end-to-end preparation (`PDBFixer` + `GypsumDL` + `Reference` pocket) degraded its `ROC-AUC` from `0.6448` to **`0.4703`** (`-0.1745`, below random `0.50`) and its `BEDROC_20` from `0.3040` to **`0.1366`** (`-55%`).

### 4.2 Secondary Official Two-Axis Consensus Comparisons (`python -S evaluate_comparison.py`)

| Secondary Comparison | Axis | Ankora `BEDROC_20` (`ROC`) | DockM8 `BEDROC_20` (`ROC`) | Paired `Δ BEDROC_20` (`95% CI`) | Verbatim Verdict |
| --- | --- | ---: | ---: | --- | --- |
| `Ankora PC-Q Core` vs. `DockM8 ECR` | `controlled` | 0.2125 (0.6179) | 0.3040 (0.6448) | `-0.0915` (`[-0.2099, +0.0276]`) | Insufficient evidence to prefer over baseline |
| `Ankora PC-Q Core` vs. `DockM8 ECR` | `end_to_end` | 0.2400 (0.6767) | 0.1366 (0.4703) | `+0.1034` (`[-0.0869, +0.3008]`) | Insufficient evidence to prefer over baseline |
| `Ankora PC-ECR` (`τ=0.05`) vs. `DockM8 ECR` | `controlled` | 0.2507 (0.6113) | 0.3040 (0.6448) | `-0.0532` (`[-0.1922, +0.0786]`) | Insufficient evidence to prefer over baseline |
| `Ankora PC-ECR` (`τ=0.05`) vs. `DockM8 ECR` | `end_to_end` | 0.3332 (0.6462) | 0.1366 (0.4703) | `+0.1966` (`[-0.0184, +0.4101]`) | Insufficient evidence to prefer over baseline |
| `Ankora PC-Q Neural` vs. `DockM8 RBR` | `controlled` | 0.2659 (0.6032) | 0.3008 (0.6571) | `-0.0349` (`[-0.1948, +0.1121]`) | Insufficient evidence to prefer over baseline |
| `Ankora PC-Q Neural` vs. `DockM8 RBR` | `end_to_end` | 0.2707 (0.6707) | 0.0931 (0.4878) | **`+0.1776` (`[+0.0092, +0.3526]`)** | **`ankora_preferred`** |

### 4.3 Shared `PoseBusters 0.6.5` (`config="dock"`) Physical-Validity Stratification

Every selected pose from both platforms was audited with the exact same locked `PoseBusters 0.6.5` (`config="dock"`) checks against each platform's own prepared receptor geometry (`ADR-032 E8`).

| Axis | Platform | Evaluated | Passed (`Pass Rate`) | Failed | Check-Level Failure Breakdown | Valid-Only `BEDROC_20` | Paired Valid `Δ BEDROC_20` (`95% CI`) |
| --- | --- | ---: | ---: | ---: | --- | ---: | --- |
| **Axis A (`controlled`)** | **Ankora `PC-Q Neural`** | 287 | **274 (`95.47%`)** | **13** | `pb_internal_energy`: 9, `pb_internal_steric_clash`: 4, `pb_minimum_distance_to_protein`: 1 | 0.2659 | `-0.0335` (`[-0.2062, +0.1372]`, null) |
| **Axis A (`controlled`)** | **DockM8 `ECR`** | 297 | 268 (`90.24%`) | 29 | `pb_internal_energy`: 24, `pb_internal_steric_clash`: 6, `pb_minimum_distance_to_protein`: 3 | 0.2995 | — |
| **Axis B (`end_to_end`)** | **Ankora `PC-Q Neural`** | 296 | **289 (`97.64%`)** | **7** | `pb_internal_steric_clash`: 4, `pb_internal_energy`: 3, `pb_minimum_distance_to_protein`: 1 | 0.2741 | `+0.1078` (`[-0.0981, +0.3206]`, null) |
| **Axis B (`end_to_end`)** | **DockM8 `ECR`** | 298 | 264 (`88.59%`) | 34 | `pb_internal_energy`: 28, `pb_internal_steric_clash`: 4, `pb_minimum_distance_to_protein`: 3, `pb_non_aromatic_ring_non_flatness`: 1 | 0.1663 | — |

> **Receptor Geometry Audit Finding (`DockM8` Axis B vs. Ankora `ADR-025`):** `DockM8 v1.1.1`'s Axis B `prepared_receptor.pdb` (rebuilt via `PDBFixer` over Chains A+B, `8,038` atoms, without energy relaxation) contained **34 overlapping/pentavalent+ carbon atoms** under RDKit proximity-bond valence perception (up to degree `9` on `THR A 29 CA`), failing strict RDKit sanitization (`Explicit valence for atom # 6 C, 5, is greater than permitted`). To audit DockM8's Axis B poses fairly without penalizing them for their receptor file failing RDKit proximity bonding, the external benchmark script loaded DockM8's Axis B receptor with `proximityBonding=False` after empirically verifying **`0/10`** check differences against `proximityBonding=True` on Axis A and **`5/5`** agreement with native `PoseBusters(config="dock").bust(..., str(pdb))`. Ankora's `ADR-025` `topology_guard_v3` Chain A receptor passed strict RDKit sanitization with `0` valence defects.

---

## 5. Full Component Breakdown & `M2` Calibration-Selected Single-Engine Comparisons

To avoid hiding component behavior behind consensus aggregates, every individual Ankora engine and every individual `DockM8` rescorer was scored on the identical `300`-parent Locked Confirmation denominator:

| Platform & Component | Axis A `BEDROC_20` (`EF_1%` / `ROC` / `PR`) | Axis A Scored | Axis B `BEDROC_20` (`EF_1%` / `ROC` / `PR`) | Axis B Scored |
| --- | --- | ---: | --- | ---: |
| `Ankora` `GNINA 1.3.3 CNN_VS` | **0.4251** (`5.66` / `0.6097` / `0.3245`) | 287/300 | 0.3935 (`5.66` / `0.6283` / `0.3114`) | 296/300 |
| `Ankora` `GNINA 1.3.3 CNNaffinity` | 0.3752 (`3.77` / `0.6176` / `0.2949`) | 287/300 | **0.4054** (`3.77` / **`0.6720`** / **`0.3159`**) | 296/300 |
| `Ankora` `GNINA 1.3.3 CNNscore` | 0.3255 (`1.89` / `0.5415` / `0.2419`) | 287/300 | 0.2701 (`3.77` / `0.5398` / `0.2371`) | 296/300 |
| `Ankora` `Vina 1.2.7` (`1-SE` on Cal) | 0.3099 (`1.89` / `0.6124` / `0.2554`) | 297/300 | 0.3383 (`1.89` / `0.6416` / `0.2747`) | 296/300 |
| `Ankora` `AutoDock-GPU 1.6` (Cal best) | 0.1766 (`0.00` / `0.5794` / `0.2136`) | 287/300 | 0.1400 (`0.00` / `0.6546` / `0.2350`) | 296/300 |
| `Ankora` `PC-ECR` (`τ=0.05`) | 0.2507 (`1.89` / `0.6113` / `0.2462`) | 287/300 | 0.3332 (`0.00` / `0.6462` / `0.2735`) | 296/300 |
| `Ankora` `PC-Q Neural` | 0.2659 (`1.89` / `0.6032` / `0.2471`) | 287/300 | 0.2707 (`0.00` / `0.6707` / `0.2714`) | 296/300 |
| `Ankora` `PC-Q Core` | 0.2125 (`0.00` / `0.6179` / `0.2438`) | 287/300 | 0.2400 (`0.00` / `0.6767` / `0.2681`) | 296/300 |
| `DockM8` `CNN-Affinity` (`gnina v1.1`) | **0.4363** (`3.77` / **`0.6969`** / **`0.3402`**) | 297/300 | 0.1138 (`0.00` / `0.4990` / `0.1746`) | 298/300 |
| `DockM8` `ECR` (5-rescorer consensus) | 0.3040 (`1.89` / `0.6448` / `0.2582`) | 297/300 | 0.1366 (`1.89` / `0.4702` / `0.1675`) | 298/300 |
| `DockM8` `RBR` (5-rescorer consensus) | 0.3008 (`1.89` / `0.6571` / `0.2733`) | 297/300 | 0.0931 (`0.00` / `0.4878` / `0.1681`) | 298/300 |
| `DockM8` `LinF9` | 0.2940 (`0.00` / `0.6391` / `0.2581`) | 297/300 | 0.1136 (`0.00` / `0.4911` / `0.1722`) | 298/300 |
| `DockM8` `GNINA-Affinity` | 0.2644 (`0.00` / `0.6206` / `0.2458`) | 297/300 | 0.1913 (`0.00` / `0.5155` / `0.1895`) | 298/300 |
| `DockM8` `SMINA_Affinity` | 0.2635 (`0.00` / `0.6206` / `0.2456`) | 297/300 | 0.1912 (`0.00` / `0.5155` / `0.1894`) | 298/300 |
| `DockM8` `AD4` | 0.2379 (`0.00` / `0.6175` / `0.2365`) | 297/300 | 0.1553 (`1.89` / `0.4692` / `0.1715`) | 298/300 |
| `DockM8` `Vinardo` | 0.2245 (`0.00` / `0.6200` / `0.2422`) | 297/300 | 0.1902 (`1.89` / `0.5479` / `0.2004`) | 298/300 |
| `DockM8` `CNN-Score` | 0.2211 (`0.00` / `0.5132` / `0.1995`) | 297/300 | 0.0857 (`0.00` / `0.4581` / `0.1593`) | 298/300 |
| `DockM8` `KORP-PL` | 0.2133 (`0.00` / `0.6394` / `0.2446`) | 297/300 | 0.0729 (`0.00` / `0.4513` / `0.1550`) | 298/300 |

### Paired Parent-Bootstrap Comparison of Individual Ankora Engines vs. `DockM8 ECR` (Exploratory / Secondary)

| Ankora Single Engine vs. `DockM8 ECR` | Axis A `Δ BEDROC_20` (`95% CI`, Verdict) | Axis B `Δ BEDROC_20` (`95% CI`, Verdict) |
| --- | --- | --- |
| `Ankora AutoDock-GPU 1.6` (Cal best) | `-0.1274` (`[-0.2788, +0.0284]`, null) | `+0.0034` (`[-0.1600, +0.1639]`, null) |
| `Ankora Vina 1.2.7` (`1-SE` on Cal) | `+0.0060` (`[-0.1386, +0.1518]`, null) | `+0.2017` (`[-0.0170, +0.4110]`, null) |
| `Ankora GNINA 1.3.3 CNNaffinity` | `+0.0712` (`[-0.1098, +0.2344]`, null) | **`+0.2688` (`[+0.0331, +0.4846]`, `ankora_preferred`)** |
| `Ankora GNINA 1.3.3 CNN_VS` | `+0.1211` (`[-0.0992, +0.3142]`, null) | **`+0.2569` (`[+0.0225, +0.4715]`, `ankora_preferred`)** |

---

## 6. Wall-Clock Execution Profile

| Run | Platform | Wall-Clock Time | Breakdown |
| --- | --- | ---: | --- |
| Stage 1 Calibration (`200` parents) | Ankora `v0.2` (3 engines + `M5`) | `1,948.7 s` (`32.5 min`) | Vina `410.6 s` + AD-GPU CUDA `147.7 s` + GNINA CUDA `686.2 s` + Cluster/Rescore (`598` medoids) `704.2 s` |
| Axis A (`controlled`, `300` parents) | Ankora `v0.2` (3 engines + `M5` + `M3`) | `4,315.0 s` (`71.9 min`) | Vina `1,105.0 s` + AD-GPU CUDA `273.6 s` + GNINA CUDA `1,377.2 s` + Cluster/Rescore (`891` medoids) `1,229.7 s` + PoseBusters `326.3 s` |
| Axis B (`end_to_end`, `300` parents) | Ankora `v0.2` (prep + 3 engines + `M5` + `M3`) | `4,670.8 s` (`77.8 min`) | Receptor/Site `7.0 s` + Ligands `140.9 s` + Vina `1,132.9 s` + AD-GPU CUDA `271.7 s` + GNINA CUDA `1,490.4 s` + Cluster/Rescore (`888` medoids) `1,282.7 s` + PoseBusters `340.4 s` |
| Axis A (`controlled`, `300` parents) | DockM8 `v1.1.1` (SMINA + 5 rescorers, CPU `14` threads) | `777.9 s` (`13.0 min`) | SMINA `768.3 s` + 5 rescorers `9.1 s` (external shared PoseBusters audit `+327.4 s`) |
| Axis B (`end_to_end`, `300` parents) | DockM8 `v1.1.1` (full CLI, CPU `14` threads) | `893.0 s` (`14.9 min`) | Full CLI incl. `PDBFixer` + `GypsumDL` + `SMINA` + 5 rescorers (external shared PoseBusters audit `+243.3 s`) |

*Trade-off disclosed honestly:* `DockM8 v1.1.1` ran `~5.2–5.5×` faster end-to-end because it runs **one** docking engine (`SMINA`) and rescores in-place without cross-engine pose sampling or physical-validity auditing; Ankora `v0.2` ran **three independent search engines** (`Vina` CPU, `AutoDock-GPU` CUDA, `GNINA 1.3.3` CUDA), pose clustering, cross-engine `--score_only` (`AutoDock4 epdb` + `Vina` + `Vinardo` + `GNINA`), and per-pose `PoseBusters 0.6.5`. Note also that Ankora's `AutoDock-GPU 1.6 CUDA` alone docked `296` ligands in `271.7 s` (`4.5 min`).

---

## 7. Real Engineering & Scientific Defects Uncovered During Live Execution

Running this real multi-engine heterogeneous library benchmark exposed **three real Ankora bugs** (fixed immediately with regression tests on `codex/v0.2-dev`) and **four real operational contrasts** in pinned `DockM8 v1.1.1`:

### Ankora `v0.2` Bugs Discovered & Fixed Live (`codex/v0.2-dev`)
1. **`4a07c19` (`fix(m5): reconstruct Meeko pose topology before RMSD clustering`):** `adapters/chemistry/pose_clustering.py` previously parsed PDBQT via RDKit proximity bonding, causing `RuntimeError: No sub-structure match found` in `CalcRMS` when sterically self-clashing GNINA poses acquired spurious proximity bonds or `CG0`/`G0` macrocycle glue atoms appeared. Fixed by Meeko-first exact-topology reconstruction (`meeko.PDBQTMolecule`) + strict bond-count fallback + per-parent domain-error containment in `services/pose_consensus.py` (`2,425/2,425` Calibration poses loaded cleanly; regression test in `test_v02_m5a_clustering_and_pcq_math.py`).
2. **`2474334` (`fix(m2a): strip AutoDock DLG USER/NEWDPF/TER envelope tags before Vina score_only`):** `_strip_pose_envelope_for_staging()` in `services/pose_rescoring.py` previously stripped only `MODEL`/`ENDMDL`, causing `Vina 1.2.7 --score_only` to reject `100%` of AutoDock4/AutoDock-GPU `.dlg`-extracted medoids (`exit=1: Unknown or inappropriate tag: USER`). Fixed on temporary staging copies only while preserving original `.dlg` pose bytes immutable (regression test in `test_v02_m2a_score_only.py`).
3. **`6672b98` (`fix(benchmarks): align evaluate_comparison.py discrete BEDROC normalization with Truchon & Bayly (2007)`):** Live verification flagged implausibly small `BEDROC_20` outputs (`~0.013` despite `ROC-AUC = 0.67`), exposing a normalization error in `benchmarks/external_comparison/evaluate_comparison.py` (`denom_term` used `(1 - exp(-α·ra))/(1 - exp(-α))` instead of discrete Truchon & Bayly Eq. 18 `(-expm1(-α)) / N / expm1(α / N)`). Fixed to match `ankora_backend.services.screening_benchmark._bedroc` to `<= 1e-12` with an explicit parity regression test in `test_v02_m6b_external_benchmark_and_budget.py`.

### Operational & Scientific Contrasts Observed in Pinned `DockM8 v1.1.1` (`3b765ea`)
1. **NVIDIA Blackwell (`sm_120`, CUDA 12.8) incompatibility:** `DockM8 v1.1.1` ships `gnina v1.1` (Dec 2023), which aborts with `SIGABRT` on RTX 5050 CUDA, requiring `CUDA_VISIBLE_DEVICES=""` CPU fallback; Ankora `v0.2`'s `GNINA 1.3.3` and `AutoDock-GPU 1.6` executed natively on RTX 5050 CUDA.
2. **Compound ID underscore parsing crash:** `DockM8`'s `pose_selection.py:69` splits `Pose ID` on `"_"` and crashes when input compound IDs contain underscores (mitigated externally via underscore-free IDs `ESR<id>` in the benchmark inputs).
3. **Unminimized receptor loop defects:** `DockM8` Axis B `PDBFixer` left `34` pentavalent+ overlapping carbons across Chains A+B without topology-guarded relaxation, and its end-to-end `ROC-AUC` dropped from `0.6448` (Axis A) to `0.4703` (Axis B).
4. **Silent chemistry fallbacks vs. fail-closed `ADR-016`:** `DockM8`'s `GypsumDL` silently enumerated undefined stereocenters and lost `2` compounds silently in SMINA (`298/300`), whereas Ankora explicitly refused `4` undefined-stereocenter inactives (`ADR-016`) and retained them visibly in the denominator.

---

## 8. Scope Boundaries & Next Scientific Steps

1. **Single-target, rigid-receptor scope:** This record covers **one** public target (`LIT-PCBA` `ESR_antago` / `5UFX`, `500` parents) under rigid receptor coordinates in WSL2/WSLg. Generalization claims require executing the full multi-target suite (including `PPARG`, `TP53`, and at least one induced-fit `apo` / gatekeeper-rotamer `FlexRes` target per `V02_EXTERNAL_BENCHMARK_PROTOCOL.md §4`) and completing physical bare-metal Linux workstation **`Gate D6`**.
2. **Actionable scientific lesson for `PC-Q` (`v0.2.1+`):** Cross-scoring unminimized Vina/GNINA poses in place on rigid `0.375 Å` AutoDock4 grids penalized `PC-Q` relative to single-engine `GNINA 1.3.3` (`0.4054` / `0.3935` on Axis B) and `Vina 1.2.7` (`0.3383`). Future consensus iterations can investigate bounded create-only local minimization (`--local_only`) prior to cross-family scoring under preregistered Calibration/Confirmation discipline, while keeping `M2`'s `1-SE` Calibration gate active so Ankora never forces consensus when a simpler calibrated engine performs better.
