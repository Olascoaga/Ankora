# ADR-013: Bounded local parallelism

- Status: Accepted
- Date: 2026-08-20

## Decision

Independent CPU-bound or tool-bound work must use bounded local parallelism when the scientific tool and artifact boundary allow it safely. Ankora uses at most the number of available logical processors minus one, never fewer than one worker, and never more workers than independent tasks.

Parallel execution must preserve deterministic source/result ordering, immutable per-task artifacts, row-isolated failures, cancellation boundaries, and complete provenance. A transformation that is order-dependent, shares unsafe mutable tool state, or lacks independent output paths remains serial until those constraints are resolved explicitly.

## Consequences

Library filtering and per-ligand ETKDG/MMFF/Meeko preparation use multiple local workers. Worker counts are visible and recorded. Future Vina and GNINA adapters must pass supported CPU/GPU settings explicitly and avoid nested oversubscription. Ankora reserves one logical processor for Windows and the interface by default; later UI controls may allow the scientist to choose a lower limit.
