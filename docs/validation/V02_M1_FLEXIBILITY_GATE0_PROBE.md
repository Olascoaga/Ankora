# Ankora v0.2 `M1` Gate 0 — Explicit-Flexibility CLI and Format Capability Probe (cross-OS, predeclared)

- **Record type:** pre-implementation **CLI / format engineering capability probe**
- **Gate:** `M1 Gate 0` of [`ADR-032`](../architecture/ADR/ADR-032-explicit-flexibility-and-pose-complex-identity.md) §2.4
- **Date executed:** `2026-11-18`
- **Hosts:** **Windows 11 x64** and **Linux `x86_64` (WSL2 Ubuntu 24.04)**
- **Driver:** `scripts/probe_m1_flexibility_capabilities.py`, plus the recorded GNINA `--out_flex .pdb` + Meeko-template follow-up on Linux
- **Fixtures:** synthetic, labelled synthetic — `SYNTHETIC_GATE0_GARYMP`, `SYNTHETIC_GATE0_AMIDE_FLEX`, `SYNTHETIC_GATE0_MACROCYCLE`
- **Outcome:** **GATE 0 PASSED** across all four engines on both hosts, subject to the locked addendum rules in `ADR-032`

## Scope declaration — what this record is, and what it is not

This is a **pre-implementation engineering capability probe**, executed live against the
pinned Ankora toolchains before any `v0.2` `M1` flexibility code is written. It exists to
discharge the **`M1 Gate 0` verification requirement** written into `ADR-032` §2.4, which
follows the [`ADR-028`](../architecture/ADR/ADR-028-gnina-cnn-vs-refinement-ensemble.md)
precedent of **empirically probing upstream CLI contracts rather than assuming documented
behavior** (where `--cnn default` was found to fail closed).

It verifies **software mechanics and upstream tool contracts only**:

- that each flag named in `ADR-032` exists, is accepted, and does what the ADR assumes;
- what each tool actually writes to disk, byte for byte, including malformed output;
- whether a tool fails closed, fails open, or **silently exits `0` while producing a wrong
  or corrupted artifact**.

**It does not establish any scientific result.** Explicitly, this record:

- does **not** extend, amend, or soften the frozen scientific benchmark claims summarized in
  [`VALIDATION_STATUS.md`](VALIDATION_STATUS.md);
- does **not** constitute redocking validation, enrichment evidence, pose-prediction
  accuracy, or prospective virtual-screening performance;
- does **not** constitute bare-metal Linux workstation acceptance
  ([`ADR-029`](../architecture/ADR/ADR-029-linux-offline-distribution.md) Gate `D6` remains open);
- reports docking energies **only** as evidence that an engine ran to completion and emitted
  a parseable artifact. The numeric values below are from a 6-residue synthetic peptide and
  carry **no** physical or biological meaning whatsoever.

All fixtures are **synthetic and labelled synthetic**. No crystallographic system, no
reference case, and no benchmark denominator is touched by this probe.

## 1. Synthetic fixtures (labelled synthetic)

### 1.1 Receptor — `SYNTHETIC_GATE0_GARYMP`

A 6-residue synthetic peptide `GARYMP`, chain `A`, chosen so that every `ADR-032` §2.1 hard
rejection (`GLY`, `ALA`, `PRO`) and at least two legitimately flexible side chains (`TYR`,
`MET`) are present in a single minimal fixture:

| Locator | Residue | Role in this probe |
| --- | --- | --- |
| `A:1` | `GLY` | `ADR-032` §2.1 hard rejection — no rotatable side chain |
| `A:2` | `ALA` | `ADR-032` §2.1 hard rejection — no `chi` torsion |
| `A:3` | `ARG` | Spectator |
| `A:4` | `TYR` | Legitimate `FlexRes` target (`3` branches) |
| `A:5` | `MET` | Legitimate `FlexRes` target (`3` branches, contributes atom type `SA`) |
| `A:6` | `PRO` | `ADR-032` §2.1 hard rejection — side chain closed onto backbone |

Protonated with `PDB2PQR 3.7.1` using `--ff=PARSE --keep-chain
--titration-state-method=propka --with-ph=7.4` and `PROPKA 3.5.1`. The full rigid PDBQT
contains `61` atoms.

`MET A:5` is deliberately included because it is the **only** source of PDBQT atom type `SA`
in the fixture — the asymmetry that exposes critical finding `F1`.

### 1.2 Ligands

