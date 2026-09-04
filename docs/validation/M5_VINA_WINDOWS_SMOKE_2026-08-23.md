# M5 AutoDock Vina 1.2.7 Windows smoke — 2026-08-23

## Scope

This validates the first M5 single-ligand execution slice and first real applied-library campaign against the official native Windows AutoDock Vina 1.2.7 executable and real Ankora artifacts, plus scheduler/recovery contracts with synthetic labeled fixtures. It is implementation evidence, not biological validation and not a claim of experimental affinity.

## Installed executable

- Source: official `ccsb-scripps/AutoDock-Vina` GitHub release `v1.2.7`
- Asset: `vina_1.2.7_win.exe`
- Installed path: `<TOOLS_ROOT>\autodock-vina-1.2.7\vina_1.2.7_win.exe`
- Size: 1,233,920 bytes
- Locally computed SHA-256: `e0c4b2715e0c1a74f6e92d0f3be0328ac97542eafbc111e6b1efad897a73cce5`
- Runtime probe: `AutoDock Vina v1.2.7`
- Upstream checksum limitation: GitHub's release-asset metadata returned no digest for this asset, so the SHA-256 above is a local post-download identity, not represented as a publisher-signed checksum.

## Exact Ankora inputs

- Job: `9d1f9e03-f103-4659-b8d8-0a848c175664`
- Receptor: `01beb9cf-1079-4c03-9ee7-2f058a8bbb5d`
- Receptor PDBQT artifact: `af565f4b-665f-4005-91ac-1dfefa9fbbff`
- Receptor SHA-256: `bb85972139b2dbe53c404ac91c870e53d4850ed19f09c7c4ca36aec1e6a8f55a`
- Binding site: `14212974-2b80-42db-ab8f-dc5cb1fda595` (P2Rank-derived)
- Box center: `(42.6396, -14.9532, 5.5543)` Å
- Box size: `(34.435, 27.212, 34.004)` Å
- Ligand: `2708d2f6-6570-4b98-8aa1-03aa96a3af40` (`RV2`)
- Ligand preparation: `dbfde6e4-6c68-478d-b49b-f8e074c5ee68`
- Ligand PDBQT SHA-256: `dca92a95a6fae0ba945a7472e258df6d256c7a602a5e3da2d10eabba9111ff14`

## Parameters and outcome

- CPU threads: 2
- Seed: 20260823
- Exhaustiveness: 1 (deliberately low smoke-test value, not a production protocol)
- Maximum modes: 3
- Minimum RMSD: 1.0 Å
- Energy range: 3.0 kcal/mol
- Timeout: 30 minutes
- Exit code: 0
- Wall time observed by the service: approximately 5.5 seconds

Preserved pose results:

| Mode | Vina score (kcal/mol) | RMSD lower bound (Å) | RMSD upper bound (Å) | Pose SHA-256 |
|---:|---:|---:|---:|---|
| 1 | -8.093 | 0.000 | 0.000 | `84fda0c550c79bfefc4d49602c1515a82a89756bd4d694cfb8f365b09ddbb690` |
| 2 | -7.382 | 3.296 | 6.666 | `2f4abd776707c684c3c34c6d4c25d3045aa68cc0fe717707d21bd3ac341bb16a` |
| 3 | -7.331 | 4.756 | 7.824 | `1b9ce6e5328bf38e365b54fa8e1eb5efe46d66ff9e139b58d99b84d4ce2b2dfe` |

Vina emitted two raw warnings, preserved without alteration in `stderr`: the search-space volume exceeded 27,000 Å³, and low exhaustiveness may prevent use of every CPU. These are expected consequences of the selected smoke-test box/parameters and are not suppressed.

