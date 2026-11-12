# Architecture

Ankora uses a thin Tauri v2 desktop shell (`WebView2` on Windows 11 x64; `WebKitGTK 4.1` on Linux x86\_64 under `ADR-026`) around a React/TypeScript interface. The interface communicates exclusively through an explicit typed `127.0.0.1` HTTP boundary with a Python 3.12 scientific backend.

The frontend owns workflow presentation, Mol\* viewer adaptation, contextual inspectors, result presentation, and provenance visibility. The backend owns scientific domain models, application services, tool adapters, subprocess execution, persistence, and provenance. Rust owns desktop lifecycle, loopback backend supervision (including monotonic `/proc/<pid>/stat` parent-watchdog termination on POSIX), and native file dialogs—never scientific logic.

External tools and docking engines are isolated behind versioned backend adapters. Original imported files remain immutable; derived artifacts record parentage and become stale when upstream decisions change. Incremental campaign progress uses per-campaign SQLite sidecars (`ADR-021`) while molecular artifacts, `record.json` terminal snapshots, and raw tool outputs remain inspectable project files.

`ADR-023` gives that evidence an explicit project identity. A catalog outside the evidence trees registers each project, preserves the original `default` tree as a migrated workspace, and safely rebuilds long-lived scientific services on project switch. `ADR-011` derives a dependency graph from the immutable records; required-reason stale markers live outside those records and propagate only to recorded descendants. Alternatives are not invalidated merely because newer evidence exists.

Independent library work uses bounded local parallelism. The default worker budget is `logical processors - 1`, capped by the number of tasks, so scientific throughput uses the workstation without starving the desktop UI. Ordering, per-molecule failure isolation, immutable output directories, tool versions, and worker counts remain explicit. Order-dependent or single-GPU sequential stages (such as `gnina_screening` with `worker_count = 1`) stay explicitly serial.

One process-local `ResourceArbiter` (`ADR-022`, extended with VRAM capacity tracking in `ADR-028`) is shared across ligand preparation, AutoDock Vina, AutoGrid4, AutoDock4 CPU, AutoDock-GPU, and Linux GNINA. A job enters scientific execution only after an atomic FIFO claim for its full CPU thread, GPU slot, host RAM, device VRAM (`gpu_memory_bytes` on single-GPU NVIDIA CUDA hosts), and disk budget fits. Waiting work remains queued, can be canceled without leaking capacity, and appears with active allocations in the system resource snapshot. Durable work leases (`ADR-020`) answer who owns recoverable work on disk; resource leases answer whether that owned work may consume machine capacity in this process now. Neither substitutes for the other.

Long-running engine work carries a durable owner lease with a periodic heartbeat. On backend startup, records left queued, running, or awaiting cancellation are reconciled to an explicit interrupted failure while retaining completed per-molecule results and raw partial outputs. Ankora never resumes inside an abandoned output directory: a scientist-requested retry creates a new immutable attempt (`ADR-020`) after acknowledgement in both desktop and API.

## Packaged toolchains and subprocess linker isolation

In packaged distributions (`ADR-024` on Windows; `ADR-029` on Linux), core scientific executables (`AutoDock Vina 1.2.7`, `AutoGrid4/AutoDock4 4.2.6`, `AutoDock-GPU 1.6`, `Eclipse Temurin OpenJDK 21`, and `P2Rank 2.5.1`) ship inside the verified application bundle and never fall back to unverified developer `PATH` entries.

On Linux (`ADR-029`), the optional `2.55 GiB` `GNINA 1.3.3` + CUDA `12.8` + cuDNN `9.25` runtime pack is imported via a zero-`sudo` 1-click GUI file selection (`POST /api/v1/tools/gnina-pack/import`), SHA-256-verified against compiled-in locks, and published atomically under `<app_local_data_dir>/toolchains/gnina-1.3.3-cuda12/` so user-installed packs survive `.deb` application upgrades. At execution time, Ankora restores `LD_LIBRARY_PATH_ORIG` (stripping PyInstaller's `_internal/` directory) and injects the pack's private `lib/` directory into `LD_LIBRARY_PATH` **exclusively** for spawned `gnina` child processes, preventing library collisions with `OpenMM`, `AutoDock-GPU`, or `WebKitGTK` and never bundling host kernel-driver libraries (`libcuda.so*`, `libnvidia-ml.so*`).

## Workbench interface and local request path

The React interface uses a fixed-viewport scientific workbench (`ADR-014`). Application menus and project context sit above a stateful workflow navigator, central viewer/data plane, contextual decision inspector, status strip, and expandable activity center. Shared semantic design tokens and accessibility rules are documented in [`docs/design/UX_FOUNDATION.md`](../design/UX_FOUNDATION.md), and the live 5-check *Anchoring* startup verification screen is documented in [`docs/design/STARTUP_SCREEN.md`](../design/STARTUP_SCREEN.md).

```text
Tauri (WebView2 / WebKitGTK) -> React -> typed fetch client -> 127.0.0.1 FastAPI -> JSON -> visible status
```

## M2 receptor path

```text
immutable original
  -> Gemmi inspection report
  -> explicit scientist decisions
  -> create-only selected PDB
  -> optional selective PDBFixer repair (topology_guard_v3)
  -> optional PDB2PQR/PROPKA protonation
  -> optional Meeko PDBQT
  -> immutable outputs + hashes + raw logs + provenance
```

The browser never launches scientific executables. FastAPI validates a complete typed decision plan, creates a unique derivative directory, and invokes adapters with argument arrays and `shell=False`. Original and prepared coordinates remain independently addressable so Mol\* can display either or overlay both.

## M3 ligand-library path

```text
immutable compound or ordered library
  -> exact inspected/resolved chemical states
  -> exact-imported-state policy OR bounded protonation/tautomer candidates
  -> explicit scientist-selected screening microstate per retained parent (ADR-016)
  -> read-only descriptors, rules, alerts, and duplicates
  -> explicit immutable selection manifest
  -> bounded per-ligand ETKDGv3/MMFF94s preparation
  -> optional Meeko PDBQT
  -> row-isolated outputs + hashes + raw logs + provenance
```

Single-compound and virtual-screening modes share the same scientific contracts while exposing dedicated data planes. Candidate microstates follow `ADR-016`: candidate order is deterministic yet scientifically unranked, one exact state must be chosen per retained parent, and downstream preparation and docking reject state-lineage mismatches.
