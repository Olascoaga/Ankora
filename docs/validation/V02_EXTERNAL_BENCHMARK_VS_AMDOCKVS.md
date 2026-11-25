# Ankora `v0.2` External Benchmark — Three Holo `LIT-PCBA` Targets (`ESR_antago`, `TP53`, `PPARG`) & Induced-Fit `FlexRes` (`1PRG`, `1US0`) vs. Pinned `AMDockVS v0.14.1` (`ADR-031`)

- **Date:** 2026-11-25
- **Status:** Completed Two-Axis Holo Multi-Target Comparison (`ADMISSIBLE_TWO_AXIS_COMPARISON`, `N = 780` Locked Confirmation Parents) + Induced-Fit Cross-Docking (`1PRG <- 3B1M/KRC`, `1US0 <- 2FZD/TOL`) + Full Apo `PPARG` (`1PRG`) `FlexRes` Screening (`N = 180` Locked Confirmation); WSL2/WSLg Execution (`Ubuntu 24.04`, `16` CPU cores, `RTX 5050 Laptop GPU CUDA 12.8`) — Does Not Alter Frozen `v0.1` Claims in [`VALIDATION_STATUS.md`](VALIDATION_STATUS.md) and Does Not Substitute for Bare-Metal Linux `Gate D6`
- **Governance:** [`ADR-030`](../architecture/ADR/ADR-030-rank-space-consensus-prioritization.md), [`ADR-031`](../architecture/ADR/ADR-031-external-benchmark-boundary.md), [`ADR-032`](../architecture/ADR/ADR-032-explicit-flexibility-and-pose-complex-identity.md), [`V02_EXTERNAL_BENCHMARK_PROTOCOL.md`](V02_EXTERNAL_BENCHMARK_PROTOCOL.md)
- **Companion Records:** [`V02_EXTERNAL_BENCHMARK_MULTITARGET_VS_DOCKM8.md`](V02_EXTERNAL_BENCHMARK_MULTITARGET_VS_DOCKM8.md) (Record `143`, Ankora `v0.2 @ 9ec95a1` verified `Export v5` bundles reused verbatim), [`V02_EXTERNAL_BENCHMARK_INDUCED_FIT_FLEXRES_VS_DOCKM8.md`](V02_EXTERNAL_BENCHMARK_INDUCED_FIT_FLEXRES_VS_DOCKM8.md) (Record `144`), [`V02_OFFLINE_INSTALLER_ATTESTATION_POST_BENCHMARK.md`](V02_OFFLINE_INSTALLER_ATTESTATION_POST_BENCHMARK.md) (Record `145`)
- **Pinned External Rival:** `AMDockVS/AMDockVS` tag **`v0.14.1`** (commit `827e80570934701344104273d795ed739df8bf09`, `ms_adtools 0.2.0`, `ms_flow 0.12.0`, `ms_env 0.4.3`, `dimorphite-dl 2.1.0`), provisioned in a completely isolated Conda environment outside Ankora (`0` shared binaries or packages; managed tools installed natively via `AMDockVSRuntime.tools.install`: `pdb2pqr 3.7.1`, `reduce 4.15`, `vina 1.2.7`, `autogrid 4.2.6`, `unidock 1.2.0 CUDA`, `gnina 1.3.3 CUDA`).
- **Headline Findings (All Positive, Null, Negative, and Throughput Trade-offs Published Verbatim):**
  1. **Holo 3-Target `LIT-PCBA` Suite (`N = 780` Locked Confirmation Parents) vs. `AMDockVS` Default Primary Engines (`Uni-Dock 1.2.0 CUDA`, `Vina 1.2.7`, `GNINA 1.3.3` default rank-1 `minimizedAffinity`):**
     - `Ankora v0.2 PC-Q Neural` outperformed every default primary ranking of `AMDockVS v0.14.1` on **3/3 targets across BOTH axes**:
       - **Axis A (`controlled`):** `0.3082` vs. `AMDockVS GNINA rank-1 minimizedAffinity 0.1954` (**`1.58×`**), `Uni-Dock 1.2.0 CUDA 0.2109` (**`1.46×`**), and `Vina 1.2.7 0.2150` (**`1.43×`**); statistically **`ankora_preferred`** (95% CI `> 0`) on `PPARG` against all three.
       - **Axis B (`end_to_end`):** `0.2827` (`ROC-AUC 0.6587`) vs. `AMDockVS GNINA rank-1 0.2174` (**`1.30×`**, `ROC 0.6236`), `Uni-Dock 1.2.0 CUDA 0.2013` (**`1.40×`**, `ROC 0.6232`, **`ankora_preferred`** on `PPARG` raw & `PB`-valid), and `Vina 1.2.7 0.1993` (**`1.42×`**, `ROC 0.6193`, **`ankora_preferred`** on `PPARG` `PB`-valid).
     - Non-neural `Ankora PC-Q Core` essentially tied `AMDockVS Vina 1.2.7` and `Uni-Dock 1.2.0 CUDA` on `BEDROC_20` (`1.00×–1.02×` macro) while posting higher Axis B macro `ROC-AUC` (`0.6647` vs. `0.6193`/`0.6232`).
  2. **Honest Split/Negative Result vs. `AMDockVS GNINA 1.3.3` Extracted `CNN_VS` (`CNNscore * CNNaffinity` from `extra` JSON):**
     - **Axis A (`controlled`):** `Ankora PC-Q Neural` led macro `BEDROC_20` **`0.3082`** vs. **`0.2762`** (`+0.0320`, `1.12×`, repaired-`PB` `0.2955` vs. `0.2724`) and was statistically **`ankora_preferred`** on unbiased **`TP53`** (`0` bias properties: `0.2754` vs. `0.1270`, **`Δ = +0.1484 [+0.0072, +0.3066]`**, `2.17×`), while `AMDockVS GNINA CNN_VS` led `ESR_antago` (`0.4462` vs. `0.3188`, CI spans zero).
     - **Axis B (`end_to_end`):** **`AMDockVS GNINA CNN_VS` posted a higher 3-target macro `BEDROC_20` (`0.3256`) than `Ankora PC-Q Neural` (`0.2827`, `Δ = -0.0429`, `0.87×`)**, driven by higher point estimates on `ESR_antago` (`0.4820` vs. `0.3517`) and `PPARG` (`0.3527` vs. `0.2515`), whereas `Ankora PC-Q Neural` had higher macro `ROC-AUC` (`0.6587` vs. `0.6460`) and led unbiased `TP53` (`0.2449` vs. `0.1420`). **Zero targets were `external_preferred`** (all 3 Axis B CIs spanned zero).
  3. **Induced-Fit `M1 FlexRes` (`1PRG <- 3B1M/KRC`, `1US0 <- 2FZD/TOL`, and Full Apo `PPARG 1PRG` Screening `N = 180`):**
     - **Verified `FlexRes` engine gaps in `AMDockVS v0.14.1`:** `Uni-Dock 1.2.0 CUDA` rejected both `1PRG` (`9` chi torsions) and `1US0` (`6` chi torsions) with upstream `GPU docking supports at most 1 torsion` (`Uni-Dock#159`); `AMDockVS`'s `gnina.py` adapter omits `--flex`/`--out_flex` completely (with no fail-closed guard); and `AMDockVS`'s Linux `AutoDock-GPU 1.6` binary is OpenCL-only (`clGetPlatformIDs(): -1001` on WSL2 NVIDIA CUDA-only driver). Consequently, **`Vina 1.2.7 --flex` (CPU)** was the only multi-torsion flexible engine available in `AMDockVS v0.14.1` on this workstation, whereas `Ankora v0.2 M1 FlexRes` executes all three (`Vina --flex`, `AutoDock-GPU CUDA --flexres`, and `GNINA CUDA --flex --out_flex`) with coupled `E8` geometry auditing.
     - **Cross-docking (`1PRG <- KRC`):** Both platforms' `Vina --flex` unlocked the crystallographic binding mode (`Ankora 0.6851 Å`, `AMDockVS 0.7818 Å`, both `3/5` coupled `PB`-valid with top-1 clash `PB=FAIL`), while Ankora additionally delivered `GNINA --flex` at **`1.0833 Å` (`5/5` valid, top-1 `PB=PASS`)** and `AutoDock-GPU --flexres` at `2.6325 Å` (`5/5` valid).
     - **Apo `1PRG` Screening (`N = 180`):** Ankora led **every** `AMDockVS` configuration (flexible and rigid) on both `BEDROC_20` and `ROC-AUC`: Axis A `PC-Q Core` (`0.2870`, `ROC 0.7362`) and `PC-ECR` (`0.1855`, `ROC 0.7496`) were statistically **`ankora_preferred`** over `AMDockVS Vina` (`0.0788`, `ROC 0.6528`) both raw and `PB`-valid; Axis B `Ankora M1 FlexRes PC-Q Neural` (`0.1724`, `ROC 0.7300`) was statistically **`ankora_preferred`** over `AMDockVS Uni-Dock` (`0.0544`, `ROC 0.5783`, `3.17×`); and `Ankora M1 FlexRes PC-ECR` (`0.2842`, `ROC 0.7616`, coupled `PB` `92.53%`) reached **`2.97×`** `AMDockVS Vina --flex` (`0.0956`, `ROC 0.6407`, coupled `PB` `87.78%`) and **`3.57×`** `AMDockVS GNINA CNN_VS` rigid (`0.0796`, `ROC 0.5856`; CIs spanned zero).
  4. **Chemical Integrity, `PoseBusters 0.6.5`, Deployment Footprint, and Throughput Trade-off:**
     - **Where `AMDockVS v0.14.1` clearly leads:** In-process ligand chemistry + PDBQT preparation (`~7–8 s` for `300` SMILES) and GPU-batched **`Uni-Dock 1.2.0 CUDA`** docking (`26.9–41.9 s` for `180–300` ligands).
     - **Where `Ankora v0.2` clearly leads:** Zero-Conda offline footprint (`272.73 MiB` `.deb` + `~2.55 GiB` optional GNINA pack vs. `11.1 GB` Conda + `ms_env` tools and `0` standalone installers in `AMDockVS v0.14.1`); explicit metal-aware protonation (`AMDockVS` `pdb2pqr` placed `HD1` on `HIS179 ND1` and `HG` on `CYS238`/`CYS242 SG` adjacent to `TP53` `ZN 313` with `warnings: None`); and `GNINA` SDF chemical fidelity (`AMDockVS` exported `22.6%–31.7%` of `GNINA` protonated amines as unsanitizable 4-bonded neutral nitrogens, dropping strict as-exported `PoseBusters 0.6.5` pass rates to `57.2%–68.0%` vs. `82.7%–91.7%` after fair formal-charge repair and `89.3%–98.0%` in Ankora).

