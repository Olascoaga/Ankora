# P2Rank Smoke Executable Identity Fix — 2026-10-28

- **Branch:** `codex/linux-p2rank-identity` (base `583524d`)
- **Scope:** `backend/src/ankora_backend/validation/native_tool_smoke.py`,
  `backend/tests/test_native_tool_smoke.py`, `docs/validation/P2RANK_SMOKE_IDENTITY.md`

## 1. Defect Observed in Real Linux Smoke

During the real Linux native-tool smoke run, P2Rank pocket prediction succeeded
(`9/10` adapters passed; overall matrix status `failed` as expected with
unavailable AutoDock-GPU), but `results[p2rank].executable_sha256` recorded the
Java binary digest (`635b...`) instead of the native P2Rank launcher `prank`
(`ad7b...`; main jar digest `4d73...`).

Cause: `EvidenceWriter.execution` sets `result.executable_sha256` only when it
is `None`. Because `run_p2rank_smoke` recorded the `java -version` probe first
(`sequence=1`), `result.executable_sha256` was already populated with the Java
executable hash before the `execute_p2rank` execution (`sequence=2`) was
recorded.

## 2. Bounded Implementation

- **Unchanged Successful `EvidenceWriter.execution` & `ToolExecution` Contract:**
  `ToolExecution.exit_code` remains `int`, and all existing successful adapter
  outputs, create-only filenames, stream hashes, and `cmd /c` (`command[2]`)
  detection are unchanged.
- **Immediate Recording with Separate Java & P2Rank Helpers (`native_tool_smoke.py`):**
  1. `record_p2rank_java_probe` runs immediately after `java -version` returns
     and **before** `_require_success(java_execution)`: it records `sequence=1`,
     merges `java_executable_sha256` and `java_version_output` into
     `result.details` without discarding prior keys, and resets
     `result.executable_sha256 = None`.
  2. `record_p2rank_execution` runs immediately after `execute_p2rank` returns
     and **before** `_require_success(execution)`: it records `sequence=2` and
     `result.version = version`, populating top-level `executable_sha256` from
     the actual P2Rank command (`prank` on Linux, `prank.bat` via `cmd /c`
     `command[2]` on Windows development, or `java.exe` on frozen Windows).
- **Additive Nullable `ExecutionEvidence.exit_code` for Timeout Failures:**
  `run_tool` raises `SCIENTIFIC_TOOL_TIMEOUT` with `details` containing
  `command`, `timeout_seconds`, `stdout`, and `stderr`, without an `exit_code`.
  `_record_domain_failure` now records structured domain failures when `command`,
  `stdout`, and `stderr` are present and `exit_code` is either an `int` or
  `None` (using internal `_PartialExecution` with `ExecutionEvidence.exit_code = None`,
  serialized as JSON `null` to represent an explicitly unknown exit status
  without fabricating `-1` or `0`). Launch failures without streams fabricate no
  output.
- Main P2Rank jar hash discovery in arbitrary developer runtimes is not claimed
  here; complete bundle payload provenance is handled separately.

## 3. Synthetic Unit Tests & Verification Status

- `test_p2rank_smoke_records_actual_launcher_hash_and_separate_java_hash`:
  verifies direct launcher and `cmd /c` wrapper identity separation and exact
  command/stream hashes using two distinct synthetic executable files.
- `test_p2rank_smoke_nonzero_java_exit_preserves_java_evidence_without_setting_adapter_hash`
  and `test_p2rank_smoke_failed_p2rank_paths_retain_java_and_adapter_evidence`:
  verify via `_run_adapter` and `_run_p2rank_smoke` that nonzero Java exits,
  launch errors without streams, real-shape timeout errors (`exit_code` absent ->
  JSON `null` with partial streams and P2Rank launcher hash recorded), domain
  errors with integer `exit_code`, and nonzero P2Rank exits all retain Java
  output streams, command arrays, and `details.java_executable_sha256`.
- **Verification Status:** Synthetic unit tests, Ruff, and mypy are **pending
  Codex execution**. The original `9/10` failed-overall run with the incorrect
  hash is retained as immutable create-only evidence; Codex will run a separate
  create-only smoke execution to verify the live executable identity.

## Coordinator checks

- Ubuntu 24.04 WSL2: **21 passed** across the smoke and P2Rank adapter tests.
- Native Windows: **29 passed** across smoke, adapter and bundled-tool tests.
- Ruff passed on the changed module and tests; strict mypy passed on the
  changed module. The real P2Rank rerun is recorded separately after integration.
- A timeout without a reported process exit code stores `null`, rather than a
  guessed code; the recorded command and partial streams remain available.
