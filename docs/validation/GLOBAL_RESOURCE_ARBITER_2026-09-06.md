# Global resource-arbiter validation — 2026-09-06

## Scope

This validation covers the application-wide admission boundary shared by
ligand filtering/preparation, Vina, AutoGrid, AutoDock4 CPU, and AutoDock-GPU.
It tests scheduling behavior; it does not recompute or reinterpret scientific
results.

## Verified contracts

Automated backend tests verify that:

- CPU, GPU, memory, and disk are acquired as one atomic claim;
- a request waits without partially consuming capacity;
- FIFO waiters cannot bypass one another;
- cancellation removes queued work and releases acquired capacity;
- impossible requests fail with structured evidence rather than waiting;
- the application injects the same arbiter into every covered service; and
- the system resource endpoint exposes capacity, queue depth, and active
  allocations.

Service regression tests cover normal completion, cancellation, structured
failure, startup recovery, and batch behavior for all covered docking paths.
Frontend coverage verifies that the shared resource panel presents active and
queued work together with allocated CPU threads and GPU slots.

## Acceptance boundary

The arbiter uses conservative workload estimates and live available
memory/disk readings. These are admission controls, not a profiler and not
scientific provenance. Engine arguments, input hashes, raw outputs, parsed
scores, molecule ordering, and immutable artifacts retain their existing
contracts. The scheduler is local to one backend process; distributed and
multi-host scheduling are not claimed.
