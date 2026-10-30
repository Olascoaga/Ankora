# Linux Portability Reconciliation — 2026-10-28

This bounded unit reconciles the two Windows-path installer compaction tests and
the user-guide redocking assertion on `codex/linux-portability` (from `a4dc44f`),
and records the factual status of the web legal inventory check and the separate
open numerical verification gate from `LINUX_SCIENTIFIC_FOUNDATION_REVIEW.md`.

## 1. Compact Windows installer tests (`backend/tests/test_compact_windows_installer.py`)

- `scripts/compact_windows_installer.py` is unchanged. `compact_script` and
  `model_script` are pure string transformations and run cross-platform.
- Only `test_output_is_create_only_and_original_is_preserved` and
  `test_compiler_failure_never_touches_protected_original` require real Windows
  drive-letter paths: both call `build()` expecting execution to pass input
  validation (`r"^[A-Za-z]:[\\/]"` and `Path(value).is_file()`) and reach
  `output.mkdir(parents=True, exist_ok=False)` or `subprocess.run(...)`. They
  are gated with `sys.platform != "win32"`.
- Added cross-platform `test_build_rejects_non_windows_payload_paths_without_touching_original`
  verifying `build()` rejects non-Windows payload paths with
  `ValueError("No generated Windows payload inputs found")` without creating
  `output` or modifying the preserved original file.

## 2. User guide redocking assertion (`backend/tests/test_user_guide_pdf.py`)

- `docs/USER_GUIDE.md` is unchanged. `test_guide_distinguishes_tutorial_and_validation_limitations`
  replaces the retired `"Current beta UI limitation"` check with the documented
  §6.1 manual redocking text (`"Calculate RMSD and save validation"`,
  `"symmetry-aware heavy-atom RMSD, computed in place"`,
  `"Do not substitute Vina's inter-mode RMSD."`, and
  `"contains a Vina reference-RMSD verdict; a docking score cannot supply one."`),
  preserving existing engine-comparison, contact, and mass assertions.

## 3. Web legal inventory verification (verified by Codex)

- Earlier failures were environment prerequisites: the initial run had no
  populated `node_modules`, and the second attempt lacked `cargo` on `PATH`.
- Executed by Codex in the `linux-science` worktree with `npm ci` completed and
  `cargo` on `PATH`: `python scripts/generate_third_party_notices.py --static-check`
  **passed** (`206` recorded and `206` installed web identities, `0` missing,
  `0` obsolete; `node_components` already skips `entry.get("link") is True` and
  `name.startswith("@ankora/")`). No legal inventory or generator changes are needed.

## 4. Open numerical verification gate (separate from this unit)

- Six tests remain open on Linux:
  `test_screening_benchmark_protocol.py::test_primary_vina_metrics_reproduce_from_the_closed_campaign`
  and five tests in `test_screening_benchmark_sensitivity_plan.py` (deterministic/
  loss-preserving reproduction, post-freeze factor tampering rejection, recorded
  plan check, and two parametrized changed-source checks).
- A single read-only comparison by Codex against the saved Vina manifest found
  six BEDROC float differences (max absolute difference `8.326672684688674e-17`)
  and a changed derived hash, with all other compared fields equal. Frozen
  manifests and thresholds are unmodified; numerical portability remains open.

## 5. Focused verification status

- Pending Codex execution: `pytest` and `ruff` on
  `backend/tests/test_compact_windows_installer.py` and `backend/tests/test_user_guide_pdf.py`.

## Coordinator verification

- Ubuntu 24.04 WSL2, locked Python 3.12.13: **25 passed, 2 skipped** in
  the two focused test files. The two skips are the Windows-drive tests.
- Windows-native Python: **27 passed** in the same two files; the drive-path
  and protected-original cases actually ran.
- Ruff passed on both changed test files. The package-lock legal inventory
  check passed after the required npm install and Rust toolchain were present.
- Raw outputs are retained in ignored local evidence. No installer, guide,
  legal payload, frozen metric or scientific output was modified.
