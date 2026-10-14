# Three-step receptor workflow — 2026-10-14

## Acceptance criteria

The scientist explicitly requests a beginner-friendly receptor menu, with few
clear steps, in addition to the separately versioned reconstruction correction.

- Default to **Choose system → Review repairs → Prepare**, showing one inspector
  step at a time. Later steps require resolved preceding prerequisites.
- Keep chain, water, ligand/cofactor and unusual-residue decisions explicit.
  Grouped missing-atom repair and absent-residue gap actions only fill a draft;
  they preserve previously selected removals/repairs and never run a tool.
- Keep all advanced controls, including structure-only derivatives and optional
  elastic relaxation. Switching modes does not reset decisions. New plans
  explicitly select the geometry guard; historical plans retain legacy behavior.
- Guided preparation requires explicit hydrogens/PDBQT choice, current exact-plan
  pKa review and a final confirmation. Edits invalidate the corresponding review
  or confirmation. Invalid numerical inputs block calculation before an API call.
- Filter pKa proposals needing attention while retaining the complete request.
  Keep original-residue focus, previous-attempt evidence and explicit recovery.
- Maintain usable 3D rendering and reachable actions at laptop viewport sizes.
- Explain incompatible observed-anchor geometry with measured distances and
  the template bond sum; do not present elastic clash relief as its solution.

## Evidence

Frontend unit/integration regressions cover all criteria, including hidden
advanced controls, no implicit calculation, retained scientist overrides,
historical method restoration and confirmation invalidation. The production
browser test uses explicitly synthetic API replies and genuine Mol* rendering;
it is not evidence of a biological preparation or installed-binary acceptance.

Edge 155 production smoke passed at 960×680 and 1280×800 under the packaged CSP
with no `unsafe-eval`: all three step actions are reachable, hidden controls
remain hidden, no document-level horizontal overflow occurs, and original PDB
and mmCIF representations render without viewer/CSP errors. Recovery still sends
exactly two explicitly requested mocked preparations and two reviews; changing
filters or draft decisions sends no preparation. Local screenshots/evidence
remain ignored. CI now invokes the same `--receptor-wizard` regression; no remote
CI success is asserted before a separately authorized push.

The full frontend gate passes **295 tests across 39 files**, including six new
guided/historical-state regressions; strict TypeScript and production build
pass. Existing unrelated synthetic-fixture React `act`/NaN warnings and the
large Mol* bundle notice remain visible, not treated as new passing scientific
evidence. Ruff and strict backend typing pass (139 source files); public-path
and frozen-validation-status checks pass. The complete scientific regression
is recorded separately rather than inferred from mocked browser replies.

The final integrated backend gate passes **760 tests**, including repaired
connectivity, chirality, bond-length rejection and legacy-identity regressions.
This verifies the fail-closed implementation, not successful completion of the
incompatible original ARG A:300 geometry. No test or new docking calculation
changes a historical benchmark result.

The real scientific proof is separate:
[topology-guarded 7AQF reconstruction](RECEPTOR_TOPOLOGY_GUARD_2026-10-14.md).
The manual distinguishes the current development assistant from historical
tutorial screenshots and the previously distributed installer. No installer or
manual PDF was rebuilt in this unit.

The final native bond-length audit changes the scientific conclusion, not the
UI's explicit-decision contract: the original 17-repair 7AQF plan is rejected
for ARG A:300's incompatible observed anchors. Its preliminary Meeko acceptance
is not promoted. The additional synthetic UI regression verifies that the
measured conflict is understandable and does not advertise clash relief as a
bond repair; no scientific reconstruction of observed atoms is inferred.
