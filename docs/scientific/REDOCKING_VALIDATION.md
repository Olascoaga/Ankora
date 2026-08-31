# Redocking validation

Redocking validation is implemented as M7. It consumes Ankora's immutable crystallographic reference and an already-preserved docking result, records a create-only verdict beside rather than inside that result, calculates configurable symmetry-aware heavy-atom RMSD without aligning the pose first, and reports Top-1, best Top-5, best overall, first pose under threshold, sampling success, and ranking success separately.

The default criterion is RMSD <= 2.0 Å. Passing means only that the evaluated configuration recovered the reference pose under the documented criterion.
