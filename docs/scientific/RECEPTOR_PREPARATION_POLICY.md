# Receptor preparation policy

M2 separates observation, decision, and transformation. Loading the Receptor step first creates a read-only inspection report from the immutable original; it does not prepare coordinates.

## Required decisions

- Select one or more polymer chains explicitly.
- Keep or remove water explicitly for the whole preparation.
- Keep or remove every non-water component on selected chains explicitly.
- Resolve every reported residue issue on selected chains with one allowed action.
- Choose a specific alternate-location label when resolving an alternate location.
- Resolve `manual_review` before any derivative can be created.
- Enable protonation and record pH/force field explicitly before requesting PDBQT.
- Resolve every observed missing-atom, alternate-location, or nonstandard-residue issue before protonation; `Leave unchanged` remains valid only when protonation is disabled for that derivative.

No bulk action is implicit. The UI may help populate decisions, but the submitted request contains each resulting choice.

## Defects and proximity

Missing residues, missing atoms, alternate locations, and nonstandard polymer residues are reported at residue level. If the scientist selects a reference component, Ankora computes the minimum distance between its observed atoms and the observed atoms of each affected residue. Distances at or below 8.0 Å are classified `near_reference`; larger distances are `remote`; issues without measurable coordinates or a reference are `unassessed`.

The proximity label informs review but never selects an action. Missing atoms and alternate locations may be repaired; other issue types may be left, removed, or sent to manual review. A missing residue has no coordinates for M2 to reconstruct, so M2 does not offer automatic loop building.

## Transformations

The first derivative contains only the selected first coordinate model, chains, components, water policy, residue removals, and chosen alternate locations. PDBFixer is invoked only for explicitly selected missing-atom repairs; automatic loop addition and nonstandard-residue replacement are disabled. PDB2PQR invokes PROPKA with recorded pH and force field. Because PDB2PQR normally repairs missing heavy atoms while adding hydrogens, Ankora blocks protonation if an observed incomplete/ambiguous residue remains `Leave unchanged`. After PDB2PQR finishes, Ankora compares input/output heavy-atom identities and rejects any unapproved addition or removal. Meeko reads the resulting PQR and is forced to use `--charge_model read` so it preserves the calculated partial charges.

A scientist may explicitly authorize an `OXT` completion only for the exact final polymer residue of a selected chain after reviewing a preserved PDB2PQR failure. The authorization records chain, residue name/number/insertion code, and atom name in the preparation request and provenance. Ankora verifies that the residue is still terminal and lacks `OXT`; the permission does not cover any other added atom or any removal. Disabling protonation clears the permission.

Every receptor run receives a unique create-only directory. Outputs include stage, filename, format, size, SHA-256, timestamp, and source relationship. Provenance includes tool/package versions, parameters, exact argument-array command, and raw logs. External-tool failures retain their stdout, stderr, command, stage, and structured failure record. Original imported bytes are never modified.

If Meeko rejects PQR connectivity, Ankora reuses Meeko's residue parser and structured inter-residue bond finder to identify invalid residue blocks or residue pairs, then maps actionable residues back to the original inspection report. Normal peptide C–N connections and CYS SG–SG disulfides are not classified as recovery targets; multiple bonds or other atom pairs are. The UI may offer an explicit control to change the affected issue decisions to `Remove`; this only edits the visible plan. It never removes residues or starts another transformation until the scientist reviews the menus and presses Apply again.
