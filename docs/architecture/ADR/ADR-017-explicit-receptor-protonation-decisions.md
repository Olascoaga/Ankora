# ADR-017: Explicit receptor protonation decisions

- Status: Accepted
- Date: 2026-09-03

## Context

PDB2PQR uses PROPKA pKa estimates to choose residue protonation states at a
requested pH. Those estimates are model predictions, not experimental
observations. Residues near the binding-site reference, metal ions, a pKa close
to the requested pH, or another coupled titration group can require scientific
judgement. A single global pH control hides those local ambiguities, while
editing hydrogens after PDB2PQR would bypass the tool's topology, optimization,
charge, and radius assignment.

PDB2PQR 3.7.1 also cannot represent every predicted state with every force
field. In particular, its AMBER path warns rather than applying neutral
termini, neutral ARG, deprotonated TYR, and some terminal side-chain states.
Ankora must not offer an override that the producing tool will ignore.

## Decision

Before creating a protonated receptor, Ankora runs the exact selected-chain,
component, residue-repair, relaxation, force-field, and pH plan in an isolated
temporary workspace. The scientist reviews a structured proposal for every
supported titratable side chain and terminus. Each proposal keeps these values
separate:

- the PROPKA pKa and pH-derived predicted state;
- the state PDB2PQR/AMBER can actually apply by default;
- the scientist-selected state; and
- whether that selection came from the prediction or an explicit override.

The review marks residues within the inspection's recorded reference-distance
cutoff, residues within 4.0 A of a retained metal, pKa values within one unit of
the requested pH, and coupled titration groups. These are review warnings, not
automatic state changes. Distances are calculated from the immutable source
coordinate frame already used by receptor inspection.

AMBER overrides are limited to states that PDB2PQR 3.7.1 can apply safely:
ASP/ASH, GLU/GLH, CYS/CYM, HIS neutral-auto/HIP, and LYS/LYN, with the
tool-specific terminal restrictions enforced. Insertion-code overrides are
rejected because PDB2PQR's pKa assignment key does not retain that identity.
Unsupported predicted states remain visible as limitations but cannot be
selected.

An explicit override changes only the pKa branch presented to PDB2PQR inside
an isolated worker process. PDB2PQR still performs its own topology patching,
hydrogen optimization, force-field charge/radius assignment, and file output.
Ankora never applies a post-hoc hydrogen edit.

The preview is review material, not a retained scientific result. Any change
to the structural or protonation plan invalidates it. Final receptor creation
reruns the exact plan and preserves that execution's raw PDB2PQR log,
structured proposals, explicit overrides, tool versions, command, output
artifacts, and provenance.

## Consequences

- A protonated receptor requires an additional explicit review step.
- Preview and final creation run PDB2PQR separately; this costs time but avoids
  promoting temporary review output into immutable evidence.
- PROPKA remains a prediction aid. Ankora records scientist overrides without
  describing either the prediction or the choice as an experimentally known
  protonation state.
- New force fields or residue-state overrides require tool-specific validation
  before they can be exposed.