| Fixture | Definition | Default Meeko PDBQT |
| --- | --- | --- |
| `SYNTHETIC_GATE0_AMIDE_FLEX` | SMILES `CC(=O)NCc1ccc(CCC)cc1` | `15` atoms, types `['A', 'C', 'HD', 'N', 'OA']`, `4` branches, `TORSDOF 4`. **Sulfur-free by construction.** |
| `SYNTHETIC_GATE0_MACROCYCLE` | 14-membered cyclic ether/ester macrocycle, built with RDKit `MMFF94s` | `16` atoms, types `['C', 'CG0', 'G0', 'OA']`, `12` branches, `has_macrocycle_glue=True`, `TORSDOF 0` |

`SYNTHETIC_GATE0_AMIDE_FLEX` is sulfur-free **by design**: it guarantees that `SA` appears in
the flexible-receptor atom types and **not** in the ligand atom types, which is exactly the
condition that `ADR-032` invariant `E7` must defend against.

### 1.3 Binding box

`20 x 20 x 20 Å` centered on the mean heavy-atom coordinates of `TYR A:4` and `MET A:5`:

| Host | Box center |
| --- | --- |
| Linux `x86_64` | `(-1.448, -1.940, -0.968)` |
| Windows 11 x64 | `(-1.467, -1.829, -1.120)` |

The small center difference is expected and recorded: each host built its own RDKit
ETKDG/MMFF94s conformer independently, so the fixture coordinates are not byte-identical
across hosts. **This probe therefore compares CLI and format behavior across hosts, never
energies across hosts.**

AutoGrid4 maps used `npts = [54, 54, 54]` at `0.375 Å` spacing, for a realized `20.25 Å`
box edge.

## 2. Verified pinned toolchains and binary SHA-256 digests

All digests were computed live on each host during the probe.

### 2.1 Linux `x86_64` (WSL2 Ubuntu 24.04)

| Tool | Version | SHA-256 |
| --- | --- | --- |
| `python` | `3.12.13` | `80d338634756ee6ffc0130ccd63909abb98681d84d6f993b5d19ca3d4428de2f` |
| `rdkit` | `2025.9.6` | *(Python distribution, not a single binary)* |
| `propka` | `3.5.1` | *(Python distribution, not a single binary)* |
| `pdb2pqr` | `3.7.1` | `2c05910b335e0c926e1fb9cd50be43be84b56285150ca2ad4fd1905144b72a7c` |
| `mk_prepare_ligand.py` (Meeko) | `0.7.1` | `e18d6b2bd171b4d67e6d650c79b8b3f5f7347a5b1e631c9e0d08ddaa59d966f8` |
| `mk_prepare_receptor.py` (Meeko) | `0.7.1` | `f0d507c9d653f3ce98cf63222fbb1a43b80c2530832b78039e604418f1034350` |
| `vina_1.2.7_linux_x86_64` | `1.2.7` | `f31f774f723bba7bbe6e9d1c47577020eea9a8da16424284c043d22593570644` |
| `autogrid4` | `4.2.6` | `91621b89d13410efde31aed2a0934b15837172ef167d783bec0b3a94d384dc72` |
| `autodock4` | `4.2.6` | `15ac656b45db209655b1aae908ed1e06e743c7be4abb55b039f0bf38a6fd9fc9` |
| `autodock_gpu_128wi` | `1.6` | `0d1be9d563be94e439eea592578b9e689b6603712507212e663c0076806a009c` |
| `gnina.cuda12.8.static` | `1.3.3` | `3340c1f49cd3c7c84d8699182a1c6af13c7fa2a22448d1204640446106f72172` |

### 2.2 Windows 11 x64

| Tool | Version | SHA-256 |
| --- | --- | --- |
| `python.exe` | `3.12.14` | `560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e` |
| `rdkit` | `2025.9.6` | *(Python distribution, not a single binary)* |
| `propka` | `3.5.1` | *(Python distribution, not a single binary)* |
| `pdb2pqr.exe` | `3.7.1` | `a483b90874e1d7f068ca9fd5c4cb77ca8a50cecebd1d1690bc1595bb609782fc` |
| `mk_prepare_ligand.exe` (Meeko) | `0.7.1` | `911f6cd990454e2823229105404acef3611f2aca30928d02e141eaca7458e06e` |
| `mk_prepare_receptor.exe` (Meeko) | `0.7.1` | `9df82869dc058a7abbd2d24bd2f99e6b474d2357d5076aa68f97994b66e1ff33` |
| `vina.exe` | `1.2.7` | `e0c4b2715e0c1a74f6e92d0f3be0328ac97542eafbc111e6b1efad897a73cce5` |
| `autogrid4.exe` | `4.2.6` | `797efce687d1ae82df59726461e0e1966b3d8edb0f8b187f982fa1ab0c12da9e` |
| `autodock4.exe` | `4.2.6` | `36c0b16c04d7df8e6225737bae65bb04058d1f4c90accfaf2d230dbc913954bf` |
| `AutoDock-GPU.exe` | `1.6` | `e1f7704efca05c8b1c05fb47fbb13ecdc472a79b3cbe7f8d8d08f69d42269a69` |
| `gnina` | — | `skipped_platform` — **Linux-only per [`ADR-027`](../architecture/ADR/ADR-027-linux-gnina.md)** |

