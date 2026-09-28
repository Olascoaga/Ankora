# LIT-PCBA primary Vina metrics — 2026-09-28

Protocol ID: `LIT_PCBA_ANKORA_VS_V1`

Status: **the preregistered primary metrics reproduce from all 11,412 frozen
parents; sensitivity analyses have not yet been executed**.

The deterministic metric manifest is
[`reference_cases/LIT_PCBA_ANKORA_VS_V1.vina-primary-metrics.json`](reference_cases/LIT_PCBA_ANKORA_VS_V1.vina-primary-metrics.json),
with manifest SHA-256
`30da8aebc3bc601204146416c51d3a17227229b96c3efd7b41087074d6e0f873`.
It reads only the independently verified primary-result manifest SHA-256
`8bf2f4586c3c659267a945cc2d7b9bcc718dff1fedd5f54f8892a89d7945bd82`.

## Primary results

Intervals are deterministic 95% stratified-parent bootstrap intervals from
2,000 replicates with fixed target-specific active/inactive counts and seed
`20260911`.

| Target | EF1% (95% CI) | BEDROC alpha 20 (95% CI) | ROC-AUC (95% CI) | PR-AUC (95% CI) |
|---|---:|---:|---:|---:|
| ESR_antago | 4.441 (1.110–8.882) | 0.1503 (0.0955–0.2107) | 0.6635 (0.6042–0.7226) | 0.04497 (0.03493–0.06636) |
| PPARG | 4.162 (0.000–12.485) | 0.1503 (0.0560–0.2659) | 0.7312 (0.6387–0.8133) | 0.01722 (0.01034–0.05029) |
| TP53 | 3.044 (0.000–7.609) | 0.1059 (0.0513–0.1689) | 0.5987 (0.5264–0.6661) | 0.03606 (0.02261–0.07898) |
| **Equal-target macro** | **3.882 (1.108–7.398)** | **0.1355 (0.0926–0.1828)** | **0.6645 (0.6211–0.7065)** | **0.03275 (0.02709–0.05303)** |

The 1% cutoffs contain four of 88 ESR_antago actives in 40 positions, one of
24 PPARG actives in 41 positions, and two of 64 TP53 actives in 35 positions.
The equal-target macro gives each assay one third of the summary regardless of
library size.

## Interpretation

- The frozen Vina protocol shows positive but modest retrospective ranking
  signal across these three target sets. The macro ROC-AUC is above random
  ordering, while early enrichment is limited to seven active observations
  across the three 1% cutoffs.
- Early-enrichment uncertainty is substantial. PPARG has only 24 actives and
  both PPARG and TP53 EF1% intervals include zero. The point estimates must not
  be presented without their intervals.
- PR-AUC is the preregistered non-interpolated average precision at distinct
  score thresholds. It is prevalence-sensitive and is not interchangeable
  with ROC-AUC.
- All 165 unscored parents remain in the denominator as one worst tie. They are
  all experimental inactives, an observed imbalance disclosed in the primary
  result record rather than removed after outcomes were known.
- Scores from different targets are never pooled or compared numerically. The
  macro summary averages target-level metrics, not raw Vina affinities.

These results do not establish binding affinity, biological activity,
prospective hit rate, pose correctness, or performance across all LIT-PCBA
targets. They describe one exact Vina 1.2.7 protocol on three frozen
retrospective target sets.

## Reproduction boundary

The evaluator maps each canonical parent hash to one exact imported-state hash
and either its best structured Vina affinity or its retained failure code.
Exact score ties use fractional expected ranks, and failures form one complete
worst tie. The manifest records every formula, point estimate, interval,
population count, bootstrap parameter, source identity, and aggregate policy.

An independent `--check` invocation re-read the 48,071,157-byte primary result,
recomputed all 2,000 replicates, and reproduced metric-manifest SHA-256
`30da8aebc3bc601204146416c51d3a17227229b96c3efd7b41087074d6e0f873`.
No docking tool was invoked and no source result was modified.

## Next boundary

The frozen one-factor-at-a-time sensitivity program follows. Chemical-state,
alternate-receptor, expanded-box, seed, and exhaustiveness comparisons retain
their predeclared paired populations and cannot replace the primary table.
