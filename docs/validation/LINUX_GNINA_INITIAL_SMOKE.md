# GNINA Linux initial exploratory smoke — predeclared

This is an engineering test of a third-party executable, not an Ankora
capability or scientific benchmark. Preserve the source project and earlier
evidence untouched. Keep downloaded executable and raw outputs outside Git.

## Executable

Official upstream GitHub release `v1.3.3`, asset `gnina.cuda12.8.static`,
2,056,131,000 bytes, published SHA-256
`3340c1f49cd3c7c84d8699182a1c6af13c7fa2a22448d1204640446106f72172`.
Source: https://github.com/gnina/gnina/releases/tag/v1.3.3 . Download into a
new isolated ignored directory; verify size and hash before execution.

## Inputs and operations

Use the previously isolated public 1HSG receptor, prepared PDB SHA-256
`4faa9c5ed9533438bbd001a91abcb38716e05660aac9b3f351475136a2d5d0ee`,
and the synthetic ethanol independently generated and minimized SDF SHA-256
`63dc82d64536769833a1744ecb2a5ac42733e91a67ac8db173b0065ea1c18a36`.
Make byte-verified copies in a new create-only run directory.

1. Record native binary identity, `--version`, `--help`, exit statuses,
   loader dependencies, GPU model and driver. Do not modify the environment.
2. With no other GPU compute job active, run a single short GNINA docking with
   explicit box centre (11.634, 22.47, 5.8585), size (24.854, 20.214, 18.635)
   Å, seed 20261029, CPU threads 2, exhaustiveness 1, maximum 2 poses,
   `--cnn_scoring rescore`, device 0 and a bounded 180-second timeout.
   Preserve command, stdout/stderr, exit status and SDF bytes/hash. These
   deliberately small settings do not support an affinity or quality claim.
3. Verify the inputs remain byte-identical. Inspect the actual SDF properties
   and model information before designing any result parser. Record failure as
   such, without silently retrying or substituting a CPU result.

No release, multi-ligand, native workstation, docking-accuracy, reproducibility
or packaging claim follows from this single test.