`Meeko 0.7.1`, `Vina 1.2.7`, `AutoGrid4`/`AutoDock4 4.2.6`, `AutoDock-GPU 1.6`, and Linux
`GNINA 1.3.3` are all already-shipped, already-hash-verified components of the frozen
baselines. Consistent with `ADR-032`, this probe introduced **`0` new executables and `0` new
Python distributions**.

## 3. Probe matrix

| Family | Surface probed | Linux `x86_64` | Windows 11 x64 |
| --- | --- | --- | --- |
| `L` | `Meeko 0.7.1` ligand flags — default, `-a`/`--flexible_amides`, `-r`/`-b` rigidification (matched and unmatched), `--rigid_macrocycles` | `rc=0` (all) | `rc=0` (all) |
| `R` | `Meeko 0.7.1` receptor `-f` split naming, `-o`/`-p` path resolution, and `GLY`/`ALA`/`PRO`/missing-residue behavior | `rc=0` / `rc=1` as recorded | identical to Linux |
| `E1` | `Vina 1.2.7` `--flex`, `--scoring vinardo`, `--score_only`, `--local_only` | `rc=0` (all) | `rc=0` (all) |
| `E2` | `AutoGrid4` + `AutoDock4 4.2.6` CPU: rigid macrocycle, and `ligand_only` vs `union` flex maps | `rc=0` / **`rc=-6`** | `rc=0` / **`rc=0` (corrupt)** |
| `E3` | `AutoDock-GPU 1.6` `--flexres`, single and `--filelist` (`-B`) batch | `rc=0` (CUDA) | `rc=0` (OpenCL) |
| `E4` | `GNINA 1.3.3` CPU/CUDA `--out_flex .pdbqt` vs `--out_flex .pdb`, plus Meeko-template coordinate re-injection for `--score_only` and `--local_only` | `rc=0` / `rc=1` as recorded | `skipped_platform` (`ADR-027`) |

### 3.1 Family `L` — Meeko ligand semi-flexible controls

Identical results on both hosts.

| Probe | Invocation | Result |
| --- | --- | --- |
| `L/amide_default` | *(defaults)* | `rc=0`, `15` atoms, `['A', 'C', 'HD', 'N', 'OA']`, `4` branches, `TORSDOF 4` |
| `L/amide_flexible_amides` | `-a` / `--flexible_amides` | `rc=0`, `5` branches, `TORSDOF 5` (**`+1`** vs default) |
| `L/amide_rigidify_match` | `-r "[c:1]-[CH2:2]-[CH2:3]-[CH3:4]" -b 2 3` | RDKit control: **`1` match** (bond `[9, 10]`). `rc=0`, `3` branches, `TORSDOF 3` (**`-1`** vs default) |
| `L/amide_rigidify_no_match` | `-r "[#16]-[CH3]" -b 1 2` | RDKit control: **`0` matches**. **`rc=0`, `TORSDOF 4` unchanged (`delta=0`)** — see finding `F6` |
| `L/macrocycle_default` | *(defaults)* | `rc=0`, `16` atoms, `['C', 'CG0', 'G0', 'OA']`, `12` branches, `has_macrocycle_glue=True`, `TORSDOF 0` |
| `L/macrocycle_rigid` | `--rigid_macrocycles` | `rc=0`, `14` atoms, `['C', 'OA']`, `0` branches, `has_macrocycle_glue=False`, `TORSDOF 0` |

### 3.2 Family `R` — Meeko receptor split and disallowed residues

Identical results on both hosts.

