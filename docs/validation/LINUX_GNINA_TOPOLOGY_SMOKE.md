# GNINA 1.3.3 PDBQT topology check — predeclared

This exploratory WSL2 engineering check follows the synthetic-ethanol GNINA
smoke and is not a redocking validation, benchmark or release acceptance. Use
only new create-only directories and preserve the previous project unchanged.

## Fixed evidence

- GNINA 1.3.3 official CUDA 12.8 executable SHA-256
  `3340c1f49cd3c7c84d8699182a1c6af13c7fa2a22448d1204640446106f72172`.
- Prior isolated 1HSG receptor PDBQT SHA-256
  `da4cf4adb8d1af6ed05984bbe39b3b9f5a7bfb13530918741694091048704588`.
- Prior independent MK1 Meeko-prepared PDBQT SHA-256
  `a578aa8d119e30c6c535e47911dc15f0af3d818f303797a051653c8c4709b9b8`.
- Prior inspected MK1 chemical-state SDF SHA-256
  `0dfcb7d3d6024bbe5572c990ff57fdd38e46cfe20b928acb8601bae3ad550982`.

## Procedure

Copy inputs and verify hashes. With no other GPU compute process active, run
two separate, explicitly recorded GNINA calculations from the same PDBQT
inputs and box, seed and CPU budget as the initial smoke; use exhaustiveness 1,
two poses, `--max_mc_steps 100`, `--cnn_scoring rescore --cnn dense_1_3`,
`--addH 0 --stripH 0`, and CUDA device 0. The first writes SDF, the second
PDBQT. Each has a 180-second timeout, retained raw output and explicit GPU
process observation. These constrained settings only reveal file formats and
topology, not meaningful docking quality. If either command fails, stop and
record it without silently changing the settings.

Record score fields, atom and hydrogen counts, SDF graph/stereochemistry
relative to the input state, and presence of Meeko mapping remarks in PDBQT.
Test whether the existing interaction reconstruction and topology comparison
could accept the PDBQT output; do not force an answer or repair mismatches.
Different executions cannot be assumed to yield the same poses. Verify source
and copied input hashes unchanged. No native-workstation, reproducibility or
scientific accuracy claim follows.
