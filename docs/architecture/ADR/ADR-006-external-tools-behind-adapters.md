# ADR-006: External scientific tools behind adapters

- Status: Accepted
- Date: 2026-08-19

## Decision

RDKit, Meeko, PDBFixer, PDB2PQR, PROPKA, Vina, GNINA, and interaction tools live behind versioned adapters.

## Consequences

Domain and UI code depend on Ankora contracts rather than tool-specific invocation or output formats.
