# LIT-PCBA Vina sensitivity execution plan — 2026-09-28

Protocol: `LIT_PCBA_ANKORA_VS_V1`

Outcome: **the complete post-primary one-factor sensitivity program is bound
without executing a sensitivity docking or computing a sensitivity metric**.
The machine-readable record is
[`reference_cases/LIT_PCBA_ANKORA_VS_V1.vina-sensitivity-plan.json`](reference_cases/LIT_PCBA_ANKORA_VS_V1.vina-sensitivity-plan.json).

## Paired populations

Receptor, box, seed, and sampling comparisons retain the complete frozen
primary population: 11,412 parents, including 11,302 prepared entries and 110
preparation failures that remain in the common worst tie. A docking failure in
one arm never removes that parent from its paired comparison.

Chemical-state sensitivity is the sole bounded-panel exception already stated
by the protocol. It retains the 96 SHA-256-selected parents: 16 actives and 16
inactives per target. All 96 have a prepared primary imported state.

## Six execution variants

1. Every bounded pH 7.4 protonation/tautomer candidate on the 96-parent panel,
   with at most 8 tautomers per protomer and 16 states per parent.
2. The predeclared alternate experimental holo receptor for each target.
3. The same primary box center with 3 Å added on every face.
4. Seed `20260912`.
5. Seed `20260913`.
6. Exhaustiveness `32` with primary seed `20260911`.

Each variant changes only the named factor. The other five full-population
variants reuse the exact primary ligand PDBQTs; the receptor and box variants
use the already frozen coordinate frame. The upper bound is 58,046 additional
Vina executions: 5 × 11,302 full-population prepared entries plus at most
96 × 16 chemical states.

## Chemical-state boundary

The numerical enumeration bounds are not a post-result optimization. They are
the public Ankora defaults introduced in commit
`56a1b918a72aa3551e82e46ccc23583bca8091fe` on 2026-09-03, before the primary
campaign. The plan records those source identities and the installed RDKit and
Dimorphite-DL versions.

Every emitted state is retained. Candidate order is not a population ranking,
truncation remains visible, and selecting a best-scoring state or reporting
best-state enrichment is forbidden. Chemical-state results are parent-level
score/rank ranges only.

## Claim boundary

The independently verified primary result and primary metric table remain
immutable. Sensitivity can qualify their stability but cannot replace them.
Raw scores are never pooled across targets, and no sensitivity value is an
affinity, potency, biological-activity, or prospective-performance claim.
