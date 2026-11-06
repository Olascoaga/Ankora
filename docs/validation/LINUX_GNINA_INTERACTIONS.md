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

The recorded check completed on WSL using ProLIF 2.2.1 and one preserved CUDA
pose. It produced 15 geometric contacts and verified that the source was
unchanged. SHA-256 of the ignored evidence record:
`8b15df695fa878089ffc15192a43d2b4a460f7675e829910e66a53d9a56fc337`.
