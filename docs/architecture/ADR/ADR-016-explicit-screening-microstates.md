# ADR-016: Bounded, explicitly selected screening microstates

- Status: Accepted
- Date: 2026-09-03

## Context

A virtual-screening library names parent compounds, but docking operates on an
exact molecular graph. Protonation and tautomer choices can change formal
charge, atom typing, grid compatibility, and the resulting ranking. Treating an
input drawing as universally correct is unsafe; silently choosing the first
enumerated alternative is equally unsafe. Dimorphite-DL and RDKit tautomer
enumeration do not provide a biological population model for Ankora to use as a
scientific ranking.

## Decision

Every screening filter manifest records one of two visible policies:

1. `exact_imported_state` keeps the submitted or explicitly component/stereo-
   resolved state and performs no protonation/tautomer selection.
2. `enumerated_selection` uses Dimorphite-DL followed by RDKit's
   `TautomerEnumerator` inside scientist-visible pH and candidate bounds. The
   scientist selects exactly one candidate per retained parent compound.

Candidate ordering is deterministic only for reproducibility and is never
presented as population, probability, biological preference, or docking
suitability. Reaching a bound produces a structured warning. Each accepted
candidate becomes an immutable child state with its parent state, canonical
isomeric SMILES, formal charge, tool versions, bounds, selected index, and
whether truncation occurred.

Filtering, conformer generation, PDBQT preparation, docking, results, and
Methods carry both the parent-compound ID and exact chemical-state ID. A PDBQT
whose recorded chemical state differs from the applied manifest is rejected as
stale rather than docked. Screening results remain one row per parent because
this policy accepts one state per parent; Ankora does not take an unacknowledged
best score across states.

## Consequences

- The default remains compatible and conservative: exact submitted state.
- Enumerated screening requires more scientist decisions and may be unsuitable
  for very large libraries until an independently validated population/selection
  policy is adopted.
- Additional microstates can be supported later as separate child entries, but
  their scores must not be collapsed into a parent-level best value without an
  explicit, validated aggregation policy.
