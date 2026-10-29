# Linux P2Rank execution — 2026-10-28

This bounded ADR-026 unit lets the existing P2Rank adapter run the natively
discovered `prank` launcher on Linux. No real P2Rank prediction, download or
scientific smoke was run in this unit. Real runtime acceptance is pending
(see the end of this record).

## Changes

`adapters/tools/pocket_detection.py`:

- **Accepted Windows paths, kept unchanged:**
  - The frozen installed backend runs the private `java.exe` with the upstream
    heap, classpath and main class, without `cmd`. It still strips Java option
    variables.
  - The development backend runs `cmd /c <prank.bat> …`.
- **Native (non-Windows) development path:**
  - It runs the discovered executable `prank` launcher directly as an argument
    array (`shell=False` in the existing runner). The kernel uses the
    launcher's own `#!` line. There is no `cmd`, `bash -c` or other shell
    reinterpretation, so paths containing spaces or shell metacharacters reach
    P2Rank literally.
  - Unchanged from Windows: `predict -f <receptor> -o <output> -visualizations 0`,
    `cwd=<output>`, stage `pocket_detection`, the 900 s timeout, the raw
    `ToolExecution` (command, exit code, stdout, stderr) and the discovered
    version.
  - `JAVA_HOME` is the discovered, version-checked home (17–23), as on Windows.
    In addition, `<JAVA_HOME>/bin` is prepended to the child's `PATH`, so the
    same Java runs whether the launcher honours `JAVA_HOME` or calls `java`
    from `PATH`. The actual upstream Linux launcher was not available to
    inspect here. No exit codes or flags of it are assumed.
  - Java option variables are not stripped, matching the accepted Windows
    development path.
- **Frozen non-Windows backend:** it stays unsupported. Discovery already
  reports the Windows payload unavailable. As a second guard, the adapter
  refuses to build a `java.exe` classpath command.