| Probe | Invocation | Result |
| --- | --- | --- |
| `R/full_rigid_receptor` | *(no `-f`)* | `rc=0`, `receptor_full.pdbqt`, `61` atoms, all `6` residues |
| `R/split_with_o_and_p_bare` | `-f A:4,A:5 -o split_a -p` | `rc=0`, `split_a_rigid.pdbqt` (`46` atoms) + `split_a_flex.pdbqt` (`15` atoms). Exact conservation: **`46 + 15 = 61`**. `flex_atom_types = ['A', 'C', 'HD', 'OA', 'SA']` |
| `R/split_with_explicit_p_filename` | `-f A:4 -p explicit_target.pdbqt` | `rc=0`, writes **`explicit_target_rigid.pdbqt` (`51`) + `explicit_target_flex.pdbqt` (`10` atoms, `3` branches)** — never `explicit_target.pdbqt`. See finding `F7` |
| `R/disallowed_and_missing_flexres/gly` | `-f A:1` | **`rc=0` (silent)** — writes `6` N-terminal **backbone** atoms (`C, CA, N, H1, H2, H3`, `2` branches) into the flex file |
| `R/disallowed_and_missing_flexres/ala` | `-f A:2` | **`rc=0` (silent)** — writes **only** `split_rigid.pdbqt` (`61` atoms); **no flex file at all** |
| `R/disallowed_and_missing_flexres/pro` | `-f A:6` | **`rc=0` (silent)** — writes `4` C-terminal **backbone** atoms (`CA, C, O, OXT`, `1` branch) into the flex file |
| `R/disallowed_and_missing_flexres/missing` | `-f A:999` | **Fails closed: `rc=1`**, `ValueError: residue_id='A:999' not in valid monomers` |

In the `A:4,A:5` split, `CA` is the `ROOT` atom inside each `BEGIN_RES ... END_RES` block, with
`CB` and beyond in `BRANCH` records — confirming that `Meeko -f` frees `chi` torsions while the
backbone stays fixed, as `ADR-032` §2 assumes. Per-residue breakdown: `TYR A:4` = `10` atoms /
`3` branches; `MET A:5` = `5` atoms / `3` branches.

### 3.3 Family `E1` — `Vina 1.2.7`

| Probe | Linux `x86_64` | Windows 11 x64 |
| --- | --- | --- |
| `vina_flex_vina_scoring` | `rc=0`, `2` models, `-3.512` / `-3.338`, `max_disp = 5.946 Å` | `rc=0`, `2` models, `-3.443` / `-3.388`, `max_disp = 5.667 Å` |
| `vina_flex_vinardo_scoring` | `rc=0`, `1` model, `-4.045`, `max_disp = 4.185 Å` | `rc=0`, `1` model, `-3.928`, `max_disp = 4.567 Å` |
| `vina --local_only --out` | `rc=0`, `max_disp = 0.086 Å`, `stdout` energy `-3.567 kcal/mol` | `rc=0`, `max_disp = 0.133 Å`, `stdout` energy `-3.511 kcal/mol` |
| `vina --score_only --flex <moved_flex>` (`vina`) | `rc=0`, `-3.625`; `UNBOUND` `-1.583` vs original `-1.721` | `rc=0`, `-3.518`; `UNBOUND` `-1.577` vs original `-1.669` |
| `vina --score_only --flex <moved_flex>` (`vinardo`) | `rc=0`, `-3.589` | `rc=0`, `-3.475` |

Each `--flex` `MODEL` contains the ligand `ROOT..TORSDOF` followed by balanced
`BEGIN_RES TYR A 4 .. END_RES` and `BEGIN_RES MET A 5 .. END_RES` blocks (`15` ligand atoms +
`15` flex atoms). Findings `F2`, `F3`, and `F4` below record the three format and semantic
traps discovered in this family.

### 3.4 Family `E2` — `AutoGrid4` + `AutoDock4 4.2.6` CPU

| Probe | `ligand_types` | Linux `x86_64` | Windows 11 x64 |
| --- | --- | --- | --- |
| `E2_autodock4_rigid_macrocycle` | `['C', 'OA']` | `rcs=[0, 0]`, `Successful Completion`, `2` models, `-2.58` / `-2.40` | `rcs=[0, 0]`, `Successful Completion`, `2` models, `-2.38` / `-2.37` |
| `E2_flex_ligand_only_maps` | `['A', 'C', 'HD', 'N', 'OA']` (**`SA` missing**) | **`exit_code = -6` (`SIGABRT`)**, `*** buffer overflow detected ***: terminated`, `0` docked models | **`rc=0` with silent physics corruption** — `2` models, `-1.12` / `-1.09`, `max_disp = 3.103 Å` |
| `E2_flex_union_maps` | `['A', 'C', 'HD', 'N', 'OA', 'SA']` | `rcs=[0, 0]`, `0` warnings, `2` models, `-1.10` / `-1.66`, `max_disp = 2.536 Å` | `rcs=[0, 0]`, `0` warnings, `2` models, `-1.38` / `-1.66`, `max_disp = 4.425 Å` |

The `union` runs produced `2` docked models with `15` ligand + `15` flex atoms and balanced
`BEGIN_RES`/`END_RES` on both hosts. This divergence is finding `F1`, the most consequential
result of the entire gate.

### 3.5 Family `E3` — `AutoDock-GPU 1.6`

