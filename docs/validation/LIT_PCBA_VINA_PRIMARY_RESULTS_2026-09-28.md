# LIT-PCBA primary Vina results — 2026-09-28

Protocol ID: `LIT_PCBA_ANKORA_VS_V1`

Status: **all 11,412 frozen parent compounds have one independently verified
terminal primary-Vina outcome; ranking metrics have not yet been computed**.

The path-free public result manifest is
[`reference_cases/LIT_PCBA_ANKORA_VS_V1.vina-primary-results.json`](reference_cases/LIT_PCBA_ANKORA_VS_V1.vina-primary-results.json),
with internal manifest SHA-256
`8bf2f4586c3c659267a945cc2d7b9bcc718dff1fedd5f54f8892a89d7945bd82`.
It is bound to the pre-result campaign-plan SHA-256
`31862a168e737d2d6d81ab9ce5eba3b316eb31225318300237b140a99c020feb`
and the corrected pre-result executor-readiness SHA-256
`e0cebb75175daff18bb4326101739535546a3d650858a86f2948914bde786696`.

## Closed population

| Target | Frozen parents | Scored | Docking failure | Preparation-unscored | Total worst tie |
|---|---:|---:|---:|---:|---:|
| ESR_antago | 3,908 | 3,855 | 13 | 40 | 53 |
| PPARG | 4,095 | 4,024 | 30 | 41 | 71 |
| TP53 | 3,409 | 3,368 | 12 | 29 | 41 |
| **Total** | **11,412** | **11,247** | **55** | **110** | **165** |

All 176 active parents produced a primary Vina score. The 165 unscored parents
are all experimental inactives: 107 exact source states required a
stereochemical decision forbidden by the frozen protocol, three failed
ETKDGv3 conformer generation, 25 exceeded the frozen per-ligand Vina timeout,
and 30 ended with a non-zero Vina exit code. This observed class imbalance is
not a reason to remove those parents. All 165 remain one worst-ranked tie in
every preregistered primary metric.

## Execution and verification evidence

- AutoDock Vina version: `1.2.7`; executable SHA-256
  `e0c4b2715e0c1a74f6e92d0f3be0328ac97542eafbc111e6b1efad897a73cce5`.
- Parameters: seed `20260911`, exhaustiveness `8`, nine modes, minimum RMSD
  `1.0 A`, energy range `3 kcal/mol`, and a 360-minute per-ligand timeout.
- Allocation: 15 concurrent one-thread Vina processes, fixed before outcomes.
- Scores were read only from the strict structured PDBQT parser; stdout was
  retained as raw evidence and was never treated as a score source.
- A scientist-requested pause retained 15 interrupted attempts. Resume
  re-hashed and skipped every already terminal row, preserved the partial
  attempts, and closed exactly those 15 rows under create-only `attempt-002`
  evidence. No prior attempt was overwritten.
- The independent verifier reconciled source order, target/class identity,
  preparation status, exact input hashes, terminal records, parsed poses,
  artifact byte counts and SHA-256 values for all 11,412 parents.
- Raw commands, staged inputs, stdout, stderr, PDBQT poses, and terminal records
  remain in ignored local evidence storage. The public manifest contains only
  repository/run-relative evidence references and hashes.

The two earlier Windows path-transport roots remain technical incident evidence
only. They produced no pose or score and are excluded by amendment 002; neither
was resumed or incorporated into this result.

## Scientific boundary

This result closes execution and integrity only. It does not establish
enrichment, affinity, activity, pose correctness, prospective performance, or
cross-target score comparability. The manifest deliberately records
`metrics_computed: false` and result status
`all_primary_vina_entries_terminal_failures_retained_metrics_not_computed`.

The next bounded unit computes the four preregistered measures from this exact
manifest: EF1%, BEDROC with alpha 20, tie-aware ROC-AUC, and non-interpolated
average precision. It must report per-target point estimates and deterministic
95% stratified-parent bootstrap intervals, followed by an equal-target macro
summary. No sensitivity result may replace this primary analysis.
