# ADR-023: Explicit project workspace identity

- Status: Accepted
- Date: 2026-09-06

## Context

Early Ankora milestones persisted all evidence below `projects/default`.
Replacing that path with an implicit current-directory convention would either
mix campaigns or require rewriting already validated evidence. Scientific
work also runs through long-lived services, so changing a label in React is not
enough to change ownership safely.

## Decision

Ankora maintains a small mutable project catalog at
`workspace/projects.json`, outside every immutable project evidence tree. Each
registered project has a validated storage identifier, a scientist-facing
name, and a registration timestamp. `default` remains a legitimate migrated
project and its existing bytes are never moved or rewritten during catalog
creation.

All persistence stores capture one explicit project root when constructed.
The active identity is bound to each local API request, and the application
rebuilds its long-lived docking, map, lease, recovery, and retry services when
the scientist switches projects. Switching is rejected while scientific work
or a resource reservation is active. An unknown project is rejected before
any directory or service is created.

The desktop exposes create/open/switch actions in a Project Workspace. A
successful switch clears the visible scientific state before loading history
from the newly active project, preventing records from two projects from
appearing together.

## Consequences

- Every structure, derivative, result, validation, analysis, and export belongs
  to one project root.
- Project names and active state may change without mutating scientific
  evidence.
- The `default` tree remains reproducible and backward compatible.
- Project switching is a deliberate operation, not an ambient environment
  variable change.
- Multi-process concurrent writers to the workspace catalog remain outside the
  current single-backend desktop contract.
