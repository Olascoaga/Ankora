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

## Observed run: service-cpu-01

The predeclared WSL run completed with GNINA 1.3.3, exit code 0, explicit
`--no_gpu`, and two topology-verified poses. In engine order, CNN scores were
0.987488687 and 0.982292295; the corresponding minimized energies were
-11.4996843 and -12.0210924 kcal/mol. This illustrates why CNN ordering is not
replaced by energy ordering. Inputs in the original project remained unchanged;
the resource reservation was released. Raw execution output and individual
pose files were retained in the isolated job directory. Evidence SHA-256:
`f2c20b69e1307a0efe965eba91646ddeb920d849c44ff90786b1039d0c1b2d61`.

This run exercises the internal CPU service, not the HTTP API, user interface,
CUDA service, restart while a process is running, or native workstation. These
scores are predictions for one non-blind engineering case, not measured
affinities or a claim of scientific validation.
