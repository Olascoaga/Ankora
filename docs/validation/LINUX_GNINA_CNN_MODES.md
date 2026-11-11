# GNINA 1.3.3 CNN scoring modes, ensemble identities, and memory probe — predeclared

## Protocol

This isolated WSL engineering probe characterizes the official standalone x86-64
Linux GNINA `1.3.3` binary (`master:6fe1ce2`, SHA-256
`3340c1f49cd3c7c84d8699182a1c6af13c7fa2a22448d1204640446106f72172`) before
widening Ankora's `ADR-027` GNINA contract in `ADR-028`. It is an exploratory
WSL2 engineering characterization on `NVIDIA GeForce RTX 5050 Laptop GPU` and
does not establish scientific enrichment, prospective virtual-screening
performance, or bare-metal Linux workstation acceptance.

### Preconditions

1. Verify the declared SHA-256 digests of the official GNINA `1.3.3` binary,
   the prepared `1HSG` receptor PDBQT
   (`da4cf4adb8d1af6ed05984bbe39b3b9f5a7bfb13530918741694091048704588`), the
   prepared `MK1` indinavir ligand PDBQT
   (`a578aa8d119e30c6c535e47911dc15f0af3d818f303797a051653c8c4709b9b8`), and its
   inspected chemical state SDF
   (`0dfcb7d3d6024bbe5572c990ff57fdd38e46cfe20b928acb8601bae3ad550982`).
2. Copy inputs into a fresh, create-only directory under
   `logs/linux-gnina-investigation/v1.3.3/` and never mutate the source files.
3. Require zero active GPU compute processes via `nvidia-smi` before launching.

### Sub-checks

1. **CLI selector check (`--cnn default`):** Invoke `gnina --score_only --cnn default --addH 0 --stripH 0 --no_gpu` and record exit code and `stderr`.
2. **Built-in ensemble membership proof (`--score_only`):** Evaluate static
   `ligand.pdbqt` against `receptor.pdbqt` with `--addH 0 --stripH 0 --device 0`
   under omitted `--cnn` (GNINA 1.3 default ensemble) and `--cnn default1.0`
   (GNINA 1.0 default ensemble), plus each candidate member model individually,
   and require arithmetic-mean agreement on `CNNscore` and `CNNaffinity` and
   population-variance agreement on `CNNvariance` within `1e-4`.
3. **Scoring-mode, output-tag, topology, wall-clock, and memory matrix:** Run
   docking on the `1HSG` crystal box (`seed = 20261029`, `--addH 0 --stripH 0`)
   across `compute ∈ {cuda, cpu}`, `cnn_scoring ∈ {rescore, refinement}`, and
   `cnn_model ∈ {dense_1_3, default_ensemble, default1_0}`, inspecting `.pdbqt`
   `REMARK` keys, `.sdf` property tags, `Meeko` -> `RDKit` topological/isomeric
   SMILES identity against `inspected_state.sdf`, wall-clock duration, peak host
   RSS, and device-level `nvidia-smi` GPU memory delta.

## Observed run: `cnn-modes-01` (initial selector & variance discovery)

The initial exploratory probe expected either omitted `--cnn`, `--cnn default`,
or `--cnn default1.0` to emit `REMARK CNNaffinity_variance` or `> <CNNaffinity_variance>`
when docking `ligand.pdbqt`. It exited fail-closed after proving two critical
facts:

1. `--cnn default` is rejected by GNINA `1.3.3` with `exit_code = 1` and
   `Usage error: Invalid model name: default`.
2. When `--ligand` is a `.pdbqt` torsion tree (`--addH 0 --stripH 0`), GNINA
   `1.3.3` emits only `minimizedAffinity`, `CNNscore`, and `CNNaffinity` in both
   `.pdbqt` `REMARK` lines and OpenBabel-converted `.sdf` output; neither
   `CNN_VS` nor `CNNaffinity_variance` is written to pose output files.
3. Under WSL2 WDDM (`driver 610.88`), per-process
   `nvidia-smi --query-compute-apps=used_gpu_memory` reports `[N/A]`, whereas
   device-level `nvidia-smi --query-gpu=memory.total,memory.used,memory.free`
   reports MiB accurately (`8151 MiB` total).

Retained create-only `cnn-modes-01/evidence.json` SHA-256:
`2379b3299f4d9c219478c1a4ab23b85fda4d7761100fe935cc2e16130976fae8`.

## Observed run: `cnn-modes-02` (candidate 5-member hypothesis falsified)

Testing an initial 5-member hypothesis read from adjacent binary `.rodata`
strings (`dense_1_3`, `dense_1_3_PT_KD_3`, `crossdock_default2018_KD_4`, `fast`,
`all_default_to_default_1_3_1` for GNINA 1.3; `default2017` in `default1.0`)
failed closed (`abs_diff_cnn_affinity = 0.3730` and `1.0086`) because `fast` is
a CLI alias for `all_default_to_default_1_3_1` rather than an ensemble member,
and `default2017` was replaced by `dense` in `CNNTorchScorer`. Direct symbol
inspection of `CNNTorchScorer<true>::CNNTorchScorer(cnn_options const&, tee_stream*)`
established the exact compiled member lists tested in `cnn-modes-03`.

Retained create-only `cnn-modes-02/evidence.json` SHA-256:
`d629d1f285d7830cbe7924acb6fed6be48480e3a15f9408a7966a11cb8855d90`.

## Observed run: `cnn-modes-03` (full CUDA + CPU rescore matrix & 600 s CPU refinement timeout)

