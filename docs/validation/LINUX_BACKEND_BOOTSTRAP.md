# Linux backend development launcher — 2026-10-28

First bounded Linux backend unit under ADR-026 and `docs/DEVELOPMENT_LINUX.md`.
Owned files: `scripts/dev_linux.py`, `backend/tests/test_linux_dev.py` and this
record. No chemistry, scientific adapter, threshold, lock, Windows script, CSP or
dependency was changed or installed. No scientific tool or docking was executed.

## Interface

Tauri runs `python3 ../../scripts/dev_linux.py` from `apps/desktop`. The launcher
is standard-library Python 3.12, resolves the repository from its own location
and runs both children from the repository root:

- backend: `[<python>, "-m", "ankora_backend", "--parent-pid", <launcher pid>]`;
  `--parent-pid` is the backend's existing guard and stops it if the launcher
  vanishes;
- frontend: `[<npm>, "run", "dev"]` (Vite on 127.0.0.1:1420);
- optional `--startup-timeout SECONDS` (default 90) bounds each readiness wait.
  It must be finite and greater than zero. NaN, infinity, zero, negative or
  non-numeric values are rejected (exit status 2) before any interpreter is
  selected or process spawned. `run_session` applies the same check to its
  startup and stop-grace bounds before checking ports.

Python selection, first match wins:

1. `ANKORA_PYTHON_PATH`. If it is missing, not executable or a Windows
   executable/path, startup fails; there is no fallback.
2. Active Conda environment (`CONDA_PREFIX`) unless it is `base`.
3. Project `.venv/bin/python`.
4. A Conda environment named `ankora-dev`, found through `CONDA_EXE`,
   `MAMBA_ROOT_PREFIX`, `~/{miniforge3,mambaforge,miniconda3,anaconda3,.conda}`.

If none qualifies, the error lists every path it checked. Unlike `dev.ps1`, this
launcher does not fall back to system Python, and it follows the
contract order (`.venv` before named `ankora-dev`). Windows binaries (`.exe`,
`.bat`, `.cmd`, `.ps1`, the `MZ` header) and anything under `/mnt/<drive>/` are
rejected for both Python and npm.

The backend inherits the developer's environment, including every `ANKORA_*_PATH`
tool override. The launcher adds four things:

- it prepends the interpreter's `bin` directory to `PATH`, so tools installed
  in that environment can be discovered;
- it prepends this checkout's `backend/src` to `PYTHONPATH`, so a worktree runs
  its own backend code;
- for a Conda environment it sets `CONDA_PREFIX`/`CONDA_DEFAULT_ENV`, as
  `dev.ps1` does; for a virtual environment it sets `VIRTUAL_ENV`;
- it sets `ANKORA_PYTHON_ENVIRONMENT` only if it is unset.

## Behaviour

- **Occupied ports:** before starting anything, the launcher checks 8765 and
  1420. A port counts as occupied when 127.0.0.1 accepts a connection or a
  `SO_REUSEADDR` bind fails. The error names the visible listener pid and
  command, and reports when it answers as an Ankora backend. The launcher never
  stops or reuses that listener.
- **Readiness:** the API is ready only when `/api/v1/health` returns
  `{"status": "ok", "backend_version": <str>}` *and* every socket listening on
  8765 on a loopback-reachable address (`/proc/net/tcp[6]`) belongs to a
  process in the backend's own session. The frontend is ready when 1420 has a
  listener owned by the npm session. If a child exits early, a foreign listener
  appears, or the time bound expires, startup fails. The error shows the last 40
  output lines and the log path.
- **Ownership and cleanup:** each child gets its own session
  (`start_new_session`). The launcher tracks the leader's exit with
  `waitid(WNOWAIT)` and does not reap it until cleanup ends, so the session id
  cannot be recycled first. Cleanup sends SIGTERM to every process group in the
  owned session, waits 5 s, then sends SIGKILL. It runs on SIGINT, SIGTERM or
  SIGHUP (exit status 128+signal), on frontend exit (the frontend's status is
  returned), on unexpected backend exit, and on any startup failure (status 1).
