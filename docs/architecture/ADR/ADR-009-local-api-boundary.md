# ADR-009: Local API boundary

- Status: Accepted
- Date: 2026-08-19

## Decision

React communicates with the Python scientific backend through an explicit typed localhost API.

## Consequences

The frontend does not invoke scientific tools or subprocesses directly. The backend binds only to localhost.