As of 2026-09-04, that observed 27,000 Å³ boundary is also a first-class
product guardrail. New single-ligand and library records above the boundary
carry structured `DOCKING_SEARCH_SPACE_LARGE` evidence with exact volume,
ratio, binding-site source, and selected exhaustiveness; completion provenance
retains the same warning. The setup interface displays volume-aware guidance
before execution and explicitly states that Ankora has not changed the selected
value. This increment did not rerun Vina or reinterpret the smoke-test scores.

## Applied-library scheduler verification

- The batch request identifies one exact library and applied filter-run artifact; the manifest SHA-256 and every available ligand PDBQT SHA-256 are recomputed before execution.
- One bounded worker pool executes independent Vina processes. A total budget of 6 CPU threads with 2 concurrent ligands was verified to emit two simultaneous Vina calls with 3 `--cpu` threads each.
- Synthetic labeled coverage verifies two-ligand concurrent fan-out, deterministic source order, exact pose persistence/content access, isolated Vina failure, batch-wide cancellation, and explicit accounting for an unprepared manifest UUID while its prepared neighbor still completes.
- Durable ligand preparation rollups now retain conformer identity and MMFF final energy after Meeko PDBQT generation; historical rollups with missing energy are recovered from the immutable conformer referenced by the PDBQT record.
- The latest applied filter-run endpoint and frontend hydration path reconstruct screening context from durable artifacts when transient component state is absent; API coverage verifies the static `latest` route is not shadowed by the filter-run UUID route.
- The scientist subsequently launched real batch `06f9a26e-a722-453a-b99a-042674abf977`: library `e128e700-1249-461a-9b12-c061d3706601`, applied filter run `57fd00c7-5c0f-4550-8be5-46fd9810b607`, receptor `01beb9cf-1079-4c03-9ee7-2f058a8bbb5d`, and binding site `cfb3d5cd-8c8a-456e-9607-b7abe57fcfb5`.
- Parameters were 15 total CPU threads, 4 concurrent ligands, 3 threads per Vina process, seed 20260823, exhaustiveness 8, 9 modes, minimum RMSD 1 Å, energy range 3 kcal/mol, and 360-minute per-ligand timeout. Execution ran from 03:34:20Z to 03:48:08Z (about 13 minutes 48 seconds).
- All 283 selected UUIDs reached a terminal retained row: 281 succeeded, Compound 143 retained expected preflight `DOCKING_LIGAND_NOT_PREPARED`, and Compound 250 retained `VINA_EXECUTION_FAILED` with exit code 1. These results require scientist review and are not interpreted here as biological hits.
- A second record created six seconds later (`244924c1-6a1e-4d28-a347-2e3e1a1a7a9b`) was an accidental duplicate that waited behind the real run, never started, and was canceled. Regression coverage now proves exact duplicate starts are idempotent and durable restoration prefers the useful completed campaign over a later zero-result cancellation. Both records remain preserved.
- Live monitoring now uses revisioned incremental updates: exact counters/status are returned every refresh, but only molecule rows changed since the caller's revision are transferred. The UI exposes percentage, completed/running/queued/failed counts and recent completions while retaining the complete source-ordered results/evidence table.

## Automated and visual verification

- Backend: 136 pytest tests, Ruff, and strict mypy across 55 source files.
- Frontend: 51 Vitest tests across 10 files, strict TypeScript, and production Vite build.
- Native: rustfmt, strict Clippy, Rust unit/doc tests, and optimized Windows Tauri build.
- Browser visual check: the M5 inspector was exercised at the normal workbench width against the real 7AQF receptor and finalized full-protein box. Parameter cells were changed to label-above-input after the initial inspection exposed a compressed seed field. The corrected upper and lower inspector sections had no text/input collisions and browser error/warning logs were empty.
- The scientist confirmed that the restarted native path detects and runs Vina. After final validation, the live development backend was restarted again and verified healthy with Vina 1.2.7 plus the new latest-campaign and incremental-progress routes; the exact latest query resolves completed batch `06f9a26e-a722-453a-b99a-042674abf977` as 283 completed / 281 succeeded / 2 failed without launching another calculation.