---

## 1. Isolation, Execution Conditions & Fairness Safeguards (`ADR-031`)

1. **Strict Environment Isolation:** `AMDockVS v0.14.1` (`827e80570934701344104273d795ed739df8bf09`) was cloned outside the Ankora tree and installed via its official `environment.yml` into a dedicated external Conda environment (`amdockvs-external`, `2.0 GB`). Its managed tools (`pdb2pqr 3.7.1`, `reduce 4.15`, `adgpu 1.6`, `unidock 1.2.0`, `gnina 1.3.3`) were installed natively via `AMDockVSRuntime.tools.install(...)` into an isolated `AMDOCK_TOOLS_HOME` (`9.1 GB`; combined on-disk footprint **`11.1 GB`**). Ankora's source tree, lockfiles, and installers were never modified or imported.
2. **Exact Same Sealed Cohorts & Verified `Export v5` Bundles:** All 3 holo `LIT-PCBA` cohorts (`ESR_antago / 5UFX`, `TP53 / 3ZME`, `PPARG / 3B1M`, `N = 780` Locked Confirmation parents) and apo `PPARG` (`1PRG`, `N = 180` Locked Confirmation) reused the exact Bemis-Murcko splits (`33cb058c...`, `c7c7d5de...`, `6c8579ab...`), identical enclosing boxes, and identical SHA-256-verified Ankora `v0.2 @ 9ec95a1` `Export v5` ZIP bundles from Records `143` and `144`.
3. **Fair `AMDockVS` Configuration on Both Axes:**
   - **Axis A (`controlled`):** Identical prepared receptors (`*_ankora_prepared.pdb`, `remove_non_structural_waters=False`, `remove_altloc=False`), identical 3D `confirmation_controlled.sdf`, identical boxes, running all 3 working flagship engines (`Uni-Dock 1.2.0 CUDA` `search_mode=balance`, `Vina 1.2.7` `exhaustiveness=8`, `GNINA 1.3.3 CUDA` `--cnn_scoring rescore`, `exhaustiveness=8`, `num_modes=5`, `seed=20261120`).
   - **Axis B (`end_to_end`):** Raw crystallographic PDBs (Chain A explicitly selected via `selected_chain_ids=["A"]`), `remove_non_structural_waters=True`, `remove_altloc=True`, `protonate_receptors(method="pdb2pqr", ph=7.4)`, raw SMILES through `AMDockVS`'s full ligand chemistry pipeline (`standardize -> protonate(dimorphite, ph=7.4) -> generate_3d(etkdgv3, seed=20261120) -> minimize(mmff)`), followed by `prepare_ligands`/`prepare_receptors` and all 3 docking engines.
