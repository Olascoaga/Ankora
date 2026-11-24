# Ankora `v0.2` Multi-Target External Benchmark — Three `LIT-PCBA` Targets (`ESR_antago`, `TP53`, `PPARG`) vs. Pinned `DockM8 v1.1.1` Post-`9ec95a1` (`ADR-031`)

- **Date:** 2026-11-24
- **Status:** Completed Three-Target Two-Axis External Comparison (`ADMISSIBLE_TWO_AXIS_COMPARISON` across `N = 780` Locked Confirmation Parents); WSL2/WSLg Execution (`Ubuntu 24.04`, `RTX 5050 Laptop GPU CUDA 12.8`) — Does Not Alter Frozen `v0.1` Claims in [`VALIDATION_STATUS.md`](VALIDATION_STATUS.md) and Does Not Substitute for Bare-Metal Linux `Gate D6`
- **Governance:** [`ADR-030`](../architecture/ADR/ADR-030-rank-space-consensus-prioritization.md), [`ADR-031`](../architecture/ADR/ADR-031-external-benchmark-boundary.md), [`ADR-032`](../architecture/ADR/ADR-032-explicit-flexibility-and-pose-complex-identity.md), [`V02_EXTERNAL_BENCHMARK_PROTOCOL.md`](V02_EXTERNAL_BENCHMARK_PROTOCOL.md)
- **Preceding Record:** [`V02_EXTERNAL_BENCHMARK_ESR1_ANT_VS_DOCKM8.md`](V02_EXTERNAL_BENCHMARK_ESR1_ANT_VS_DOCKM8.md) (pre-`9ec95a1` baseline on `ESR_antago`)
- **Primary 3-Target Summary (`Ankora v0.2 @ 9ec95a1 PC-Q Neural` vs. `DockM8 v1.1.1 @ 3b765ea ECR`, `N = 780` Locked Confirmation Parents):**
  - **Axis A (`controlled`, identical prepared receptor, identical 3D ligands, identical box):**
    - Equal-target macro `BEDROC_20`: **Ankora `0.3082`** vs. **DockM8 ECR `0.2060`** (`Δ = +0.1022`, **`1.50×`**; Ankora leads on **3/3** targets; macro `ROC-AUC` **`0.6441`** vs. `0.5924`; `PoseBusters 0.6.5`-valid macro `BEDROC_20` **`0.2955`** vs. `0.1876`, **`1.58×`**).
    - Per-target paired 95% CIs on Axis A: all 3 individual targets report **`Insufficient evidence to prefer over baseline`** (`ESR_antago`: `+0.0148 [-0.1649, +0.1851]`; `TP53`: `+0.1539 [-0.0666, +0.3613]`; `PPARG`: `+0.1378 [-0.0421, +0.3651]`).
  - **Axis B (`end_to_end`, full native preparation + docking + consensus from raw CIF/PDB + raw SMILES):**
    - Equal-target macro `BEDROC_20`: **Ankora `0.2827`** vs. **DockM8 ECR `0.0707`** (`Δ = +0.2119`, **`4.00×`**; macro `ROC-AUC` **`0.6587`** vs. `0.4659`; `PoseBusters 0.6.5`-valid macro `BEDROC_20` **`0.2960`** vs. `0.0818`, **`3.62×`**).
    - Per-target paired 95% CIs on Axis B vs. `DockM8 ECR`: **`ankora_preferred`** (95% CI strictly `> 0`) on **`TP53`** (`+0.1747 [+0.0124, +0.3573]`, `PB`-valid `+0.1746 [+0.0111, +0.3482]`) and **`PPARG`** (`+0.2461 [+0.0483, +0.4857]`, `PB`-valid `+0.2798 [+0.0765, +0.5188]`), and **`Insufficient evidence to prefer over baseline`** on **`ESR_antago`** (`+0.2151 [-0.0185, +0.4248]`).
    - Per-target paired 95% CIs on Axis B vs. `DockM8 RBR`: **`ankora_preferred`** on **3/3 targets** — both raw (`ESR_antago +0.2586`, `TP53 +0.1683`, `PPARG +0.2475`) and `PoseBusters`-valid (`+0.2309`, `+0.1799`, `+0.2821`); macro `0.2827` vs. `0.0579` (**`4.88×`**).

