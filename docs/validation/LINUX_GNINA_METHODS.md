# Linux GNINA Methods integration check

The predeclared `scripts/validate_linux_gnina_methods.py` copies a previously
recorded WSL CUDA job into a new isolated project and requests its Methods
report. It checks engine version and executable hash, seed, model, rescoring,
score units, software identity, and the absence of unrelated AutoDock steps.
It saves the response and checks the original files and evidence are unchanged.
No docking is rerun. This is one-case engineering evidence, not scientific
validation, a benchmark, or native Linux workstation acceptance.
