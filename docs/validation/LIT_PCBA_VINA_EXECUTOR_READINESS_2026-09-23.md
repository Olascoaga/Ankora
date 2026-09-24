# LIT-PCBA primary Vina executor readiness — 2026-09-23

Protocol ID: `LIT_PCBA_ANKORA_VS_V1`

Status: **the exact-plan executor is implemented and verified; no real
benchmark docking process has started, no benchmark score has been read, and no
enrichment metric has been computed**.

The path-free readiness record is
[`reference_cases/LIT_PCBA_ANKORA_VS_V1.vina-executor-readiness.json`](reference_cases/LIT_PCBA_ANKORA_VS_V1.vina-executor-readiness.json),
with internal manifest SHA-256
`da94c97dcac942692198457ef2bd821d7485668577e220297561f7ffaa8a3eaf`.
It supersedes readiness SHA-256
`544aa0dcf86b71aa5778e99d1c6ccc2e40af3320d21c18581e9299814e515b0f`
after the pre-result Windows path incident recorded in amendment 002.
It binds the implementation, command-line entry point, strict pose parser, and
six synthetic execution-contract tests by repository path, byte count, and
SHA-256.

## Execution guarantees

- The executor consumes primary plan SHA-256
  `31862a168e737d2d6d81ab9ce5eba3b316eb31225318300237b140a99c020feb`
  and re-hashes the executable, parser, receptors, and ligand inputs before
  allowing work to start.
- It resolves only the relative paths already frozen in that plan. There is no
  ligand reselection, target substitution, box reconstruction, or parameter
  translation.
- Each verified receptor and ligand is copied byte-for-byte into a bounded path
  under the create-only run root. Source and staged byte count and SHA-256 must
  agree, and an unsafe Windows external-tool path is rejected before the first
  entry attempt starts.
- Each parent owns create-only `attempt-NNN` evidence. A started but interrupted
  attempt is retained and resume creates the next attempt; only a hash-verified
  terminal record is skipped.
- Each terminal entry is written before aggregate completion. The public result
  manifest is withheld until all 11,412 parents have a terminal outcome.
- Fifteen independent Vina processes run concurrently with one thread each, as
  frozen. One failed or malformed ligand does not abort its neighbors.
- Actual commands, stdout, stderr, raw multi-pose PDBQT output, parser failures,
  and trace evidence remain under the ignored local run root. The public
  manifest exposes only relative evidence paths, sizes, hashes, structured
  poses, and terminal failure codes.
- Scores are accepted only from the strict `REMARK VINA RESULT` parser. A
  missing, malformed, non-sequential, or structurally invalid output is retained
  unscored; stdout is never parsed as a score.
- Preparation failures and future docking failures remain in the same
  pre-registered worst-ranked unscored tie. Metrics remain a separate later
  phase.

## Verification performed

Six synthetic tests close successful incremental execution and no-op resume,
per-ligand process failure isolation, malformed-output rejection, interruption
with preserved retry lineage, evidence/path tamper rejection, and pre-execution
Windows path-budget rejection. They invoke a
synthetic executor and therefore establish software behavior only, not docking
performance or scientific validity.

The full backend gate passes 607 tests. Ruff and strict mypy over 133 source
files pass, the public validation status remains synchronized, and the staged
public-path check rejects absolute workstation paths. Frontend and native code
were unchanged and retain their previous green gate.

## Authorized next boundary

The software boundary now permits execution or deterministic resume of the
three exact primary campaigns. The run must use the ignored local evidence root
and may publish a result manifest only after all 11,412 rows are terminal.
Sensitivity campaigns and metric calculation remain prohibited until the
primary run closes and its complete evidence independently verifies.
