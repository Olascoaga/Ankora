# Docking policy

AutoDock Vina 1.2.7 is the first implemented native-Windows engine. AutoDock4
is the accepted second scoring family under ADR-015: AutoGrid4 produces an
immutable map set, AutoDock4 CPU is the reproducible reference execution path,
and AutoDock-GPU 1.6 is an implemented optional accelerator with its own
explicit search protocol and non-bitwise-reproducibility warning. GNINA remains
deferred until an official native-Windows path exists.

The scientist chooses the engine, execution backend, input artifacts, search
space, random seed, search controls, and resource budget explicitly. Every run
retains the exact command or parameter files, executable version and hash,
input/output hashes, raw output, structured results, failures, and provenance.

AutoDock4 CPU preflight is per ligand. Stock AutoGrid4 4.2.6 is limited to 14
ligand affinity-map atom types and does not parameterize Meeko macrocycle glue
types such as `CG0`/`G0`. Ankora retains an affected molecule as an explicit
engine-incompatible row; it never coerces those pseudoatoms to carbon or drops
the molecule from the campaign denominator. The GPU route is separately
preflighted and may accept only inputs supported by its real verified
parser/tool contract; CPU incompatibility is never silently reclassified as
GPU compatibility.

The same build reports a separate ceiling of 20 receptor atom types, which
Ankora enforces independently of the ligand limit. A prepared receptor is not
expected to approach it, so exceeding it indicates an unexpected receptor
composition and must surface as an explicit preflight failure rather than a
truncated map set.

Vina poses and AutoDock4 clusters remain independent result models. Ankora may
show them side by side, but never merges their scores, invents a consensus
number, or labels either computational score as experimental affinity.

Vina and AutoDock4 results may be presented side by side, but only their
rankings are compared. Their scores come from different scoring functions on
different scales, so Ankora computes no combined, averaged, or consensus number
and exposes no field that could be read as one. What it does report is how much
the two independent orderings agree: Spearman's rank correlation over the
molecules both engines docked, and how many molecules both place in their own
top N. Those describe agreement between orderings and are never a score for any
molecule.

A comparison is refused unless both campaigns used the same receptor, the same
binding site, and the same applied selection manifest. Comparing rankings from
different experiments would produce a plausible-looking table that means
nothing.
