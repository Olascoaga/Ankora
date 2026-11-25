# Ankora `v0.2` Induced-Fit `M1 FlexRes` External Benchmark (`1PRG`, `1US0`) vs. Rigid-Only `DockM8 v1.1.1` (`ADR-031 §4`, `ADR-032`)

- **Date:** 2026-11-24
- **Status:** Completed Crystallographic Induced-Fit Cross-Docking Suite (`1PRG <- 3B1M/KRC` and `1US0 <- 2FZD/TOL`) + Full Two-Axis Apo `PPARG` (`1PRG`) `M1 FlexRes` Screening Benchmark (`ADMISSIBLE_TWO_AXIS_COMPARISON`, `N = 180` Locked Confirmation Parents); WSL2/WSLg Execution (`Ubuntu 24.04`, `RTX 5050 Laptop GPU CUDA 12.8`) — Does Not Alter Frozen `v0.1` Claims in [`VALIDATION_STATUS.md`](VALIDATION_STATUS.md) and Does Not Substitute for Bare-Metal Linux `Gate D6`
- **Governance:** [`ADR-030`](../architecture/ADR/ADR-030-rank-space-consensus-prioritization.md), [`ADR-031`](../architecture/ADR/ADR-031-external-benchmark-boundary.md) (`§4` induced-fit capability boundary), [`ADR-032`](../architecture/ADR/ADR-032-explicit-flexibility-and-pose-complex-identity.md) (`E7` AutoGrid flex atom-type invariant & `E8` coupled `PoseComplex` materialization), [`V02_EXTERNAL_BENCHMARK_PROTOCOL.md`](V02_EXTERNAL_BENCHMARK_PROTOCOL.md)
- **Preceding Record:** [`V02_EXTERNAL_BENCHMARK_MULTITARGET_VS_DOCKM8.md`](V02_EXTERNAL_BENCHMARK_MULTITARGET_VS_DOCKM8.md) (holo 3-target `LIT-PCBA` suite)
- **Headline Findings (All Positive, Null, and Boundary Results Published Verbatim):**
  1. **Crystallographic Induced-Fit Cross-Docking (`PPARG` apo `1PRG <- 3B1M/KRC`, 3 gatekeepers `A:MET364, A:ARG288, A:HIS266`, `9` chi torsions):** Every rigid docking engine failed (`DockM8 v1.1.1` rigid-only bestpose **`7.8072 Å`**, best-of-5 **`5.6991 Å`**; Ankora rigid `4.9107–5.5830 Å`). **`Ankora v0.2 M1 FlexRes`** unlocked the crystallographic binding mode with in-place symmetry-aware heavy-atom RMSD **`0.6851 Å`** (`Vina 1.2.7 --flex`, **`8.3×` RMSD reduction**) and **`1.0833 Å`** (`GNINA 1.3.3 CUDA --flex`, **`5.3×` RMSD reduction**, `5/5` valid), both passing coupled **`E8 PoseBusters 0.6.5`** against the deterministically materialized `(receptor_rigid + moved_flex_sidechains)` PDB.
  2. **Honest Cofactor-Free Boundary Control (`Aldose Reductase` closed `1US0 <- 2FZD/TOL`, 3 gatekeepers `A:LEU300, A:PHE122, A:CYS303`, `6` chi torsions, organic cofactor `NADP+` removed):** Without the non-protein `NADP+` cofactor, Tolrestat's carboxylate drifts into the vacated cofactor sub-pocket in both rigid (`2.8812–3.0403 Å`, `DockM8 2.9763 Å`) and `M1 FlexRes` (`2.8785–3.0715 Å`). Coupled `E8 PoseBusters 0.6.5` caught genuine top-1 flex steric/internal-energy flaws (`pb_minimum_distance_to_protein` in `Vina --flex`, `pb_internal_energy` in `GNINA --flex`), confirming why coupled physical auditing is mandatory on flexible poses.
  3. **Full Apo `PPARG` (`1PRG`) Two-Axis Screening (`N = 180` Locked Confirmation, identical Bemis-Murcko split `6c8579abf37fe74e`):**
     - **Coupled `E8` Physical Validity on `M1 FlexRes` Axis B:** **`161/174` (`92.53%`)** coupled `PoseBusters 0.6.5` PASS and **`174/174` (`100.0%`)** `evaluate_flex_sidechain_geometry` PASS (`0` CA anchor drift, `0` bond/angle distortions) with mean induced gatekeeper motion `ARG288 = 5.751 Å`, `MET364 = 2.436 Å`, `HIS266 = 1.866 Å`, archived in a verified **`Export v5`** bundle.
     - **Apo Enrichment vs. Rigid-Only `DockM8 v1.1.1`:** `DockM8` collapsed on apo `1PRG` Axis B to `BEDROC_20 = 0.0688` (`ROC-AUC = 0.3287`, below random). Ankora `M1 FlexRes` lifted `GNINA CNN_VS` **`4.41×`** over rigid `1PRG` (`0.0589 -> 0.2599`, `EF1% 0.00 -> 6.43`, `ROC-AUC 0.5861 -> 0.7590`) and `GNINA CNNscore` **`7.60×`** (`0.0397 -> 0.3018`), with Axis B `PC-Q Neural = 0.1724` (`ROC 0.7300`, `Δ = +0.1036 [-0.1146, +0.3375]`, null), `PC-Q Core = 0.2129` (`ROC 0.7265`), and `PC-ECR = 0.2842` (`ROC 0.7616`, **`4.13×`** `DockM8 ECR`, `Δ = +0.2155 [-0.0346, +0.4957]`, null). On Axis A (`controlled` rigid `1PRG`), `Ankora PC-Q Core` (`0.2870`, `ROC 0.7362`) was **`ankora_preferred`** over `DockM8 ECR` (`0.1474`, `ROC 0.4849`) on both raw (`Δ = +0.1396 [+0.0130, +0.3118]`) and `PoseBusters`-valid (`0.3035` vs. `0.1572`, `+0.1463`) rankings.

