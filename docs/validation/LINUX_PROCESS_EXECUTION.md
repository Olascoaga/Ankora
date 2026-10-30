# Linux Scientific Process Lifetime and Cancellation Validation

## Scope

This validation record covers the bounded POSIX scientific subprocess lifetime,
process-tree termination, pipe drainage, and cancellation unit for the Linux port
under [ADR-026](../architecture/ADR/ADR-026-linux-port-and-native-acceptance.md).

Owned files in this unit:

- `backend/src/ankora_backend/execution/subprocess_runner.py`
- `backend/src/ankora_backend/execution/cancellable_subprocess.py`
- `backend/tests/test_subprocess_runner.py`
- `backend/tests/test_posix_subprocess_runner.py`
- `docs/validation/LINUX_PROCESS_EXECUTION.md`

No scientific scoring, chemistry logic, thresholds, resource budgets, backend
launcher scripts, tool discovery modules, or dependency manifests were modified.

## Implemented Contract

1. **Owned POSIX session membership and `(pid, starttime)` birth identity (`os.name != "nt"`)**:
   - Scientific subprocesses launched through `run_tool` and `run_cancellable_tool`
     always use `subprocess.Popen(..., shell=False)` with explicit argument arrays,
     working directory (`cwd`), and environment mapping (`env`).
   - On POSIX, child tools are started with `start_new_session=True`, making the
     launched tool the leader of an isolated session and process group
     (`sid == pgid == process.pid`).
   - Leader exit is inspected without reaping via
     `os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)`
     (with `/proc/<pid>/stat` zombie-state fallback). Keeping the session leader
     unreaped until cleanup finishes prevents the kernel from reusing the session ID
     or root process-group ID even if the leader exits before its descendants.
   - `_PosixProcessTracker` scopes ownership to current members of the owned
     session (`stat.pid == root_pid`, `stat.sid == root_pid`, or
     `stat.pgrp == root_pid`) and tracks birth identity via `/proc/<pid>/stat`
     field 22 (`starttime`). It does not adopt bare remembered PIDs across `/proc`
     scans and does not claim coverage of arbitrary daemonized processes that enter
     a new session (`setsid`).
   - Before any `os.kill` or `os.killpg` is issued, `_signal_posix_targets`
     revalidates current `/proc/<pid>/stat` ownership (`sid`/`pgrp` and matching
     `starttime`), ensuring a child PID that exits, is reaped, and is reused by an
     unrelated process/process group is never signaled.

2. **Throttled `/proc` scanning and non-busy waiting**:
   - While the session leader is still running, normal poll iterations check only
     `cancel_event`, deadline, non-blocking pipe readiness, and single-PID
     `_has_leader_exited_no_reap(process)` without scanning `/proc`.
   - Once the session leader exits, `/proc` is scanned once to check whether any
     descendant in the owned session remains alive; if a descendant outlives the
     leader, subsequent `/proc` scans are throttled to at most once every `0.25s`
     (`<= 4/sec`) plus a one-time check on pipe EOF transition.
   - After both `stdout` and `stderr` reach EOF, the runner waits via
     `cancel_event.wait(timeout=...)` or `time.sleep(...)` rather than spinning on
     an empty selector.

3. **Single-thread non-blocking pipe capture and exception-safe cleanup**:
   - On POSIX, `_PosixSelectorPipes` reads binary `Popen` pipes (`text=False`)
     using `os.set_blocking(fd, False)` and `selectors.DefaultSelector()` in the
     runner thread, decoding UTF-8 (`errors="replace"`) with universal newline
     normalization at completion.
   - Each per-fd drain call is bounded to a fixed quantum (`_MAX_READS_PER_DRAIN = 16`
     reads of `64 KiB` per poll), leaving continuously readable pipes registered for
     subsequent poll ticks without discarding bytes so outer timeout and
     cancellation checks cannot be starved by continuous output.
   - `_PosixSelectorPipes._register` fails closed (cleaning up the selector and
     already-registered streams on error without falling back to blocking
     `stream.read()`), and `_run_posix_tool_process` places tracker and pipe
     initialization inside `try ... finally` immediately after `Popen` so
     post-spawn setup failures or unexpected loop exceptions terminate the owned
     session and close all pipe/selector file descriptors before propagating.

4. **Pre-canceled contract and Windows preservation**:
   - If `cancel_event.is_set()` is already true before `run_cancellable_tool`
     spawns the child process, `run_cancellable_tool` does not launch the
     scientific executable and immediately returns:
     `CancellableToolExecution(command=command, exit_code=-1, stdout="", stderr="", canceled=True, timed_out=False)`.
   - Launch failures (`OSError` from `subprocess.Popen`) raise `AnkoraDomainError`
     with `code="SCIENTIFIC_TOOL_LAUNCH_FAILED"` and the platform-neutral message
     `"Ankora could not launch the configured scientific tool."`
   - On Windows (`os.name == "nt"`), the `taskkill /PID <pid> /T /F` flow is
     preserved, and when `cancel_event` becomes set concurrently with
     `process.communicate(timeout=0.2)` returning, `_kill_tree_and_drain` cleans up
     any surviving tree members while preserving the already captured `stdout` and
     `stderr` exactly once without duplication.

