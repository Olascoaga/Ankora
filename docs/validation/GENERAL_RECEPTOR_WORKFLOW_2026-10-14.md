# General receptor workflow validation — 2026-10-14

## Scope and acceptance

Validate general preparation mechanics and clear support boundaries, without
protein-specific code, observed-atom reconstruction, force-parameter tuning or
automatic component removal. This is not a docking/affinity benchmark, universal
receptor recipe, biological rotamer validation or acceptance of the historical
7AQF all-17-repair plan. Historical scientific evidence and the distributed
installer are unchanged.

Acceptance requires that:

- The versioned repair kernel completes controlled missing atoms for all 20
  standard amino-acid templates while preserving observed coordinates and
  passing its connectivity, bond geometry and rebuilt stereochemistry checks.
- Independent public structures exercise complete preparation at different pH
  values; original bytes, complete requests, versions and raw outputs survive.
- Retained incomplete non-polymer components require appropriate decisions
  before protein repair, rather than being advertised as repairable amino acids.
- Explicit component removal resolves that component's observations once, not
  twice. Exact chain/name/sequence/insertion identity controls the scope.
- Old redundant decisions remain in recorded requests without executing repairs
  for excluded coordinates. No existing artifact is rewritten.

## Predeclared native matrix

The original [V1 plan](reference_cases/RECEPTOR_WORKFLOW_MATRIX_V1.plan.json)
was recorded before execution at 20:32 UTC. Its SHA-256 is
`f274c8cbc35a8209ccd29a1beb25ba2836dbdb10a4fe36830528628abae19222`.
The explicitly amended [V2 plan](reference_cases/RECEPTOR_WORKFLOW_MATRIX_V2.plan.json)
was recorded before its run at 20:42 UTC, SHA-256
`1035809da16b098966ef9a9771c1ab70a628c1458479026311b28c71434e5aba`.
V1 and its failure were retained, not overwritten or recast as success.

Sources were fetched as RCSB mmCIF files. These choices are diagnostic requests,
not recommendations to remove water or components in every experiment.

| Source | Explicit system | V1 observation | V2 observation |
| --- | --- | --- | --- |
| [1CRN](https://www.rcsb.org/structure/1CRN) | A; pH 7.4; remove water/non-water components | Docking-ready PDBQT | Docking-ready PDBQT |
| [1UBQ](https://www.rcsb.org/structure/1UBQ) | A; pH 6.5; remove water/non-water components | Docking-ready PDBQT | Docking-ready PDBQT |
| [4HHB](https://www.rcsb.org/structure/4HHB) | A/B; pH 7.4; remove water, keep non-water components | `PDBFIXER_REPAIR_INCOMPLETE`: requested PO4 B:147, matched zero residues | `needs_decision` before preparation; PO4 B:147 is not offered amino-acid repair |

The 4HHB request retained HEM A:142, PO4 B:147 and HEM B:148. The source reports
missing O1/O2/O3/O4 for PO4 B:147. V1 exposed a generic inspection bug that offered
Repair for every missing-atom issue regardless of component class. The fix
restricts missing-atom Repair to standard polymer residues; alternate-conformer
selection remains separate. V2 honors the reported supported actions instead of
forcing Repair. This validates a decision boundary, **not successful heme
parameterization/protonation**: neither run reached that stage for this system.
There was no automatic keep-to-remove fallback or altered-chemistry retry.

All three source files rehashed unchanged in both runs. SHA-256:

| Source | Imported mmCIF |
| --- | --- |
| 1CRN | `23787562c427d7c1abe5420e86d5f1d0a6c7007dec1e8ce85645a6d69c32e8ba` |
| 1UBQ | `056f98710cb2b36f633c45e41902a02eb446e82871da21ff2dd44f74a56ca0f6` |
| 4HHB | `2d3ca1bf21ddff35af2e2bc5d331720f7bfc46a16c4829ea3ec1b41062d5f5a6` |

Both successful runs produced the same hashes for these outputs:

| Source | AMBER PQR | Receptor PDBQT |
| --- | --- | --- |
| 1CRN | `22bed75bf07a531aa9dadc5ac55d6d2836ca1d35026389225ae3eba6790e3273` | `6db6c9742ea0bc4d8b475661856f5c8e1032f6ff1ee4428d47c1c88def7164f3` |
| 1UBQ | `f64f6e36b157f4284f4fd87c8486e583dddd5149eb34509ce5a86be32e714fc1` | `e5586ff2efc9ccf50695881474a78b06075bfb2b3d765493aa6b3f314a960e0e` |

No missing final OXT authorization was needed for these inputs. Optional elastic
relaxation was disabled; there were no missing-atom repairs in the two completed
native systems. Thus they exercise the complete preparation path, not realistic
missing-side-chain reconstruction in a crowded pocket.

Runtime: Windows native, PDBFixer 1.12.0, OpenMM 8.5.2, PDB2PQR 3.7.1, PROPKA
3.5.1, Meeko 0.7.1, RDKit 2025.9.6, Gemmi 0.7.5. Requests explicitly record
`topology_guard_v3`, seed 20261014, AMBER charges and per-case pH; the controlled
repair tests use OpenMM Reference. Three independent case workers were used.

## Controlled repair and regression evidence

Twenty synthetic fixtures derive heavy atoms and coordinates from the installed
PDBFixer standard templates: retain N/CA/C/O and remove the side chain; for GLY,
remove O. Each reconstruction uses the unchanged guarded kernel and recorded
seed. These tests do not invent experimental expectations. All 20 passed,
alongside existing insertion-code, retained-Zn, bond/chirality mutation and
observed-coordinate regression tests (31 geometry tests total).

Synthetic component tests verify no tool call for excluded components, optional
redundant historical decisions, immutable imported bytes and structured early
rejection of unsupported component repair. The diagnostic harness tests reject
unsupported/ignored policy fields, stop on an incomplete retained component and
refuse output-directory reuse. Sources, inspections, requests, tool logs,
failures and outcomes remain in separate ignored local diagnostic roots; no raw
machine paths or private data are included in this record.

Run the bounded matrix in a new directory with
`scripts/run_receptor_workflow_matrix.py --plan <plan> --output <new-directory>
--fetch-public-rcsb`. Fetching is opt-in. The process exit status distinguishes
harness errors/source mutation from measured scientific failures; inspect every
recorded outcome rather than interpreting exit zero as universal success.

This evidence broadens regression coverage. It does not imply arbitrary
cofactor support, correct biological protonation in every system, a validated
repair of incompatible observed geometry, or new installer acceptance.
