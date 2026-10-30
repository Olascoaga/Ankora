# Windows CI on the hash-locked Python environment — 2026-10-28

## Observed failure (reported by the coordinator; CI log not re-read here)

Windows CI run 40803611622 failed four tests:

- two explicit-protonation tests on triethylamine;
- one frozen sensitivity-plan identity test;
- one stale manual assertion, which Gemini is fixing separately.

The job installed `python -m pip install -e "backend[dev]"`, which resolves the
version ranges in `backend/pyproject.toml`. It resolved Dimorphite-DL 2.1.0,
RDKit 2026.9.1 and NumPy 2.5.4. The accepted hash-locked Windows environment
specifies Dimorphite-DL 2.0.2, RDKit 2025.9.6 and NumPy 2.5.2.

Version drift is the probable cause of the three scientific failures. It is
not proven until the changed workflow passes on native Windows CI.

## Change (`.github/workflows/ci.yml` only)

The resolving install is replaced by these steps, in this order. Each runs one
command, because a GitHub Actions `pwsh` step reports only its last command's
exit code.

1. `pip install --require-hashes --only-binary=:all: -r requirements/windows-py312.lock`.
   This installs all 74 Python pins, including pytest, ruff and mypy, as wheels
   whose bytes must match the locked SHA-256. In hash mode pip refuses any
   unlocked transitive dependency.
2. The same command with `requirements/windows-packaging.lock`. This adds the
   seven build tools: pefile, setuptools 83.0.0, PyInstaller and its
   dependencies.
3. `pip install --no-deps --no-build-isolation -e backend`. Nothing is resolved
   or upgraded. The build backend is the locked setuptools, which satisfies
   `setuptools>=75`; build isolation is not used, so nothing is fetched for the
   build.
4. `pip check`.
5. **A version check** (`shell: python`).
   - It requires 64-bit CPython 3.12, because the locked wheels are cp312.
   - It prints the Python and pip versions and every installed locked
     distribution.
   - It fails if any distribution in either lock is missing or at another
     version.
   - It explicitly requires the lock to still pin Dimorphite-DL 2.0.2,
     RDKit 2025.9.6 and NumPy 2.5.2.

The pip cache is keyed on the two lock files; cached wheels are still verified
against their hashes. All other existing gates and their order are unchanged:
the public-path, validation-status and Windows lock checks, the smoke matrix,
backend tests, Ruff, mypy, frontend tests, type check and build, the browser
smokes, and Rust format, Clippy, tests and the Tauri build.

There is no Conda install, and no package version, lock, test expectation,
timing, scoring or frozen manifest was changed.

## Scope and boundary

- **What the CI environment is:** the wheel-compatible Python stack from the
  accepted Windows locks. It is not the complete Windows release or Conda
  environment.
- **OpenMM and PDBFixer are absent:** they come from Conda, so the tests that
  need them still skip through their existing `importorskip`, as with the
  previous install.
- **No Conda runtime check:** `verify_windows_environment_lock.py --runtime`
  requires the Conda prefix and is not run in CI. Only the static lock check
  runs.
- **Interpreter:** `setup-python` still requests `"3.12"`.
  - The accepted environment uses CPython 3.12.13 from conda-forge. Whether
    `actions/setup-python` publishes a Windows 3.12.13 build could not be
    checked here, because the network query was not approved.
  - CPython 3.12.11 and later are security-only source releases, so official
    Windows binaries may not exist.
  - The CI therefore asserts 3.12 x64 and logs the exact patch version. Pin the
    exact patch only after confirming availability.
- **pip version:** pip comes from the runner and is not locked. It is logged.
- **Hash evidence:** hashes are enforced when pip installs. Installed
  distribution metadata does not record the wheel's SHA-256, so the version
  check proves versions, not bytes, after installation.
- **PyInstaller:** the packaging lock installs PyInstaller into the test
  environment, as in the release build environment. No test invokes it.

## Checks performed here (Ubuntu 24.04 WSL2; no CI run)

- **The workflow parses with PyYAML.**
  - 28 steps, no duplicate names, `windows-latest`, `actions/setup-python@v5`.
  - No remaining `backend[dev]` install.
  - The five locked steps precede the smoke matrix and the backend tests.
  - Parsing first failed because `--only-binary=:all: -r` in an unquoted scalar
    contains a YAML mapping separator; those two commands are now quoted.
- **The inline version-check script compiles.** A dry run with the locked
  Linux interpreter (CPython 3.12.13, pip 26.2.1):
  - It confirmed Dimorphite-DL 2.0.2, RDKit 2025.9.6, NumPy 2.5.2 and every
    other shared pin.
  - As designed, it failed on exactly the six Windows-only or packaging
    differences of that Linux environment: altgraph, pyinstaller,
    pyinstaller-hooks-contrib, pywin32-ctypes and win32-setctime are missing,
    and setuptools is the Conda 84.2.1.
- **`verify_windows_environment_lock.py`:** passed (36 Conda, 74 Python,
  7 packaging).
- **Public-path and validation-status checks:** passed.
- **Version-sensitive tests in the locked Linux environment** (same Dimorphite,
  RDKit and NumPy as the Windows lock):
  - `test_ligand_protonation.py`, `test_ligand_microstates.py` (including the
    triethylamine cases) and `test_windows_environment_lock.py`: **17 passed**.
  - `test_screening_benchmark_sensitivity_plan.py`: **5 failed**. Its primary
    metrics do not reproduce bitwise on Linux, the known BEDROC floating-point
    difference recorded in `LINUX_SCIENTIFIC_FOUNDATION_REVIEW.md`. This Linux
    run therefore says nothing about the Windows sensitivity failure. No frozen
    number, hash or expectation was changed.
- **No dedicated test:** asserting the workflow text would only mirror it.

## Pending acceptance

A native Windows CI run of this workflow must show:

- the locked install and the version check passing;
- the two triethylamine protonation tests passing;
- the frozen sensitivity identity test reproducing.

Until then, the fix is unproven. The stale manual assertion is outside this
change.

## Coordinator verification on native Windows

An isolated Windows Python 3.12.13 environment installed both existing wheel
locks with hash verification and installed the backend without dependency
resolution. `pip check` passed, and the exact inline workflow version check
reported **80 locked distributions at their expected versions**.

The version-sensitive protonation tests, frozen sensitivity reproduction and
updated guide assertion passed together: **11 passed**, with one dependency
deprecation warning. The original development environment was not changed.
These checks cover the four failures observed in CI run 40803611622; they do
not prove the whole hosted workflow is green.

The hosted runner previously selected CPython 3.12.10. The
[setup-python version manifest](https://github.com/actions/python-versions/blob/main/versions-manifest.json)
lists Linux builds but no Windows build for CPython 3.12.13 at this review.
The workflow therefore continues to request the 64-bit CPython 3.12 family and
logs its exact patch version. Windows Conda remains the separately accepted
full scientific runtime; OpenMM/PDBFixer and hosted-runner verification are
still outside this local wheel-only check.
