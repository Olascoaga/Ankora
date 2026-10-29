# Receptor terminal oxygen review

## Purpose and scientific limits

The receptor inspection reports a candidate when the last observed standard
protein polymer residue in a chain lacks an atom named OXT. This is an advisory
about the source coordinates, not proof of a biological terminus, an omission,
or a prediction that PDB2PQR will add an oxygen. Nonstandard and nucleic-acid
ends are not proposed. Existing OXT atoms are not proposed even if their
occupancy is zero, matching the preparation guard against duplicate additions.
The observation uses the first coordinate model and preserves the source.

The interface offers each candidate individually, initially unchecked, for
explicit authorization. Selecting a checkbox only changes the draft plan; it
does not add an atom. Changing selected chains or removing the candidate residue
requires clearing incompatible authorizations. Actual preparation continues to
validate the exact final selected-chain end and rejects all other unapproved
heavy-atom changes. Residue removals or repairs can change the final end, so a
source-level candidate is not a guarantee that the later tool can apply it.

## Verification

Synthetic PDB and mmCIF cases cover separate chains, insertion codes, an
existing OXT, and unchanged original bytes. The synthetic UI test covers
unchecked initial state, explicit per-chain authorization, the exact request,
and invalidation when the selected chain or residue is removed. The existing
preparation tests continue to reject unapproved heavy-atom additions.

Read-only inspection of the exact 1HSG mmCIF used in the previous failed smoke
(SHA-256 `d2ba73b5c4be05c45275571bbb4dd042347927f91c6c05038c0df5d1ce23c268`)
reported candidates PHE A:99 and PHE B:99, matching the earlier PDB2PQR
proposal. This confirms detection for that input, not a chemical judgment that
the atoms should be added. The original failed protocol remains unchanged.

Focused receptor/API and guard tests passed on Linux (89 tests); the receptor
preparation and completeness subset also passed natively on Windows (60 tests).
The complete frontend suite passed on Linux (338 tests), including the
existing recovery workflow updated to require clearing an authorization when
its residue is removed. Backend Ruff, backend mypy (142 source files) and
frontend TypeScript checks passed. The scientific tools and generated artifacts
from the independent exploratory 1HSG run are documented separately in
`LINUX_CRYSTAL_REDOCKING_FOLLOWUP.md`.
