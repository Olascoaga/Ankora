# ADR-022: Global scientific resource arbitration

- Status: Accepted
- Date: 2026-09-06

## Context

Per-operation worker limits prevent one ligand library or docking campaign
from multiplying its own parallelism, but they cannot prevent several valid
operations from oversubscribing the same workstation together. Ligand
preparation, Vina, AutoGrid, AutoDock4 CPU, and AutoDock-GPU compete for CPU,
host memory, output-disk capacity, and, where applicable, an accelerator.
Starting them independently can make the desktop unresponsive, exhaust disk
space, or turn an otherwise valid scientific run into a resource failure.

The existing durable work lease records ownership and enables startup
reconciliation. It does not model machine capacity and must not be overloaded
for that purpose.

## Decision

The backend owns one process-local `ResourceArbiter`, created with the
application and injected into every supported scientific service. Before a
worker changes a durable record from queued to running, it requests one atomic
claim containing all estimated CPU threads, GPU slots, host-memory bytes, and
output-disk bytes needed by that unit of work.

Claims are admitted in FIFO order only when the complete claim fits. A claim
never holds one resource while waiting for another. Cancellation removes a
waiter or releases an acquired lease, and release is idempotent. A request
larger than configured capacity fails with structured
`RESOURCE_REQUEST_EXCEEDS_CAPACITY` evidence instead of waiting forever.

The default CPU capacity is the logical processor count minus one. The default
GPU capacity is one exclusive slot because the supported AutoDock-GPU adapter
currently runs one selected device. Memory and disk admission use live
available capacity with explicit safety reserves. Workload-specific estimates
are conservative scheduling inputs, not measured scientific outputs. Narrow
environment overrides support controlled validation and unusual machines.

The localhost system resource response reports capacity, queued claims, and
active allocations. It does not expose this scheduler as a promise of exact
instantaneous operating-system utilization.

## Consequences

- Independent services cannot silently multiply CPU or GPU concurrency across
  the application.
- Memory and disk are considered in the same admission decision as CPU/GPU.
- Waiting jobs remain cancelable and visibly queued; capacity is recovered on
  every terminal path.
- Durable work leases and resource leases remain separate, explicit concepts.
- Existing scientific commands, scores, artifacts, ranking semantics, and
  immutable evidence are unchanged.
- The arbiter coordinates one backend process. Multi-host or distributed
  scheduling remains outside this decision.
