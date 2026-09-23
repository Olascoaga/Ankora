# LIT-PCBA ligand-preparation results — 2026-09-23

Protocol ID: `LIT_PCBA_ANKORA_VS_V1`

Status: **all 11,412 frozen parent compounds have one independently verified
terminal ligand-preparation outcome; no docking score or enrichment metric has
been computed**.

The path-free public result manifest is
[`reference_cases/LIT_PCBA_ANKORA_VS_V1.ligand-preparation.json`](reference_cases/LIT_PCBA_ANKORA_VS_V1.ligand-preparation.json),
with internal manifest SHA-256
`d7704f66118820974a6c55a0a5fcc366ac33c5738db3af9672a77eadb74a3ab0`.
It is bound to the pre-result preparation-plan SHA-256
`b6370eb32566e84ba569460f35efe5e89bdff12172609d92f203f51edd0d48e1`.
The full run completed on 2026-09-21 and its retained local evidence was
independently re-hashed on 2026-09-23.

## Closed population

| Target | Class | Frozen parents | Prepared PDBQT | Unresolved exact state | ETKDGv3 failure |
|---|---|---:|---:|---:|---:|
| ESR_antago | active | 88 | 88 | 0 | 0 |
| ESR_antago | inactive | 3,820 | 3,780 | 38 | 2 |
| PPARG | active | 24 | 24 | 0 | 0 |
| PPARG | inactive | 4,071 | 4,030 | 40 | 1 |
| TP53 | active | 64 | 64 | 0 | 0 |
| TP53 | inactive | 3,345 | 3,316 | 29 | 0 |
| **Total** | **all** | **11,412** | **11,302** | **107** | **3** |

All 176 active parents and 11,126 of 11,236 inactive parents produced a
converged MMFF94s conformer and a Meeko 0.7.1/Gasteiger PDBQT. Every one of the
11,302 prepared rows records distinct conformer and PDBQT evidence with hashes.
The remaining 110 parents are retained as the pre-registered unscored worst tie;
none is removed from a target denominator.

## Explicit non-prepared outcomes

- The 107 `unresolved_chemical_state` rows all carry
  `STEREOCHEMISTRY_REQUIRES_DECISION`. The exact imported graph has undefined
  stereochemistry, and the frozen policy forbids Ankora from inventing a
  stereoisomer after cohort definition.
- Three inactive parents carry `LIGAND_CONFORMER_GENERATION_FAILED` at the
  `ligand_conformer_generation` stage. ETKDGv3 could not generate an independent
  conformer for ESR_antago source identifiers `144211746` and `144207089`, and
  PPARG source identifier `144211746`, under their target-specific frozen seeds.
- The fact that every non-prepared parent is inactive is an observed class
  imbalance, not a license to drop those rows or revise the failure rule. It
  must remain visible when enrichment results are interpreted.

## Execution and verification evidence

- RDKit version: `2025.09.6`.
- Meeko version: `0.7.1` for all 11,302 prepared rows.
- Worker count: `15`, fixed before outcomes and bounded to logical processors
  minus one.
- Attempts: all 11,412 parents completed in `attempt-001`; no interrupted
  attempt was hidden or overwritten.
- Every public artifact path is repository/run-relative. Raw commands, logs,
  conformers, PDBQTs, and immutable service records remain in the local evidence
  root and were re-hashed by the independent verifier.
- The verifier reconciled source order and identity against the exact 11,412-row
  plan, confirmed the complete status census, and required conformer plus PDBQT
  evidence for every `prepared` row.

The manifest records `scores_seen: false`, `docking_executed: false`, and
`scores_or_metrics_computed: false`. These outcomes establish only that the
frozen input population has been prepared or retained as an explicit failure.
They do not establish enrichment, affinity, activity, pose correctness, or
cross-target performance.

## Next pre-result boundary

Before the first library docking process starts, freeze an executable primary
Vina campaign plan that binds each target to its exact primary receptor PDBQT,
primary co-crystal box, prepared-parent artifact identities, 110 retained
unscored rows, fixed Vina 1.2.7 settings, executable identity, bounded worker
allocation, restart/resume semantics, and score-parser contract. That plan must
be verified without reading a docking score. Sensitivity campaigns and metric
calculation remain downstream.
