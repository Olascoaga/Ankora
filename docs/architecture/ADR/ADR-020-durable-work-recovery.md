# ADR-020: Durable work ownership and interruption recovery

- Status: Accepted
- Date: 2026-09-04

## Context

Docking and map generation can run for minutes or hours. A backend crash,
forced process termination, Windows restart, or machine failure can leave a
durable record saying `queued`, `running`, or `cancel_requested` even though no
process still owns it. Treating that record as live makes the interface wait
forever. Treating it as safely resumable risks mixing new execution with
partial engine outputs whose completeness cannot be established.

Library campaigns add another constraint: molecules that reached a terminal
state before the interruption are valid recorded results and must not be lost
merely because later entries did not finish.

## Decision

Vina, AutoGrid, AutoDock4 CPU, and AutoDock-GPU jobs and campaigns acquire a
durable lease when their worker starts. The lease records a unique backend
instance, acquisition time, and periodically refreshed heartbeat. Normal
completion, failure, or cancellation releases it.

At backend startup Ankora scans durable work records before accepting new
requests. Any record still in `queued`, `running`, or `cancel_requested` is
closed as `failed` with an engine-specific `*_INTERRUPTED` code. The failure
evidence includes the previous status, reconciliation time, and the prior
owner/heartbeat when a lease exists. A missing lease does not make an active
record safe; it is also reconciled as interrupted because no current worker
owns it.

For campaigns, already terminal entries remain byte-for-byte represented by
the same records. Only active entries become interrupted failures, and the
campaign counts are recomputed from the preserved terminal state. Raw and
partial output directories are never deleted or reused.

Retry is explicit and creates a new job or campaign with its own identifier,
directory, lease, and provenance. Ankora does not silently auto-resume or
write new results into an abandoned attempt.

The startup recovery summary is shown in the shared activity center. Each
interruption reports its prior state and preserved/computationally interrupted
entry counts. Its retry control remains disabled until the scientist confirms
that the action creates a new immutable attempt. The API independently enforces
the same confirmation and accepts only the engine-specific interruption codes
written by startup reconciliation; an ordinary scientific or tool failure is
not relabelled as resumable work.

## Consequences

- The interface can distinguish slow work from work whose owner disappeared.
- Completed molecules survive a process or machine failure.
- Partial evidence remains available for diagnosis without being promoted to
  a successful scientific result.
- Retrying consumes additional time and storage, but preserves a clear
  immutable boundary between attempts.
- Startup reconciliation is operational recovery, not scientific validation;
  it does not infer whether an engine output was complete from a human-readable
  log.
