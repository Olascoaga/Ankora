# Architecture

Ankora uses a thin Tauri v2 Windows shell around a React/TypeScript interface. The interface talks through an explicit typed localhost HTTP boundary to a Python 3.12 scientific backend.

The frontend owns workflow presentation, viewer adaptation, inspectors, result presentation, and provenance visibility. The backend owns scientific domain models, application services, adapters, execution, persistence, and provenance. Rust owns desktop lifecycle and native integration, not scientific logic.

External tools and docking engines are isolated behind adapters. Original files are immutable; derived artifacts record parentage and become stale when upstream decisions change. Structured state will use SQLite while molecular artifacts and raw tool output remain normal project files.

ADR-023 gives that evidence an explicit project identity. A catalog outside
the evidence trees registers each project, preserves the original `default`
tree as a legitimate migrated workspace, and safely rebuilds long-lived
scientific services on project switch. ADR-011 derives a dependency graph from
the immutable records; required-reason stale markers live outside those records
and propagate only to recorded descendants. Alternatives are not invalidated
just because newer evidence exists.

Independent library work uses bounded local parallelism. The default worker budget is `logical processors - 1`, capped by the number of tasks, so scientific throughput uses the machine without starving the Windows UI. Ordering, per-molecule failure isolation, immutable output directories, tool versions, and worker counts remain explicit. Order-dependent or thread-unsafe stages stay serial until they have a safe parallel boundary.

One process-local resource arbiter, defined by ADR-022, is shared by ligand preparation, Vina, AutoGrid, AutoDock4 CPU, and AutoDock-GPU. A job enters scientific execution only after an atomic FIFO claim for its full CPU, GPU, memory, and disk estimate fits. Waiting work remains queued, can be canceled without leaking capacity, and appears with active allocations in the system resource snapshot. Durable work leases under ADR-020 answer who owns recoverable work; resource leases answer whether that owned work may consume this process's machine capacity now. Neither substitutes for the other.

Long-running engine work carries a durable owner lease with a periodic
heartbeat. On backend startup, records left queued, running, or awaiting
cancellation are reconciled to an explicit interrupted failure. Completed
per-molecule results and raw partial outputs are retained. Ankora never resumes
inside an abandoned output directory: a scientist-requested retry creates a
new immutable attempt under ADR-020. The typed startup summary opens in the
shared activity center, and retry requires acknowledgement in both the desktop
and API before the original recorded request is revalidated and dispatched.

The React interface uses a fixed-viewport scientific workbench under ADR-014. Application menus and project context sit above a stateful workflow navigator, central viewer/data plane, contextual decision inspector, status strip, and expandable activity center. The shell owns theme, density, panel resizing/collapse, warnings, provenance, commands, tool readiness, and active-job reporting so milestone screens can focus on scientific decisions. Shared semantic design tokens and accessibility rules are documented in `docs/design/UX_FOUNDATION.md`.

## Local request path

```text
Tauri -> React -> typed fetch client -> 127.0.0.1 FastAPI -> JSON -> visible status
```

The development launcher starts the backend on localhost before Vite. The backend exposes health/system/tool discovery, immutable structure import, read-only receptor inspection, and receptor preparation endpoints.

## M2 receptor path

```text
immutable original
  -> Gemmi inspection report
  -> explicit scientist decisions
  -> create-only selected PDB
  -> optional selective PDBFixer repair
  -> optional PDB2PQR/PROPKA protonation
  -> optional Meeko PDBQT
  -> immutable outputs + hashes + raw logs + provenance
```

The browser never launches scientific executables. FastAPI validates a complete typed decision plan, creates a unique derivative directory, and invokes adapters with argument arrays and `shell=False`. Original and prepared coordinates remain independently addressable so Mol* can display either or overlay both.

Tool discovery does not execute the tools. A requested optional stage fails with a structured diagnostic when its dependency is unavailable. Successful and failed executions preserve the exact command and raw output; successful molecular outputs are hashed and associated with their source artifact.

## M3 ligand-library path

```text
immutable compound or ordered library
  -> exact inspected/resolved chemical states
  -> exact-imported-state policy OR bounded protonation/tautomer candidates
  -> explicit scientist-selected screening microstate per retained parent
  -> read-only descriptors, rules, alerts, and duplicates
  -> explicit immutable selection manifest
  -> bounded per-ligand ETKDG/MMFF preparation
  -> optional Meeko PDBQT
  -> row-isolated outputs + hashes + raw logs + provenance
```

Single-compound and virtual-screening modes share the same scientific contracts but expose different data planes. The screening table never becomes the source of scientific truth: it renders typed backend records, manifest decisions, and immutable derivative evidence.

Screening microstates follow ADR-016. Candidate order is deterministic but
scientifically unranked, one exact state must be selected per retained parent,
and downstream preparation and docking reject state-lineage mismatches. Results
remain parent-level rows because Ankora does not silently choose a best score
across multiple chemical states.
