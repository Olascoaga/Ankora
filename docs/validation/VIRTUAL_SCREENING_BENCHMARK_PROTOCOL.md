# Virtual-screening benchmark protocol

Protocol ID: `LIT_PCBA_ANKORA_VS_V1`

Status: **evaluation contract, target cohort, exact AVE-unbiased source,
templates, numerical boxes, chemical-state sentinels, official structure
bytes, coordinate frames, six explicit receptor plans, and six structured
protonation previews frozen before docking**. Scientist review is pending and
no enrichment result exists yet.

The first acquisition attempt is recorded in
[`LIT_PCBA_SOURCE_ACQUISITION_2026-09-11.md`](LIT_PCBA_SOURCE_ACQUISITION_2026-09-11.md).
The exact maintainer archives were acquired and identified. A pre-result
amendment records that the frozen counts correspond to the AVE-unbiased
training-plus-validation population rather than the differently sized `full`
archive. A derived nine-target Zenodo archive failed the source contract and
was not substituted. The fail-closed inspector generated the path-free
[`reference_cases/LIT_PCBA_ANKORA_VS_V1.inputs.json`](reference_cases/LIT_PCBA_ANKORA_VS_V1.inputs.json)
manifest without executing docking.

The subsequent pre-result
[`LIT_PCBA_TEMPLATE_SELECTION_2026-09-14.md`](LIT_PCBA_TEMPLATE_SELECTION_2026-09-14.md)
record freezes primary/alternate holo templates by best experimental resolution
with PDB ID as an exact-tie breaker. The complete 36-candidate RCSB metadata
snapshot and selected source-member hashes are preserved in
[`reference_cases/LIT_PCBA_ANKORA_VS_V1.templates.json`](reference_cases/LIT_PCBA_ANKORA_VS_V1.templates.json).

The next pre-result record,
[`LIT_PCBA_BOX_AND_SENTINEL_FREEZE_2026-09-15.md`](LIT_PCBA_BOX_AND_SENTINEL_FREEZE_2026-09-15.md),
derives three exact numerical co-crystal boxes and selects 96 chemical-state
sensitivity parents without looking at a score. The path-free
[`reference_cases/LIT_PCBA_ANKORA_VS_V1.geometry-sentinels.json`](reference_cases/LIT_PCBA_ANKORA_VS_V1.geometry-sentinels.json)
reproduces from the exact source archive, source-population manifest, and
template manifest.

The official-structure intake record,
[`LIT_PCBA_STRUCTURE_INTAKE_2026-09-15.md`](LIT_PCBA_STRUCTURE_INTAKE_2026-09-15.md),
hashes the six selected RCSB mmCIF files and proves their coordinate frames
against the exact paired source receptor and ligand MOL2 files without fitting
or superposition. The path-free
[`reference_cases/LIT_PCBA_ANKORA_VS_V1.structures.json`](reference_cases/LIT_PCBA_ANKORA_VS_V1.structures.json)
retains the exact chain, co-crystal residue, alternate-location, coordinate,
and source-preparation-difference evidence.

The receptor-plan record,
[`LIT_PCBA_RECEPTOR_PLAN_FREEZE_2026-09-17.md`](LIT_PCBA_RECEPTOR_PLAN_FREEZE_2026-09-17.md),
turns those inspections into six complete typed structural requests before any
scientific tool is run. The path-free
[`reference_cases/LIT_PCBA_ANKORA_VS_V1.receptor-plans.json`](reference_cases/LIT_PCBA_ANKORA_VS_V1.receptor-plans.json)
selects chain A, removes waters and co-crystal/solvent ligands, retains the two
TP53 structural zinc ions, leaves missing loops unmodelled, repairs reported
missing atoms, and selects only the source-coordinate-matched altloc A. Final
receptor creation remains gated on six structured PROPKA previews and review.

