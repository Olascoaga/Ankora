# ADR-018: Exploratory search spaces and explicit Vina sampling

- Status: Accepted
- Date: 2026-09-04

## Context

A full-protein box is the only search-space preview that Ankora can compute for
every docking-ready receptor without assuming a known ligand or pocket. It is
therefore useful as the initial visual state, but its universal availability
does not make it a validated binding site. Persisting that box with the same
friction as a focused site can turn a navigation default into an unintended
scientific decision.

AutoDock Vina 1.2.7 also emits a runtime warning when a search-space volume
exceeds 27,000 A^3. Larger spaces are harder to sample, but there is no
universal, system-independent conversion from box volume to a correct
exhaustiveness. Silently increasing exhaustiveness would conceal a protocol
change and still would not establish convergence.

## Decision

Binding Site continues to open with a read-only, non-persistent full-protein
preview. A new full-protein source record can be created only after the
scientist explicitly acknowledges that the box represents a blind exploratory
search rather than a validated site. The acknowledgement is recorded in the
immutable binding-site request and enforced by the backend, not only by the
interface. Existing finalized records remain readable.

Ankora computes the exact rectangular volume for every Vina setup. Above
27,000 A^3 it creates a structured `DOCKING_SEARCH_SPACE_LARGE` warning that
records the volume, threshold, ratio, selected exhaustiveness, binding-site
source, and the fact that Ankora changed no parameters. The warning is retained
on single-ligand and library campaigns and propagated into their provenance.

The interface presents the same threshold before a large box is finalized and
shows volume-aware guidance beside Vina's explicit controls. It recommends a
narrower scientifically justified site or a recorded sensitivity series at
increasing exhaustiveness. It never claims that a particular exhaustiveness is
adequate and never changes it automatically.

## Consequences

- Visiting Binding Site still provides immediate spatial context without
  creating an artifact.
- A whole-receptor search now requires an additional explicit scientific
  decision.
- Large Vina searches remain possible and fully user-controlled, but the risk
  cannot disappear into raw stderr.
- Publication suitability depends on recorded sampling-sensitivity evidence,
  not on crossing a hard-coded preset.
