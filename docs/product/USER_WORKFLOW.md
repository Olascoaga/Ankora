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

M1-M8 are implemented. Later milestone numbering follows the visible workflow rather than the original bootstrap numbering:

- M6 Results: durable project-level campaign, compound, pose, cluster/run, comparison, and evidence review.
- M7 Validation: redocking against an immutable crystallographic reference with symmetry-aware RMSD and explicit recovery metrics.
- M8 Export: reproducible methodology and data bundles.
- M9 Pose Interactions: structured analysis and an Ankora-rendered 2D diagram for one exact preserved pose, integrated into Results rather than added as a ninth rail step.
