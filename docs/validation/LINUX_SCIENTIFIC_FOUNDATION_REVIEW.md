# Linux scientific foundation — coordinator review, 2026-10-28

This bounded ADR-026 unit adds the reproducible scientific environment, native
tool discovery and scientific subprocess lifetime on Linux. It does not close
the full Linux parity, GPU, distribution or native-workstation gates.

## Source and integration

The work starts from published Linux PR head `e705ff6`, avoiding the unrelated
unpublished manual ancestry of the original local bootstrap checkout. Isolated
branches were reviewed and integrated sequentially; no two agents edited one
branch concurrently. The Windows development checkout was preserved.

The integration commits are:

- `dc57ac4`: declare the already-pinned pefile development dependency.
- `a8c5141`: native scientific tool discovery with Windows rules retained.
- `d944030`: explicit LF/CRLF bytes in the synthetic evidence-writer test.
- `d94a939`: Linux environment locks, verifier and tamper tests.
- `6c60ce4`: bounded POSIX process lifetime and cancellation.

The existing PR's Windows CI run failed during collection because pefile was
missing from `backend[dev]`. Its four focused payload-builder tests now pass
locally. A new remote CI success is not claimed; this unit has not been pushed.

## Environment and native identities

The new environment verifies 45 Conda artifacts and 75 pip pins against both
committed locks and installed metadata. Common scientific versions match the
accepted Windows versions. The unchanged Windows lock verifier also passes.
See [the environment record](LINUX_SCIENTIFIC_RUNTIME.md) for reconstruction,
tamper tests and the disclosed Conda/pip `packaging` overlay.

Native executable identities were read from the actual installed files:

| Tool | Observed version | SHA-256 |
| --- | --- | --- |
| Vina | 1.2.7 | `f31f774f723bba7bbe6e9d1c47577020eea9a8da16424284c043d22593570644` |
| AutoGrid4 | 4.2.6 | `91621b89d13410efde31aed2a0934b15837172ef167d783bec0b3a94d384dc72` |
| AutoDock4 CPU | 4.2.6 | `15ac656b45db209655b1aae908ed1e06e743c7be4abb55b039f0bf38a6fd9fc9` |

All three are x86-64 ELF. Vina came from the upstream v1.2.7 Linux release;
the release API supplied no independent asset digest, so its SHA above is the
locally observed identity, not an upstream-published checksum. AutoGrid4 and
AutoDock4 are Ubuntu package revision 4.2.6-9. Java is OpenJDK
21.0.12.1+1-1~24.04.4. Native engine packages and Java are outside the Python
locks and require separate distribution/license closure before a Linux bundle.

## Observed verification

- Native discovery: 61 tests passed on Linux. No scientific executable is
  launched during discovery; ELF, script permissions and metadata are read.
- Locks plus synthetic raw-output identity: 49 tests passed on Linux.
- Native Windows discovery/locks/evidence tests: 76 passed, 34 POSIX skips.
  The first Windows attempt hit an existing temporary-directory permission
  error; a new workspace-local temporary directory passed without code changes.
- Final process tests: 20 passed and 2 Windows skips on Linux; 7 passed and
  15 POSIX skips on Windows. Both actual host branches were exercised.
- Ruff passed; strict backend mypy passed on 141 source files with the full
  scientific environment, and the two final execution modules passed separately.
- Both environment verifiers, public-path checks and the frozen public
  validation-status check passed. Private memory, raw logs, credentials and
  machine-specific paths are excluded from tracked evidence.

### Actual native smoke, with final integrated process runner

The canonical `python scripts/run_native_tool_smoke.py` entry point produced
**8/10 passed; overall status failed**, explicitly preserving the two pending
adapters. The passed checks were scientific imports, PDBFixer explicit repair,
PDB2PQR/PROPKA, Meeko receptor, Meeko ligand (existing ETKDGv3/MMFF94s fixture),
and version/compiled-limit probes of Vina, AutoGrid4 and AutoDock4 CPU.

