# ADR-015: AutoDock4 as the second docking engine, CPU first and GPU later

- Status: Accepted
- Date: 2026-08-23 (accepted 2026-08-24 after scientist + Codex review)

## Context

ADR-008 named GNINA as an initial docking engine alongside Vina. The
2026-08-23 decision that shipped AutoDock Vina 1.2.7 as the first native M5
engine (`memory/DECISIONS.md`) deferred GNINA explicitly: *"GNINA is deferred
because its official distribution is Linux-oriented and adopting WSL or
another non-native execution authority would conflict with the current
Windows-native product boundary; that requires a separate architecture
decision rather than a silent workaround."* `memory/NEXT_SESSION.md` restates
the same block. This ADR is that follow-up investigation. The scientist
accepted the amended CPU-first direction on 2026-08-24.

### GNINA remains not viable natively on Windows

Checked directly, not assumed:

- Every GNINA GitHub release from v1.0.3 through v1.3.3 (queried via the
  GitHub releases API) ships exactly one Linux ELF binary per release
  (300 MB-2 GB, statically bundling CUDA/libtorch). No `.exe`, no Windows
  asset, in any release.
- No Windows path via conda either. Bioconda does not build for Windows at
  all, and the official `gnina` Anaconda channel's own `molgrid` package — a
  native C++/CUDA dependency required by GNINA's CNN scoring pipeline — is
  published only for `linux-64`, `osx-64`, and `osx-arm64`.
- No evidence found of a working third-party native Windows build (searched
  forums, issues, forks); the closed build issues that exist are all
  Linux/WSL2 dependency problems (OpenBabel/CMake, GLIBC version mismatches,
  CUDA architecture mismatches), suggesting the Linux build itself is already
  fragile.
- `gninatorch` (PyPI) is a genuine, relevant partial alternative: a pure
  PyTorch reimplementation of GNINA's CNN *scoring* function, with the
  pretrained weights converted, and no dependency on the compiled GNINA
  binary. Because it is pure PyTorch it is realistically Windows-installable.
  But it only rescores poses — it does not perform the docking/pose search
  itself, so it cannot replace GNINA as a docking engine on its own.

This ADR does not propose reversing GNINA's deferral; that conclusion stands.

### The AutoDock4 lineage has a real native-Windows path, on both CPU and GPU

Both executables consume the **same family** of grid maps produced by
`autogrid4` and use AutoDock4's semi-empirical free-energy force field. They
are not automatically equivalent searches: AutoDock-GPU defaults to
heuristics, automatic stopping, and ADADELTA local search, whereas the
historical CPU protocol uses different search defaults. Ankora therefore
records the scoring family, execution backend, and complete search protocol
separately and never implies bitwise or protocol equivalence:

| | `autodock4.exe` (CPU) | `AutoDock-GPU.exe` (GPU) |
| --- | --- | --- |
| Windows binary | Yes — in the AutoDock 4.2.6 suite installer, bundled with `autogrid4.exe` and `cygwin1.dll` | Yes — official release asset since v1.6 (confirmed via the releases API; absent in ≤ v1.5.3) |
| Hardware requirement | Any CPU | OpenCL-capable GPU (NVIDIA/AMD/Intel); no CUDA Toolkit needed |
| Job input | `.dpf` docking parameter file | Command-line flags (`--ffile`, `--lfile`, `--nrun`, `--seed`, `--nev`, …); `--import_dpf` exists but upstream documents it as *"only partial support"* |
| Output | `.dlg` docking log | `.dlg` **by default** (`--dlgoutput`, default yes), plus optional XML (`--xmloutput`, default yes) |
| Maintenance | AutoDock 4.2.6 is the stable legacy release | Actively developed; wiki FAQ commits to Windows binaries per major release plus a maintained Visual Studio project |

Both are GPL, freely downloadable from Scripps, with no registration gate —
the same posture as Vina and P2Rank.

### Why CPU first

The scientist proposed implementing the CPU engine before the GPU one. On
investigation this is the better sequence, for four reasons:

1. **It enables scientifically useful side-by-side comparison.** Vina's empirical
   scoring function and AutoDock4's semi-empirical one are genuinely
   different methods, so agreement between them can be inspected.
   AutoDock4-CPU versus AutoDock-GPU would be the *same* scoring function on
   different search backends — that is not an independent scoring opinion and
   does not constitute consensus. Ankora does not create a combined score.
2. **It works for every user.** A GPU-only second engine leaves anyone
   without a compatible OpenCL device with a single engine and no consensus
   capability at all.