4. **Two Explicit Fairness Safeguards in Shared `PoseBusters 0.6.5` Auditing:**
   - **Docked-water consistency (`TP53` and `PPARG` Axis B):** Although `AMDockVS`'s `prepare_receptors(keep_waters=False)` stripped all waters from the docking PDBQT (`0` `HOH` atoms), its stored `current_payload_id` PDB retained `1` water (`3` atoms) on `TP53` and `2` waters (`6` atoms) on `PPARG` (matching `AMDockVS`'s `TODO.md` note `retained_structural_waters has no consumer`). To avoid artificial water-clash penalties, `PoseBusters 0.6.5` stripped `HOH` lines whenever the docked PDBQT contained zero waters, auditing strictly against the exact receptor atoms present during docking.
   - **Dual reporting for `AMDockVS GNINA` SDF exports:** Because `AMDockVS` feeds PDBQT into `gnina` and archives OpenBabel's raw SDF output without Meeko bond-order reconstruction, `22.6%–31.7%` of protonated amines failed RDKit/PoseBusters sanitization as neutral 4-bonded nitrogens. Every `GNINA` comparison reports **both** strict as-exported `PoseBusters` pass rates **and** coordinate-level pass rates after neutral 4-bonded `N -> N+1` formal-charge repair (zero coordinate modifications).
   - **Identical `E8` coupled flex materialization (`1PRG` and `1US0`):** `AMDockVS Vina --flex` poses carry moved side-chain `ATOM` blocks inside the `<flexres>` SD property; these were materialized onto the rigid receptor using the exact same `materialize_coupled_receptor_pdb` parent-triad non-polar H transfer used for Ankora `M1 FlexRes`.

