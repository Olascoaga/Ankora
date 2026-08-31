# ADR-007: Mol* behind a viewer abstraction

- Status: Accepted
- Date: 2026-08-19

## Decision

Mol* is the initial molecular viewer, isolated behind an Ankora viewer adapter.

## Consequences

Frontend domain and workflow logic do not depend directly on the Mol* API.