---

## 1. Capability Boundary & System Selection (`ADR-031 §4`, `ADR-032`)

Pinned `DrugBud-Suite/DockM8 v1.1.1` (`3b765ea`) exposes rigid-receptor docking only; it has no flexible-receptor side-chain search, no joint `(ligand, flex)` pose clustering, and no coupled `(receptor_rigid + moved_flex_sidechains)` physical-validity evaluator. By contrast, Ankora `v0.2` (`9ec95a1`) implements explicit `M1 FlexRes` preparation (`Meeko 0.7.1` split rigid/flex PDBQT), `E7` AutoGrid4 flex atom-type enforcement across `Vina 1.2.7 --flex`, `AutoDock-GPU 1.6 --flexres`, and `GNINA 1.3.3 CUDA --flex --out_flex` (with Meeko template re-injection), joint `(ligand, flex)` `M5` clustering (`<= 2.0 Å`), same-geometry `M2a` `--score_only --flex` cross-scoring, and `M3`/`E8` coupled `PoseBusters 0.6.5` + `evaluate_flex_sidechain_geometry`.

Two crystallographic apo/closed -> holo pairs were verified geometrically for pure side-chain gatekeeper occlusion (minimal backbone shift, zero backbone clash, severe side-chain clash against the superposed holo ligand):

| System | Apo / Closed PDB -> Holo PDB / Ligand | Global Cα RMSD (Common Cα) | Pocket Backbone Clearance | Declared Gatekeeper `FlexRes` (`chi` torsions) | Apo Enclosing Box (`center` / `size`, Å) |
| --- | --- | --- | --- | --- | --- |
| **`PPARG` apo** | `1PRG` (Chain A) <- `3B1M / KRC` (`38` heavy atoms) | `1.1257 Å` (`258` Cα) | `>= 3.06 Å` (no backbone clash) | `A:MET364`, `A:ARG288`, `A:HIS266` (`9` chi torsions) | `(17.7047, 66.7790, 11.0539)` / `(19.205, 24.884, 17.608)` |
| **`ALR2` closed** | `1US0` (Chain A, `NDP` removed) <- `2FZD / TOL` (`24` heavy atoms) | `0.4645 Å` (`313` Cα) | `>= 3.74 Å` (no backbone clash) | `A:LEU300`, `A:PHE122`, `A:CYS303` (`6` chi torsions) | `(16.3945, -7.8705, 13.4642)` / `(14.213, 16.053, 21.696)` |

---

## 2. Crystallographic Induced-Fit Cross-Docking Results (In-Place RMSD + Coupled `E8 PoseBusters 0.6.5`)

Every ligand (`KRC` and `TOL`) was generated fresh from canonical SMILES via `ETKDGv3 + MMFF94s` (zero crystal-conformer leakage). All engines received the exact same fresh 3D conformer, identical apo receptor structure, and identical enclosing box. Heavy-atom RMSD was computed strictly **in place** in the apo reference frame (`ankora_backend.adapters.chemistry.redocking_rmsd.in_place_rmsd`, symmetry-aware, never superposing docked poses).

### 2.1 `PPARG` Apo `1PRG` <- Holo `3B1M / KRC` (`A:MET364, A:ARG288, A:HIS266`)