---

## 2. Three-Target Holo `LIT-PCBA` Results (`N = 780` Locked Confirmation Parents)

All comparisons were executed with stdlib-only `python -S benchmarks/external_comparison/evaluate_comparison.py` (`2,000` stratified paired parent-bootstrap replicates, `seed = 20261120`).

### 2.1 Equal-Weight 3-Target Macro Summary (`ESR_antago`, `TP53`, `PPARG`)

| Comparison (`Ankora v0.2` vs. `AMDockVS v0.14.1`) | Axis A `BEDROC_20` (`Ank` vs. `AMD`, Ratio) | Axis A Macro `ROC-AUC` | Axis A `PB`-Valid `BEDROC_20` | Axis B `BEDROC_20` (`Ank` vs. `AMD`, Ratio) | Axis B Macro `ROC-AUC` | Axis B `PB`-Valid `BEDROC_20` |
| --- | --- | --- | --- | --- | --- | --- |
| **`PC-Q Neural` vs. `GNINA CNN_VS`** *(strict PB)* | **`0.3082`** vs. `0.2762` (`+0.0320`, **`1.12×`**) | `0.6441` vs. `0.6491` | `0.2955` vs. `0.2981` | `0.2827` vs. **`0.3256`** (`-0.0429`, `0.87×`) | **`0.6587`** vs. `0.6460` | `0.2960` vs. `0.3744` |
| **`PC-Q Neural` vs. `GNINA CNN_VS`** *(repaired PB)* | **`0.3082`** vs. `0.2762` (`+0.0320`, **`1.12×`**) | `0.6441` vs. `0.6491` | **`0.2955`** vs. `0.2724` | `0.2827` vs. **`0.3256`** (`-0.0429`, `0.87×`) | **`0.6587`** vs. `0.6460` | `0.2960` vs. `0.3342` |
| **`PC-Q Neural` vs. `GNINA rank-1 aff.`** *(default)* | **`0.3082`** vs. `0.1954` (`+0.1128`, **`1.58×`**) | **`0.6441`** vs. `0.6231` | **`0.2955`** vs. `0.2462` | **`0.2827`** vs. `0.2174` (`+0.0653`, **`1.30×`**) | **`0.6587`** vs. `0.6236` | **`0.2960`** vs. `0.2711` |
| **`PC-Q Neural` vs. `Uni-Dock 1.2.0 CUDA`** | **`0.3082`** vs. `0.2109` (`+0.0973`, **`1.46×`**) | **`0.6441`** vs. `0.6230` | **`0.2955`** vs. `0.2133` | **`0.2827`** vs. `0.2013` (`+0.0814`, **`1.40×`**) | **`0.6587`** vs. `0.6232` | **`0.2960`** vs. `0.1971` |
| **`PC-Q Neural` vs. `Vina 1.2.7`** | **`0.3082`** vs. `0.2150` (`+0.0931`, **`1.43×`**) | **`0.6441`** vs. `0.6247` | **`0.2955`** vs. `0.2180` | **`0.2827`** vs. `0.1993` (`+0.0834`, **`1.42×`**) | **`0.6587`** vs. `0.6193` | **`0.2960`** vs. `0.2014` |
| **`PC-Q Core` (non-neural) vs. `Vina 1.2.7`** | `0.2158` vs. `0.2150` (`+0.0007`, `1.00×`) | `0.6234` vs. `0.6247` | `0.2132` vs. `0.2180` | `0.2033` vs. `0.1993` (`+0.0040`, `1.02×`) | **`0.6647`** vs. `0.6193` | **`0.2144`** vs. `0.2014` |
| **`PC-Q Core` (non-neural) vs. `Uni-Dock CUDA`** | `0.2158` vs. `0.2109` (`+0.0048`, `1.02×`) | `0.6234` vs. `0.6230` | `0.2132` vs. `0.2133` | `0.2033` vs. `0.2013` (`+0.0020`, `1.01×`) | **`0.6647`** vs. `0.6232` | **`0.2144`** vs. `0.1971` |

### 2.2 Per-Target Detailed Breakdown (`Ankora PC-Q Neural` vs. `AMDockVS v0.14.1`)

