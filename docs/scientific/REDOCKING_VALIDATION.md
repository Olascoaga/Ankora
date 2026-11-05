# Redocking validation

Redocking validation is implemented as M7. It consumes Ankora's immutable crystallographic reference and an already-preserved docking result, records a create-only verdict beside rather than inside that result, calculates configurable symmetry-aware heavy-atom RMSD without aligning the pose first, and reports Top-1, best Top-5, best overall, first pose under threshold, sampling success, and ranking success separately.

The default criterion is RMSD <= 2.0 Å. Passing means only that the evaluated configuration recovered the reference pose under the documented criterion.

## Input admission and desktop workflow (2026-10-20)

Validation accepts completed individual Vina, AutoDock4 CPU or AutoDock-GPU
results. A screening campaign is not an individual redocking experiment. The
scientist first performs the docking in Docking, then explicitly chooses that
result, an original crystallographic ligand and a threshold in Validation.
No docking is launched by this measurement.

New measurements require a preserved 3D crystallographic extraction with an
exact residue locator, from the receptor's original structure. Byte-identical
reimports of that original are accepted by source SHA-256, not by PDB name or
ligand similarity. Local imports and prepared/minimized conformers are not
crystallographic references. Reference and pose bytes must match their recorded
SHA-256 and size; heavy-atom counts and molecular graph mapping must agree.
Incompatible or altered inputs produce a structured failure and no verdict.

The new paginated reference listing is project-scoped. Historical validation
records remain readable without rewriting them or rerunning any benchmark.
The RMSD itself does not establish repeatability; the historical repeatability
field is source metadata, not a conclusion of this measurement.

## GNINA single jobs (2026-11-04, backend only)

Validation also accepts a completed GNINA single job as a source, on Linux,
through the same measurement and the same admission rules. The RMSD definition,
threshold, two verdicts and immutable reference frame are unchanged.

GNINA's poses are measured in the engine's own mode order, which is its
descending CNN pose score. They are never re-sorted by the minimized affinity,
because `ranking_success` has to be about the ranking the engine produced. A
validated pose may therefore carry the dimensionless CNN pose score and the
predicted CNN affinity in pK beside — never inside — the minimized empirical
affinity in kcal/mol. All three are predictions of that engine for that pose,
none is a measured affinity, and none shares a scale with a Vina score or an
AutoDock4 binding energy.

Repeatability is recorded as not assessed for a GNINA source rather than as
`false`: no GNINA repeat evidence exists yet, so neither answer has been
measured. The verdict's provenance keeps the identities the GNINA job recorded
for its own executable, docking receptor, prepared ligand and conformer, with
its CNN configuration and compute selection, so the verdict names the exact run
it judged. Removing the GNINA result moves its verdicts with it.

Recovering one reference pose with GNINA would validate that configuration on
that system only. No GNINA reference case is frozen, there is no UI entry point
yet, and native Linux workstation acceptance remains pending. See
`docs/validation/GNINA_REDOCKING.md` and ADR-027.
