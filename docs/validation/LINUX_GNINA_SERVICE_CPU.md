# GNINA CPU service engineering check

## Predeclared protocol

This is a bounded WSL engineering check of the internal GNINA single-job CPU
service. It is not blind redocking, a biological benchmark, GUI acceptance,
CUDA validation, or native Linux workstation validation. The previously
prepared public 1HSG/MK1 exploratory project is copied into a new create-only
directory; its existing files and recorded evidence must not be modified.

Use the previously recorded GNINA 1.3.3 binary identity and 1HSG/MK1 prepared
PDBQT receptor, PDBQT ligand, conformer and search box. Explicitly choose CPU,
two threads, seed 20261029, exhaustiveness 1 and at most two modes. Run the
actual service, not an executable from the frontend. Require terminal success,
verified pose topology, preserved engine ranking, immutable raw output and
input hashes, complete execution evidence and released CPU/work leases. Record
failure rather than replacing evidence if any condition fails. Any new attempt
requires a new directory and separately identified evidence.
