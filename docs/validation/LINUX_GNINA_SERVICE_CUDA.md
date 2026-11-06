# Experimental GNINA CUDA service engineering check

## Predeclared protocol

Run the experimental internal GNINA single-job CUDA service in WSL, using a
new create-only copy of the previously prepared public 1HSG/MK1 exploratory
project. Verify the recorded GNINA binary and prepared receptor, ligand and
conformer hashes before launch. Leave the original project untouched. Use the
recorded binding site, explicit CUDA device 0, two CPU threads, seed 20261029,
exhaustiveness 1 and at most two modes. Do not run while an unrelated GPU
compute process is active. Preserve failure evidence rather than rewriting it.

Require successful execution, pose topology validation, preserved score order,
raw output, released resources and process-specific GPU observation from
`nvidia-smi` matching the GNINA binary and job directory. A GPU process
observation is not independent evidence that every CNN operation ran on GPU,
nor proof of logical-to-physical device mapping. This is an engineering check,
not a blind benchmark, general scientific validation, cancellation test,
interface acceptance, or native workstation test. CUDA stays disabled by
default pending those checks.

## Observed run: service-cuda-01

The predeclared isolated WSL service run completed. The service verified the
pose topology and retained the engine output, observed its process on a GPU,
confirmed the original project files were unchanged, and released its resource
reservation. The recorded evidence SHA-256 is
`4a1588773f4b5ca674854a30746061b8bd3edd25e04f62f0a66dc53a2ee87a73`.
The evidence remains in the ignored local investigation directory. The scope
and limitations above still apply; in particular, CUDA is not enabled in the
application and no claim about inference for every operation is made.
