# Windows CI: isolated Python environment — 2026-10-28

## Observed failure (reported by the coordinator)

Windows CI run 40808598327, on PR head `71c9038`, completed both hash-locked
installs (`requirements/windows-py312.lock` and
`requirements/windows-packaging.lock`), then failed at `python -m pip check`.

- The hosted base interpreter from `actions/setup-python` already contains
  pipx 1.18.4.
- pipx requires `filelock>=4.2` and `packaging>=26.3`.
- Ankora's hash-locked versions are filelock 3.32.4 and packaging 26.2.

The same locks passed `pip check` in a clean native Windows virtual
environment. The conflict therefore comes from tools pre-installed on the
runner image, not from the locks.

## Change (`.github/workflows/ci.yml`)

1. The setup-python step gets `id: setup-python`. Its inputs (Python 3.12,
   pip cache keyed on both locks) are unchanged.
2. A new step, *Create isolated Python environment*, runs immediately after
   it in pwsh:
   - `& "<setup-python python-path output>" -m venv $env:RUNNER_TEMP\ankora-ci-venv`,
     without `--system-site-packages`;
   - an explicit `$LASTEXITCODE` check, because pwsh does not stop on native
     command failures;
   - `VIRTUAL_ENV` appended to `GITHUB_ENV`;
   - the environment's `Scripts` directory appended to GITHUB's official
     `GITHUB_PATH`, which prepends it to `PATH` for all later steps.
3. A new step, *Verify the isolated Python environment* (`shell: python`), runs
   before any other Python use. It requires that:
   - `python` on `PATH` is that environment (`sys.prefix` equals
     `VIRTUAL_ENV` and differs from `sys.base_prefix`);
   - user site-packages are disabled;
   - no visible distribution lies outside the environment, so pipx and other
     base packages cannot appear.

   It logs the interpreter, its base and the distributions it sees.

Every later `python` and `python -m pip|pytest|ruff|mypy` command, including the
`shell: python` version check and test subprocesses using `sys.executable`,
resolves to this environment. The stdlib-only path, validation-status and
Windows lock scripts also now run inside it.

Unchanged:

- the hash-locked install commands (`--require-hashes --only-binary=:all:`);
- `--no-deps --no-build-isolation -e backend`;
- `pip check` and the version check against the locks;
- all test, lint, type, frontend, browser-smoke and Rust/Tauri steps and their
  order;
- the locked versions themselves.

Node, npm, npx, rustup and cargo are unaffected, because the environment's
`Scripts` directory contains only Python entry points. The Node smokes use
synthetic in-process backends and launch no Python, and the Windows Tauri
build does not invoke Python. No hosted package was deleted, and no locked
version was upgraded or downgraded.

## Regression tests (`backend/tests/test_windows_ci_workflow.py`, 5 tests)

- **Structural:**
  - the isolated environment is created by the exact setup-python
    interpreter, immediately after setup-python, without system site-packages,
    with the exit-code check and both `GITHUB_PATH`/`GITHUB_ENV` writes, and is
    followed by the `shell: python` verification;
  - no earlier step uses Python, and no later step refers back to the hosted
    interpreter;
  - the locked installs, editable `--no-deps` install, `pip check`, version
    check and backend tests stay in that order, with no `backend[dev]`.
- **Behavioural:** the actual verification script from the workflow is run
  against real local environments created with `--without-pip`, with
  `PYTHONPATH` removed. It:
  - accepts a clean venv;
  - rejects the non-isolated interpreter;
  - rejects a `--system-site-packages` venv that sees base distributions.
- **Regression value:** the three structural tests were also run against the
  previous workflow (`HEAD` before this change), and all three fail there, as
  intended.

## Checks (Ubuntu 24.04 WSL2, locked Python 3.12.13; not Windows)

- **`pytest backend/tests/test_windows_ci_workflow.py backend/tests/test_readme.py`:**
  16 passed (5 new, 11 existing).
- **Workflow YAML** parses with PyYAML. It has 30 steps (28 before), no
  duplicate names, and preserved order. The only additions are the two steps
  above; the only changed existing step is `id: setup-python`.
- **`ruff check backend`** and `ruff format --check` on the new test: passed.
- **Strict mypy** on `backend/src` and the new test: no issues in 143 files.
  The PyYAML import carries an explicit `import-untyped` ignore because stub
  packages are not part of the locks.
- **`verify_windows_environment_lock.py`, the public-path check and the
  validation-status check:** passed.

## Caveats

- **Hosted CI not yet run:** the fix is not proven until a Windows CI run with
  this workflow passes `pip check` and the subsequent gates.
- **pwsh step not executed:** PowerShell is not installed here. Its syntax
  follows GitHub's documented `GITHUB_PATH`/`GITHUB_ENV` pattern for pwsh, but
  it was only parsed, never run.
- **pip:** the version inside the new environment comes from the setup-python
  interpreter's bundled `ensurepip`, not from a lock. It is logged by both
  verification steps.
- **Cache:** the pip download cache remains shared through setup-python.
  Hashes are still enforced on every locked install.
- **Scope:** the scope boundary of `WINDOWS_CI_LOCKED_ENVIRONMENT.md` still
  applies. This is the wheel-compatible locked stack, not the Conda release
  environment, so OpenMM and PDBFixer tests still skip.
