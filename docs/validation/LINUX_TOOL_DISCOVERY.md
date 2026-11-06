# Linux tool discovery — 2026-10-28

This is the ADR-026 gate 2 discovery unit. It changes how external tools are
*found* on Linux. It does not run any tool, change chemistry, or claim that a
Linux scientific workflow is accepted. No tool was installed, executed or
benchmarked.

## Scope

- `backend/src/ankora_backend/adapters/tools/discovery.py`: native rules for
  non-Windows hosts.
- `backend/tests/test_linux_tool_discovery.py` (new) and
  `backend/tests/test_tool_discovery.py`: focused tests.
- `backend/tests/test_bundled_scientific_tools.py`: its fixture now pins Windows
  rules. That file is the Windows installed-mode contract and otherwise fails
  on Linux, because Linux deliberately rejects the Windows payload. This
  one-line test change sits outside the originally listed files and is flagged
  for review.

On Windows, the host switch `_windows_host()` (`os.name == "nt"`) leaves every
previous branch and result unchanged. The only Windows-side edit rewrites the
AutoDock subdirectory list `bin, windows, x86, x64` as a constant, with the
same order and result.

## Native rules (Linux, including WSL)

A candidate is native only if all of the following hold. Nothing is executed;
only headers, permissions and metadata are read.

- It resolves to a regular file with the execute bit set.
- It starts with an ELF header (`\x7fELF`), or with `#!` naming an absolute
  interpreter.
- Neither the given path nor the resolved one has a Windows suffix (`.exe`,
  `.bat`, `.cmd`, `.com`, `.ps1`, `.dll`), and neither lies on a WSL drive
  mount (`/mnt/<letter>/`).
- A script's interpreter is not a Windows file either.

Because of the content check, a PE image renamed without `.exe` and carrying the
execute bit (as every DrvFs file does) is rejected.

**Search order:** an explicit path first, then PATH, then the unresolved
active-Python `bin` directories (`sys.executable`'s directory and
`sys.prefix/bin`). For a venv this is its own `bin`, not the system Python it
symlinks to. The default PATH search walks each entry and skips non-native
files. `shutil.which` would stop at the first match, which on WSL can be a
Windows file. Empty PATH entries (the current directory) are ignored.

**Explicit configuration** (`ANKORA_*_PATH`, and `JAVA_HOME` for Java) is
authoritative. If it is missing, non-executable, non-native, a Windows file, or
a directory without the expected name, the tool is unavailable. There is no
fallback to PATH or other locations.

**Portable distributions:** only narrowly named directories directly under
`~/tools` are considered. There is no broad disk scan.

| Tool | Native names / locations | Recorded identity |
| --- | --- | --- |
| Meeko | `mk_prepare_ligand.py`, `mk_prepare_receptor.py` (the Meeko 0.7.1 console entry points, confirmed from installed metadata), then the plain names | path |
| PDB2PQR / PROPKA | `pdb2pqr`, `propka3` | path |
| AutoDock Vina | `vina` on PATH; `~/tools/(autodock-)vina-<ver>/` with `vina`, `vina_<ver>`, `vina_<ver>_linux_x86_64` (newest first) | path, ELF architecture, SHA-256; version only from a versioned file name, after resolving symlinks |
| AutoGrid4 / AutoDock4 | `autogrid4`, `autodock4`; `~/tools/autodock(suite\|4)-<ver>/{,bin,x86_64Linux2}` | path, ELF architecture, SHA-256; version only from a versioned parent or grandparent directory, as on Windows |
| P2Rank | the `prank` shell launcher; `~/tools/p2rank*` | path; version from the distribution `README.md` or a versioned directory name |
| Java (P2Rank) | `JAVA_HOME`, `java` on PATH resolved through symlinks, `sys.prefix`, `sys.prefix/lib/jvm`, `~/tools/jdk-*`/`jre-*` | home; accepted only if `release` reports `JAVA_VERSION` major 17–23 |

ELF architectures are reported as `x86`, `x86_64`, `arm64` or `unknown`, the
same vocabulary as the existing PE reader. An unversioned `vina`, `autodock4`
or `autogrid4` reports `version=None`. Vina's version is still verified from
`--version` by the existing adapter before docking.

### Deliberate differences from Windows

- **Java metadata:** Linux requires the Java `release` metadata. Windows still
  treats a home without it as compatible.
- **`JAVA_HOME`:** on Linux an explicit `JAVA_HOME` is authoritative. Windows
  keeps its accepted fallback to other installations.
- **AutoDock-GPU:** it is always unavailable on Linux, even when a native binary
  exists. Each GPU engine/runtime needs its own native acceptance (ADR-026), and
  none exists yet.
- **Frozen mode:** the private payload is a Windows inventory. On Linux,
  `_bundled_discovery` and bundled Java report nothing available; a frozen Linux
  external payload is not implemented. Frozen Python workers (Meeko, PDB2PQR,
  PROPKA through `sys.executable`) are unchanged.
- **GNINA:** it is reported only as present or absent through the generic native
  rules. It remains outside the port (ADR-026).

## Tests

All fixtures are synthetic: minimal ELF headers, PE headers or `#!` stubs,
labelled as such and never launched. No scientific result is mocked.

