# Virtual-screening benchmark protocol

Protocol ID: `LIT_PCBA_ANKORA_VS_V1`

Status: **evaluation contract and target cohort frozen before acquisition or
docking**. No enrichment result exists yet.

This is the first bounded unit of adversarial-audit point 26. The machine-
readable source of truth is
[`reference_cases/LIT_PCBA_ANKORA_VS_V1.spec.json`](reference_cases/LIT_PCBA_ANKORA_VS_V1.spec.json).
Any scientific change after this commit requires a numbered amendment written
before looking at docking scores. An unavailable source or infeasible protocol
may stop the run; it may not be silently replaced.

## Evidence hierarchy and cohort

The primary evidence will use LIT-PCBA because its labels come from
confirmatory PubChem dose-response assays and include measured inactives. The
authors report 15 final target sets, 7,844 confirmed actives, and 407,381
confirmed inactives after assay-artifact and physicochemical-bias controls
([original article, DOI 10.1021/acs.jcim.0c00155](https://doi.org/10.1021/acs.jcim.0c00155)).
That design makes it preferable to generated decoys, but does not make it a
ground truth for affinity or prospective activity.

The frozen primary cohort contains the three distinct target/phenotype sets
that fit Ankora's current per-campaign capacity, have at least 20 reported
actives, and have no more than 5,000 reported compounds:

| Set | PubChem AID | Reported actives | Reported inactives | Reported templates |
|---|---:|---:|---:|---:|
| ESR_antago | 743080 | 88 | 3,820 | 15 |
| PPARG | 743094 | 24 | 4,071 | 15 |
| TP53 | 651631 | 64 | 3,345 | 6 |

These source censuses come from the [maintainer's LIT-PCBA dataset
page](https://lab.drugdesign.unistra.fr/datasets/lit-pcba/). Acquisition must
preserve and hash the exact archive and used members, then reconcile raw,
parsed, duplicate, conflict, preparation-failure, scored, and unscored counts.
The reported counts are expectations to check, not values to force.

DUD-E may later be run only as a secondary decoy diagnostic. Its original
construction provides property-matched, topologically dissimilar computational
decoys ([original article, DOI 10.1021/jm300687e](https://doi.org/10.1021/jm300687e)).
That construction can make enrichment sensitive to analogue and decoy bias;
DUD-E therefore cannot establish performance on measured inactives, affinity,
biological activity, or ligand-based/ML generalization. Its results must never
be pooled with LIT-PCBA.

## Frozen ranking unit and loss accounting

- One canonical parent compound is one ranking unit. Its duplicate key is the
  RDKit canonical isomeric SMILES of the sanitized source graph, without
  uncharging, tautomerization, fragment removal, or other chemical rewriting.
  Exact duplicates are not extra evidence; the same key appearing in both
  classes is quarantined as a label conflict.
- One exact prepared chemical state is linked to each primary ranking unit.
  Enumerating states and retaining the most favorable score is forbidden in
  the primary analysis.
- All frozen parents remain in every denominator. Parsing, preparation,
  docking, or score-reading failures form one worst-ranked tie group. They are
  never dropped from the metric table.
- Lower scores rank more favorably within an engine. Engine families and
  scoring functions are evaluated separately; their numeric values are never
  pooled.
- Equal scores receive fractional top-cutoff membership and expected rank
  within their complete tie group. Input-file order therefore cannot alter a
  metric.

## Frozen metrics

Metrics are reported per target and as an equal-target macro average. There is
no pooled micro-average, because a large assay must not decide the claim for
the other targets.

- **EF1%:** `ceil(0.01 * N)` ranking positions; a tie crossing the boundary
  contributes its expected fractional number of actives.
- **BEDROC:** alpha `20.0`, normalized as defined by Truchon and Bayly
  ([original article, DOI 10.1021/ci600426e](https://doi.org/10.1021/ci600426e));
  exact-score ties use the mean exponential weight over their occupied ranks.
- **ROC-AUC:** probability that an active ranks above an inactive, with half
  credit for an exact tie.
- **PR-AUC:** non-interpolated average precision evaluated at distinct score
  thresholds. The label `PR-AUC` is never used without this definition.

Point estimates must be accompanied by deterministic 95% stratified bootstrap
intervals over parent compounds (2,000 replicates, seed `20260911`). With only
24 reported PPARG actives, uncertainty is part of the result rather than a
footnote.

## Primary preparation and docking boundary

- The complete source sets are evaluated; Ankora's Lipinski, Veber, Ghose,
  Muegge, QED, PAINS, and Brenk views are descriptive only. Excluding molecules
  with those filters would change class prevalence after the benchmark was
  defined.
- Primary chemical state is `exact_imported_state`; ETKDGv3 and MMFF94s use
  recorded deterministic seeds and the existing converged-only selection
  policy. Every failure remains in the ranking denominator.
- AutoDock Vina `1.2.7` is the first engine. The screening protocol uses seed
  `20260911`, exhaustiveness `8`, maximum poses `9`, minimum RMSD `1.0 A`, and
  energy range `3 kcal/mol`. The executable hash and observed version must be
  captured at execution.
- Each target uses one exact holo receptor and its co-crystallized ligand from
  the acquired LIT-PCBA source. Exact PDB identifiers, receptor preparation,
  and box coordinates must be frozen in an input manifest before any library
  docking begins.

## Sensitivity boundary

Sensitivity is one-factor-at-a-time and is never allowed to replace the
primary result. The exact paired population is held constant for each
comparison.

1. **Chemical state:** retain every bounded pH-state score for a predeclared
   hash-selected sentinel panel; report score/rank ranges per parent rather
   than selecting the best state.
2. **Receptor:** primary holo structure versus one predeclared alternate
   experimental holo structure of the same phenotype.
3. **Box:** primary co-crystal box versus the same center with `+3.0 A` on
   every face.
4. **Seed:** `20260911`, `20260912`, and `20260913` with all other settings
   unchanged.
5. **Sampling:** exhaustiveness `8` versus `32` with the primary seed.

Exact receptor and sentinel identities remain an acquisition deliverable, not
a post-result choice. The acquisition manifest must close those fields before
execution.

## Claims this protocol cannot establish

- Docking score is not binding free energy, potency, or biological activity.
- Three target sets do not establish performance across the LIT-PCBA universe
  or prospective screening campaigns.
- Retrospective enrichment cannot validate a favorable individual pose; pose
  recovery remains a separate redocking question.
- Dataset curation, target/template selection, duplicates, and assay artifacts
  can still bias results. Every census and deviation remains visible.