- **Unavailable message:** it is now platform-neutral ("not configured on this
  system").
- **Host rules:** the adapter uses discovery's existing `_windows_host()`
  selector, so the frozen Windows contract tests (which pin it) still exercise
  the Windows path on Linux, without editing that module.
- **`java_executable(home)`:** returns `bin/java.exe` under Windows rules and
  `bin/java` otherwise.

`validation/native_tool_smoke.py`:

- The P2Rank Java probe now uses `java_executable`. It runs `java` on Linux,
  where it previously ran `java.exe`.
- The package-probe worker names the stable module
  `ankora_backend.validation.native_tool_smoke`. It previously used `__name__`,
  which is `"__main__"` under `python -m`.
- The matrix, its 10 adapter IDs, the fixtures, the create-only evidence and
  failed-run retention are unchanged. AutoDock-GPU remains reported as
  unavailable; no GPU support is implied. The docstrings of the module and of
  `scripts/run_native_tool_smoke.py` no longer say Windows-only.

## Threads and resources (proposal; not implemented)

Neither `detect_pockets` nor its API route exposes a worker/thread parameter,
so none was added. P2Rank's default flags and resource behaviour are unchanged.

Proposed interface: an optional `threads: int | None = None` on
`execute_p2rank`, appending P2Rank's thread option only when explicitly set.
It would be supplied by the service from the existing resource arbiter and
recorded in the provenance parameters. For a bounded smoke, the coordinator
can instead limit processor affinity externally.

## Tests (synthetic; no chemistry)

- **`test_linux_p2rank.py`** (6 tests, skipped on Windows). It uses real native
  discovery and the real POSIX runner with a SYNTHETIC `#!` launcher that only
  records its invocation and never predicts. The Java home is a synthetic ELF
  header plus release metadata, and is never executed. The tests cover:
  - direct launch with the exact argument array, where the launcher, receptor
    and output paths contain spaces, `&`, `;`, `$(…)`, backticks, quotes and
    `*`, and no injected file is created;
  - the working directory, `JAVA_HOME`, the `PATH` head and the recorded
    command;
  - raw stdout/stderr (including non-ASCII) and the version;
  - a nonzero exit returned unchanged;
  - a missing launcher (platform-neutral message, no launch);
  - an incompatible explicit Java 11;
  - frozen Linux refusal (no launch);
  - stage, cwd and the 900 s timeout.
- **`test_pocket_detection_adapter.py`:** the Windows development path is now
  pinned explicitly, with the exact `cmd /c` argument array, cwd, timeout and
  `JAVA_HOME`. It also checks the host-specific Java executable.
- **`test_native_tool_smoke.py`:** the probe worker module is stable when
  `__name__ == "__main__"`, and the Java probe shares the adapter's host rules.
- **Frozen Windows:** the classpath/private-Java contract continues in
  `test_bundled_scientific_tools.py`, which is unchanged.

## Checks (Ubuntu 24.04 WSL2, locked `ankora-dev` Python 3.12.13, this checkout)

- **Focused tests:** P2Rank, adapter, smoke, bundled payload, Windows-rule and
  native discovery, the pocket-detection service, both process-runner modules
  and the API: **114 passed, 2 skipped**. The skips are the real Windows
  `cmd`/`tasklist` runner tests.
- **`ruff check backend scripts/run_native_tool_smoke.py`:** passed.
- **`ruff format --check`:** passes on the adapter, the script and the three
  test files. `native_tool_smoke.py` keeps its formatting from before this
  change in untouched lines.
- **Strict mypy** (`backend/pyproject.toml`, `src`, 141 files): no issues.
- **`python -m ankora_backend.validation.native_tool_smoke --check`:** "10
  supported adapters; GNINA explicitly deferred". This validates the matrix
  only; no tool ran.

## Pending real check (coordinator)

The following are not executed or claimed here; Codex will append acceptance:

- Review of the P2Rank source, release, hash and licence.
- Inspection of the real Linux `prank` launcher's Java/home handling.
- A bounded real prediction through `execute_p2rank` and the native-tool smoke
  matrix (P2Rank on the fixed upstream receptor), recording raw streams,
  version and output hashes.
- The Windows-native rerun of the adapter and bundled tests.

## Coordinator acceptance — real native prediction

On Ubuntu 24.04 WSL2, the existing upstream PDBFixer 1BHL receptor fixture
(SHA-256 `7ff77930c706778d5009d49fe314d36829fb24b42392c9ca76a49b91301f228f`)
was analyzed through the native adapter with two available CPUs. P2Rank 2.5.1
returned exit code 0 and wrote a structured predictions CSV containing one
candidate (CSV SHA-256
`42574b705d8a1d6e0fd3a122b05b879e3cc5855bc30b6aa32c777d9eec458e7b`).
This is a runtime smoke, not a claim that the pocket is experimentally validated.

The native launcher, Java executable and P2Rank main JAR were separately hashed:

- Launcher: `ad7bedfcb833b639aebe171c005920017e68acb071cb5508e8147726ad5d115c`
- OpenJDK 21 executable: `635baf419576ec4ad4f785014283fb93f1be1103e6d02252f7a00517f0e2a245`
- Main P2Rank JAR: `4d73a85b796bd5ec5563d840abb5b1005f37b4651fd7f8aaad4b01a936ea1ece`

The existing cached upstream P2Rank 2.5.1 archive was independently verified
against SHA-256 `d243f2d9036ac053fefb9407b5fe1c85f4fe077c519fd975ac585e995feab274`.
The development runtime uses the previously reviewed
`ankora-vecmath-1.5.2-only-v1` variant: the documented vecmath 1.3.1 file was
omitted after verifying its own hash, and vecmath 1.5.2 was retained and
verified. This does not establish redistribution acceptance for the full Linux
runtime or all of its dependencies.

The corrected create-only native smoke manifest SHA-256 is
`57744f25ad68edfd87e0acbf0b1940e7d30275ca1f9e344587d74a81e59d0602`.
Its P2Rank top-level executable identity is the launcher hash above and its
Java probe hash is recorded separately. Raw commands, outputs, version probe,
fixture and output hashes remain in ignored local evidence. The earlier smoke
with Java incorrectly attributed as P2Rank is retained rather than overwritten.

The complete matrix reports **9/10 passed and overall failed** because Linux
AutoDock-GPU acceptance remains open. Linux P2Rank adapter/service-focused tests
passed (35); the Windows adapter/bundled checks passed (22, six Linux-only skips).
The subsequent evidence-identity tests passed separately on Linux and Windows.
