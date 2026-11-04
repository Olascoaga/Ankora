# Linux GNINA pose interaction integration check

The predeclared script `scripts/validate_linux_gnina_interactions.py` copies the
previously recorded WSL CUDA API job into a new isolated directory. It checks
that the inventory preserves GNINA's pose hash and distinct scores, requests a
ProLIF analysis of the first recorded pose, checks its identity and persisted
history, and verifies that the original evidence and project files are unchanged.
It does not run docking again. This is a single-case engineering check, not
scientific validation, a benchmark, or acceptance on a native Linux workstation.

The test writes failure or success evidence under ignored local logs. ProLIF
contacts are geometric observations, not measured binding affinities.
