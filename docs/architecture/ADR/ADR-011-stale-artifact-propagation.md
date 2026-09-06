# ADR-011: Stale downstream artifact propagation

- Status: Accepted
- Date: 2026-08-19

## Decision

The dependency graph is rebuilt from immutable scientific records and their
recorded identifiers. It is not a second source of scientific truth. A graph
node represents one persisted record; an edge points from an upstream input to
a record that explicitly names that input.

Stale state is an explicit scientist decision with a required reason. The
marker is stored as mutable workspace metadata outside the project's evidence
tree. Marking a node stale propagates to every reachable descendant, but never
edits, deletes, or moves the record or its molecular artifacts.

An older result, an alternative preparation, or another branch is not stale
merely because a newer one exists. Missing references are reported as
unresolved links for inspection and do not silently invalidate a record.

## Consequences

Users can still inspect stale artifacts and the reason for their state, but
Ankora must not present them as current. The graph may be regenerated at any
time from retained records plus the small stale-marker file. Existing
intrinsic stale flags remain honored and also propagate downstream.

Project identity is governed by ADR-023. In particular, stale metadata is
scoped by project and cannot create a dependency across project boundaries.
