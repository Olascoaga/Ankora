# LIT-PCBA source acquisition record — 2026-09-11

Protocol: `LIT_PCBA_ANKORA_VS_V1`

Outcome: **the exact LIT-PCBA AVE-unbiased source was acquired, hashed, and
reconciled before any Ankora preparation, docking, score, or enrichment result
was inspected**. The path-free input manifest is
[`reference_cases/LIT_PCBA_ANKORA_VS_V1.inputs.json`](reference_cases/LIT_PCBA_ANKORA_VS_V1.inputs.json).

## Maintainer sources and pre-result amendment

The [LIT-PCBA maintainer page](https://lab.drugdesign.unistra.fr/datasets/lit-pcba/)
reports 88/3,820 `ESR_antago`, 24/4,071 `PPARG`, and 64/3,345 `TP53`
active/inactive compounds. An initial attempt followed stale routed links on
the newer `lab` host and received HTTP 404. The exact downloads remained
available on the maintainer's original `drugdesign.unistra.fr` host.

Both relevant archives were acquired and identified before any Ankora result:

| Maintainer archive | Bytes | SHA-256 |
|---|---:|---|
| `LIT-PCBA_full.tar.gz` | 53,808,785 | `81f361fb5bd2c219cd72f1b580dbc8980311911703df53598134163a8282df34` |
| `LIT-PCBA_AVE_unbiased.tar.gz` | 57,399,933 | `1f50ef6bf66b8e987f056a2d2528f1d5a9031ad542ddc97f8ee2fbfd651c8de3` |

The archive called `full` contains different populations for the three target
directories: 102/4,948, 27/5,211, and 79/4,168. The preregistered counts close
exactly only in the AVE-unbiased archive after combining its supplied training
and validation rows (`active_T.smi` + `active_V.smi`, and `inactive_T.smi` +
`inactive_V.smi`).

This source-product correction is recorded in
[`reference_cases/LIT_PCBA_ANKORA_VS_V1.amendment-001.json`](reference_cases/LIT_PCBA_ANKORA_VS_V1.amendment-001.json),
whose SHA-256 is frozen in the protocol specification and verified by the
inspector. The target set, phenotype, census, ranking unit, failure policy,
metrics, bootstrap, and docking settings did not change. The amendment
explicitly records `scores_seen: false`.

## Exact AVE-unbiased census reconciliation

The source inspector read the compressed archive without extracting it and
closed the following accounting:

| Set | Source directory | Active rows | Inactive rows | Evaluation units | Templates |
|---|---|---:|---:|---:|---:|
| ESR_antago | `ESR1_ant` | 88 | 3,820 | 88 / 3,820 | 15 |
| PPARG | `PPARG` | 24 | 4,071 | 24 / 4,071 | 15 |
| TP53 | `TP53` | 64 | 3,345 | 64 / 3,345 | 6 |
| **Total** | — | **176** | **11,236** | **176 / 11,236** | **36** |

Across the three sets there were zero unparsed rows, zero exact within-class
duplicate rows, and zero cross-class canonical-state conflicts under the
frozen RDKit canonical-isomeric-SMILES identity. Consequently every source
row remains one evaluation unit. Every one of the 36 crystallographic
`*_protein.mol2` members has an exactly paired `*_ligand.mol2` member.

The manifest records the source archive identity, every selected source member
identity, canonicalization accounting, target-to-directory mapping, template
identities, and verified amendment reference. It contains no absolute local
paths. Its canonical content identity is:

`ebc5170e741939ef0e0b3e6c53129f15747cfdf0d54727746fc53c481372645b`

Its status remains `inputs_inspected_no_docking_executed`.

## Candidate archive inspected and rejected

A derived archive from [Zenodo record 10682034](https://zenodo.org/records/10682034),
DOI `10.5281/zenodo.10682034`, was also preserved locally and rejected before
any Ankora scores were inspected:

- filename: `LITPCBA_9t_subset.tar.xz`
- size: 16,396,368 bytes
- SHA-256: `79715f457752e511b0357b8d52d38fa013372a74691efd7c9addb75e2318d1ff`

Its README describes prepared, preselected ligand decoys and downstream GOLD
and strain-analysis products. It omits the frozen `PPARG` and `TP53` sets and
does not preserve the required population or chemical-state boundary. It was
not substituted for primary evidence and remains Git-ignored.

## Remaining acquisition boundary

The source population is now closed. Before any library docking begins, point
26 still requires a separate immutable execution-input manifest selecting one
exact primary holo template per target, freezing receptor preparation and
co-crystal-derived box coordinates, and recording the sentinel identities for
the bounded sensitivity analyses. Those choices must be made without looking
at benchmark scores.