## Synthetic Process Test Coverage

All process-control tests use explicitly labeled `SYNTHETIC` Python child and
grandchild probes (`sys.executable -c ...`) or labeled `SYNTHETIC` `/proc` and
Windows-branch unit stubs, and never invent scientific data:

- `backend/tests/test_subprocess_runner.py`:
  - Preserves Windows `cmd` / `ping` / `tasklist` tree-kill and `cmd /c echo`
    tests gated on `sys.platform == "win32"`.
  - Covers cross-platform exact argument array, `cwd`, `environment`,
    `stdout`/`stderr` capture, non-zero exit codes, platform-neutral
    `SCIENTIFIC_TOOL_LAUNCH_FAILED` reporting, pre-canceled `run_cancellable_tool`
    non-spawn behavior, and single-capture preservation on the Windows
    `communicate` + concurrent cancellation branch.
- `backend/tests/test_posix_subprocess_runner.py`:
  - Covers isolated POSIX session/process-group creation (`sid == pgid == pid`),
    exact `stdout`/`stderr` capture across child + grandchild, and non-zero exits
    for both `run_tool` and `run_cancellable_tool`.
  - Covers `run_tool` and `run_cancellable_tool` timeout and active cancellation
    where child and grandchild ignore `SIGTERM`, use separate process groups within
    the owned session (`os.setpgid(0, 0)`), and hold pipes open, verifying partial
    output preservation, bounded return time, no surviving descendants, and
    survival of an unrelated sentinel session.
  - Covers leader-exits-before-grandchild scenarios for both `run_tool` and
    `run_cancellable_tool` (both with pipes held open and with stdio redirected to
    `/dev/null`).
  - Covers deterministic `/proc`-table PID reuse rejection when a recorded child
    PID reappears with a different `starttime` and unrelated `sid`/`pgrp`.
  - Covers `/proc` scan throttling during active leader execution, bounded
    per-poll `_drain_fd` quantum on a continuously readable pipe, multi-megabyte
    `stdout`/`stderr` preservation across multiple drain quanta, post-`Popen`
    selector/pipe registration failure cleanup, unexpected runner-loop exception
    cleanup, and repeated canceled runs with zero leaked threads or file
    descriptors.

## Verification Status

- **Prior Codex runs** (recorded in ignored raw logs
  `logs/linux-phase2-20261028/process-tests.log` and JUnit XML):
  - Initial revision: `12 passed, 2 skipped in 4.84s`.
  - Second revision: `17 passed, 2 skipped in 6.99s`; strict `mypy` clean on both
    execution modules (the 2 Windows-specific `cmd`/`tasklist` tests were skipped
    on Linux; this does not constitute native Windows runtime execution).
- **Current revision checks (Pending Codex Execution)**:
  - `pytest backend/tests/test_subprocess_runner.py backend/tests/test_posix_subprocess_runner.py` — **PENDING (to be run by Codex)**
  - `ruff check backend/src/ankora_backend/execution/subprocess_runner.py backend/src/ankora_backend/execution/cancellable_subprocess.py backend/tests/test_subprocess_runner.py backend/tests/test_posix_subprocess_runner.py` — **PENDING (to be run by Codex)**
  - `mypy backend/src/ankora_backend/execution/subprocess_runner.py backend/src/ankora_backend/execution/cancellable_subprocess.py backend/tests/test_subprocess_runner.py backend/tests/test_posix_subprocess_runner.py` — **PENDING (to be run by Codex)**
  - `python3 scripts/check_public_paths.py` — **PENDING (to be run by Codex)**

## Final coordinator review — 2026-10-28

Codex reviewed the assigned implementation and requested corrections before
acceptance: birth identity rather than remembered PIDs, reduced process-table
scanning, selector-based pipe lifetime, exact-once Windows capture, bounded
drain quanta, and cleanup when registration fails after process creation.

The final revision was checked on both real hosts:

- Ubuntu 24.04 WSL2, locked Python 3.12.13: **20 passed, 2 skipped in 7.10 s**
  across the subprocess and POSIX subprocess test files. The two skips are the
  real Windows `cmd`/`tasklist` tests, exercised separately on Windows.
- Windows-native Python: **7 passed, 15 skipped in 2.79 s**. This includes
  `taskkill /T` and exact capture; the 15 skips are POSIX-specific tests.
- Ruff passed on both implementation modules and their two test files.
- Strict mypy passed on both implementation modules.
- `git diff --check` passed. Raw test logs and JUnit remain in ignored local
  evidence; no private paths or execution logs are published.

These checks validate process lifetime and the existing typed capture contract.
They do not certify any docking energy or GPU runtime. Ownership covers the
launched POSIX session; deliberately daemonized tools that create a new session
are outside this contract. A native Linux workstation remains a later gate.