3. **Almost all of the work is shared.** The grid-generation stage
   (`autogrid4` + `.gpf` generation) is identical for both, and — the
   decisive detail — AutoDock-GPU emits the same `.dlg` format by default, so
   the results parser written for the CPU engine is directly reusable. Adding
   GPU afterwards is close to swapping the executable and its job-parameter
   surface, not building a second pipeline.
4. **It removes a hardware dependency from the critical path.** GPU support
   can be validated whenever suitable hardware and driver conditions are
   available, without blocking a working second engine.

The real cost of CPU-first is speed: AutoDock4's LGA search is substantially
slower than Vina's. For single-ligand consensus docking — the actual use case
motivating this — that is acceptable. For large virtual-screening libraries it
is not, which is precisely the gap the GPU phase would later close.

## Decision

Give the AutoDock4 lineage GNINA's deferred "second engine" slot, implemented
in two phases. Vina remains the first and default engine.

### Phase 1 — `autogrid4.exe` + `autodock4.exe` (CPU)

**Stage 1: grid generation (per receptor + box).** Inputs already exist in
Ankora: the docking-ready receptor PDBQT (M2) and the finalized `BindingBox`.
Ankora generates the `.gpf` itself — a fixed-keyword plain-text format, with
no AutoDockTools/Python 2 dependency:

| GPF keyword | Source |
| --- | --- |
| `receptor` | receptor PDBQT path |
| `gridcenter` | `BindingBox.center_x/y/z`, direct mapping |
| `npts` | `ceil(BindingBox.size_x/y/z ÷ spacing)` (default 0.375 Å), then increment any odd result to the next even integer. This guarantees that discretization never shrinks the scientist-confirmed box. Record requested and realized sizes. |
| `receptor_types` / `ligand_types` | parsed from atom types already present in the receptor/ligand PDBQT — the same AutoDock atom-type vocabulary the Vina pipeline already uses |
| `map` / `elecmap` / `dsolvmap` | deterministic output filenames |

Run as `autogrid4.exe -p receptor.gpf -l receptor.glg`. Produces
`receptor.maps.fld`, `receptor.maps.xyz`, and one `.map` per atom type plus
electrostatic and desolvation maps.

**Stage 2: docking (per ligand).** Unlike Vina and AutoDock-GPU, the CPU
engine takes no meaningful job flags — the entire job is the `.dpf` file, so
Ankora must generate it. Note the asymmetry: **the GPF is per receptor+box;
the DPF is per ligand.** A screening run generates one grid set and many DPFs.
Authoritative keyword ordering and defaults (from AutoDockTools'
`DockingParameters.py`, `genetic_algorithm_local_search_list4_1`):

| DPF keyword | Role | AutoDockTools default |
| --- | --- | --- |
| `autodock_parameter_version` | force-field version | `4.1` |
| `ligand_types` | ligand atom types | from ligand PDBQT |
| `fld` | grid field file from stage 1 | — |
| `map` / `elecmap` / `desolvmap` | affinity maps from stage 1 | — |
| `move` | ligand PDBQT | — |
| `about` | ligand centre of rotation | ligand centroid |
| `tran0` / `quaternion0` / `dihe0` | initial pose state | `random` |
| `torsdof4` | torsional degrees of freedom | from ligand |
| `seed` | RNG seed | `pid`, `time` — **must be set explicitly** for reproducibility |
| `ga_pop_size` | GA population | `150` |
| `ga_num_evals` | energy evaluations per run | `2500000` |
| `ga_num_generations` | GA generation cap | `27000` |
| `ga_run` | independent LGA runs | `10` |
| `rmstol` | clustering RMSD tolerance | `2.0` |
| `unbound_model` | unbound-state model | `bound` |
| `analysis` | emit clustering analysis | `1` |

Run as `autodock4.exe -p ligand.dpf -l ligand.dlg`.

For the existing full-protein 7AQF box, `58.521 × 85.371 × 68.626 Å` at
`0.375 Å` spacing becomes `npts = 158 × 228 × 184` and a realized covered
size of `59.250 × 85.500 × 69.000 Å`. The former draft's
`156 × 228 × 183` would both shrink X and violate AutoGrid's even-`npts`
requirement.

**Results model — genuinely different from Vina's.** Vina returns a ranked
list of poses. AutoDock4 performs `ga_run` independent searches and then
*clusters* them by `rmstol`, reporting a `CLUSTERING HISTOGRAM` plus the
lowest-energy conformation per cluster. Cluster population is scientifically
meaningful (a large tight cluster indicates a reproducible solution), so the
results surface must represent clusters and their populations rather than
flattening everything into a Vina-shaped ranked table.