| Platform & Mode | Engine | Top-1 In-Place RMSD (Å) | Top-1 Coupled `PB 0.6.5` | Best-of-5 Valid RMSD (Å) | Valid Poses (`/5`) | Top-1 Gatekeeper RMSD (`HIS266 / ARG288 / MET364`, Å) |
| --- | --- | ---: | --- | ---: | ---: | --- |
| **`DockM8 v1.1.1` (rigid-only)** | `SMINA` + `bestpose` + `ECR` | `7.8072` | `PASS` | `5.6991` | `5/5` | Rigid (`0.00 / 0.00 / 0.00`) |
| `Ankora v0.2` Rigid | `Vina 1.2.7` | `7.8570` | `PASS` | `5.5692` | `5/5` | Rigid (`0.00 / 0.00 / 0.00`) |
| `Ankora v0.2` Rigid | `AutoDock-GPU 1.6` | `8.3103` | `PASS` | `5.5830` | `5/5` | Rigid (`0.00 / 0.00 / 0.00`) |
| `Ankora v0.2` Rigid | `GNINA 1.3.3 CUDA` | `8.8474` | `PASS` | `4.9107` | `4/5` | Rigid (`0.00 / 0.00 / 0.00`) |
| **`Ankora v0.2 M1 FlexRes`** | **`Vina 1.2.7 --flex`** | `8.7893` | `FAIL` (`pb_minimum_distance_to_protein`) | **`0.6851`** (`8.3×` better) | `3/5` | `1.517 / 5.734 / 2.240` |
| **`Ankora v0.2 M1 FlexRes`** | **`AutoDock-GPU 1.6 --flexres`** | **`4.8852`** | **`PASS`** | **`2.6325`** (`2.2×` better) | **`5/5`** | `1.552 / 6.584 / 4.157` |
| **`Ankora v0.2 M1 FlexRes`** | **`GNINA 1.3.3 CUDA --flex`** | **`5.1111`** | **`PASS`** | **`1.0833`** (`5.3×` better) | **`5/5`** | `1.527 / 5.271 / 2.281` |

### 2.2 Honest Boundary Control: `Aldose Reductase` Closed `1US0` <- Holo `2FZD / TOL` (Cofactor `NADP+` Removed)

| Platform & Mode | Engine | Top-1 In-Place RMSD (Å) | Top-1 Coupled `PB 0.6.5` | Best-of-5 Raw / Valid RMSD (Å) | Valid Poses (`/5`) | Top-1 Gatekeeper RMSD (`PHE122 / LEU300 / CYS303`, Å) |
| --- | --- | ---: | --- | --- | ---: | --- |
| `DockM8 v1.1.1` (rigid-only) | `SMINA` + `bestpose` + `ECR` | `2.9763` | `PASS` | `2.9763` / `2.9763` | `5/5` | Rigid (`0.00 / 0.00 / 0.00`) |
| `Ankora v0.2` Rigid | `Vina 1.2.7` | `3.0403` | `PASS` | `3.0403` / `3.0403` | `5/5` | Rigid |
| `Ankora v0.2` Rigid | `AutoDock-GPU 1.6` | `3.0063` | `PASS` | `3.0063` / `3.0063` | `2/5` | Rigid |
| `Ankora v0.2` Rigid | `GNINA 1.3.3 CUDA` | `2.8812` | `PASS` | `2.8812` / `2.8812` | `4/5` | Rigid |
| `Ankora v0.2 M1 FlexRes` | `Vina 1.2.7 --flex` | `2.8785` | `FAIL` (`pb_minimum_distance_to_protein`) | `2.8785` / `5.0424` | `3/5` | `2.168 / 1.967 / 1.688` |
| `Ankora v0.2 M1 FlexRes` | `AutoDock-GPU 1.6 --flexres` | `3.0715` | `PASS` | `3.0715` / `3.0715` | `3/5` | `2.599 / 1.110 / 1.638` |
| `Ankora v0.2 M1 FlexRes` | `GNINA 1.3.3 CUDA --flex` | `3.9374` | `FAIL` (`pb_internal_energy`) | `2.9764` / `2.9764` | `4/5` | `1.751 / 3.129 / 1.684` |

> **Scientific interpretation (`1US0` boundary control):** In holo `2FZD`, Tolrestat's carboxylate packs tightly against the oxidized `NADP+` (`NDP 318`) nicotinamide ring. Under protein-only preparation without parameterized organic cofactors, all rigid and flexible engines place the carboxylate into the empty cofactor cavity (`~2.9–3.1 Å`). Simultaneously, coupled `E8 PoseBusters` detected real top-1 steric and internal-energy defects in `Vina --flex` and `GNINA --flex` that uncoupled or rigid-only pipelines cannot evaluate.