| Target (`N` Conf.) | Axis | `AMDockVS` Engine | Ankora `BEDROC_20` (`ROC`) | `AMDockVS` `BEDROC_20` (`ROC`) | Paired `Δ BEDROC_20` (`95% CI`) | Verbatim `ADR-031` Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| **`ESR_antago`** (`300`) | Axis A | `GNINA CNN_VS` | `0.3188` (`0.6117`) | **`0.4462`** (`0.6166`) | `-0.1274` `[-0.3118, +0.0775]` | `Insufficient evidence to prefer over baseline` |
| **`ESR_antago`** (`300`) | Axis A | `GNINA rank-1 aff.` | **`0.3188`** (`0.6117`) | `0.3055` (`0.6377`) | `+0.0133` `[-0.1300, +0.1432]` | `Insufficient evidence to prefer over baseline` |
| **`ESR_antago`** (`300`) | Axis A | `Uni-Dock CUDA` | **`0.3188`** (`0.6117`) | `0.3023` (`0.6374`) | `+0.0165` `[-0.1926, +0.2217]` | `Insufficient evidence to prefer over baseline` |
| **`ESR_antago`** (`300`) | Axis A | `Vina 1.2.7` | **`0.3188`** (`0.6117`) | `0.3159` (`0.6117`) | `+0.0029` `[-0.1975, +0.1838]` | `Insufficient evidence to prefer over baseline` |
| **`ESR_antago`** (`300`) | Axis B | `GNINA CNN_VS` | `0.3517` (`0.6716`) | **`0.4820`** (`0.5880`) | `-0.1303` `[-0.2993, +0.0628]` | `Insufficient evidence to prefer over baseline` |
| **`ESR_antago`** (`300`) | Axis B | `GNINA rank-1 aff.` | **`0.3517`** (`0.6716`) | `0.2809` (`0.5868`) | `+0.0708` `[-0.0434, +0.1868]` | `Insufficient evidence to prefer over baseline` |
| **`ESR_antago`** (`300`) | Axis B | `Uni-Dock CUDA` | **`0.3517`** (`0.6716`) | `0.3220` (`0.6452`) | `+0.0297` `[-0.1742, +0.2188]` | `Insufficient evidence to prefer over baseline` |
| **`ESR_antago`** (`300`) | Axis B | `Vina 1.2.7` | **`0.3517`** (`0.6716`) | `0.2994` (`0.6186`) | `+0.0523` `[-0.1271, +0.2308]` | `Insufficient evidence to prefer over baseline` |
| **`TP53`** (`300`, `0` bias) | Axis A | `GNINA CNN_VS` | **`0.2754`** (`0.5272`) | `0.1270` (`0.5407`) | **`+0.1484` `[+0.0072, +0.3066]`** | **`ankora_preferred`** |
| **`TP53`** (`300`, `0` bias) | Axis A | `GNINA rank-1 aff.` | **`0.2754`** (`0.5272`) | `0.1191` (`0.5522`) | `+0.1563` `[-0.0538, +0.3598]` | `Insufficient evidence to prefer over baseline` |
| **`TP53`** (`300`, `0` bias) | Axis A | `Uni-Dock CUDA` | **`0.2754`** (`0.5272`) | `0.1612` (`0.5872`) | `+0.1142` `[-0.0870, +0.3077]` | `Insufficient evidence to prefer over baseline` |
| **`TP53`** (`300`, `0` bias) | Axis A | `Vina 1.2.7` | **`0.2754`** (`0.5272`) | `0.1616` (`0.5897`) | `+0.1138` `[-0.0987, +0.3213]` | `Insufficient evidence to prefer over baseline` |
| **`TP53`** (`300`, `0` bias) | Axis B | `GNINA CNN_VS` | **`0.2449`** (`0.5639`) | `0.1420` (`0.5243`) | `+0.1028` `[-0.0534, +0.2726]` | `Insufficient evidence to prefer over baseline` |
| **`TP53`** (`300`, `0` bias) | Axis B | `GNINA rank-1 aff.` | **`0.2449`** (`0.5639`) | `0.1261` (`0.5723`) | `+0.1187` `[-0.0542, +0.2886]` | `Insufficient evidence to prefer over baseline` |
| **`TP53`** (`300`, `0` bias) | Axis B | `Uni-Dock CUDA` | **`0.2449`** (`0.5639`) | `0.1404` (`0.5817`) | `+0.1045` `[-0.0927, +0.3024]` | `Insufficient evidence to prefer over baseline` |
| **`TP53`** (`300`, `0` bias) | Axis B | `Vina 1.2.7` | **`0.2449`** (`0.5639`) | `0.1349` (`0.5668`) | `+0.1100` `[-0.0887, +0.3051]` | `Insufficient evidence to prefer over baseline` |
| **`PPARG`** (`180`, `5` bias) | Axis A | `GNINA CNN_VS` | **`0.3304`** (`0.7935`) | `0.2554` (`0.7900`) | `+0.0750` `[-0.1166, +0.2728]` | `Insufficient evidence to prefer over baseline` |
| **`PPARG`** (`180`, `5` bias) | Axis A | `GNINA rank-1 aff.` | **`0.3304`** (`0.7935`) | `0.1616` (`0.6794`) | **`+0.1687` `[+0.0244, +0.3635]`** | **`ankora_preferred`** |
| **`PPARG`** (`180`, `5` bias) | Axis A | `Uni-Dock CUDA` | **`0.3304`** (`0.7935`) | `0.1693` (`0.6444`) | **`+0.1610` `[+0.0086, +0.3751]`** | **`ankora_preferred`** (raw & `PB` `+0.1623`) |
| **`PPARG`** (`180`, `5` bias) | Axis A | `Vina 1.2.7` | **`0.3304`** (`0.7935`) | `0.1677` (`0.6728`) | **`+0.1627` `[+0.0078, +0.3804]`** | **`ankora_preferred`** (raw & `PB` `+0.1695`) |
| **`PPARG`** (`180`, `5` bias) | Axis B | `GNINA CNN_VS` | `0.2515` (`0.7407`) | **`0.3527`** (`0.8257`) | `-0.1012` `[-0.3121, +0.0786]` | `Insufficient evidence to prefer over baseline` |
| **`PPARG`** (`180`, `5` bias) | Axis B | `GNINA rank-1 aff.` | **`0.2515`** (`0.7407`) | `0.2452` (`0.7117`) | `+0.0063` `[-0.1446, +0.1611]` | `Insufficient evidence to prefer over baseline` |
| **`PPARG`** (`180`, `5` bias) | Axis B | `Uni-Dock CUDA` | **`0.2515`** (`0.7407`) | `0.1416` (`0.6426`) | **`+0.1099` `[+0.0103, +0.2555]`** | **`ankora_preferred`** (raw & `PB` `+0.1455`) |
| **`PPARG`** (`180`, `5` bias) | Axis B | `Vina 1.2.7` | **`0.2515`** (`0.7407`) | `0.1635` (`0.6725`) | `+0.0879` `[-0.0012, +0.2310]` | Null raw / **`ankora_preferred` `PB`-valid** (`+0.1231 [+0.0176, +0.2823]`) |

