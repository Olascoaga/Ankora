# LIT-PCBA box and sentinel freeze — 2026-09-15

Protocol: `LIT_PCBA_ANKORA_VS_V1`

Outcome: **three numerical primary boxes, three expanded box-sensitivity
controls, and 96 chemical-state sensitivity parents were frozen before any
benchmark docking score or enrichment result existed**. The machine-readable
record is
[`reference_cases/LIT_PCBA_ANKORA_VS_V1.geometry-sentinels.json`](reference_cases/LIT_PCBA_ANKORA_VS_V1.geometry-sentinels.json).

## Co-crystal boxes

Each primary box comes from the exact primary-template `ligand.mol2` member
already identified by the source and template manifests. Only heavy atoms
contribute to the axis-aligned coordinate extrema. Explicit hydrogens are
counted as evidence but excluded because they are modeled chemical-state
coordinates rather than the crystallographic heavy-atom pose. The primary box
adds 5 Å on every face, matching Ankora's normal co-crystal-box default. The
box sensitivity control keeps the center fixed and adds 3 Å on every face, so
every size increases by exactly 6 Å.

| Target | Template | Heavy atoms (H excluded) | Center x, y, z (Å) | Primary size x × y × z (Å) | Expanded size (Å) |
|---|---|---:|---|---|---|
| ESR_antago | 5UFX | 34 (34) | −2.1045, −30.917, 21.77 | 17.181 × 20.268 × 22.648 | 23.181 × 26.268 × 28.648 |
| PPARG | 3B1M | 38 (26) | 11.741, 48.9585, 61.2305 | 22.02 × 17.279 × 21.035 | 28.02 × 23.279 × 27.035 |
| TP53 | 3ZME | 22 (19) | 91.9175, 94.1415, −45.6755 | 14.047 × 20.353 × 17.181 | 20.047 × 26.353 × 23.181 |

The manifest retains each source-member path, size, and SHA-256 plus its exact
coordinate bounds. These are search-space definitions, not evidence that the
co-crystallized ligand or any docked pose is biologically correct.

## Chemical-state sensitivity panel

The panel contains 16 active and 16 inactive parents per target: 96 parents in
total. This fixed, class-balanced panel is large enough to expose systematic
state sensitivity while bounding the additional state-enumeration and docking
work. It is not used to calculate the primary enrichment metrics.

Selection is data-independent after source canonicalization. Every parent is
ranked by SHA-256 of the protocol ID, target ID, class label, and RDKit
canonical isomeric SMILES separated by NUL bytes. Source member, physical line,
and source identifier break only a theoretical exact digest tie. The first 16
per target/class are retained. The manifest stores source location and
identifier plus hashes of both source and canonical SMILES; it does not copy
the library's molecular strings into Git.

For sensitivity execution, every bounded state of every sentinel parent must
be retained and reported as score/rank ranges. Selecting the best state for a
parent is forbidden. The primary cohort remains `exact_imported_state` for all
11,412 parents.

## Reproduction and fail-closed boundary

The manifest identity is
`fea2d678f492317d874492b7c21c5732a70cb0e056aead4c11b5f702aa7d57fb`.
Running `scripts/freeze_screening_benchmark_geometry.py --check` against the
exact ignored source archive rebuilds and compares the complete record. It
rejects changed archive/member hashes, unsafe members, changed target censuses,
unparseable or duplicated canonical parents, malformed/non-finite MOL2
coordinates, missing classes, and insufficient sentinel populations.

This unit does not convert or bless the source `protein.mol2` files. Exact
primary and alternate receptor intake must first prove that official and source
coordinates share a congruent frame, then freeze chain/component decisions,
repair, protonation review, and PDBQT identities. No docking may start until
that receptor boundary closes.