The review-only preview execution is recorded in
[`LIT_PCBA_PROTONATION_PREVIEW_2026-09-17.md`](LIT_PCBA_PROTONATION_PREVIEW_2026-09-17.md).
All six plans completed with PDB2PQR 3.7.1 and PROPKA 3.5.1, producing 449
structured proposals, of which 102 carry one or more focused-review flags. The
path-free
[`reference_cases/LIT_PCBA_ANKORA_VS_V1.protonation-previews.json`](reference_cases/LIT_PCBA_ANKORA_VS_V1.protonation-previews.json)
retains the exact proposals and evidence hashes. No default or override is yet
accepted, and the previews were not promoted to final receptors or PDBQT. The
retained TP53 outputs expose a blocking tautomer issue: automatic neutral
HIS179 protonates the ND1 atom that coordinates zinc. Explicit neutral
histidine-tautomer control and corrected TP53 previews are therefore required
before scientific review can close.

This protocol initiated adversarial-audit point 26. The machine-readable
source of truth is
[`reference_cases/LIT_PCBA_ANKORA_VS_V1.spec.json`](reference_cases/LIT_PCBA_ANKORA_VS_V1.spec.json).
Any scientific change after this commit requires a numbered amendment written
before looking at docking scores. An unavailable source or infeasible protocol
may stop the run; it may not be silently replaced.

## Evidence hierarchy and cohort

The primary evidence uses LIT-PCBA because its labels come from
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
page](https://lab.drugdesign.unistra.fr/datasets/lit-pcba/) and close exactly
against the AVE-unbiased archive when its supplied training and validation
rows are combined. The acquired archive and every used member are hashed in
the input manifest. It records 176 active and 11,236 inactive rows with zero
unparsed rows, within-class duplicates, or cross-class canonical conflicts.
Preparation failures, scored compounds, and unscored compounds remain future
execution accounting and may not disappear from these denominators.

Before extraction or docking, the project ran
`scripts/inspect_screening_benchmark_source.py` against the frozen specification
and exact archive. The inspector rejects missing or mismatched target
censuses and template pairs, unsafe members, and ambiguous archive paths. Its
path-free manifest records archive/member SHA-256 identities plus duplicate,
parse-failure, and cross-label-conflict accounting. It also verifies the hash,
protocol identity, and pre-result declaration of Amendment 001.

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
intervals over parent compounds with fixed active/inactive counts (2,000
replicates, seed `20260911`). Percentiles use linear interpolation at
`(replicates - 1) * p`. Per-target resamples at the same replicate index are
macro-averaged, so the macro interval also gives every target equal weight.
With only 24 reported PPARG actives, uncertainty is part of the result rather
than a footnote.

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
  the acquired LIT-PCBA source. Primary PDB identifiers are frozen as 5UFX,
  3B1M, and 3ZME; alternates are 2IOG, 5Y2T, and 5O1I. Exact primary box
  coordinates are frozen from the heavy atoms in the corresponding source
  ligand MOL2 with 5 Å padding on each face; modeled explicit hydrogens cannot
  move the bounds. Official mmCIF bytes for all six structures are now hashed,
  and every source ligand heavy atom matches its official co-crystal residue
  at the same Cartesian coordinate within 0.001 Å without superposition.
  Exact structural preparation requests are frozen for all six templates.
  Their pH 7.4 AMBER protonation previews have executed without creating final
  receptors. Scientist review and a frozen default/override decision set remain
  mandatory before any final receptor PDBQT or library docking begins.

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

Exact template, box, sentinel, official-structure, coordinate-frame, and
structural receptor-plan and protonation-preview identities are closed. The sentinel panel contains
16 active and 16 inactive parents per target, ranked solely by a
protocol/target/class/canonical-state SHA-256 key. Scientist acceptance or
override of the recorded PROPKA proposals and final prepared-receptor identities remain the final open pre-execution deliverable,
not a post-result choice. The source `protein.mol2` files are exact benchmark
inputs, but they are not silently relabelled as Ankora docking-ready receptor
derivatives.

## Claims this protocol cannot establish

- Docking score is not binding free energy, potency, or biological activity.
- Three target sets do not establish performance across the LIT-PCBA universe
  or prospective screening campaigns.
- Retrospective enrichment cannot validate a favorable individual pose; pose
  recovery remains a separate redocking question.
- Dataset curation, target/template selection, duplicates, and assay artifacts
  can still bias results. Every census and deviation remains visible.
