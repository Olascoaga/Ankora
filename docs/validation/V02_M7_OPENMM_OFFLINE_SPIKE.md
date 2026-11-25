# Ankora v0.2 Conditional `M7` Feasibility Spike — Zero-Network `OpenMM` Small-Molecule Parameterization (Dual-OS)

- **Date:** 2026-11-21
- **Branch:** `codex/v0.2-dev` (`142e904`)
- **Governance:** [`ADR-031`](../architecture/ADR/ADR-031-external-benchmark-boundary.md) (`<= 1.00 MiB` Core installer budget & forbidden heavy-ML dependencies), [`ADR-032`](../architecture/ADR/ADR-032-explicit-flexibility-and-pose-complex-identity.md)
- **Preceding Record:** [`V02_OFFLINE_INSTALLER_ATTESTATION.md`](V02_OFFLINE_INSTALLER_ATTESTATION.md)
- **Verdict:** **`DEFER` FROM `v0.2.0` CORE INSTALLER** (eligible only as a future `ADR-029`-style optional offline add-on pack in `v0.3+`, never inside the Core desktop bundle).

---

## 1. Spike Objective & Zero-Network Guardrail

Before authorizing any `M7` (`OpenMM` protein-ligand complex minimization / explicit-solvent relaxation) implementation inside `Ankora v0.2`, this spike empirically measured whether Ankora's already-locked Windows and Linux scientific runtimes (`OpenMM 8.5.2`, `RDKit 2025.9.6`, `PDBFixer 1.12.0`, `Meeko 0.7.1`) can parameterize diverse drug-like small molecules **100% offline** (`socket.socket` monkeypatch-blocked prior to importing `openmm` or `rdkit`) without breaking `ADR-031`'s Core installer-size cap (`<= 1.00 MiB` cumulative delta) or substituting unvalidated shortcut force fields.

---

## 2. Empirical Dual-OS Probe Results (`socket.socket` Blocked)

Executed identically in locked `ankora-dev` (`Python 3.12.13`) on both **Windows 11 x64** and **Linux x86\_64 (WSL2 Ubuntu 24.04)**:

| Metric | Windows 11 x64 (`ankora-dev`) | Linux x86\_64 WSL2 (`ankora-dev`) |
| --- | --- | --- |
| `socket.socket` network block active | `true` | `true` |
| Locked `OpenMM` version & platforms | `8.5.2` (`Reference`, `CPU`, `OpenCL`) | `8.5.2` (`Reference`, `CPU`, `CUDA`) |
| Built-in `openmm/app/data/*.xml` files | `84` (proteins, nucleic acids, waters, lipids, ions only) | `84` (proteins, nucleic acids, waters, lipids, ions only) |
| External small-molecule parameterizers installed (`openmmforcefields`, `openff.toolkit`, `openff.interchange`, `openff.nagl`, `espaloma`, `parmed`, `acpype`, `antechamber`) | **`0 / 8`** | **`0 / 8`** |
| Protein-only `amber14-all.xml` + `implicit/gbn2.xml` CPU minimization (`GARYMP`, `50` steps) | **PASS** (`-338.296` -> `-367.273 kcal/mol`, `3,358 ms`) | **PASS** (`-337.645` -> `-366.660 kcal/mol`, `2,005 ms`) |
| Diverse 10-compound small-molecule panel under native `OpenMM` (`amber14-all.xml`) | **`0 / 10` passed** (`ValueError: No template found for residue 0 (UNL)` on all 10) | **`0 / 10` passed** (`ValueError: No template found for residue 0 (UNL)` on all 10) |
| Same 10-compound panel under already-locked `RDKit` `MMFF94s` (`M3` strain engine) | **`9 / 10` passed** (`bortezomib` boron honestly flagged unparameterized) | **`9 / 10` passed** (`bortezomib` boron honestly flagged unparameterized) |

### 2.1 Ten-Compound Diverse Small-Molecule Panel Breakdown

| Probe Compound | Chemical Class | `RDKit MMFF94s` (`M3`) | Native `OpenMM 8.5.2` (`amber14-all.xml`) |
| --- | --- | --- | --- |
| `aspirin_neutral` | Neutral carboxylic acid | Parameterized | Failed (`No template found for residue 0 (UNL)`) |
| `ibuprofen_anion` | Anionic carboxylate | Parameterized | Failed (`No template found for residue 0 (UNL)`) |
| `diphenhydramine_cation` | Cationic tertiary amine | Parameterized | Failed (`No template found for residue 0 (UNL)`) |
| `celecoxib_sulfonamide` | Sulfonamide + `-CF3` | Parameterized | Failed (`F atoms not supported by any template`) |
| `diclofenac_chloro` | Aryl dichloride | Parameterized | Failed (`Cl atoms not supported by any template`) |
| `bromobenzene_hal` | Aryl bromide | Parameterized | Failed (`Br atoms not supported by any template`) |
| `indomethacin_indole` | Indole amide + `Cl` | Parameterized | Failed (`Cl atoms not supported by any template`) |
| `chloramphenicol_nitro` | Nitroaromatic + `Cl` | Parameterized | Failed (`Cl atoms not supported by any template`) |
| `alendronate_phosphonate` | Bisphosphonate | Parameterized | Failed (`No template found for residue 0 (UNL)`) |
| `bortezomib_boronic` | Boronic acid (`B`) | Unparameterized (honest `NOT_EVALUABLE`) | Failed (`B atoms not supported by any template`) |

---

## 3. Footprint & Scientific Integrity Decision (`DEFER`)

1. **No zero-byte shortcut is scientifically acceptable:** Native `OpenMM` ships zero small-molecule force-field templates (`0 / 10` coverage). Synthesizing an ad-hoc unvalidated `Gasteiger` + `UFF` XML hack for protein-ligand complex MD/relaxation would violate Ankora's scientific policy against silent methodological shortcuts.
2. **Real offline small-molecule parameterizers violate `ADR-031` Core size & dependency boundaries:**
   - **GAFF2 / OpenFF Sage + AM1-BCC (`openmmforcefields` + `openff-toolkit` + `openff-forcefields` + `ambertools`/`antechamber`/`sqm`):** requires `~180–350 MiB` compressed (`> 500 MiB` unpacked) plus GPL/LGPL source-companion compliance—**`200×` to `350×` over** `ADR-031`'s `1.00 MiB` Core delta cap (currently attested at `+395 KiB` `.deb` / `+640 KiB` `.tar.zst` / `+787 KiB` `.exe` across `M0`–`M6.5`).
   - **Neural charge assignment (`openff-nagl` / `espaloma`):** requires `torch` or `onnxruntime`, explicitly forbidden in Core installers by `ADR-031 §1`.
3. **Existing `v0.2` Core coverage already addresses post-docking refinement and physical quality:** `M1` provides create-only `--local_only` pose refinement in `Vina 1.2.7` and Linux `GNINA 1.3.3` (preserving parent poses immutably), and `M3` provides coupled `PoseBusters 0.6.5` + dual `MMFF94s` conformational strain (`9/10` panel coverage, honest `NOT_EVALUABLE` on boron) within `< 0.79 MiB` total installer delta.
4. **Closure:** Conditional `M7` is **formally deferred** out of `v0.2.0` Core. If post-docking `OpenMM` protein-ligand minimization/MD is prioritized in `v0.3+`, it must ship strictly as a separate optional offline add-on pack (following `ADR-029`'s GNINA pack architecture) with audited `OpenFF Sage` / `AM1-BCC` parameterization and corresponding license/source bundles.
