# ADR-010: SQLite plus artifact store

- Status: Accepted
- Date: 2026-08-19

## Decision

Structured project state uses SQLite; molecular files and raw outputs remain normal project artifacts.

## Consequences

The database stores identity and relationships without hiding scientific artifacts in opaque blobs.
