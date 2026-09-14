# LIT-PCBA holo-template selection — 2026-09-14

Protocol: `LIT_PCBA_ANKORA_VS_V1`

Outcome: **one primary and one alternate experimental holo template were
selected for each target before any benchmark docking, score, or enrichment
result existed**. The machine-readable record is
[`reference_cases/LIT_PCBA_ANKORA_VS_V1.templates.json`](reference_cases/LIT_PCBA_ANKORA_VS_V1.templates.json).

## Frozen selection rule

The candidate set is not an arbitrary Protein Data Bank search. It is exactly
the 36 receptor/ligand pairs already present in the hash-bound LIT-PCBA source
manifest. Every candidate had to resolve through the RCSB Data API as one
X-ray structure with one positive experimental resolution.

Within each frozen target set, candidates are ordered by:

1. lowest experimental resolution in angstrom; then
2. lexicographically smallest lowercase PDB ID for an exact tie.

The first candidate is primary and the second is the predeclared receptor
sensitivity alternate. Ligand similarity, docking score, enrichment, title,
publication date, and manual preference play no part in the ordering. Crystal
resolution alone does not prove biological representativeness; it is used here
as a transparent deterministic selector among templates already curated for
the target/phenotype by the benchmark source.

## Frozen choices

| Target | Primary | Resolution | Alternate | Resolution | Candidate count |
|---|---|---:|---|---:|---:|
| ESR_antago | 5UFX | 1.5503 Å | 2IOG | 1.60 Å | 15 |
| PPARG | 3B1M | 1.60 Å | 5Y2T | 1.70 Å | 15 |
| TP53 | 3ZME | 1.35 Å | 5O1I | 1.40 Å | 6 |

For every selected PDB ID the manifest carries the exact source `protein.mol2`
and `ligand.mol2` member paths, byte sizes, and SHA-256 identities. All 36
candidates and their recorded RCSB method, resolution, and title remain in the
same file, so the runner-up choice can be reproduced rather than inferred.

## Metadata identity and offline reproduction

The normalized metadata snapshot was obtained from the official RCSB GraphQL
endpoint on 2026-09-14. The manifest records the endpoint and SHA-256 of the
exact query. Its input is source-population manifest
`ebc5170e741939ef0e0b3e6c53129f15747cfdf0d54727746fc53c481372645b`;
its own canonical identity is
`105607968656e9af12e757ee4ec154c19567926f049db9f26a5420d4b8434743`.

`scripts/freeze_screening_benchmark_templates.py --check` rebuilds every
choice from the recorded candidate metadata without network access. It fails
if the source-population manifest changes, a candidate is missing or added, an
entry is duplicated, a structure is not unambiguously X-ray, a resolution is
absent, or a source receptor/ligand identity cannot be joined exactly.

## Remaining pre-docking boundary

This record selects structural templates; it does not yet claim that a source
MOL2 receptor is an Ankora-ready receptor. Before screening starts, the project
must freeze and execute one explicit receptor-preparation path for each primary
template, derive the primary co-crystal box from its exact ligand coordinates,
record the alternate-template preparation for sensitivity, and select the
hash-determined chemical-state sentinel panel. No result exists yet.