`cnn-modes-03` verified all ensemble identities and completed all 10 CUDA matrix
runs plus both CPU `rescore` runs before hitting the predeclared `600 s` ceiling
on `cpu_refinement_dense_1_3_pdbqt`:

1. **Exact built-in ensemble identities proven (`--score_only` on `ligand.pdbqt`):**
   - **Omitted `--cnn` (`default_1_3_ensemble`, 3 models):**
     `("dense_1_3", "dense_1_3_PT_KD_3", "crossdock_default2018_KD_4")` —
     `CNNscore = 0.21269` (`|mean - ensemble| = 3.33e-6`),
     `CNNaffinity = 3.46361` (`|mean - ensemble| = 6.67e-6`),
     `CNNvariance = 1.36585` (`|pvar - stdout| = 9.88e-7`).
   - **`--cnn default1.0` (`default1.0`, 5 models):**
     `("dense", "general_default2018_3", "dense_3", "crossdock_default2018", "redock_default2018_2")` —
     `CNNscore = 0.55411` (`|mean - ensemble| = 0.0`),
     `CNNaffinity = 4.70562` (`|mean - ensemble| = 2.00e-6`),
     `CNNvariance = 0.54250` (`|pvar - stdout| = 1.23e-6`).
2. **CUDA & CPU matrix summary (`exhaustiveness = 4, num_modes = 5`, except CPU refinement `exhaustiveness = 2`):**

| Run key | Duration (s) | Peak host RSS (MiB) | Peak GPU delta (MiB) | Mode-1 `(CNNscore, CNNaffinity, minimizedAffinity)` | Meeko topology preserved |
|---|---:|---:|---:|---|---|
| `cuda_rescore_dense_1_3_pdbqt` | `26.10` | `993.38` | `+151` | `(0.9796, 8.5648, -12.0547)` | `True` |
| `cuda_rescore_default_ensemble_pdbqt` | `26.14` | `1011.40` | `+179` | `(0.9204, 8.8606, -12.0547)` | `True` |
| `cuda_rescore_default1_0_pdbqt` | `27.74` | `1018.41` | `+185` | `(0.9427, 8.5458, -12.0547)` | `True` |
| `cuda_refinement_dense_1_3_pdbqt` | `133.61` | `1183.27` | `+233` | `(0.9807, 8.1667, +4.1367)` | `True` |
| `cuda_refinement_default_ensemble_pdbqt` | `294.14` | `1218.55` | `+245` | `(0.7185, 9.0474, -10.5593)` (mode 3 `+28.1389`) | `True` |
| `cuda_refinement_default1_0_pdbqt` | `431.13` | `1228.00` | `+255` | `(0.5666, 8.0352, -9.3319)` (mode 3 `+0.4001`) | `True` |
| `cpu_rescore_dense_1_3_pdbqt` | `43.36` | `630.24` | `0` | `(0.9796, 8.5657, -12.0547)` | `True` |
| `cpu_rescore_default_ensemble_pdbqt` | `99.83` | `643.14` | `0` | `(0.9203, 8.8609, -12.0547)` | `True` |
| `cpu_refinement_dense_1_3_pdbqt` (`exhaustiveness=2`) | `> 600.0` (timed out) | — | `0` | killed cleanly via `SIGTERM` | — |

3. **Coupling of `minimizedAffinity` under `refinement`:** Under `refinement`,
   high-scoring CNN poses (`CNNscore = 0.9807` on `dense_1_3`, `0.6801` on mode
   3 of `default_1_3_ensemble`) produced positive empirical Vina energies
   (`+4.14` to `+28.14 kcal/mol`), proving empirically that `minimizedAffinity`
   on CNN-gradient-refined geometry reflects Vina's steric repulsion evaluated at
   CNN-preferred coordinates rather than an independent empirical energy minimum.

Retained create-only `cnn-modes-03/evidence.json` SHA-256:
`579b9750c76fdabf72493bea8543ab3a47f6725e157a6b804a2d31a47d5b01de`.

## Observed run: `cnn-modes-04` (CPU `default1.0` rescore & bounded CPU refinement ceiling)

`cnn-modes-04` completed the remaining CPU `default1.0` rescore cell and bounded
CPU `refinement` at `exhaustiveness = 1, num_modes = 1` with `status: "completed"`:

1. `cpu_rescore_default1_0_pdbqt` (`--cpu 4 --exhaustiveness 2 --num_modes 5 --no_gpu`):
   completed in `90.96 s` (`peak_host_rss_mib = 653.49`, `peak_device_delta_gpu_mib = 0`),
   mode-1 `(CNNscore = 0.9415, CNNaffinity = 8.5564, minimizedAffinity = -12.0211)`,
   preserving exact `Meeko` -> `RDKit` topological and stereochemical identity
   (`topology_matches_input_state = True`).
2. `cpu_refinement_dense_1_3_pdbqt` (`--cpu 4 --exhaustiveness 1 --num_modes 1 --no_gpu`):
   exceeded the `60 s` probe window (`duration_seconds = 60.18`, `timed_out = True`,
   `exit_code = -15`, `peak_host_rss_mib = 701.77`) even for a single Monte Carlo
   trajectory and single output pose, confirming together with `cnn-modes-03`
   (`> 600 s` at `exhaustiveness = 2`) that `compute = "cpu"` with
   `cnn_scoring = "refinement"` is operationally intractable and must be rejected
   fail-closed at request admission in `ADR-028`.

Retained create-only `cnn-modes-04/evidence.json` SHA-256:
`7fd3a0df820cb4c9c7498b3b5c72f5f60d2987401abe9bb48dfffda3d4b4c54c`.

