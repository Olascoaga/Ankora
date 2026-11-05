# Linux GNINA Methods integration check

The predeclared `scripts/validate_linux_gnina_methods.py` copies a previously
recorded WSL CUDA job into a new isolated project and requests its Methods
report. It checks engine version and executable hash, seed, model, rescoring,
score units, software identity, and the absence of unrelated AutoDock steps.
It saves the response and checks the original files and evidence are unchanged.
No docking is rerun. This is one-case engineering evidence, not scientific
validation, a benchmark, or native Linux workstation acceptance.

The check completed successfully on one preserved GNINA 1.3.3 CUDA job. It
verified the recorded box coordinates without rounding, GNINA identity and
score semantics; the source project and its evidence remained unchanged.
SHA-256 of the private evidence record:
`85924dec359dbedb1c959bc769b9f9244b98135a6aeb4f88be0c1889f1ac2e94`.
