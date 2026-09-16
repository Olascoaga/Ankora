# LIT-PCBA official-structure intake — 2026-09-15

Protocol: `LIT_PCBA_ANKORA_VS_V1`

Outcome: **the six selected official RCSB structures were acquired, hashed,
and shown to share the exact LIT-PCBA source coordinate frames before receptor
preparation or docking**. The machine-readable record is
[`reference_cases/LIT_PCBA_ANKORA_VS_V1.structures.json`](reference_cases/LIT_PCBA_ANKORA_VS_V1.structures.json).

## Direct coordinate evidence

The comparison uses same-element heavy atoms at their recorded Cartesian
coordinates. It performs no translation, rotation, fitting, or superposition.
A coordinate match must be within 0.001 Å. Every source ligand heavy atom must
match, while at least 98% of source receptor heavy atoms must match. The ligand
requirement is the decisive proof that the frozen source-derived box and the
official receptor occupy the same frame; the receptor comparison independently
guards against an unrelated structure being accepted at that site.

| Target | Role | PDB | Receptor exact matches | Source ligand exact matches | Official co-crystal residue |
|---|---|---|---:|---:|---|
| ESR_antago | Primary | 5UFX | 1,845 / 1,859 (99.2469%) | 34 / 34 | 86Y A:601 |
| ESR_antago | Alternate | 2IOG | 1,915 / 1,939 (98.7622%) | 39 / 39 | IOG A:600 |
| PPARG | Primary | 3B1M | 2,073 / 2,083 (99.5199%) | 38 / 38 | KRC A:1 |
| PPARG | Alternate | 5Y2T | 2,083 / 2,087 (99.8083%) | 34 / 34 | 8LX A:501 |
| TP53 | Primary | 3ZME | 1,528 / 1,532 (99.7389%) | 22 / 22 | QC5 A:1291 |
| TP53 | Alternate | 5O1I | 1,507 / 1,511 (99.7353%) | 23 / 23 | 9GH A:402, altloc A |

All matched source receptor atoms belong to author chain A. RMSD over every
accepted receptor and ligand coordinate match is 0.000000 Å at the precision
recorded by both inputs.

## Differences are evidence, not permission to convert

The source receptor MOL2 files are already processed representations. Between
4 and 24 heavy atoms per template do not match a same-element official atom at
the 0.001 Å threshold. Their exact source atom identifiers are retained in the
manifest. They occur only under ASN, GLN, and HIS residue labels in this
cohort; this record does not infer or silently reproduce the transformation
that produced them.

Consequently, this unit proves spatial congruence but does not bless the source
protein MOL2 as an Ankora receptor. The next unit must freeze and execute one
explicit chain/component, repair, protonation-review, and receptor-PDBQT plan
for every primary and alternate official structure.

## Reproduction and fail-closed boundary

The manifest identity is
`d7bcac2269f70432ff4cd35f7288e07ca8d0f766ab23372558e3ac32b82e459f`.
The official files remain under ignored validation storage; the manifest
records each filename, RCSB URI, byte count, and SHA-256 without publishing a
machine path. Running
`scripts/freeze_screening_benchmark_structures.py --check` with the exact
source archive and official files rebuilds the complete record without network
access.

The verifier rejects changed dependencies, source members, official bytes,
entry IDs, model counts, target/template roles, unsafe archive paths,
malformed or non-finite MOL2 coordinates, insufficient receptor overlap, a
shifted ligand, or a ligand that maps across more than one official residue.
No receptor derivative, docking score, or enrichment result was produced.
