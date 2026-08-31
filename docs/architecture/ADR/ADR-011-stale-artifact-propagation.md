# ADR-011: Stale downstream artifact propagation

- Status: Accepted
- Date: 2026-08-19

## Decision

Changes in upstream scientific decisions explicitly invalidate dependent downstream artifacts.

## Consequences

Users can still inspect stale artifacts, but Ankora must not present them as current.