- `test_linux_tool_discovery.py`: 34 tests.
  - It is **skipped on Windows**, because it needs POSIX permission bits and
    symlinks.
  - It covers executable identity by content, Windows-interpreter scripts, WSL
    drive paths, ELF architecture, and the PATH search skipping a masquerading
    PE that `shutil.which` would have picked.
  - It covers the Meeko `.py` names, unresolved venv directories, explicit
    configuration without fallback, and the configured-directory names.
  - Engine cases: official Vina 1.2.7 Linux release name with architecture and
    SHA-256, unversioned `vina`, a symlink to a versioned release, the newest
    configured release, the AutoDock suite `x86_64Linux2` layout, and
    AutoDock-GPU staying unavailable.
  - P2Rank cases: the `prank` launcher and a non-executable `prank`.
  - Java cases: alternatives symlinks, the 17–23 table, missing metadata,
    fallback to named `~/tools` homes, authoritative `JAVA_HOME`, and a PE
    `java`.
  - Frozen Windows payload: not reported on Linux.
- `test_tool_discovery.py`: 13 tests. An autouse fixture pins Windows rules on
  every host. On Windows that is a no-op. On Linux it keeps the unchanged
  Windows resolution covered, without proving Windows filesystem semantics
  (case folding, PATHEXT).
- `test_bundled_scientific_tools.py`: 14 tests, with Windows rules pinned as
  above.

## Checks (Ubuntu 24.04 WSL2, Python 3.12.3, this checkout's `backend/src` first)

- The discovery modules above, plus the discovery consumers (ligand, unicode
  paths, receptor adapters, AutoGrid, P2Rank adapter, API, Vina adapter, native
  smoke) and the GPU payload builder: **112 passed, 1 failed**.
  - The failure is **pre-existing** and unrelated:
    `test_native_tool_smoke.py::test_evidence_writer_preserves_raw_output_commands_and_fixture_hashes`
    expects the SHA-256 of a fixture written with Windows CRLF endings
    (`d853…`); Linux writes LF (`1acc…`). It failed identically before this
    change.
  - The pre-change baseline for the consumer subset was 61 passed with that
    same failure. After this change, and before pinning the payload fixture,
    seven Windows installed-mode tests failed by design; with Windows rules
    pinned they pass.
- `ruff check backend`: passed. `ruff format --check` passes on the new or fully
  owned files. `test_tool_discovery.py` keeps three previously unformatted
  blocks, outside the changed lines.
- `mypy --config-file backend/pyproject.toml backend/src` (strict, 141 files):
  `discovery.py` has no issues. The only error is that `propka` is not installed
  in the development environment (`__main__.py`), which is not caused by this
  change.

## Not accepted / remaining work

- No real Linux scientific tool was installed or discovered in this unit. Real
  discovery against Codex's conda-forge Linux environment is still to be
  recorded.
- **P2Rank cannot run on Linux yet.** Discovery now returns `prank`, but the
  non-frozen runner in `adapters/tools/pocket_detection.py` always launches
  `cmd /c <prank>`.
- **Process-tree cleanup on Linux:** `execution/subprocess_runner.py` uses
  `taskkill` and, elsewhere, kills only the direct child. P2Rank's Java child
  would survive a timeout. This belongs to the process-tree cancellation unit.
- **Adapter messages:** six adapters still say "on this Windows system": Vina,
  AutoGrid4, AutoDock4, AutoDock-GPU, Meeko ligand preparation and P2Rank.
- **Conda metadata:** discovery reports no version from `conda-meta` package
  records. That would be real evidence for unversioned conda-installed
  binaries; see the lock proposal below.
- **Scope of this evidence:** native workstation acceptance, Linux GPU engines
  and a frozen Linux payload remain later gates.

## Proposed (not applied): P2Rank runner on Linux

In `execute_p2rank`, keep both Windows branches. On non-Windows hosts, launch the
discovered launcher directly as an argument array:
`executable=discovered.path`, with the same `predict … -visualizations 0`
arguments and `JAVA_HOME` set to the discovered home. Make the unavailable
message platform-neutral.

## Proposed interface: Linux environment lock verification

This mirrors `scripts/verify_windows_environment_lock.py` without changing it.
Nothing has been implemented.

- **Files:**
  - `environment/linux-64.conda.lock`: `@EXPLICIT`; HTTPS conda-forge or
    defaults URLs, each with a `#<sha256>` fragment.
  - Optionally `requirements/linux-py312.lock`: `--only-binary=:all:`,
    `--require-hashes`, each pin with `--hash=sha256:`.
  - Neither may contain local or absolute paths.
- **Command:**
  `python scripts/verify_linux_environment_lock.py [--root DIR] [--runtime]`,
  exiting with status 0 or 1, like the Windows verifier.
  - The repository check enforces the format, trusted hosts and SHA-256
    fragments. It also requires the accepted scientific versions shared with
    Windows (python 3.12.13, numpy 2.5.2, scipy 1.18.0, openmm 8.5.2,
    pdbfixer 1.12) and the native tool packages with their exact versions
    (vina 1.2.7, the AutoDock4/AutoGrid4 package, OpenJDK 17–23, P2Rank).
  - `--runtime` requires Linux x86-64, Python 3.12.13 and a Conda prefix. It
    compares `importlib.metadata` versions and `conda-meta/*.json` records
    (name, version, build) with the lock.
- **Discovery link (optional, separate unit):** an optional field on
  `DiscoveredTool`, for example `conda_package="vina-1.2.7-<build>"`. It would
  be filled only when the resolved executable is listed in that record's
  `files`, so the version comes from package metadata and not from a name.