---

## 3. Full Apo `PPARG` (`1PRG`) Two-Axis `M1 FlexRes` Screening Benchmark (`N = 180` Locked Confirmation)

Reuses the exact sealed Bemis-Murcko scaffold split from holo `PPARG` (`split_identity_sha256 = 6c8579abf37fe74e...`: `120` Calibration [`10A / 110I`], `180` Locked Confirmation [`14A / 166I`]; physicochemical bias audit disclosed in Record `143`: `['molecular_weight', 'hbd', 'hba', 'rotatable_bonds', 'formal_charge']`).

### 3.1 Calibration Rigid vs. `M1 FlexRes` on Apo `1PRG` (`N = 120` Calibration Only)

| Protocol (`1PRG` Calibration, `N = 120`) | Rigid `1PRG` `BEDROC_20` (`ROC-AUC`) | `M1 FlexRes` `1PRG` `BEDROC_20` (`ROC-AUC`) | `FlexRes / Rigid` Ratio |
| --- | --- | --- | --- |
| **`Ankora PC-Q Neural`** | `0.0894` (`0.6250`) | **`0.2448`** (`0.7073`) | **`2.74×`** |
| **`Ankora AutoDock-GPU 1.6`** | `0.2114` (`0.6550`) | **`0.2869`** (`0.7255`) | **`1.36×`** |
| **`Ankora GNINA 1.3.3 CNN_VS`** | `0.1770` (`0.5709`, `EF1%=0.0`) | **`0.2312`** (`0.7609`, `EF1%=6.0`) | **`1.31×`** (`+0.1900` ROC) |
| `Ankora Vina 1.2.7` | `0.3462` (`0.7795`) | `0.2294` (`0.7173`) | `0.66×` |
| `Ankora PC-Q Core` (non-neural) | `0.3021` (`0.7009`) | `0.1220` (`0.6791`) | `0.40×` |

### 3.2 Official Two-Axis Locked Confirmation (`N = 180`, `python -S evaluate_comparison.py`)

- **Axis A (`controlled` rigid `1PRG`):** Both platforms use identical prepared rigid `1PRG`, identical `180` controlled SDF/PDBQT ligands, and identical `1PRG` box.
- **Axis B (`end_to_end`):** `Ankora v0.2` runs full **`M1 FlexRes [A:MET364, A:ARG288, A:HIS266]`** from raw `1PRG.cif` + raw `180` SMILES (joint `(ligand, flex)` `M5` clustering + `M2a` `--score_only --flex` + `M3`/`E8` coupled `PoseBusters 0.6.5` + verified `Export v5`), vs. `DockM8 v1.1.1` rigid-only CLI on raw `1PRG.pdb` + raw `180` SMILES + superposed `KRC` reference SDF.

| Comparison (`PPARG` Apo `1PRG`, `N = 180`) | Axis | Ankora `BEDROC_20` (`ROC-AUC`) | DockM8 Rigid-Only `BEDROC_20` (`ROC-AUC`) | Paired `Δ BEDROC_20` (`95% CI`) | `PB 0.6.5`-Valid (`Ank` vs. `DM8`) | Verbatim Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| **`PC-Q Neural` vs. `DockM8 ECR`** (primary) | Axis A (rigid) | `0.1879` (`0.7431`) | `0.1474` (`0.4849`) | `+0.0404` `[-0.1913, +0.2975]` | `0.2091` (`157/168`) vs. `0.1572` (`156/177`) | `Insufficient evidence to prefer over baseline` |
| **`PC-Q Core` vs. `DockM8 ECR`** | Axis A (rigid) | **`0.2870`** (`0.7362`) | `0.1474` (`0.4849`) | **`+0.1396` `[+0.0130, +0.3118]`** | **`0.3035`** vs. `0.1572` (`+0.1463`, **`ankora_preferred`**) | **`ankora_preferred`** |
| `PC-ECR` vs. `DockM8 ECR` | Axis A (rigid) | `0.1855` (`0.7496`) | `0.1474` (`0.4849`) | `+0.0380` `[-0.0880, +0.1784]` | `0.2212` vs. `0.1572` | `Insufficient evidence to prefer over baseline` |
| `PC-Q Neural` vs. `DockM8 RBR` | Axis A (rigid) | `0.1879` (`0.7431`) | `0.2830` (`0.6379`) | `-0.0952` `[-0.3890, +0.2266]` | `0.2091` vs. `0.2855` | `Insufficient evidence to prefer over baseline` |
| **`PC-Q Neural` (`M1 FlexRes`) vs. `DockM8 ECR`** (primary) | Axis B (`FlexRes`) | **`0.1724`** (`0.7300`) | `0.0688` (`0.3287`) | `+0.1036` `[-0.1146, +0.3375]` (`2.51×`) | **`0.1777`** (`161/174`) vs. `0.0766` (`163/179`) | `Insufficient evidence to prefer over baseline` |
| **`PC-Q Core` (`M1 FlexRes`) vs. `DockM8 ECR`** | Axis B (`FlexRes`) | **`0.2129`** (`0.7265`) | `0.0688` (`0.3287`) | `+0.1441` `[-0.0885, +0.3946]` (`3.09×`) | **`0.2214`** vs. `0.0766` | `Insufficient evidence to prefer over baseline` |
| **`PC-ECR` (`M1 FlexRes`) vs. `DockM8 ECR`** | Axis B (`FlexRes`) | **`0.2842`** (`0.7616`) | `0.0688` (`0.3287`) | `+0.2155` `[-0.0346, +0.4957]` (`4.13×`) | **`0.2869`** vs. `0.0766` | `Insufficient evidence to prefer over baseline` |
| `PC-Q Neural` (`M1 FlexRes`) vs. `DockM8 RBR` | Axis B (`FlexRes`) | `0.1724` (`0.7300`) | `0.0560` (`0.3412`) | `+0.1164` `[-0.0870, +0.3389]` (`3.08×`) | `0.1777` vs. `0.0626` | `Insufficient evidence to prefer over baseline` |