Both **single** (`--flexres`) and **`--filelist`** (`-B` batch) modes exited `0` with
`All jobs ran without errors.` on both hosts, each emitting `2` docked `DOCKED:` models with
`15` ligand + `15` flex atoms and balanced `BEGIN_RES`/`END_RES`.

| Host / mode | Energies | `max_disp` |
| --- | --- | --- |
| Linux CUDA (`autodock_gpu_128wi`), single | `-2.32` / `-2.40` | `4.848 Å` |
| Linux CUDA, `--filelist` | `-2.32` / `-2.40` | `4.848 Å` |
| Windows OpenCL (`AutoDock-GPU.exe`), single | `-1.05` / `-1.75` | `2.974 Å` |
| Windows OpenCL, `--filelist` | `-1.01` / `-2.20` | `2.993 Å` |

**Serial-numbering divergence (recorded for `E8` reconstruction):** `AutoDock4` CPU **continues**
atom serial numbers `16..30` inside `BEGIN_RES`, whereas `AutoDock-GPU` **restarts at `1..15`**.
`PoseComplex` reconstruction must therefore match flex atoms by
`(chain, resseq, icode, resname, atom_name)` and never by PDBQT serial number.

`AutoDock-GPU` flexible-side-chain runs continue to inherit the existing
`DOCKING_GPU_REPRODUCIBILITY_UNVERIFIED` notice; nothing in this probe reclassifies GPU
reproducibility.

### 3.6 Family `E4` — Linux `GNINA 1.3.3` `--out_flex` anatomy

| Probe | Result |
| --- | --- |
| `gnina_flex_cpu` (`--no_gpu`) | `rc=0`, `2` ligand modes, `-2.45` / `-2.53 kcal/mol`, `CNNscore 0.7672` / `0.7536`, `CNNaffinity 3.212` / `3.075` |
| `gnina_flex_cuda` | `rc=0`, `2` ligand modes, `CNNscore 0.7669` / `0.7535`, `CNNaffinity 3.211` / `3.075` |
| `--out_flex gnina_flex_cpu.pdbqt` | **Fragmented and unusable** — `num_modes * num_flex_residues = 4` `MODEL` blocks, no `BEGIN_RES`/`END_RES`, `TYR` re-rooted on `CG..CZ`; reuse **fails closed `rc=1`** |
| `--out_flex flex.pdb` | `rc=0`, **exactly `1` `MODEL ... ENDMDL` block per mode** (`2` total), all moved flex residues in one block with `CONECT` records |
| Meeko-template re-injection -> `--score_only` | **`rc=0`** |
| Meeko-template re-injection -> `--local_only` | **`rc=0`** |

Finding `F5` records this family in full, including the verified working solution.

## 4. Critical empirical findings

Seven findings changed what `v0.2` `M1` must implement. Each is stated as the observed fact
first, then the fail-closed engineering consequence it forces.

### `F1` — `AutoGrid4` `ligand_types` must be the **union**; the failure mode is OS-dependent and silently wrong on Windows

**Observed.** With maps built from `ligand_atom_types` alone (`['A', 'C', 'HD', 'N', 'OA']`,
omitting the `SA` contributed only by the flexible `MET A:5`):

- **Linux `autodock4 4.2.6`** (`15ac656b...`) **crashed**: `exit_code = -6` (`SIGABRT`),
  `*** buffer overflow detected ***: terminated`, `0` docked models written.
- **Windows `autodock4.exe 4.2.6`** (`36c0b16c...`) **exited `0`** with `Successful
  Completion` and wrote `2` docked models (`-1.12` / `-1.09 kcal/mol`), after printing only:
  `WARNING: the atom type (SA) of atom number 29 could not be found; ... Note that AutoDock
  will use the default atom type = 1, instead.`

With `union` maps (`['A', 'C', 'HD', 'N', 'OA', 'SA']`), both hosts exited `0` with `0`
warnings and correct balanced flex output.

**Why this shapes `M1`.** This is the single most dangerous result in the gate. The Windows
path **silently substitutes a default atom type for a real flexible side-chain atom** and
still reports success with numerically plausible energies. A scientist comparing Windows and
Linux runs of the same protocol would see one crash and one "successful" result, and the
"successful" one is the corrupted one. Ankora can never rely on the engine to surface this.

Consequently `ADR-032` invariant `E7` is **tightened**: `ligand_types` MUST be computed as
`union(ligand_atom_types, flex_receptor_atom_types)`, validated against the `14`-type stock
AutoGrid4 ceiling **before** map generation, and map identity MUST bind
`(receptor_rigid_sha256, flex_residues, flex_atom_types)` with `AUTOGRID_FLEXRES_MAP_MISMATCH`
failing closed on any mismatch. Detecting this after the fact is not an option, because on
Windows there is nothing in the exit code or result file to detect.

