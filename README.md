# Ankora

Ankora is a native Windows visual workbench for performing molecular docking step by step. It is designed to keep scientists in control of every inspection, preparation, execution, and review decision.

This repository contains the implemented and accepted M1-M9 functional workspaces. Ankora preserves crystallographic compounds and local SDF/SD-style MOL/SMILES libraries, previews Lipinski/Veber/Ghose/Muegge/QED properties plus PAINS/Brenk and duplicate findings, requires an immutable filtered-selection manifest before batch 3D preparation, and displays one traceable row per molecule with SMILES, properties, rules, alerts, MMFF energy, and status. It resolves disconnected components and undefined tetrahedral stereochemistry only through visible choices, offers explicit physiological-pH protonation-state enumeration, supports bounded scientist-selected protonation/tautomer microstates for screening, creates explicitly confirmed MMFF-minimized independent ETKDGv3 conformers, prepares converged conformers as Meeko ligand PDBQT, and defines an editable immutable docking box.

M5 runs one prepared ligand or an applied screening library through native AutoDock Vina 1.2.7 or the AutoDock4 scoring family. AutoGrid4 4.2.6 creates immutable reusable map sets; AutoDock4 4.2.6 provides the reproducible CPU reference path; AutoDock-GPU 1.6 provides optional accelerated execution with its distinct search protocol and an explicit non-bitwise-reproducibility warning. Screening campaigns restore after refresh, report exact molecule-level progress, retain failures, expose every pose or AutoDock cluster/run, and support side-by-side Vina/AutoDock4 ranking comparison without inventing a combined score. M6 adds durable project-level Results, M7 records redocking validation, M8 exports reproducible campaign bundles with explicit campaign, input, and export-event identity, and M9 analyzes an exact preserved pose with structured ProLIF contacts, an Ankora-rendered 2D diagram, and Mol* residue focus.

Independent library operations use bounded multicore execution by default: Ankora uses the available logical processors minus one, capped by the number of molecules, while preserving source order, per-molecule artifacts, isolated errors, and recorded worker counts. For virtual-screening docking, one explicit total CPU budget is divided between concurrent Vina processes so outer scheduling never silently multiplies Vina's inner `--cpu` allocation. A single application-wide resource arbiter admits ligand preparation, Vina, AutoGrid, AutoDock4 CPU, and AutoDock-GPU work only when their complete CPU, GPU, memory, and disk reservation fits; queued and active allocations are visible through the system resource status.

The desktop interface is a fixed scientific workbench rather than a scrolling form: explicit wide, medium, and small shell states respond to usable CSS pixels (including Windows display scaling), workflow and inspector panels are resizable/collapsible, receptor issues and screening compounds use viewer-linked data tables, single-ligand and virtual-screening modes are explicit, and background work, warnings, provenance, commands, and tool readiness live in a shared activity center. Long scientific documents such as pose-interaction review have one obvious workspace scrollbar; dense tables retain only their bounded data-region scrolling. If the backend or machine stops during engine work, the next startup preserves and exposes the interrupted attempt; an explicitly confirmed retry starts under a new immutable identity rather than appending to partial evidence. Dark, light, and Windows-following themes plus comfortable/compact density are available from the View menu. The implementation rules are recorded in [docs/design/UX_FOUNDATION.md](docs/design/UX_FOUNDATION.md).

The Project Workspace creates and switches independent scientific workspaces
without rewriting the migrated `default` project. It also exposes the
record-derived dependency graph: scientists may mark an input stale with an
explicit reason, after which Ankora marks only its downstream dependents stale
while retaining every original record and alternative branch for inspection.

## Prerequisites

- Windows 11 x64
- Node.js 22+ and npm
- Python 3.12+
- RDKit 2025.9+ (installed by the backend package)
- AutoDock Vina 1.2.7 for native docking (official Windows executable)
- AutoGrid4 + AutoDock4 4.2.6 for immutable maps and the reproducible CPU backend
- AutoDock-GPU 1.6 as optional accelerated execution on a compatible OpenCL device
- Rust stable and the Tauri v2 Windows prerequisites

## Setup

```powershell
.\scripts\bootstrap.ps1
```

### Anaconda / Conda development environment

Conda is supported as an optional development environment. Keep Ankora out of the Conda `base` environment:

```powershell
conda env create -f environment.yml
conda activate ankora-dev
.\scripts\bootstrap.ps1 -PythonEnvironment Conda
```