Receptor transformation uses the existing upstream PDBFixer 1BHL fixture;
repair and ligand fixtures are explicitly synthetic. No user receptor or
historical campaign was modified. Tool commands, versions, exact output streams,
fixture/output hashes and failures are retained in ignored local evidence.
OpenMM/BLAS execution was limited to two threads for this bounded check.

The final smoke manifest SHA-256 is
`80be9e3e1527fb9c29d31741204021b191e624abf1e809c95d4ef843b2c33dd8`.

- **P2Rank pending:** the smoke still requests Windows `java.exe`, and the
  product adapter uses `cmd /c`. Native discovery/Java resolution is implemented;
  native prediction execution and its accepted runtime are a separate next unit.
- **AutoDock-GPU pending:** no accepted Linux GPU binary/runtime is installed.
  The discovery path deliberately reports it unavailable. GNINA is deferred.
- The direct `-m ankora_backend.validation.native_tool_smoke` invocation also
  exposes an existing `__main__` worker-module issue. The canonical script imports
  the module correctly. Preserve that failed evidence; do not call the direct
  module invocation accepted.

No docking energy, redocking accuracy or Windows/Linux numerical parity is
certified by version probes or preparation smoke.

## Full backend suite and outstanding portability

Before the final runner/lock integration, the Linux suite reported
949 passed and 13 failed. Final integrated suite: **1012 passed, 10 failed,
2 skipped**, in 151.88 seconds (plus one dependency deprecation warning).
The complete output and JUnit are retained locally; the full suite is not green.

The outstanding groups are:

1. Two compact Windows installer tests use Windows-only payload path rules.
   Do not port the Windows packager by weakening those checks.
2. Six historical metric/sensitivity checks require exact reproduction of a
   frozen Windows manifest. A separate read-only comparison found six BEDROC
   floating-point differences, maximum absolute delta `8.326672684688674e-17`,
   and consequently a different derived manifest hash. Other compared fields
   were identical. This is consistent with platform numerical differences;
   it is not proof of their low-level cause. No frozen number, threshold or hash
   was changed and no docking campaign was rerun. Define and review the Linux
   numerical verification contract separately while preserving original bytes.
3. The web production dependency legal inventory differs from package-lock.
   Refresh and review provenance before distribution, not by skipping inventory
   validation.
4. A manual test expects the removed phrase `Current beta UI limitation`.
   Reconcile its acceptance assertions with the current documented redocking UI.

## Next bounded work

Implement and test native P2Rank execution, resolve the recorded portability
failures without changing historical evidence, then execute a preregistered
bounded CPU docking/redocking campaign through the real application services.
Only after that proceed to independent GPU acceptance, a complete Linux bundle
and final native-workstation validation. Existing Windows installers, UI and
scientific projects remain unchanged by this unit.

## Follow-up verification — Linux P2Rank and Windows CI

Native P2Rank execution and Java probing were added and tested, followed by a
separate correction to preserve each executable identity and partial timeout
evidence. See [the native P2Rank record](LINUX_P2RANK_EXECUTION.md) and
[the smoke identity record](P2RANK_SMOKE_IDENTITY.md). A real P2Rank prediction
on the fixed upstream receptor and the existing preparation checks passed;
the full scientific smoke remains **9/10 and overall failed**, with Linux
AutoDock-GPU still unavailable.

The earlier web legal-inventory failure occurred before the new worktree had
its web and Rust prerequisites. After `npm ci` and with `cargo` available, the
unchanged static inventory check passed with 206 matching web identities. The
Windows installer path tests and outdated guide assertion were reconciled and
exercised on native Windows. A separate isolated Windows wheel environment
matched 80 locked distributions and passed the 11 focused CI failure-case
tests; a hosted CI run of the new workflow remains required.

After these changes, the Linux backend suite reported **1032 passed, 6 failed,
4 skipped**. The six failures all concern strict bitwise comparison of the
historical metrics/sensitivity records described above. The four skips are
Windows-only path/process tests that passed separately on Windows. Frozen
artifacts and their existing strict verification were not changed.