### Phase 2 — `AutoDock-GPU.exe` (optional acceleration)

Reuses stage 1 unchanged and the same cluster-native result contract. Replaces
the DPF with command-line flags (`--ffile`, `--lfile`, `--nrun`, `--seed`,
`--nev`, `--resnam`). Prefer its structured XML where it contains the required
evidence and preserve DLG/raw output as well. It is presented as an
execution-backend choice for the AutoDock4 scoring family — not as a third
scoring method. GPU-specific search behavior (local-search method, heuristics,
automatic stopping, device, driver) remains explicit. Only one GPU campaign
at a time regardless of the CPU worker budget, since the GPU is a shared
resource (ADR-013).

### Proposed engineering guardrails (mirroring existing conventions)

- Probe `--version` (or equivalent) and require an exact expected version
  before accepting a job, same discipline as the Vina adapter.
- Record the generated `.gpf` and `.dpf` contents alongside the command, exit
  code, and raw stdout/stderr as provenance. They are generated rather than
  scientist-authored, but they are the complete scientific parameter set and
  must be as auditable as a Vina command line.
- Set `seed` explicitly rather than accepting the `pid`/`time` default — an
  unrecorded seed would make a run unreproducible, which the project's
  provenance rules do not permit.
- The `npts` cover-then-next-even conversion must be deterministic and test-covered
  comparably to the Vina adapter: it is the one place a bug could silently
  shrink or misalign a box the scientist already confirmed.
- AutoGrid runs in an ASCII-only job directory with short relative filenames;
  the historical GPF implementation does not reliably tolerate whitespace or
  non-ASCII filenames. User/project paths remain recorded in provenance.
- One immutable map set is keyed by receptor PDBQT hash, requested and
  realized grid geometry, spacing, the union of receptor/ligand atom types,
  AutoGrid executable version/hash, parameter-file hash, smoothing,
  dielectric, and every other force-field-affecting setting. A new atom type
  creates a new superset map artifact; an existing map set is never mutated.
- Every independent run and pose is preserved. The primary UI groups results
  by cluster and exposes cluster population and representative energy, then
  expands to the constituent runs. Meeko's DLG reader is preferred for pose
  and energy extraction; a minimal validated parser may supplement exact
  `RANKING` records that Meeko does not expose through a public API.
- Keep AutoDock4's score distinct from Vina's and never fabricate a merged
  consensus number (ADR-008). Presenting both engines' results side by side
  is the goal; inventing a combined score is not.
- Label AutoDock4 energies as computational estimates in kcal/mol, never
  experimental affinity — same boundary already applied to Vina scores and to
  MMFF minimization energies.

## Accepted delivery sequence

0. **Windows compatibility spike:** acquire official binaries, record source,
   SHA-256, PE architecture, version and dependencies, and prove small-box and
   full-protein-grid behavior before product readiness is claimed.
1. **Immutable AutoGrid maps:** typed GPF contract, atom-type preflight,
   create-only map-set artifacts, GLG/raw evidence, and cache identity.
2. **AutoDock4 CPU single ligand:** typed DPF contract, one real job, complete
   DLG preservation, cluster-native results, and 3D review.
3. **AutoDock4 CPU library:** one map set reused by a bounded pool of
   single-core CPU processes, exact molecule progress, cancellation, and
   isolated failures.
4. **Scientific validation and comparison:** redocking evidence and Vina/AD4
   side-by-side presentation without a synthetic consensus score.
5. **AutoDock-GPU:** explicit device discovery, one GPU campaign at a time,
   shared maps/result contract, and backend-specific search provenance.

## Implementation status — 2026-08-26

The native execution program is complete and scientifically accepted as
implemented. Phase 0 recorded official binary identities and real pocket plus
full-protein AutoGrid evidence. Phase 1 persists immutable reusable map sets.
Phases 2 and 3 execute AutoDock4 CPU for one ligand or an applied library while
preserving deterministic DPF files, complete DLG evidence, clusters, runs,
poses, failures, cancellation, and progress. The comparison portion of item 4
is implemented for compatible Vina/AutoDock4 campaigns; experimental redocking
validation remains the separate M7 milestone. Phase 5 executes AutoDock-GPU
1.6 for one ligand or one-process `--filelist` library campaigns and records
the real device, backend-specific protocol, and non-bitwise-reproducibility.