For M2 repair, protonation, and receptor PDBQT generation, create/update the Conda environment from `environment.yml`, activate it, and install the optional receptor tools:

```powershell
conda env update -f environment.yml --prune
conda activate ankora-dev
.\scripts\bootstrap.ps1 -PythonEnvironment Conda -ReceptorTools
```

The basic M2 inspection and explicit structural-selection derivative work without these optional receptor tools. PDBFixer is supplied through conda-forge; PDB2PQR/PROPKA are installed from the backend's versioned `receptor` extra. Meeko and ProLIF are core backend dependencies because ligand/receptor PDBQT handling and exact-pose interaction analysis depend on them.

`scripts/dev.ps1` automatically prefers an active Conda environment and then a locally installed environment named `ankora-dev`; it also adds that environment's executable directories for M2 tool discovery. Set `ANKORA_PYTHON_PATH` only when an explicit interpreter override is needed. `scripts/test.ps1` uses an active Conda environment or the normal `.venv` verification fallback. Future packaged releases will not require Anaconda.

Ankora reports the Python environment used by its active backend in **Scientific tools**. Use **Rescan tools** after installing a console tool into that same environment. The development launcher now stops with a clear error if an older Ankora backend already owns port 8765; close that older development session instead of silently reusing the wrong Python environment.

If `conda` is unavailable in PowerShell after installation, open Anaconda Prompt or run `conda init powershell` from Anaconda Prompt and restart PowerShell.

### AutoDock Vina

Ankora supports the official AutoDock Vina 1.2.7 Windows executable. Set `ANKORA_VINA_PATH` to the executable or its containing directory, add `vina.exe` to `PATH`, or place the official versioned executable below a narrowly named portable directory such as `%USERPROFILE%\tools\autodock-vina-1.2.7\vina_1.2.7_win.exe`. Ankora verifies the executable's reported version before every docking job; discovery alone does not authorize or launch a calculation.

### AutoDock4 family

ADR-015 accepts AutoDock4 as Ankora's second native scoring family and AutoDock-GPU as an optional execution backend for that same scoring family. The backend discovers `autogrid4.exe`, `autodock4.exe`, and `AutoDock-GPU.exe` independently through `ANKORA_AUTOGRID4_PATH`, `ANKORA_AUTODOCK4_PATH`, and `ANKORA_AUTODOCK_GPU_PATH`, `PATH`, the active Python runtime, or narrowly named portable folders below `%USERPROFILE%\tools`. Discovery records architecture and SHA-256 without launching a calculation; every execution performs its own version/device probe.

Official AutoGrid4/AutoDock4 4.2.6 CPU and AutoDock-GPU 1.6 Windows binaries are verified on the development machine. Production integration includes immutable map persistence and reuse, cancellable single-ligand and library CPU jobs, cluster-native DLG review, one-process GPU `--filelist` campaigns, exact progress and preserved raw evidence. See `docs/validation/AUTODOCK4_PHASE0_WINDOWS.md`, `docs/validation/AUTODOCK4_PHASE1_MAPS.md`, and `docs/validation/AUTODOCK_CPU_VS_GPU_BENCHMARK.md`. Redistribution of third-party binaries remains subject to a separate license/package review.

## Development

Start the desktop application and local backend together:

```powershell
conda activate ankora-dev  # only when using Conda
npm run tauri:dev
```

For browser-only interface development, run the backend and web workspace in separate terminals:

```powershell
.\.venv\Scripts\python.exe -m ankora_backend
npm run dev
```

If PowerShell blocks `npm.ps1`, use `npm.cmd` for direct commands (for example, `npm.cmd run tauri:dev`). Ankora's PowerShell scripts already select `npm.cmd` explicitly and do not require changing the machine execution policy.

## Verification

```powershell
.\scripts\test.ps1
```

The verification script runs the Python and frontend checks plus Rust formatting, Clippy, native tests, and a release build of the Tauri application. Windows CI runs the same native coverage.

The backend binds to `127.0.0.1:8765`. Imported originals, receptor/ligand derivatives, binding sites, and docking results are preserved under `.ankora-data` during development. Ankora performs no telemetry or cloud upload. Receptor/ligand transformations and docking execution occur only after every applicable decision is explicit.

See [CODEX_BOOTSTRAP.md](CODEX_BOOTSTRAP.md) for the project contract and [AGENTS.md](AGENTS.md) for the implementation policy. Agent continuity memory is intentionally local and is not published.
