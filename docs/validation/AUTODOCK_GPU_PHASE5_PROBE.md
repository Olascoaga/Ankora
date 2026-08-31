# AutoDock-GPU — Phase 5 probe (ADR-015 item 5)

Everything below was measured by running the real `AutoDock-GPU.exe` v1.6 on
this machine against real project data. Nothing here is inferred from
documentation.

Date: 2026-08-26. Binary: `<TOOLS_ROOT>\autodock-gpu-1.6\AutoDock-GPU.exe`.

## The hardware question, answered first

Phase 0 confirmed the binary's `--help` probe succeeds but never launched a
docking. It does run here.

| | |
| --- | --- |
| GPU | NVIDIA GeForce RTX 5050 Laptop (4 GB), driver 32.0.16.1088 |
| Secondary | Intel UHD Graphics |
| OpenCL runtime | `<SYSTEM_ROOT>\System32\OpenCL.dll` present |
| Khronos ICD registry key | **absent** under both `HKLM\SOFTWARE\Khronos` and the WOW6432Node path |
| Device AutoDock-GPU selected | `NVIDIA GeForce RTX 5050 Laptop GPU` |
| Kernel build | succeeded, 3 warnings |

The missing ICD registry key did not prevent device discovery. Device
enumeration must therefore be probed by running the tool, never inferred from
the registry.

## What the real `--help` reports

The defaults confirm ADR-015's warning that CPU and GPU are **not the same
search**:

| Flag | Default | Note |
| --- | --- | --- |
| `--heuristics` | `1` (yes) | ligand-based automatic evaluation count |
| `--autostop` | `1` (yes) | converges out early on a 0.15 kcal/mol std-dev tolerance |
| `--lsmet` | `ad` (ADADELTA) | the CPU protocol uses Solis-Wets |
| `--nrun` | `20` | CPU `ga_run` default in Ankora is 10 |
| `--nev` | `2500000` | matches Ankora's CPU default |
| `--dlgoutput` | `1` (yes) | the CPU-format log |
| `--xmloutput` | `1` (yes) | an additional XML |
| `--ffile` | — | takes the AutoGrid `.fld`, so **the same map sets apply** |
| `--import_dpf` | — | upstream documents "only partial support" |

## Measured: same ligand, same map set, same seeds

Map set `ebb2a3b0` (58×54×52 intervals, 12 atom types), ligand
`Compound_252_prepared.pdbqt` (5 types, 7 torsions), seeds (2, 3), 10 runs.

| | wall time | best cluster | clusters | populations |
| --- | --- | --- | --- | --- |
| AutoDock4 CPU, 2.5M evals × 10 | **241.25 s** | −2.87 | 5 | 2, 3, 3, 1, 1 |
| AutoDock-GPU, same protocol | **1.81 s** | −3.21 | 5 | 3, 1, 2, 3, 1 |
| AutoDock-GPU, its own defaults | **0.479 s** | −3.30 | 3 | 2, 7, 1 |

**133× at a matched protocol.** The 503× implied by the default-settings run is
not a like-for-like comparison: autostop halted that search at roughly 841k
evaluations instead of 2.5M.

**The two backends do not agree, and should not be expected to.** At an
identical nominal protocol on identical maps the best cluster differs by
0.34 kcal/mol, with the GPU finding the lower minimum and a different cluster
structure. The scoring function is the same; ADADELTA is a different search.
A GPU result is therefore **not a substitute for a CPU result** and the two
must never be pooled into one ranking.

## Parser compatibility

ADR-015 called the shared `.dlg` format "the decisive detail". It holds:
`parse_autodock4_log` accepts AutoDock-GPU output **unchanged**, returning
clusters, ranking rows and per-run poses.

Anchors, compared against a real 4.2.6 CPU log:

| Anchor | CPU 4.2.6 | AutoDock-GPU 1.6 |
| --- | --- | --- |
| `RANKING` rows | yes | yes, identical 6-column layout |
| `CLUSTERING HISTOGRAM` | yes | yes |
| `DOCKED: ` pose prefix | yes | yes |
| `FINAL DOCKED STATE` | **no** | yes (additive, harmless) |
| `Successful Completion` | yes | **no** |

**One incompatibility.** `log_reports_success()` tests for
`Successful Completion` and returns `False` on a perfectly good GPU run. The
GPU `.dlg` carries no completion phrase at all — it ends at `Run time` /
`Idle time`. The verdict is on **stdout**: `All jobs ran without errors.`
versus `The job was not successful.` A GPU runner must judge success from
stdout plus a complete ranking table, not from a marker in the log.

## Defects this probe surfaced in already-shipped code

1. **Seed floor was wrong.** `AutoDock4DockingParameters` accepted `seed >= 1`
   and the interface offered `min={1}`, but AutoDock4 4.2.6 fatals outright:
   `Random number seed cannot be zero or one, or negative`. A scientist
   choosing seed 1 got a hard tool failure that Ankora's validation allowed
   through. Verified by real runs that 1 fails and 2 is accepted; the floor is
   now the tool's own. Fixed here.

2. **A canceled AutoGrid run leaves orphaned partial maps.** Directory
   `1d3a4580` holds map files truncated at 5.5% of their declared
   `NELEMENTS 158 228 184` — the full-protein run canceled at 21 s during the
   Phase 1 cancellation test. Cancellation correctly refused to write
   `record.json`, so the API never offers it and every one of the seven real
   map sets is complete and exactly the declared size. But the partial files
   are never cleaned up. Not fixed here; tracked separately.

## What this means for the implementation

- The engine is viable on this machine and worth building.
- The parser is reusable; only the success verdict needs its own path.
- Device discovery must run the tool, not read the registry.
- Ankora must record the execution backend and the complete search protocol on
  every result, and must not present CPU and GPU results as interchangeable or
  poolable. `DOCKING_POLICY.md` already forbids merging engines; the same rule
  applies between backends of the same engine.