### `F2` — Windows `vina.exe 1.2.7` emits a 30-NUL-byte line inside every `--flex` model

**Observed.** On Windows 11 x64, `vina.exe 1.2.7` (`e0c4b271...`) emits a line of
**`30` NUL bytes** (`b'\x00' * 30 + b'\r\n'`) immediately after `TORSDOF 4` and before
`BEGIN_RES TYR A 4`, in **every** flex model — under both `vina` and `vinardo` scoring and
under `--local_only`:

| Windows artifact | NUL bytes |
| --- | ---: |
| `vina_flex_out.pdbqt` (`2` models) | `60` |
| `vinardo_flex_out.pdbqt` (`1` model) | `30` |
| `vina_local_out.pdbqt` (`1` model) | `30` |

Linux `vina_1.2.7_linux_x86_64` emits **`0`** NUL bytes across all outputs.

**Why this shapes `M1`.** An embedded NUL truncates input in C/C++ string handling, which is
exactly what `RDKit`, `MDAnalysis`, and `Mol*` use. A Windows flex pose could therefore be
silently truncated at the ligand/flex boundary — losing precisely the moved side chains that
`E8` exists to preserve. Ankora must **strip pure-NUL lines when materializing derived pose
splits and `PoseComplex` artifacts**, while leaving the **raw `vina` output immutable on
disk** per `ADR-004` and the `AGENTS.md` raw-output rule. The corruption is repaired in the
derivative, never in the evidence.

### `F3` — `Vina --local_only --out` writes a flat PDBQT and echoes a **stale** energy

**Observed.** On both hosts, `--local_only --out vina_local_out.pdbqt` exited `0`
(`max_disp = 0.086 Å` Linux, `0.133 Å` Windows) and wrote a **flat PDBQT with `0`
`MODEL`/`ENDMDL` wrappers**. Its `REMARK VINA RESULT` header carried the **stale inherited
input energy** (`-3.512` Linux / `-3.443` Windows), not the newly minimized value, which
appeared only on `stdout` as `Estimated Free Energy of Binding : -3.567 kcal/mol` (Linux) /
`-3.511 kcal/mol` (Windows).

**Why this shapes `M1`.** A pose parser that assumes `MODEL` wrappers would read `0` poses
from a successful refinement, and a parser that trusts `REMARK VINA RESULT` would record the
**parent pose's** energy as the refined result — attaching a wrong number to a real
derivative under `ADR-032` §1.5. `M1` must therefore accept flat single-pose PDBQT
(`0` `MODEL` lines) and parse the authoritative `--local_only` energy **from `stdout` only**.

### `F4` — `Vina --score_only --flex` recomputes `UNBOUND` from the moved geometry

**Observed.** `--score_only --flex <moved_flex>` succeeded (`rc=0`) for both scoring
functions — `vina` `-3.625` (Linux) / `-3.518` (Windows); `vinardo` `-3.589` / `-3.475`. Vina
recomputes `(4) Unbound System's Energy` from the **passed moved flex geometry**:
`-1.583` vs the docking-time `-1.721` (Linux), and `-1.577` vs `-1.669` (Windows).

**Why this shapes `M1`.** The flag works, so cross-family rescoring on the coupled complex is
viable — but the `UNBOUND` reference has **moved**, which shifts total affinity relative to the
docking-time value. Comparing a `--score_only` total against a docking total without recording
this is a silent apples-to-oranges comparison. The `UNBOUND` reference shift MUST be recorded
explicitly in `M5` `PC-Q` cross-family rescoring provenance.

### `F5` — `GNINA 1.3.3` `--out_flex` requires `.pdb` and ordinal pose pairing

**Observed, in three parts.**

1. **The `.pdbqt` trap.** `--out_flex gnina_flex_cpu.pdbqt` fragments output into
   `num_modes * num_flex_residues = 4` `MODEL` blocks (`MODEL 3` TYR, `MODEL 3` MET,
   `MODEL 4` TYR, `MODEL 4` MET), **omits `BEGIN_RES`/`END_RES` entirely**, and re-roots `TYR`
   on `CG..CZ`. Feeding an extracted block back to `gnina --flex` **fails closed** with
   `rc=1`, `Parse error on line 12 in file "model1_flex.pdbqt": Unknown or inappropriate tag`
   — for both `--score_only` and `--local_only`.