The real CPU/GPU benchmark over 257 common molecules measured approximately
21x wall-clock acceleration and Spearman rho 0.9463. This supports GPU use for
screening but does not make CPU and GPU searches interchangeable or establish
either result as experimentally correct.

## Resolved review questions and remaining compatibility evidence

- GNINA remains visible as deferred/pending upstream; its history is not
  erased. `ToolsResponse` gains separate `autogrid4`, `autodock4`, and
  `autodock_gpu` slots. Product scope names Vina + AutoDock4 as the native
  engines and AutoDock-GPU as optional acceleration.
- The official AutoDock 4.2.6 Windows installer downloaded on 2026-08-24 is
  an unsigned PE32/x86 NSIS executable (`Machine 0x014c`, SHA-256
  `306dc72a06e80a2da6f3c410ac6aba7ebdaeef6b702eca42de44c7c6c9d48755`).
  Its payload was extracted without a system install and inspected directly.
  `autogrid4.exe` is x86, SHA-256
  `797efce687d1ae82df59726461e0e1966b3d8edb0f8b187f982fa1ab0c12da9e`;
  `autodock4.exe` is x86, SHA-256
  `36c0b16c04d7df8e6225737bae65bb04058d1f4c90accfaf2d230dbc913954bf`.
  Their real version probes both report 4.2.6 and GPLv2+; AutoGrid reports
  `MAX_ATOM_TYPES=14`, `MAX_MAPS=16`, and `MAX_GRID_PTS=1025`.
- The x86 address-space risk was measured against real 7AQF artifacts. The
  co-crystallized-ligand box (`58 × 54 × 52`) completed in 9.80 s. The full
  protein box (`158 × 228 × 184`) completed in 5 min 22.88 s and wrote a
  453.56 MiB evidence set. Both GLGs end in `Successful Completion`. Therefore
  this exact 4.2.6 CPU toolchain is accepted for development and Phase 1 map
  persistence; binary redistribution still requires a separate license/package
  review.
- The real 283-entry selection contains 282 prepared PDBQTs. One prepared
  macrocycle (Compound 195) contains Meeko `CG0`/`G0` glue types, which stock
  AutoGrid/AutoDock4 4.2.6 cannot parameterize, and Compound 143 has no PDBQT.
  Both remain explicit CPU-incompatible rows. The 281 compatible molecules
  require ten ligand affinity-map types (`A C Cl F HD N NA OA S SA`), below the
  14-type limit. Ankora never coerces the glue pseudoatoms or silently drops
  either row.
- Meeko 0.7.1 can read DLG pose/energy blocks, but the required cluster metadata
  is private implementation state. Ankora therefore uses the smallest validated
  supplementary parser over real preserved `RANKING`, `CLUSTERING HISTOGRAM`,
  and `DOCKED:` records, with fixtures captured from real 4.2.6 output.
- Cluster-first UI and side-by-side Vina/AD4 comparison are accepted. No
  combined ranking or consensus number is created.
- GPU device selection is explicit in Phase 5. The current development machine
  has an NVIDIA GeForce RTX 5050 Laptop GPU with approximately 8 GB VRAM, but
  that does not make GPU availability a universal assumption.
- AutoDock4 is GPL; AutoDock-GPU carries GPL-2.0 and LGPL-2.1 components.
  Actual distribution license files must be retained and reviewed before any
  binary is bundled with Ankora.
- Reproducible commands, hashes, GPF/GLG evidence, and map inventory are recorded
  in `docs/validation/AUTODOCK4_PHASE0_WINDOWS.md` and
  `docs/validation/AUTODOCK4_PHASE1_MAPS.md`. Production AutoGrid, AutoDock4 CPU,
  and AutoDock-GPU execution are implemented and accepted. This acceptance
  covers the recorded execution/result contracts; protocol accuracy remains a
  separate redocking-validation milestone.

## Primary references

- AutoDock4 download: https://autodock.scripps.edu/download-autodock4/
- AutoDock 4.2.6 user guide: https://autodock.scripps.edu/wp-content/uploads/sites/56/2022/04/AutoDock4.2.6_UserGuide.pdf
- AutoDock4 source: https://github.com/ccsb-scripps/AutoDock4
- AutoGrid source: https://github.com/ccsb-scripps/AutoGrid
- AutoDock-GPU source and releases: https://github.com/ccsb-scripps/AutoDock-GPU and https://github.com/ccsb-scripps/AutoDock-GPU/releases
- Meeko docking/export documentation: https://meeko.readthedocs.io/en/develop/tutorial1.html and https://meeko.readthedocs.io/en/develop/export_usage.html