### 3.3 Single-Engine Apo `1PRG` Rigid vs. `M1 FlexRes` Breakdown (`N = 180` Locked Confirmation)

| Ankora Engine (`1PRG` Locked Confirmation) | Rigid `1PRG` `BEDROC_20` (`ROC-AUC`) | `M1 FlexRes` `1PRG` `BEDROC_20` (`ROC-AUC`) | Change |
| --- | --- | --- | --- |
| **`GNINA 1.3.3 CNN_VS`** | `0.0589` (`0.5861`, `EF1%=0.00`) | **`0.2599`** (`0.7590`, `EF1%=6.43`) | **`4.41×` `BEDROC_20`, `+0.1729` ROC-AUC** |
| **`GNINA 1.3.3 CNNscore`** | `0.0397` (`0.5456`) | **`0.3018`** (`0.7676`) | **`7.60×` `BEDROC_20`, `+0.2220` ROC-AUC** |
| `AutoDock-GPU 1.6` | `0.3500` (`0.8262`) | `0.2686` (`0.8010`) | `-0.0814` |
| `Vina 1.2.7` | `0.0940` (`0.6523`) | `0.0940` / `ROC 0.6562` | Parity |

### 3.4 Coupled `E8` Side-Chain Geometry Census & Verified `Export v5` Bundles

- **Axis B `M1 FlexRes` coupled `E8 PoseBusters 0.6.5`:** `161/174` (`92.53%`) PASS, `13` FAIL, `3` topology-reconstruction refusals; **`174/174` (`100.0%`)** `evaluate_flex_sidechain_geometry` PASS (`0` CA drift, `0` covalent distortions).
- **Measured induced-fit side-chain displacement across all `174` winning `FlexRes` medoids:**
  - `A:ARG288`: mean heavy-atom RMSD **`5.751 Å`** (max **`7.604 Å`**)
  - `A:MET364`: mean heavy-atom RMSD **`2.436 Å`** (max **`4.593 Å`**)
  - `A:HIS266`: mean heavy-atom RMSD **`1.866 Å`** (max **`4.868 Å`**)
- **Verified `Export v5` Bundles (`scripts/verify_export_bundle.py --require-format 5`):**
  - Axis A (Rigid `1PRG`): `Ankora_PPARG_1PRG_AxisA_Rigid_PCQ_consensus-run-744fe719_inputs-138e90f5_20261124-133358_export-21148665_bundle.zip` — SHA-256 `f3dfe912b3e3bc723282f4595731f432001858be4d9334b63bef0602889879d7` (`170` verified evidence files).
  - Axis B (`M1 FlexRes 1PRG`): `Ankora_PPARG_1PRG_AxisB_FlexRes_PCQ_consensus-run-af02af47_inputs-bdfdc136_20261124-160130_export-760af7a5_bundle.zip` — SHA-256 `ae6724c50fac6192de4d8ab85b41b93ab2a50ec96b512f6cfe7381c0429f2404` (`176` verified evidence files).