2. **The `.pdb` contract.** `--out_flex flex.pdb` exits `0` and writes **exactly `1`
   `MODEL ... ENDMDL` block per docking mode** (`2` for `2` modes), each containing all moved
   flex residues plus `CONECT` records in a single block (`TYR A 4` atoms `1..10`,
   `MET A 5` atoms `11..15`). **However**, GNINA's OpenBabel writer shares a model counter
   with `--out`, so the flex models are labelled `MODEL 3` and `MODEL 4` — numbered from
   `num_modes + 1`.
3. **The verified solution.** Re-injecting the moved `(x, y, z)` coordinates from
   `--out_flex flex.pdb`, matched by `(chain, resseq, icode, resname, atom_name)`, back into
   the **immutable Meeko `split_a_flex.pdbqt` template** makes both reuse paths succeed:

   | Re-injected invocation | Result |
   | --- | --- |
   | `--score_only` | **`rc=0`** — `Affinity: -2.44780 kcal/mol`, `CNNscore: 0.76707`, `CNNaffinity: 3.21187`, `CNNvariance: 0.30426`, `Intramolecular energy: -1.78429` |
   | `--local_only --out local_lig.pdbqt --out_flex local_flex.pdb` | **`rc=0`** — `Affinity: -2.45952 -1.85262 kcal/mol`, `RMSD: 0.15265`, `CNNscore: 0.76030`, `CNNaffinity: 3.19781`, `CNNvariance: 0.32435` |

**Why this shapes `M1`.** The naive implementation — `--out_flex <file>.pdbqt`, then pair
poses by `MODEL` integer — is wrong in two independent ways at once, and the second way is
silent. Pairing ligand `MODEL 1` with flex `MODEL 1` would find **no match** (flex models start
at `3`), and any fallback to literal integer equality risks pairing a ligand pose with the
wrong side-chain conformation — producing a `PoseComplex` that never existed. `M1` must
invoke `--out_flex <file>.pdb`, pair by **0-based ordinal model index**, and re-inject
coordinates into the immutable Meeko template. GNINA's own flex output is a **coordinate
source, never a reusable topology**.

### `F6` — `Meeko` ligand rigidification **silently exits `0`** when the SMARTS matches nothing

**Observed.** With an RDKit control proving the match count beforehand:

| Flag | RDKit control | Meeko result |
| --- | --- | --- |
| `--rigid_macrocycles` | — | `rc=0`, `CG0`/`G0` removed, `16 -> 14` atoms, `['C', 'OA']`, `0` branches — unlocks `AutoGrid4`/`AutoDock4` cleanly on **both** hosts |
| `-r "[c:1]-[CH2:2]-[CH2:3]-[CH3:4]" -b 2 3` | **`1` match** (bond `[9, 10]`) | `rc=0`, `TORSDOF 4 -> 3` |
| `-r "[#16]-[CH3]" -b 1 2` | **`0` matches** | **`rc=0`, `TORSDOF` unchanged at `4`** |
| `-a` / `--flexible_amides` | — | `rc=0`, `TORSDOF 4 -> 5` (**`+1`**) |

**Why this shapes `M1`.** A scientist who asks for a scaffold to be held rigid and receives
`rc=0` will reasonably believe it was held rigid. Meeko reports nothing: the exit code,
`stdout`, and the effective `TORSDOF` are **identical** to not passing the flag at all, so
there is no downstream signal to detect. This directly satisfies `ADR-032` §1.2's requirement
that "a pattern that matches nothing is reported as a structured outcome, never silently
ignored" — and proves Ankora cannot delegate that reporting to Meeko. `M1` must run an RDKit
`GetSubstructMatches` **pre-check** and emit structured `LIG_RIGIDIFY_SMARTS_NO_MATCH` on `0`
matches.

The `--rigid_macrocycles` row independently confirms the `ADR-032` §1.1
`"rigid_input_conformation"` unlock: the `CG0`/`G0` pseudoatoms are **never created**, so
macrocycles reach the AutoDock4 family with **no atom-type coercion** — exactly as the ADR
specifies, and `E2_autodock4_rigid_macrocycle` then docked successfully on both hosts.

### `F7` — `Meeko -f` split path resolution, and `GLY`/`ALA`/`PRO` **all silently exit `0`**

**Observed.**

- **Path resolution.** `-p explicit_target.pdbqt` **strips the `.pdbqt` suffix** and always
  writes `<stem>_rigid.pdbqt` + `<stem>_flex.pdbqt` (`51` + `10` atoms). The file literally
  named `explicit_target.pdbqt` is **never created**.
- **Split anatomy.** `CA` is the `ROOT` atom inside `BEGIN_RES`, with `CB` and beyond in
  `BRANCH` records. Atom conservation is exact: `46 + 15 = 61`.