---

## 1. Root-Cause Physics Fix (`9ec95a1`) Diagnosed Strictly on Calibration

Following Record `142` (`V02_EXTERNAL_BENCHMARK_ESR1_ANT_VS_DOCKM8.md`), where `Ankora v0.2 PC-Q` trailed its own single engines (`AutoDock-GPU`, `GNINA`) on `ESR_antago`, a strictly Calibration-only diagnostic (`N = 200` `ESR_antago` Calibration split; zero Confirmation peeking) identified the exact physical cause:

1. **AutoDock4 `4.2.6` `epdb` `unbound_model` bug:** Even when `unbound_model bound` is written into the `.dpf`, AutoDock4 `4.2.6`'s C++ `epdb` code path hardcodes `(4) Unbound System's Energy = +0.00 kcal/mol`, leaving the raw ligand intramolecular energy `(2)` (`-2` to `-10 kcal/mol` on polar/zwitterionic decoys) un-subtracted in `Estimated Free Energy of Binding`. By contrast, native `AutoDock4` docking, `AutoDock-GPU 1.6`, and `Vina 1.2.7 --scoring ad4` all evaluate `unbound_model bound` (`(4) = (2)`, so $\Delta G = (1)\text{ Intermolecular} + (3)\text{ Torsional}$).
2. **Calibration-only ablation impact (`ESR_antago`, `N = 200`):** Correcting `autodock4 epdb` to `unbound_model bound` (`(1) + (3)`, while preserving all raw `.dlg` terms verbatim) lifted `autodock4 epdb` Calibration `BEDROC_20` from **`0.3517` (`EF1% = 0.00`)** to **`0.7585` (`EF1% = 5.71`)**, matching `Vina 1.2.7 --scoring ad4 --score_only` and native `AutoDock-GPU 1.6` within `0.00–0.01 kcal/mol` across `10/10` real ligands. A secondary Calibration ablation testing `--local_only` slightly degraded `PC-Q Neural` (`0.5824 -> 0.5357`), confirming that strict in-place `--score_only` (`mutated_original_pose = False`) with corrected `unbound_model bound` is both physically cleaner and stronger.
3. **Commit `9ec95a1` (`fix(m2a,m5): apply unbound_model=bound to AutoDock4 epdb rescoring and parallelize consensus medoids`):**
   - Added `ParsedAutoDock4EpdbResult.bound_unbound_free_energy_kcal_mol` (`autodock4_job.py`) while preserving raw `estimated_free_energy_kcal_mol` and terms `(1)`–`(4)` verbatim in `PoseRescoreFunctionEvidence`.
   - Replaced per-medoid AutoGrid map file copying with read-only symlinks (`shutil.copy2` fallback) in `pose_rescoring.py` and added deterministic parallel medoid rescoring (`rescore_workers`) in `pose_consensus.py` (`17×` faster `epdb` cross-scoring: `891` medoids in `72.8 s` vs. `1,229.7 s`).
   - Verified dual-OS (`18/18` pytest on Windows & Linux, `ruff`, `mypy --strict`, `ADR-031` `0`-byte dependency delta).

### Out-of-Sample Before/After Verification on `ESR_antago` (`5UFX`, Locked Confirmation `N = 300`)

| Consensus Variant (`ESR_antago` `5UFX`) | Axis A Pre-`9ec95a1` (Rec. `142`) | Axis A Post-`9ec95a1` | Axis A Gain | Axis B Pre-`9ec95a1` (Rec. `142`) | Axis B Post-`9ec95a1` | Axis B Gain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **Ankora `PC-Q Neural`** | `0.2659` | **`0.3188`** | **`+0.0529`** | `0.2707` | **`0.3517`** (`EF1%=1.89`) | **`+0.0810`** |
| **Ankora `PC-Q Core` (non-neural)** | `0.2125` | **`0.2782`** | **`+0.0657`** | `0.2286` | **`0.2751`** | **`+0.0465`** |
| **Ankora `PC-ECR`** | `0.2507` | **`0.2906`** | **`+0.0399`** | `0.2720` | **`0.3132`** | **`+0.0412`** |
| `DockM8 v1.1.1 ECR` (unchanged reference) | `0.3040` | `0.3040` | `0.0000` | `0.1366` | `0.1366` | `0.0000` |

---

## 2. Sealed Multi-Target Cohorts, Split Provenance & Decoy Bias Audits (`ADR-031 §3`)

All three targets come from the frozen `LIT-PCBA_AVE_unbiased.tar.gz` benchmark archive (`LIT_PCBA_ANKORA_VS_V1`), sealed by Ankora `M2` (`ProtocolCalibrationService.create_split`) using Bemis-Murcko scaffold-disjoint grouping (`grouping_strategy = "parent_and_murcko_scaffold"`, seed `20261120`, `0` shared parents and `0` shared scaffolds across Calibration/Confirmation):

| Target (PDB) | Receptor Class & Governance | Total Cohort | Calibration (`40%`) | Locked Confirmation (`60%`) | `split_identity_sha256` (prefix) | Physicochemical Bias Audit Flagged Properties |
| --- | --- | ---: | --- | --- | --- | --- |
| **`ESR_antago`** (`5UFX`) | Nuclear receptor antagonist (Chain A, `86Y` site) | `500` (`88A` / `412I`) | `200` (`35A` / `165I`, `167` scaffolds) | `300` (`53A` / `247I`, `248` scaffolds) | `33cb058cfaa44733` | `['clogp']` |
| **`TP53`** (`3ZME`) | Metalloprotein (Chain A, structural **`ZN 313`** retained; explicit coordination overrides `HIS179=HIE`, `CYS238=CYM`, `CYS242=CYM`; `QC5` site) | `500` (`64A` / `436I`) | `200` (`26A` / `174I`, `47` scaffolds) | `300` (`38A` / `262I`, `296` scaffolds) | `c7c7d5ded4ec30aa` | **`[]` (0 properties flagged)** |
| **`PPARG`** (`3B1M`) | Nuclear receptor agonist (Chain A, `KRC` site) | `300` (`24A` / `276I`) | `120` (`10A` / `110I`) | `180` (`14A` / `166I`) | `6c8579abf37fe74e` | `['molecular_weight', 'hbd', 'hba', 'rotatable_bonds', 'formal_charge']` (disclosed) |

> **Honest bias disclosure (`ADR-031 §3`):** `TP53` has zero physicochemical decoy bias across all 6 audited properties; `ESR_antago` flags `clogp`; `PPARG` flags 5 physicochemical properties in the underlying `LIT-PCBA` active/inactive distributions. Because both Ankora and `DockM8` evaluate the **exact same sealed parent split** under identical denominators and worst-tie failure retention, relative paired deltas remain controlled while absolute enrichment values on `PPARG` must be read alongside its disclosed property shift.

---

## 3. Official Two-Axis External Comparison Results (`evaluate_comparison.py`)

All comparisons below were produced by stdlib-only `python -S benchmarks/external_comparison/evaluate_comparison.py` (`2,000` stratified paired parent bootstrap replicates, seed `20261120`) consuming Ankora exclusively via SHA-256-verified **`Export v5`** ZIP bundles (`scripts/verify_export_bundle.py --require-format 5`):

### 3.1 Primary Comparison: `Ankora v0.2 PC-Q Neural` vs. `DockM8 v1.1.1 ECR`

| Target (`N` Conf.) | Axis | Ankora `BEDROC_20` (`EF1%`, `ROC-AUC`, `PR-AUC`) | DockM8 `ECR` `BEDROC_20` (`EF1%`, `ROC-AUC`, `PR-AUC`) | Paired `Δ BEDROC_20` (`95% CI`) | Verbatim `ADR-031` Verdict |
| --- | --- | --- | --- | --- | --- |
| **`ESR_antago`** (`300`) | Axis A (`controlled`) | **`0.3188`** (`1.89`, `0.6117`, `0.2691`, `287/300`) | `0.3040` (`1.89`, `0.6448`, `0.2582`, `297/300`) | `+0.0148` `[-0.1649, +0.1851]` | `Insufficient evidence to prefer over baseline` |
| **`TP53`** (`300`) | Axis A (`controlled`) | **`0.2754`** (`0.00`, `0.5272`, `0.1773`, `286/300`) | `0.1215` (`2.63`, `0.5573`, `0.1623`, `293/300`) | `+0.1539` `[-0.0666, +0.3613]` | `Insufficient evidence to prefer over baseline` |
| **`PPARG`** (`180`) | Axis A (`controlled`) | **`0.3304`** (`6.43`, `0.7935`, `0.2485`, `171/180`) | `0.1926` (`6.43`, `0.5753`, `0.1371`, `177/180`) | `+0.1378` `[-0.0421, +0.3651]` | `Insufficient evidence to prefer over baseline` |
| **3-Target Macro (`780`)** | **Axis A (`controlled`)** | **`0.3082`** (Macro `ROC-AUC 0.6441`) | `0.2060` (Macro `ROC-AUC 0.5924`) | **`+0.1022` (`1.50×`)** | **Ankora higher on 3/3 targets** |
| **`ESR_antago`** (`300`) | Axis B (`end_to_end`) | **`0.3517`** (`1.89`, `0.6716`, `0.2981`, `296/300`) | `0.1366` (`1.89`, `0.4703`, `0.1674`, `298/300`) | `+0.2151` `[-0.0185, +0.4248]` | `Insufficient evidence to prefer over baseline` |
| **`TP53`** (`300`) | Axis B (`end_to_end`) | **`0.2449`** (`0.00`, `0.5639`, `0.1763`, `293/300`) | `0.0702` (`0.00`, `0.4605`, `0.1229`, `300/300`) | **`+0.1747` `[+0.0124, +0.3573]`** | **`ankora_preferred`** |
| **`PPARG`** (`180`) | Axis B (`end_to_end`) | **`0.2515`** (`6.43`, `0.7407`, `0.1989`, `177/180`) | `0.0054` (`0.00`, `0.4669`, `0.0738`, `179/180`) | **`+0.2461` `[+0.0483, +0.4857]`** | **`ankora_preferred`** |
| **3-Target Macro (`780`)** | **Axis B (`end_to_end`)** | **`0.2827`** (Macro `ROC-AUC 0.6587`) | `0.0707` (Macro `ROC-AUC 0.4659`) | **`+0.2119` (`4.00×`)** | **Ankora `ankora_preferred` on 2/3 (`3/3` vs `RBR`)** |

### 3.2 Shared `PoseBusters 0.6.5` Physical-Validity Stratification (`config="dock"`)

| Target | Axis | Ankora `PB` Pass Rate (`PB`-Valid `BEDROC_20`) | DockM8 `PB` Pass Rate (`PB`-Valid `BEDROC_20`) | DockM8 Axis B `PDBFixer` Pentavalent Carbons | Paired `PB`-Valid `Δ BEDROC_20` (`95% CI`) | Verdict |
| --- | --- | --- | --- | ---: | --- | --- |
| **`ESR_antago`** | Axis A | `275/287` (`95.82%`) — **`0.3188`** | `268/297` (`90.24%`) — `0.2995` | `0` (Ankora rec.) | `+0.0193` `[-0.1649, +0.2031]` | Null |
| **`TP53`** | Axis A | `256/281` (`91.10%`) — **`0.2293`** | `259/293` (`88.40%`) — `0.0700` | `0` (Ankora rec.) | `+0.1594` `[-0.0090, +0.3303]` | Null |
| **`PPARG`** | Axis A | `150/168` (`89.29%`) — **`0.3383`** | `161/177` (`90.96%`) — `0.1933` | `0` (Ankora rec.) | `+0.1450` `[-0.0398, +0.3829]` | Null |
| **3-Target Macro** | **Axis A** | **`92.07%`** — **`0.2955`** | `89.87%` — `0.1876` | `0` | **`+0.1079` (`1.58×`)** | — |
| **`ESR_antago`** | Axis B | **`290/296` (`97.97%`)** — **`0.3544`** | `264/298` (`88.59%`) — `0.1663` | **`34`** (RDKit valence fail) | `+0.1881` `[-0.0529, +0.4226]` | Null |
| **`TP53`** | Axis B | **`263/287` (`91.64%`)** — **`0.2453`** | `272/300` (`90.67%`) — `0.0707` | **`8`** (RDKit valence fail) | **`+0.1746` `[+0.0111, +0.3482]`** | **`ankora_preferred`** |
| **`PPARG`** | Axis B | **`161/174` (`92.53%`)** — **`0.2883`** | `163/179` (`91.06%`) — `0.0084` | **`5`** (RDKit valence fail) | **`+0.2798` `[+0.0765, +0.5188]`** | **`ankora_preferred`** |
| **3-Target Macro** | **Axis B** | **`94.05%`** — **`0.2960`** | `90.11%` — `0.0818` | **`47` across 3/3 targets (`0` on Ankora)** | **`+0.2142` (`3.62×`)** | — |

> **Receptor preparation integrity finding (`3/3` targets):** On every single target in Axis B, `DockM8 v1.1.1 --protein_protonation pdbfixer` produced unminimized rebuilt loop/terminal coordinates containing hypervalent (`>= 5`-bonded) carbon atoms (`34` on `5UFX`, `8` on `3ZME`, `5` on `3B1M`), causing RDKit standard `proximityBonding=True` receptor sanitization to fail and requiring `proximityBonding=False` fallback during external `PoseBusters` auditing (plus stripping/ignoring explicit zinc coordination governance on `3ZME` and collapsing `PPARG` Axis B `BEDROC_20` from `0.1926` to `0.0054`). Ankora's explicit receptor governance produced **`0/3`** receptor sanitization errors across all targets.

### 3.3 Secondary & Non-Neural Variants (3-Target Macro `BEDROC_20`, `N = 780`)

| Comparison | Axis A Macro (`Ankora` vs. `DockM8`) | Axis B Macro (`Ankora` vs. `DockM8`) | Axis B Significant Targets (`95% CI > 0`) |
| --- | --- | --- | --- |
| **`PC-Q Neural` vs. `DockM8 ECR`** (primary) | **`0.3082`** vs. `0.2060` (`+0.1022`, `1.50×`) | **`0.2827`** vs. `0.0707` (`+0.2119`, `4.00×`) | **`2/3`** (`TP53`, `PPARG`) |
| **`PC-Q Neural` vs. `DockM8 RBR`** | **`0.3082`** vs. `0.2369` (`+0.0713`, `1.30×`) | **`0.2827`** vs. `0.0579` (`+0.2248`, `4.88×`) | **`3/3`** (`ESR_antago`, `TP53`, `PPARG` — raw & `PB`) |
| **`PC-Q Core` (non-neural) vs. `DockM8 ECR`** | `0.2158` vs. `0.2060` (`+0.0098`, `1.05×`) | **`0.2033`** vs. `0.0707` (`+0.1326`, `2.87×`) | **`1/3`** (`PPARG`: `+0.1541 [+0.0081, +0.3934]`) |
| **`PC-ECR` vs. `DockM8 ECR`** | `0.2031` vs. `0.2060` (`-0.0029`, `0.99×`) | **`0.2159`** vs. `0.0707` (`+0.1452`, `3.05×`) | **`1/3`** (`PPARG`: `+0.1761 [+0.0122, +0.4155]`) |

### 3.4 Single-Engine & Calibration Breakdown (Honest Mechanistic Attribution)

| Target | Calibration Leader (`BEDROC_20`) | Confirmation Axis A (`Vina` / `AD-GPU` / `GNINA CNN_VS` / **`PC-Q Neural`**) | Confirmation Axis B (`Vina` / `AD-GPU` / `GNINA CNN_VS` / **`PC-Q Neural`**) |
| --- | --- | --- | --- |
| **`ESR_antago`** | `AD-GPU` (`0.7313`), `ad4 epdb` (`0.7585`), `PC-Q Neural` (`0.5824`) | `0.2044` / `0.3694` / `0.3125` / **`0.3188`** | `0.2649` / `0.3587` / `0.3408` / **`0.3517`** |
| **`TP53`** | `Vina` (`0.4762`), `GNINA CNN_VS` (`0.3126`), `PC-Q Neural` (`0.1584`) | `0.1598` / `0.1884` / `0.1290` / **`0.2754`** *(PC-Q beats all 3 engines!)* | `0.1580` / `0.2056` / `0.2174` / **`0.2449`** *(PC-Q beats all 3 engines!)* |
| **`PPARG`** | **`PC-Q Neural` (`0.4505`)**, `GNINA CNN_VS` (`0.4202`) | `0.2064` / `0.1539` / `0.3182` / **`0.3304`** *(PC-Q beats all 3 engines!)* | `0.2152` / `0.1757` / `0.2921` / **`0.2515`** |

Two transparent scientific observations emerge:
1. On **Confirmation Axis A**, post-`9ec95a1` `Ankora PC-Q Neural` outperformed **every single individual Ankora docking engine** on `2/3` targets (`TP53`: `0.2754` vs. max single `0.1884`; `PPARG`: `0.3304` vs. max single `0.3182`) and outperformed `DockM8 ECR` on `3/3` targets (`0.3082` vs. `0.2060`).
2. The non-neural `PC-Q Core` (`0.2158`) essentially tied `DockM8 ECR` (`0.2060`) on Axis A — showing honestly that **GNINA 1.3.3 CUDA neural scoring + multi-engine pose diversity** drives the Axis A controlled advantage over `DockM8`'s SMINA+5-rescorer pipeline, while **Ankora's explicit receptor/ligand preparation governance** drives the **`4.00×`** Axis B end-to-end advantage (`0.2827` vs. `0.0707`, with `PC-Q Core` alone reaching **`2.87×`** on Axis B!).

---

## 4. Verified `Export v5` Bundle Digests (`scripts/verify_export_bundle.py --require-format 5`)

| Target | Axis | Verified Export v5 Bundle Filename | SHA-256 |
| --- | --- | --- | --- |
| `ESR_antago` (`9ec95a1`) | Axis A | `Ankora_ESR1_ant_AxisA_Controlled_PCQ_9ec95a1_consensus-run-1569d819_inputs-51cb7433_20261124-050757_export-4bac6f4f_bundle.zip` | `bc87293f22acf1138aef1caf1549bd709f3cb1b1ac5975f6ed9b599f663260aa` |
| `ESR_antago` (`9ec95a1`) | Axis B | `Ankora_ESR1_ant_AxisB_EndToEnd_PCQ_9ec95a1_consensus-run-286b2ba6_inputs-66a54557_20261124-050932_export-d4e335d3_bundle.zip` | `e242f7400b72fb08b04854753e1d1921b5f2d2bd6b991f31b433f60fca3f9a3f` |
| `TP53` (`9ec95a1`) | Axis A | `Ankora_TP53_AxisA_Controlled_PCQ_consensus-run-60b6fa62_inputs-e31ea6aa_20261124-074405_export-153ed1d5_bundle.zip` | `4432060a19dd0a64ba2ab4b17805113cf5d1b4f9762b6b35d01d7924188a9710` |
| `TP53` (`9ec95a1`) | Axis B | `Ankora_TP53_AxisB_EndToEnd_PCQ_consensus-run-45e5017e_inputs-80c37190_20261124-084159_export-d4f155e9_bundle.zip` | `8d3ab97eb026e5c082197e8d7a7b1076aaeea13081c5aae4d010ea6c7b2d13ab` |
| `PPARG` (`9ec95a1`) | Axis A | `Ankora_PPARG_AxisA_Controlled_PCQ_consensus-run-0d91688f_inputs-6720f7ef_20261124-100349_export-fe990cf1_bundle.zip` | `478a6e218366ce29d9872742405bcfdef046494a4c399b8f41a54954598b6e82` |
| `PPARG` (`9ec95a1`) | Axis B | `Ankora_PPARG_AxisB_EndToEnd_PCQ_consensus-run-24b75e92_inputs-c12afc45_20261124-104335_export-805ce914_bundle.zip` | `40e26d544001cacd9d951c8275564d28380bc5c70f2def91ad885a7e5737526a` |
