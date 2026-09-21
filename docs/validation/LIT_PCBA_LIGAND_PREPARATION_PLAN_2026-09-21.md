# LIT-PCBA ligand-preparation plan freeze — 2026-09-21

Protocol ID: `LIT_PCBA_ANKORA_VS_V1`

Status: **the exact loss-preserving plan for all 11,412 primary ranking units is
frozen before ligand preparation, docking, score inspection, or enrichment
calculation**.

## Frozen population and identity

The machine-readable plan is
[`reference_cases/LIT_PCBA_ANKORA_VS_V1.ligand-preparation-plan.json`](reference_cases/LIT_PCBA_ANKORA_VS_V1.ligand-preparation-plan.json),
with manifest SHA-256
`b6370eb32566e84ba569460f35efe5e89bdff12172609d92f203f51edd0d48e1`.
It rebuilds from the exact 57,399,933-byte AVE-unbiased archive and the frozen
source-population manifest.

| Target | Active parents | Inactive parents | Total |
|---|---:|---:|---:|
| ESR_antago | 88 | 3,820 | 3,908 |
| PPARG | 24 | 4,071 | 4,095 |
| TP53 | 64 | 3,345 | 3,409 |
| **Total** | **176** | **11,236** | **11,412** |

Every parent retains its global and target-local source order, class label,
source member, physical line, source identifier, source-SMILES SHA-256,
canonical-isomeric-SMILES SHA-256, and deterministic conformer seed. Molecular
strings are not copied into Git. Repeating a canonical parent within one target
is rejected; the same molecule may legitimately be an independent ranking unit
in different targets.

## Exact chemical and 3D policy

- The primary state is the exact imported sanitized graph. No uncharging,
  tautomerization, fragment removal, salt selection, or other chemical rewrite
  is allowed.
- Undefined stereochemistry and disconnected components are not guessed. The
  parent remains in the denominator and receives a recorded preparation
  failure.
- Lipinski, Veber, Ghose, Muegge, QED, PAINS, and Brenk are descriptive only.
  No filter can remove a benchmark parent.
- Each preparable parent uses a 20-member ETKDGv3 pool with chirality enforced.
  Its seed is derived solely from pre-result source identity by the exact
  SHA-256 rule recorded in the manifest.
- MMFF94s runs for at most 500 iterations per conformer. The lowest-energy
  converged conformer is selected. If none converges, the lowest-energy
  nonconverged conformer is retained as evidence but cannot proceed to Meeko.
- A converged conformer proceeds through Meeko 0.7.1 with Gasteiger charges.
  Exact tool versions, commands, standard output/error, immutable artifacts,
  hashes, and provenance must be retained during execution.

These are geometry-generation and docking-input decisions, not evidence that a
state is physiologically dominant or that its MMFF energy is comparable with
another compound.

## Loss and execution boundary

Execution is create-only, restartable, and bounded to logical processors minus
one, capped by the number of pending parents. Parsing, state ambiguity,
embedding, MMFF, nonconvergence, Meeko, and unexpected failures each remain
explicit terminal rows. A failed parent is retained later as part of the one
worst-ranked tie group; it is never deleted from an enrichment denominator.

The plan checker recomputes the source archive/member identities, canonical
parents, hashes, source order, and all deterministic seeds. Its synthetic
contract also rejects duplicate parents and any altered loss/docking boundary.

No ligand preparation has run in this phase. The next bounded unit executes
and independently verifies all 11,412 terminal outcomes. Docking, scores,
enrichment metrics, and sensitivity results remain prohibited until that
reconciliation closes.

## Execution contract

The restartable executor is implemented in
`scripts/run_screening_benchmark_ligand_preparation.py`. It reconstructs each
target library from the hash-verified archive, applies Ankora's production
descriptor and structural-alert path with every rule set to descriptive-only,
and then runs the existing ETKDGv3/MMFF94s and Meeko services. It writes one
create-only attempt directory per parent, skips only a hash-verified terminal
attempt on resume, and refuses to publish a completion manifest until all
11,412 source parents have terminal rows.

Synthetic contracts cover complete census closure, ambiguous-state retention,
interruption/resume behavior, and evidence tampering. A one-parent local
integration smoke also reached Meeko 0.7.1 and produced a PDBQT through the
same executor. Neither synthetic evidence nor that smoke is a benchmark
result. The 11,412-parent run remains the next pre-docking action.