- **Disallowed residues.** Every `ADR-032` §2.1 hard rejection **silently exited `0`** with a
  broken artifact — `GLY` (`A:1`) wrote `6` N-terminal **backbone** atoms
  (`C, CA, N, H1, H2, H3`) into the flex file; `ALA` (`A:2`) wrote **no flex file at all**,
  only a `61`-atom rigid file; `PRO` (`A:6`) wrote `4` C-terminal **backbone** atoms
  (`CA, C, O, OXT`) into the flex file.
- **Missing locator.** `-f A:999` **failed closed** (`rc=1`,
  `ValueError: residue_id='A:999' not in valid monomers`).

**Why this shapes `M1`.** Two independent consequences. First, any implementation that
constructs the output path from `-p` verbatim will look for a file that does not exist; `M1`
must resolve the `<stem>_rigid.pdbqt` + `<stem>_flex.pdbqt` pair. Second, and far more
seriously, `GLY`/`ALA`/`PRO` do **not** fail — they produce receptors whose **backbone atoms
are modelled as freely rotating**, which is not a side-chain rotation and is not a physically
meaningful docking model. Only the *missing* residue fails closed. This empirically confirms
that the `ADR-032` §2.1 `422` rejections must be enforced **by Ankora, before
`mk_prepare_receptor` is ever invoked** — the upstream tool provides no guard whatsoever.

## 5. `M1` Gate 0 Go/No-Go outcome

**GATE 0 PASSED** on **both Windows 11 x64 and Linux `x86_64` (WSL2 Ubuntu 24.04)**.

Every upstream CLI surface named in `ADR-032` exists, is accepted by the pinned executables,
and is usable for `v0.2` `M1` — **subject to the locked addendum rules** recorded in
[`ADR-032` Empirical Gate 0 Addendum](../architecture/ADR/ADR-032-explicit-flexibility-and-pose-complex-identity.md#empirical-gate-0-addendum-2026-11-18).

| Engine | Flexible-side-chain path | Gate 0 verdict | Binding condition |
| --- | --- | --- | --- |
| `AutoDock Vina 1.2.7` | `--flex`, `--score_only`, `--local_only` | **PASS** (both hosts) | `F2` NUL-line stripping on derived splits; `F3` `stdout` energy parsing and flat-PDBQT support; `F4` `UNBOUND` shift recorded |
| `AutoDock4 4.2.6` CPU | `AutoGrid4` maps + DPF `flexres` | **PASS** (both hosts) | `F1` `union` `ligand_types`, validated against the `14`-type ceiling before map generation |
| `AutoDock-GPU 1.6` | `--flexres`, single and `--filelist` | **PASS** (Linux CUDA + Windows OpenCL) | Serial-number restart requires `(chain, resseq, icode, resname, atom_name)` atom matching |
| `GNINA 1.3.3` | `--flex` / `--out_flex` | **PASS** (Linux only, `ADR-027`) | `F5` `--out_flex .pdb` only, 0-based ordinal pairing, Meeko-template re-injection |

No `ADR-032` path is blocked. `0` flags behaved contrary to the ADR in a way that removes a
capability; `7` behaved in ways that **add mandatory fail-closed engineering**, now locked in
the ADR addendum.

**Residual risk accepted into `M1`.** Four of the seven findings are *silent* failure modes
(`F1` on Windows, `F3`, `F6`, `F7`) — the tool exits `0` and produces an artifact that looks
valid. For each, the defense is a **pre-invocation check or a `stdout`-authoritative parse
inside Ankora**, because by construction there is no post-hoc signal in the exit code or the
output file to detect them.

## 6. Boundaries of this record

- Fixtures are **synthetic and labelled synthetic**. The `GARYMP` peptide is a CLI and format
  test article, not a protein target.
- Energies, `CNNscore`, `CNNaffinity`, `CNNvariance`, and `max_disp` values are recorded
  **solely** as proof that an engine ran to completion and emitted a parseable artifact. They
  are **not** scientific results and support **no** claim about binding.
- Cross-host energies are **not comparable** in this record: each host built its RDKit
  conformer independently (§1.3), so the inputs differ. Only CLI behavior and file formats are
  compared across hosts.
- Linux coverage is **WSL2**. Native bare-metal Linux workstation acceptance remains governed
  by [`LINUX_NATIVE_WORKSTATION_PROTOCOL.md`](LINUX_NATIVE_WORKSTATION_PROTOCOL.md) and stays
  open.
- GNINA remains **Linux-only** per `ADR-027`; the Windows GNINA column is `skipped_platform`,
  not a failure.
- This record is **pre-implementation evidence of upstream capability**. It is not an
  acceptance record for any Ankora capability. Per `AGENTS.md`, each `M1` capability becomes
  complete only with its own implementation, tests, acceptance criteria, and recorded
  validation evidence.