### 2.3 Shared `PoseBusters 0.6.5` Physical Validity & Chemical Governance Census (Holo Suite)

| Target | Axis | Ankora `v0.2` `PB` Pass | `AMDockVS Vina` `PB` Pass | `AMDockVS Uni-Dock` `PB` Pass | `AMDockVS GNINA CNN_VS` Strict Export `PB` (Sanitization Fails) | `AMDockVS GNINA CNN_VS` Repaired `N+1` `PB` |
| --- | --- | ---: | ---: | ---: | --- | ---: |
| **`ESR_antago`** | Axis A | **`275/287` (`95.82%`)** | `279/297` (`93.94%`) | `272/297` (`91.58%`) | `202/297` (`68.01%`, **`67`** fails) | `252/297` (`84.85%`) |
| **`ESR_antago`** | Axis B | **`290/296` (`97.97%`)** | `285/300` (`95.00%`) | `278/300` (`92.67%`) | `194/300` (`64.67%`, **`70`** fails) | `248/300` (`82.67%`) |
| **`TP53`** | Axis A | `256/281` (`91.10%`) | **`276/293` (`94.20%`)** | `273/293` (`93.17%`) | `189/293` (`64.51%`, **`74`** fails) | `251/293` (`85.67%`) |
| **`TP53`** | Axis B | `263/287` (`91.64%`) | **`281/300` (`93.67%`)** | **`281/300` (`93.67%`)** | `198/300` (`66.00%`, **`83`** fails) | `271/300` (`90.33%`) |
| **`PPARG`** | Axis A | `150/168` (`89.29%`) | **`165/177` (`93.22%`)** | **`165/177` (`93.22%`)** | `107/177` (`60.45%`, **`54`** fails) | `158/177` (`89.27%`) |
| **`PPARG`** | Axis B | `161/174` (`92.53%`) | `169/180` (`93.89%`) | **`174/180` (`96.67%`)** | `113/180` (`62.78%`, **`57`** fails) | `165/180` (`91.67%`) |

- **Receptor chemical audit:** Unlike `DockM8 v1.1.1` (`47` hypervalent carbons across `3/3` Axis B targets), `AMDockVS v0.14.1` (`pdb2pqr 3.7.1`) produced **`0/3`** hypervalent carbons. However, on metalloprotein **`TP53` (`3ZME`, structural `ZN 313`)**, `AMDockVS`'s `pdb2pqr` placed `HD1` on `HIS179 ND1` (`2.01 Å` from `ZN 313`) and `HG` on `CYS238`/`CYS242 SG` (`2.31–2.33 Å` from `ZN 313`) with `ZN` charge `0.000` and `warnings: None`, whereas Ankora explicitly detected `ZN 313` coordination and verified `HIS179=HIE`, `CYS238=CYM`, `CYS242=CYM` in the written PDB/PQR.

---

## 3. Induced-Fit `FlexRes` Benchmark (`1PRG`, `1US0`) vs. `AMDockVS v0.14.1`

### 3.1 Crystallographic Cross-Docking (Fresh SMILES -> `ETKDGv3` Conformer, In-Place RMSD + Coupled `E8 PoseBusters 0.6.5`)

