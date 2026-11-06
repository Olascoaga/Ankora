# GNINA screening CPU API check — predeclared

## Protocol

This is a bounded WSL engineering check, not scientific validation, a benchmark,
CUDA testing or native Linux workstation acceptance. The input library contains
the synthetic SMILES ethanol (`CCO`) and ethylamine (`CCN`). Copy the previously
prepared 1HSG exploratory project into a new create-only directory and verify
the previously recorded receptor and GNINA binary hashes. Import and filter
the two-molecule library, generate independent conformers with Ankora and
prepare their PDBQT files using the real configured Meeko. Do not change the
source project.

Through the real in-process API, explicitly start a GNINA CPU screening with
two threads per job, seed 20261029, exhaustiveness 1, two poses and a three-minute
per-job timeout. Poll to completion, retaining every selected entry and the
individual raw files, command, tool identity and output. Require two successful
jobs, no failures, each linked to the campaign; check pose hashes through the
API, GNINA CNN ordering, released resources and unchanged source files. Retain
the entire isolated data directory and write the result and failure evidence
once, even when the check fails. Never overwrite a run or change these criteria
after observing the results.
