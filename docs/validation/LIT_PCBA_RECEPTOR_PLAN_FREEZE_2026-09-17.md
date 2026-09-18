# LIT-PCBA receptor-plan freeze — 2026-09-17

Protocol: `LIT_PCBA_ANKORA_VS_V1`

Outcome: **six explicit receptor-preparation plans are frozen before any
PROPKA preview, receptor derivative, docking score, or enrichment result**.
The path-free machine record is
[`reference_cases/LIT_PCBA_ANKORA_VS_V1.receptor-plans.json`](reference_cases/LIT_PCBA_ANKORA_VS_V1.receptor-plans.json).

## Decisions fixed before execution

- Official RCSB PDBx/mmCIF coordinates are the only receptor-coordinate
  source. The paired source protein MOL2 is never converted into a receptor.
- Author chain A is selected for every template because every exact
  source-receptor coordinate match belongs to that one chain.
- All waters and co-crystal/solvent ligands are removed. The structural Zn in
  both TP53 structures is retained explicitly.
- Reported missing residues remain unmodelled; Ankora will not invent loops.
  Every incomplete observed residue is repaired, and repaired structures use
  the already validated restrained-relaxation contract.
- Polymer alternate locations are selected only when one deposited conformer
  uniquely matches the frozen source-receptor coordinates within 0.001 Å. All
  such choices are altloc A. This is not an occupancy heuristic: several B
  conformers have higher deposited occupancy but do not match the benchmark
  source coordinates.
- Protonation is fixed at pH 7.4 with the AMBER force field. An absent `OXT`
  is authorized only at the exact final observed polymer residue. That residue
  is described as a coordinate-model terminus, not as the biological sequence
  terminus.
- Final receptor creation remains blocked until each exact structural plan has
  produced a structured PROPKA preview and every proposal has been reviewed.
  Any override must be frozen before the corresponding final run.

## Inspection census

Water counts below cover the complete deposited structure; each request removes
the waters that belong to selected chain A. Issue counts cover chain A only.

| Target | Role | PDB | Waters | Missing residues | Missing-atom residues | Altloc issues | Retained components | Coordinate C terminus |
|---|---|---|---:|---:|---:|---:|---|---|
| ESR_antago | Primary | 5UFX | 616 | 15 | 6 | 8 | none | HIS A:547; OXT authorized |
| ESR_antago | Alternate | 2IOG | 184 | 3 | 1 | 0 | none | ALA A:551; OXT authorized |
| PPARG | Primary | 3B1M | 278 | 23 | 0 | 0 | none | TYR A:477; OXT already present |
| PPARG | Alternate | 5Y2T | 453 | 33 | 0 | 0 | none | LEU A:476; OXT authorized |
| TP53 | Primary | 3ZME | 512 | 24 | 0 | 13 | Zn A:313 | ARG A:290; OXT authorized |
| TP53 | Alternate | 5O1I | 425 | 23 | 6 | 16 | Zn A:401 | LYS A:291; OXT authorized |

The exact component and residue locators, distances to the co-crystal
reference, reported missing atom names, source-match counts for every altloc,
and complete typed `ReceptorPreparationRequest` are retained per template.
The 5O1I issue census includes six alternate waters and the altloc-A
co-crystal ligand; their explicit issue actions are `remove`, consistent with
the frozen water/component policy.

## Reproduction and boundary

Manifest SHA-256:
`117bc6a50589b0f02c952584291598b5f3aeeaa29d54d127e63dc0bfb21fae55`.

`scripts/freeze_screening_benchmark_receptor_plans.py --check` rebuilds the
record from the exact source archive, structure manifest, and ignored official
structure bytes without invoking PDBFixer, PDB2PQR, PROPKA, Meeko, or a docking
engine. The verifier rejects changed official bytes, changed source members,
an ambiguous source-aligned alternate location, a missing selected chain or
reference component, an unsupported issue, and any manifest drift.

This freeze is not a claim that a receptor is docking-ready. The next bounded
unit must execute all six create-only PROPKA previews, retain their raw
evidence, review every proposal, and freeze any exact protonation overrides
before final receptor creation. No docking result exists.
