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

## Observed result

Both predeclared calculations exited zero and their PIDs were observed on the
CUDA device. The inspected MK1 state contained 45 heavy atoms; both SDF output
poses contained the same 45 heavy atoms and the same canonical isomeric SMILES
as that state. PDBQT output retained Meeko's SMILES mapping remarks; Meeko
reconstructed the ligand and its isomeric SMILES matched the input state.
These are observations for this particular molecule and settings, not a
general guarantee for arbitrary ligands.

The PDBQT scores were emitted as `REMARK minimizedAffinity`, `REMARK CNNscore`
and `REMARK CNNaffinity`. Pose 1 ranked above pose 2 by CNNscore even though
its empirical energy was higher; preserving the recorded GNINA order is
essential. Both the PDBQT fixture and the independently minimized input
conformer are retained in backend tests using the public reference case. Each
pose is validated against the exact conformer topology before it can be used
by a future GNINA service.

The SDF output hash was
`dc24a24c6d260f5cdc25115fd711ec9cde9193c5c5c10e936f01ad1dfdaff16f` and
the PDBQT output hash was
`831ea0384cbff50568b8de9c767d79e855bc84971a8fd3abf3e84de8af9b25e0`.
The retained machine evidence SHA-256 is
`0467acccf862079be9b3dc22d39b524ab8a0067f66874f1c94e3114bfa8578d0`.
Original inputs remained unchanged. Raw stdout, stderr and output files remain
in the ignored local investigation directory.

## Adapter check — predeclared

Run one further create-only WSL engineering check using the exact same
hash-pinned PDBQT receptor, PDBQT ligand and prepared conformer. Invoke
Ankora's GNINA adapter and its real probe, with CUDA device 0, `dense_1_3`,
`rescore`, explicit `--addH 0 --stripH 0`, seed 20261029, two CPU threads,
exhaustiveness 1, two maximum poses and the same declared search box. Use
GNINA's normal Monte Carlo step policy and a three-minute timeout; do not
substitute a CPU execution or change the parameters after seeing a result.
Observe the executable PID on the GPU, retain command/stdout/stderr and output
hashes, parse each PDBQT score, verify every pose against the exact conformer
using the same isomeric topology guard, and check the original input hashes.
This is not an API, GUI, campaign, redocking, or scientific acceptance test.

The declared `adapter-01` check completed with GNINA 1.3.3, an observed CUDA
process and two PDBQT poses. Ankora's adapter parsed the three score fields in
the reported order, and each pose passed the isomeric topology check against
the independently prepared conformer. The generated PDBQT SHA-256 was
`aa2800f741e15eb5a53c99a66108d72f3c4f20f17fadcae9fba0f5eb57714530`;
the retained machine evidence SHA-256 was
`588b17a73ec9f9d8b0efd60737945698d774249df8d246e26cf1c448256608ac`.
The inputs stayed byte-identical. The adapter supports explicit CPU/CUDA,
`rescore`, the built-in `dense_1_3` model and `--addH 0 --stripH 0`; it does
not itself establish actual GPU execution or publish a result. A future
service must independently verify the requested device, reserve resources,
persist raw evidence and integrate recovery before exposing GNINA in the UI.
