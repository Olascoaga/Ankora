# User workflow

The persistent workflow is:

1. Structure
2. Receptor
3. Ligand
4. Binding site
5. Docking
6. Results
7. Validation
8. Export

Every scientific stage follows `Inspect -> Decide -> Apply -> Review -> Continue`. Users may inspect prior stages without automatically deleting later artifacts. Changing an upstream decision marks dependent outputs stale.

Binding Site opens with a full-protein box for immediate visual orientation,
but that preview is not a saved scientific decision. Finalizing a blind
whole-receptor search requires an explicit exploratory-use acknowledgement.
Docking then shows the exact box volume and sampling guidance beside Vina's
unchanged, scientist-controlled exhaustiveness.

For Vina, choose the purpose of the next calculation before confirming it:
`Screening` provides throughput-oriented starting values, `Pose refinement`
provides a deeper starting point for a focused shortlist, and `Custom` records
scientist-edited values. Changing a sampling value automatically changes the
purpose to Custom and clears the previous confirmation. A purpose label does
not establish convergence or make a calculation suitable for publication;
record a system-specific sensitivity or convergence study when that claim is
needed.

M1-M8 are implemented. Later milestone numbering follows the visible workflow rather than the original bootstrap numbering:

- M6 Results: durable project-level campaign, compound, pose, cluster/run, comparison, and evidence review.
- M7 Validation: redocking against an immutable crystallographic reference with symmetry-aware RMSD and explicit recovery metrics.
- M8 Export: reproducible methodology and data bundles.
- M9 Pose Interactions: structured analysis and an Ankora-rendered 2D diagram for one exact preserved pose, integrated into Results rather than added as a ninth rail step.
