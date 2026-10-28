# Development dependency: pefile — 2026-10-28

## Problem

Windows PR CI run 40750727321 failed while collecting
`backend/tests/test_gpu_payload_builder.py`. The test imports
`scripts/build_autodock_gpu_payload.py`, which imports `pefile` at module level
to read the import table of the rebuilt AutoDock-GPU executable. CI installs
`backend[dev]`, which did not declare `pefile`. The 2026-10-13 receptor
relaxation record had already noted that a basic `.venv` cannot collect this
suite for the same reason.

## Change

`backend/pyproject.toml` declares `pefile==2024.8.26` in the `dev` extra. This
is the identity already pinned and hash-locked in
`requirements/windows-packaging.lock`, so development, CI and packaging resolve
the same release.

The following are unchanged: runtime dependencies, the `receptor` extra, the
Windows scientific and packaging locks, CI workflow policy, and the tests,
which are neither skipped nor altered. `pefile` is pure Python and is used only
by this build script and its tests. It makes no scientific claim.

## Checks (Ubuntu 24.04 WSL2, Python 3.12.3)

Codex installed `pefile 2024.8.26` into the developer environment. Tests ran
from the repository root, as in CI, with this checkout's `backend/src` first on
the import path:

- `pytest --collect-only backend/tests/test_gpu_payload_builder.py`: 4 tests
  collected; no import error.
- `pytest backend/tests/test_gpu_payload_builder.py`: 4 passed.
- The imported module was this checkout's `scripts/build_autodock_gpu_payload.py`,
  and the installed `pefile.__version__` was `2024.8.26`.
- `backend/pyproject.toml` parses; runtime dependencies are byte-for-byte the
  same list.

Not executed: the Windows CI rerun (requires a push, which Codex coordinates) and
a fresh `pip install -e "backend[dev]"` resolution, because no installs were
allowed in this unit. The tests use synthetic build metadata only; no
AutoDock-GPU build, docking or GPU run took place.