| System | Platform & Mode | Engine | Top-1 RMSD (Å) | Top-1 Coupled `PB` | Best-of-5 Valid RMSD (Å) | Valid (`/5`) | Wall Time |
| --- | --- | --- | ---: | --- | ---: | ---: | ---: |
| **`PPARG` apo `1PRG <- 3B1M/KRC`** | `AMDockVS` Rigid | `Vina 1.2.7` | `7.8564` | `PASS` | `5.5758` | `5/5` | `17.3 s` |
| **`PPARG` apo `1PRG <- 3B1M/KRC`** | `AMDockVS` Rigid | `Uni-Dock 1.2.0 CUDA` | `5.6817` | `PASS` | `5.6817` | `5/5` | `2.8 s` |
| **`PPARG` apo `1PRG <- 3B1M/KRC`** | `AMDockVS` Rigid | `GNINA 1.3.3 CUDA` | `8.8225` | `PASS` | `6.4509` | `5/5` | `16.4 s` |
| **`PPARG` apo `1PRG <- 3B1M/KRC`** | **`AMDockVS FlexRes`** | **`Vina 1.2.7 --flex`** | `8.7105` | `FAIL` (`pb_min_dist`) | **`0.7818`** | `3/5` | `58.3 s` |
| **`PPARG` apo `1PRG <- 3B1M/KRC`** | `AMDockVS FlexRes` | `Uni-Dock` / `GNINA` / `AD-GPU` | `N/A` | `N/A` | *Blocked (`>1` torsion / no `--flex` / OpenCL)* | `0` | — |
| **`PPARG` apo `1PRG <- 3B1M/KRC`** | **`Ankora M1 FlexRes`** *(Rec. 144)* | **`Vina` / `GNINA` / `AD-GPU`** | `8.7893` / **`5.1111`** / **`4.8852`** | `FAIL` / **`PASS`** / **`PASS`** | **`0.6851`** / **`1.0833`** / **`2.6325`** | `3/5` / **`5/5`** / **`5/5`** | — |
| **`ALR2` `1US0 <- 2FZD/TOL`** *(no `NADP+`)* | `AMDockVS` Rigid | `Vina` / `Uni-Dock` / `GNINA` | `3.0160` / `3.0818` / `3.0163` | `PASS` (`3/3`) | `3.0160` / `3.0818` / `3.0163` | `5/5`, `4/4`, `5/5` | `1.6–9.5 s` |
| **`ALR2` `1US0 <- 2FZD/TOL`** *(no `NADP+`)* | `AMDockVS FlexRes` | `Vina 1.2.7 --flex` | `2.8827` | `FAIL` (`pb_min_dist`) | `5.0330` (`2.8827` raw) | `2/5` | `24.9 s` |

### 3.2 Full Apo `PPARG` (`1PRG`) Two-Axis Screening (`N = 180` Locked Confirmation, Split `6c8579ab...`)

| Comparison (`PPARG` Apo `1PRG`, `N = 180`) | Axis | Ankora `BEDROC_20` (`ROC-AUC`) | `AMDockVS` `BEDROC_20` (`ROC-AUC`) | Paired `Δ BEDROC_20` (`95% CI`) | `PB 0.6.5`-Valid (`Ank` vs. `AMD`) | Verbatim Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| **`PC-Q Core` vs. `AMDockVS Vina`** | Axis A (rigid) | **`0.2870`** (`0.7362`) | `0.0788` (`0.6528`) | **`+0.2082` `[+0.0207, +0.4019]`** (`3.64×`) | **`0.3035`** vs. `0.0803` (**`ankora_preferred`**) | **`ankora_preferred`** |
| **`PC-ECR` vs. `AMDockVS Vina`** | Axis A (rigid) | **`0.1855`** (`0.7496`) | `0.0788` (`0.6528`) | **`+0.1066` `[+0.0018, +0.2617]`** (`2.35×`) | **`0.2212`** vs. `0.0803` (**`ankora_preferred`**) | **`ankora_preferred`** |
| `PC-Q Neural` vs. `AMDockVS GNINA CNN_VS` | Axis A (rigid) | **`0.1879`** (`0.7431`) | `0.1068` (`0.6975`) | `+0.0811` `[-0.0757, +0.2690]` (`1.76×`) | **`0.2091`** vs. `0.1019` (`0.0866` rep.) | `Insufficient evidence to prefer over baseline` |
| `PC-Q Neural` vs. `AMDockVS Uni-Dock` | Axis A (rigid) | **`0.1879`** (`0.7431`) | `0.0952` (`0.5940`) | `+0.0926` `[-0.1118, +0.3265]` (`1.97×`) | **`0.2091`** vs. `0.0955` | `Insufficient evidence to prefer over baseline` |
| **`PC-Q Neural` (`FlexRes`) vs. `AMDockVS Vina --flex`** | Axis B (`FlexRes`) | **`0.1724`** (`0.7300`) | `0.0956` (`0.6407`) | `+0.0768` `[-0.0104, +0.2139]` (`1.80×`) | **`0.1777`** (`92.53%`) vs. `0.1087` (`87.78%`) | `Insufficient evidence to prefer over baseline` |
| **`PC-Q Core` (`FlexRes`) vs. `AMDockVS Vina --flex`** | Axis B (`FlexRes`) | **`0.2129`** (`0.7265`) | `0.0956` (`0.6407`) | `+0.1174` `[-0.0169, +0.2797]` (`2.23×`) | **`0.2214`** vs. `0.1087` | `Insufficient evidence to prefer over baseline` |
| **`PC-ECR` (`FlexRes`) vs. `AMDockVS Vina --flex`** | Axis B (`FlexRes`) | **`0.2842`** (`0.7616`) | `0.0956` (`0.6407`) | `+0.1887` `[-0.0160, +0.3972]` (`2.97×`) | **`0.2869`** vs. `0.1087` | `Insufficient evidence to prefer over baseline` |
| **`PC-ECR` (`FlexRes`) vs. `AMDockVS GNINA CNN_VS` (rigid)** | Axis B (`FlexRes` vs. rigid) | **`0.2842`** (`0.7616`) | `0.0796` (`0.5856`) | `+0.2046` `[-0.0082, +0.4331]` (`3.57×`) | **`0.2869`** vs. `0.1141` (`0.1057` rep.) | `Insufficient evidence to prefer over baseline` |
| **`PC-Q Neural` (`FlexRes`) vs. `AMDockVS Uni-Dock` (rigid)** | Axis B (`FlexRes` vs. rigid) | **`0.1724`** (`0.7300`) | `0.0544` (`0.5783`) | **`+0.1180` `[+0.0074, +0.2871]`** (`3.17×`) | **`0.1777`** vs. `0.0547` (**`ankora_preferred`**) | **`ankora_preferred`** |

