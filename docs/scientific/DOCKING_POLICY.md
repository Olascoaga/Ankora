# Docking policy

AutoDock Vina `1.2.7` is the first implemented docking engine across Windows and
Linux. AutoDock4 is the accepted second scoring family under `ADR-015`:
AutoGrid4 `4.2.6` produces an immutable affinity-map set, AutoDock4 `4.2.6` CPU
is the reproducible reference execution path, and AutoDock-GPU `1.6` (`OpenCL`
on Windows; `CUDA 12` on Linux) is an optional accelerator of the AutoDock4
scoring family with its own explicit search protocol and structured
non-bitwise-reproducibility notice (`DOCKING_GPU_REPRODUCIBILITY_UNVERIFIED`).
On Linux `x86_64`, `GNINA 1.3.3` is implemented as a third, distinct deep-learning
scoring family for both single-ligand jobs and sequential virtual-screening
campaigns under `ADR-027` and `ADR-028`. GNINA remains deferred on native Windows.

The scientist chooses the engine, execution backend, input artifacts, search
space, random seed, search controls, and resource budget explicitly. Every run
retains the exact command or parameter files, executable version and SHA-256,
input/output hashes, raw stdout/stderr and pose files, structured results,
row-level failures, and provenance.

## Search space and Vina sampling protocols

A full-protein search space is an exploratory option, not a default scientific
claim about the binding site. Ankora may show it as the initial non-persistent
preview because it is universally computable, but creating it requires an
explicit acknowledgement. For Vina, a box volume above `27,000 Å^3` records a
structured warning (`DOCKING_SEARCH_SPACE_LARGE`) alongside the engine's raw
output. Ankora displays the exact volume and selected exhaustiveness, recommends
a focused box or a recorded sampling-sensitivity series, and never modifies
exhaustiveness automatically.

New Vina requests also record whether their exact sampling values were selected
for `screening`, `pose_refinement`, or as a scientist-edited `custom` protocol.
`screening` starts at exhaustiveness `8` with `9` modes and a `3 kcal/mol`
energy range; `pose_refinement` starts at exhaustiveness `32` with `20` modes
and a `5 kcal/mol` range. Both use a `1 Å` minimum inter-mode RMSD. These are
purpose-labelled starting points, not convergence guarantees; that judgment
requires recorded system-specific sensitivity evidence.

## AutoGrid4 and AutoDock4 preflight boundaries

AutoDock4 CPU preflight is per ligand. Stock AutoGrid4 `4.2.6` is limited to `14`
ligand affinity-map atom types and does not parameterize Meeko macrocycle glue
types such as `CG0`/`G0`. Ankora retains any affected molecule as an explicit
engine-incompatible row; it never coerces pseudoatoms to carbon or drops the
molecule from the campaign denominator. Stock AutoGrid4 also enforces a separate
ceiling of `20` receptor atom types, which Ankora checks independently before
launching map generation. AutoDock-GPU is preflighted against its own verified
executable/device contract, and CPU incompatibility is never silently
reclassified as GPU compatibility.

## Linux GNINA 1.3.3 scoring modes, ensembles, and CUDA boundaries

GNINA consumes Ankora's hash-verified prepared receptor and Meeko ligand
`.pdbqt` artifacts with `--addH 0 --stripH 0` so chemical states chosen in `M2`
and `M3` are never rewritten silently during docking. Requested `CUDA` runs
never fall back silently to `CPU`; single-GPU CUDA execution requires
`nvidia-smi` observation of the job's process and matching physical GPU UUID
before poses can be published.

GNINA quantities remain strictly separated from empirical `kcal/mol` scales:

- **`CNNscore` (`[0, 1]`, dimensionless, descending):** 3D convolutional pose
  score that governs within-ligand pose ordering (`mode = 1..N`). It is an
  uncalibrated neural score, not an experimentally calibrated probability.
- **`CNNaffinity` (`pK`, descending):** neural predicted binding affinity on a
  log-dissociation scale; still a model prediction, not an experimental measurement.
- **`CNN_VS` (`CNNscore * CNNaffinity`, descending):** virtual-screening hit
  prioritization product introduced in `ADR-028` (`gnina_cnn_vs`, with explicit
  `cnn_vs_source` provenance). Screening campaigns record an explicit
  `hit_ranking_metric` (`"cnn_score"` default or `"cnn_vs"`). Because negative
  `CNNaffinity` (`K_d > 1 M`) makes `CNN_VS` negative and inverts `CNNscore`
  ordering among negative-pK decoys, Ankora emits `GNINA_CNN_VS_NONPOSITIVE_AFFINITY`
  whenever `hit_ranking_metric == "cnn_vs"` and any completed molecule has
  `CNNaffinity <= 0`.
- **`CNNaffinity_variance`:** persisted only when emitted by the GNINA binary
  (`None` on standard `1.3.3` prepared-PDBQT runs); Ankora never fabricates
  ensemble dispersion numbers.
- **`minimizedAffinity` (`kcal/mol`):** empirical energy evaluated at the output
  pose coordinates. Under `cnn_scoring = "rescore"` (`CPU` or `CUDA`), poses are
  minimized empirically and rescored by the CNN. Under `cnn_scoring = "refinement"`
  (`CUDA` only, requiring `timeout_minutes >= 10` and `ResourceArbiter` VRAM
  admission), coordinates are optimized jointly against 3D CNN and empirical
  gradients; closer CNN-preferred contacts can cross Vina's steric repulsion
  wall and produce positive `minimizedAffinity` values, so `minimizedAffinity`
  under `refinement` is **not** an independent empirical energy check.

Built-in CNN model selection is pinned fail-closed to the verified GNINA `1.3.3`
binary SHA-256 (`3340c1f49cd3c7c84d8699182a1c6af13c7fa2a22448d1204640446106f72172`)
and records every evaluated member network in `cnn_model_identity`:

- `dense_1_3` (default, `1` model: `("dense_1_3",)`);
- `default_1_3_ensemble` (`3` knowledge-distilled 1.3 models:
  `("dense_1_3", "dense_1_3_PT_KD_3", "crossdock_default2018_KD_4")`, invoked by
  omitting `--cnn` because `--cnn default` is rejected by GNINA `1.3.3`);
- `default1.0` (`5` GNINA 1.0 models:
  `("dense", "general_default2018_3", "dense_3", "crossdock_default2018", "redock_default2018_2")`).

## Cross-engine non-pooling and rank-agreement rules

Vina poses, AutoDock4 clusters, and GNINA CNN-ordered poses remain independent
result models. Ankora may display results from different engines within the same
project, but it **never** averages, normalizes, or merges scores across scoring
functions into a combined consensus number, and never labels any computational
metric as experimental affinity.

Side-by-side statistical rank comparison (`EngineComparisonService`) is
implemented specifically between compatible **AutoDock Vina** (`vina_batch_id`)
and **AutoDock4 CPU** (`autodock4_batch_id`) library campaigns that share the
exact prepared receptor, finalized binding site, and applied selection manifest.
It reports Spearman's rank correlation (`rho`) over commonly docked molecules
and Top-`N` overlap, without computing a merged score. Incompatible inputs fail
closed, and GNINA campaigns remain in their separate CNN catalog family without
cross-engine Spearman pooling.