- **Raw output:** child stdout/stderr bytes are copied to the terminal and to
  `logs/dev-linux/<UTC>-<pid>/{backend,frontend}.log` (created only, Git-ignored).
  `session.json` records the interpreter, its source, both command arrays,
  ports, times, exit status and any error. The environment is never recorded.
- **HTTP probes:** these use an opener that bypasses any inherited HTTP proxy.

## Checks executed (Ubuntu 24.04 WSL2, system Python 3.12.3)

Run with the developer venv (pytest 8.4.2, Ruff 0.17.3, mypy):

- `pytest backend/tests/test_linux_dev.py`: 20 passed.
- `ruff check` and `ruff format --check` with `backend/pyproject.toml` on both
  Python files: passed.
- `mypy --strict --python-version 3.12 scripts/dev_linux.py`: no issues.
- System `python3 scripts/dev_linux.py --help`: loads with the stdlib only.

The lifecycle tests run real processes, sockets and signals. Every child is an
explicitly SYNTHETIC stdlib stand-in (a health-only HTTP server, a socket
listener, a crashing script or a hung script), and each spawns a helper
grandchild. The tests prove:

- an occupied port is rejected before any spawn and the foreign listener keeps
  accepting connections;
- foreign versus owned listener identity;
- frontend exit returns its status and leaves no leader or helper alive;
- a backend crash reports its raw stderr and never starts the frontend;
- a wrong health payload and a never-listening backend both hit the time bound
  and are cleaned up;
- SIGTERM and SIGINT sent to a real launcher process return 143 and 130 with
  every owned process gone.

The interpreter-selection tests use synthetic, never-executed files.

### Review follow-up

Codex reviewed the first commit and raised two findings:

- **Unbounded `--startup-timeout`:** NaN or infinity could make startup
  unbounded. It is now validated as described above. The regression tests:
  - pass 11 rejected CLI values; each must exit with status 2 while
    `select_python` and `Popen` are set to fail if called;
  - check that three valid values are accepted;
  - check that `run_session` rejects NaN, infinity, zero and negative
    startup/stop bounds and leaves its log directory empty.
- **Hard-coded platform in the API test:**
  `test_api.py::test_system_endpoint_reports_runtime` asserted
  `platform == "windows"`, so it failed on Linux, where the API correctly
  reports `linux`. The expected value now comes from the interpreter
  (`win32` → `windows`, `linux` → `linux`). On Windows it still checks for
  `windows`, and an unsupported host fails. `system_info` is unchanged.

Follow-up checks:

- `pytest backend/tests/test_linux_dev.py backend/tests/test_api.py
  backend/tests/test_structure_workspace.py`: 73 passed. The only warning is
  the existing Starlette/httpx `TestClient` deprecation.
- `ruff check`, run from `backend/` with its project configuration, on the
  launcher and both test files: passed.
- `ruff format --check`: the launcher and launcher tests pass. `test_api.py`
  has three previously unformatted blocks in lines this change does not
  touch; they were left as they are.
- `mypy --strict` on the launcher: no issues.

## Not executed / limitations

- **Real backend end to end:** `main()` was not run with the real
  `ankora_backend`. The smoke command needed a permission approval that was not
  given in this session. Real health and identity against uvicorn, real
  `npm run dev` and a Tauri window are therefore unverified here. Node
  dependencies are not installed in this worktree.
- **Launcher killed with SIGKILL:** the backend stops through `--parent-pid`,
  but Vite would survive. In normal use Tauri's dev shutdown sends SIGTERM to
  all descendants.
- **Mirrored WSL networking:** with a Windows listener on the same ports, only
  the connect/bind probes were reasoned about, not tested.
- **`PYTHONPATH` precedence:** the checkout's `backend/src` takes precedence
  over an editable install of another checkout in the selected environment.
  This is intentional.
- **Windows:** the test module is skipped there; `dev.ps1` is unchanged.
- **Scope of this evidence:** it is development evidence for gate 1 only, not
  native Linux acceptance.