- Coupled `E8` gatekeeper displacements on `AMDockVS Vina --flex` (`180/180` scored, `158/180 = 87.78%` coupled `PB` PASS): `A:ARG288` mean `5.264 Å` (max `7.529 Å`), `A:MET364` mean `2.212 Å` (max `2.612 Å`), `A:HIS266` mean `1.654 Å` (max `4.832 Å`), closely matching Ankora's `FlexRes` motion (`5.751 / 2.436 / 1.866 Å`, `161/174 = 92.53%` coupled `PB` PASS).

---

## 4. Wall-Clock Throughput & Deployment Comparison (Honest Trade-off Table)

| Stage / Metric | `AMDockVS v0.14.1` Measured | `Ankora v0.2` (`8fb602c`) Measured | Practical Interpretation |
| --- | --- | --- | --- |
| **Distribution & Footprint** | `0` standalone installers (`mamba` + `pip` + `5` `ms_env` tool dirs = **`11.1 GB`**) | Standalone offline `.exe` (`408.2 MiB`), `.deb` (`272.7 MiB`), `.tar.zst` (`314.6 MiB`) + optional 1-click GNINA CUDA pack (`~2.55 GiB`) | Ankora wins decisively on zero-Conda offline deployability |
| **Axis B Chemistry + PDBQT Prep (`300` SMILES + rec.)** | **`7.1–7.9 s`** (`6.5–7.3 s` chem + `0.61 s` `ms_adtools`) | Process-isolated per-compound audit + explicit microstate/metal verification (`~1–2 min`) | **`AMDockVS` is `~10×` faster** via in-process batch workers |
| **GPU Fast Rigid Screening (`300` ligs)** | **`Uni-Dock 1.2.0 CUDA`: `37.9–41.9 s`** (`26.9–30.5 s` for `180` PPARG) | `AutoDock-GPU 1.6 CUDA` (`~2–3 min` / `300` ligs); no `Uni-Dock` yet | **`AMDockVS` (`Uni-Dock`) wins raw GPU throughput** (rigid-only; blocked at `>1` flex torsion) |
| **CPU `Vina 1.2.7` (`300` ligs, `exh=8`)** | `904.6–1,069.6 s` (`15.1–17.8 min`); `1PRG FlexRes` (`180`): **`2,954.6 s` (`49.2 min`)** | Comparable single-engine `Vina 1.2.7` timing | Parity on upstream `Vina 1.2.7` binary |
| **`GNINA 1.3.3 CUDA` (`300` ligs, `exh=8`)** | `878.1–1,016.2 s` (`14.6–16.9 min`, rigid-only) | Comparable rigid speed + **supports `GNINA --flex --out_flex`** (`1PRG` `4.41×` lift) | Ankora adds GPU `FlexRes` + Meeko topology fidelity (`0%` vs. `23%–32%` export valence errors) |
| **Governance, Consensus & Auditability** | No multi-engine consensus, no out-of-sample Calibration/Confirmation, no `PoseBusters`, no `ProLIF` rules, no `Export` verifier | Full `M1`–`M6.5`: `PC-Q`/`PC-ECR`/`PC-L2`, `1-SE` Calibration, coupled `E8 PoseBusters 0.6.5`, declarative `ProLIF`, `ADR-033` analog expansion, `python -S` verified `Export v5/v6` | Ankora provides end-to-end verifiable scientific governance |
