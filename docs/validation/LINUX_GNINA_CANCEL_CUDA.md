# GNINA CUDA cancellation engineering check

## Predeclared protocol

Use a new create-only copy of the previously prepared 1HSG/MK1 project and
the pinned GNINA 1.3.3 Linux binary. Check the recorded binary and input hashes;
do not alter the original project. Explicitly select CUDA device 0, two CPU
threads, two poses, and exhaustiveness 128 so there is time to observe the
process; cap execution at three minutes. Do not start if an unrelated GPU
compute process is active.

Poll `nvidia-smi` until its compute PID matches both the GNINA executable and
the unique job directory, then request cancellation through the service. Require
canceled status, recorded cancellation, no published poses, observed process
exit, released resources, and unchanged original project. Preserve raw output
and evidence even on failure. This is an isolated WSL engineering check, not a
native workstation test, GUI test, or scientific benchmark.

## Observed run: service-cancel-cuda-01

The predeclared WSL run observed the GNINA process on a GPU before requesting
cancellation. The job ended canceled without publishing poses; the observed
process exited, resource reservations were released, and the original project
remained unchanged. Evidence SHA-256:
`8326f27ab6337dc290629bc9106f429a665123f601e6e72a5b739610fcb60b6f`.
The observation establishes the process was reported on a GPU, not that every
CNN operation used it or that logical and physical device indices coincide.
