# Linux AutoDock-GPU campaign and cancellation: declared engineering test

This WSL2 development check is isolated and is not a scientific benchmark,
native Linux workstation acceptance, or installer validation. It follows the
earlier single-job service smoke. The CUDA binary, AutoGrid, prior project and
their SHA-256 identities remain exactly those recorded in
`LINUX_AUTODOCK_GPU_SERVICE_SMOKE.md`. The original project is copied into a
new create-only directory and verified unchanged; existing scientific records
and frozen validation evidence are never modified.

## Campaign

Import a deliberately synthetic two-entry library (`CCO ethanol` and `CCN
ethylamine`). Apply the default advisory filters with explicit confirmation;
generate independent conformers with RDKit/MMFF94s and prepare their docking
files using the real installed Meeko. Generate fresh AutoGrid maps for that
selection against the prior isolated 1HSG receptor and box. Run one actual
AutoDock-GPU file-list campaign, two independent runs per molecule, population
150, 5,000 evaluations, heuristics and autostop off, ADADELTA, 2 Å cluster
threshold and seeds 20261029/20261030/20261031. Assert two successful entries,
saved pose hashes, recorded CUDA device, raw output, and resource release.
These deliberately short settings are not a docking-quality protocol.

## Cancellation

After the campaign terminates and the GPU is free, start a separate single
job against one prepared library ligand and the same maps. Use two runs,
population 150 and 100,000,000 maximum evaluations; disable heuristics and
autostop. Do not wait for the calculation to finish. When the actual pinned GPU
binary is observed as a live process belonging to this isolated job, send the
real API cancellation request. Record PID and process start identity, final
state and raw tool output; verify the owned GPU process is gone, no poses were
published and the reservation was released. If the process finishes before
cancellation or cannot be observed, mark the cancellation leg inconclusive,
do not adjust parameters or silently retry. Enforce bounded waits and retain
failures. Run only when no unrelated GPU compute process is active.

The first campaign/cancellation run uses only the predeclared hash-pinned
discovery override used in the earlier smoke. If successful, Linux development
discovery may be enabled for explicitly configured native executables; that
does not certify arbitrary CUDA/OpenCL builds or hardware. A separate
predeclared run will exercise product discovery without the override.

## First attempt and declared continuation

`campaign-cancel-01` failed during initialization before importing the library
or launching AutoGrid or the GPU. The runner incorrectly assumed every earlier
evidence event contained a `body`; pose-content events do not. The original
project was unchanged. Its retained evidence SHA-256 is
`a93231ece1b8261cd0b6f4a0d92f918e3d640312549299d83f0048d85f772325`.
After correcting that evidence lookup, run once in the new create-only
`campaign-cancel-02` directory with precisely the same settings above. Do not
alter or replace the first attempt.

## Campaign completed; stricter cancellation check

`campaign-cancel-02` completed both actual file-list ligands and preserved
their pose hashes and raw CUDA output. A separate job was canceled after its
executable was observed, the process exited with `-15`, no pose was published,
and the GPU reservation was released. The original project stayed unchanged.
Evidence SHA-256:
`2825ab92afcbc1811d4a7fb2d73b19f06bc0bd26dfe306f65c6eb9c1def2b271`.
The canceled execution had no device stdout and lasted 0.065 s; this proves
process cancellation, not that the process had initialized the GPU.

Predeclare `campaign-cancel-03` with the same inputs and parameters. In this
run, wait until `nvidia-smi` reports the exact observed process PID as a GPU
compute process before requesting cancellation. If the process or GPU context
cannot be observed, cancel any live job, retain the evidence, and report the
leg as inconclusive. The test is still WSL-specific and is not a native Linux
workstation or hung-driver validation.

## GPU-context cancellation completed; product-discovery check declared

`campaign-cancel-03` completed the real two-ligand campaign and canceled a
separate job after `nvidia-smi` reported the same Linux PID as a compute
process. The owned process exited, no pose was published, the GPU reservation
was released and the original project remained unchanged. Evidence SHA-256:
`499f92e67284d35f22469427ab26047137513bd01d02710fbd435507c9bac46f`.
This is one WSL CUDA device, not evidence about an uninterruptible driver hang.

With native Linux discovery implemented, install a create-only copy of the
previously hashed binary in the versioned per-user tools directory. Predeclare
`campaign-cancel-product-01`: use the same input, output safeguards and fixed
campaign/cancellation parameters, but run with Ankora's real product
discovery (no override or configured GPU environment variable). Require the
`/tools` endpoint to report the expected binary SHA-256 and path, then verify
the real campaign, GPU-context cancellation, process exit and resource release.
This check is not a general compatibility or installer claim.

`campaign-cancel-product-01` completed with native product discovery and no
GPU-path override: `/tools` found the expected SHA-256, the two-ligand CUDA
campaign completed, and a separate job was canceled after its PID was observed
in `nvidia-smi`. The process exited, no canceled poses were published, GPU
capacity was released, and the original project remained unchanged. Retained
evidence SHA-256:
`ace4d1dd31ba05a8571d9cb5fd898709fa7771b98a41d47912e8c625f13285f4`.
The native discovery and GPU service selection passed 87 WSL tests and the
Windows engine, discovery and resource selection passed 69 tests. Ruff and
backend mypy (142 files) passed. Product discovery identifies a native binary;
the version and device are checked when launching a job, and a successful
test on this WSL device does not certify other GPU builds or platforms.
An additional direct native probe in the same WSL environment, with both
`LD_LIBRARY_PATH` and `ANKORA_AUTODOCK_GPU_PATH` unset, reported version 1.6,
the same executable SHA-256 and the RTX 5050. This is local runtime evidence,
not a bundled or relocatable Linux installation.
