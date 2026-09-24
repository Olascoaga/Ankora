# LIT-PCBA primary Vina campaign plan — 2026-09-23

Protocol ID: `LIT_PCBA_ANKORA_VS_V1`

Status: **the complete primary AutoDock Vina campaign is frozen and verified;
no docking process has started, no score has been read, and no enrichment
metric has been computed**.

The path-free executable plan is
[`reference_cases/LIT_PCBA_ANKORA_VS_V1.vina-primary-plan.json`](reference_cases/LIT_PCBA_ANKORA_VS_V1.vina-primary-plan.json),
with internal manifest SHA-256
`31862a168e737d2d6d81ab9ce5eba3b316eb31225318300237b140a99c020feb`.
It binds the previously frozen geometry, final receptors, and complete ligand
preparation result by their internal manifest hashes.

## Closed campaign census

| Target | Primary receptor | Frozen parents | PDBQT ready | Retained unscored |
|---|---|---:|---:|---:|
| ESR_antago | 5UFX | 3,908 | 3,868 | 40 |
| PPARG | 3B1M | 4,095 | 4,054 | 41 |
| TP53 | 3ZME | 3,409 | 3,380 | 29 |
| **Total** | — | **11,412** | **11,302** | **110** |

Every source parent occurs exactly once. Each ready row records the exact
relative PDBQT path, byte count, and SHA-256. Each non-prepared row records its
terminal preparation status, error code, and stage and remains in the future
worst-ranked tie. The plan contains no absolute workstation path and copies no
molecular string into Git.

## Frozen execution identity

- Engine: AutoDock Vina `1.2.7`.
- Executable: `vina_1.2.7_win.exe`, 1,233,920 bytes, SHA-256
  `e0c4b2715e0c1a74f6e92d0f3be0328ac97542eafbc111e6b1efad897a73cce5`.
- Sampling preset: seed `20260911`, exhaustiveness `8`, maximum poses `9`,
  minimum RMSD `1.0 Å`, and energy range `3 kcal/mol`.
- Timeout: `360` minutes per ligand.
- CPU allocation: `15` concurrent ligands × `1` Vina thread = `15` of `15`
  allocated logical threads. This throughput-first policy prevents nested Vina
  parallelism from silently oversubscribing the machine.
- Receptors: the exact primary prepared PDBQT for 5UFX, 3B1M, and 3ZME.
- Search spaces: the exact pre-registered 5 Å-per-face co-crystal boxes. Each
  target records the complete Vina argument template, not only a box label.

## Parser and failure boundary

The frozen parser source is
`backend/src/ankora_backend/adapters/engines/vina.py`, SHA-256
`e13e32f5b6c401966debe80fe0049f4ae87f1cc3c8eb31f4566c57c1acc50993`.
It requires sequential `MODEL`/`ENDMDL` blocks beginning at one, exactly one
`REMARK VINA RESULT` record per pose, and no non-whitespace content outside
model blocks. Scores will come only from that structured PDBQT remark; stdout
is retained as raw evidence but is not a score source.

The execution contract is create-only and restartable. Terminal entry evidence
must be persisted incrementally, raw Vina output must be retained, and a failed
ligand may not abort or disappear from the campaign. Preparation failures and
future docking failures share the pre-registered unscored worst tie when
metrics are eventually computed.

## Verification performed

The plan generator independently re-hashed:

- all three primary receptor PDBQTs;
- all 11,302 prepared ligand PDBQTs;
- the exact Vina executable; and
- the exact parser source.

Synthetic contract tests prove deterministic, path-free construction and fail
closed when a parameter or scientific input byte changes. Recorded-data tests
close the 11,412-parent census and require `scores_seen: false`,
`docking_executed: false`, and `scores_or_metrics_computed: false`.

## Subsequent pre-result boundary

The required benchmark executor is now implemented and hash-bound in
[`reference_cases/LIT_PCBA_ANKORA_VS_V1.vina-executor-readiness.json`](reference_cases/LIT_PCBA_ANKORA_VS_V1.vina-executor-readiness.json),
manifest SHA-256
`da94c97dcac942692198457ef2bd821d7485668577e220297561f7ffaa8a3eaf`.
Its verification record is
[`LIT_PCBA_VINA_EXECUTOR_READINESS_2026-09-23.md`](LIT_PCBA_VINA_EXECUTOR_READINESS_2026-09-23.md).
The exact primary campaigns may now execute or resume. Sensitivity runs and all
metric calculation remain downstream until their complete terminal evidence
has been independently verified.
