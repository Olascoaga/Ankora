# ADR-004: Immutable original inputs

- Status: Accepted
- Date: 2026-08-19

## Decision

Imported and downloaded structures and ligands are never modified in place.

## Consequences

Transformations produce derived artifacts with explicit parent links.
