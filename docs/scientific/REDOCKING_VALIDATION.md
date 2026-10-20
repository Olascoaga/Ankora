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
