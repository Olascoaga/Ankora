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

## Optional repair relaxation and recovery

New UI requests explicitly select the versioned `topology_guard_v3` construction
method, seed and recorded OpenMM Reference platform. It keeps observed atoms
fixed during reconstruction, retains native bonded geometry with stronger
new-atom bond restraints, and checks repaired connectivity and template
chirality before protonation, then PQR connectivity after hydrogenation.
This is separate from optional elastic relaxation and is not full receptor
minimization. Historical requests/records without the method remain `legacy`;
restoring one never silently upgrades it. See
[ADR-025](../architecture/ADR/ADR-025-topology-guarded-receptor-repair.md) for the
exact protocol, rejected candidates, validation boundary and limitations.

The completed guard also rejects reconstructed template-known bonds whose
length differs by more than 0.2 Å and explains incompatible fixed-anchor spans.
This internal safeguard does not prove optimal geometry. In original 7AQF,
ARG A:300's observed CD/CZ anchors cannot accommodate normal bonds through
missing NE; the current guard rejects that plan before protonation despite a
preliminary Meeko-accepted output. Moving/rebuilding observed side-chain atoms
requires a new explicit protocol and scientific authorization, not an automatic
fallback to a looser check or successive residue deletion.

The opt-in OpenMM declash stage acts after explicit missing-atom repairs.
Selecting an alternate conformation is not a PDBFixer atom repair. The existing
repulsive potential and bond tethers are not a full biomolecular force field;
observed atoms have elastic positional restraints, not frozen coordinates.
Ankora rejects an attempt if an originally observed heavy atom moves more than
0.5 Å. This is an internal acceptance safeguard, not a universal chemical
criterion or proof of an irreparable steric clash.

New tolerance failures retain the maximum displacement and threshold plus every
exceeded atom's exact residue locator, name, measured displacement and coordinates
before/after. The list is ordered by descending displacement, with deterministic
identity tie-breaking, and residue identities are deduplicated. All raw worker
logs and failed-stage PDB files remain in the original failed attempt.

The interface offers inspection of the original residue in 3D and an explicit
draft-only option to disable relaxation. It never infers a residue to remove or
automatically retries. Skipping relaxation does not establish acceptable repaired
geometry. A checked relaxation option remains possible to turn off when no
missing-atom repairs remain; unresolved manual-review decisions still block Apply.
Advanced force/iteration settings remain available but folded by default.

Failures are bound to the attempted decision snapshot. Subsequent plan edits
label the error as belonging to a previous plan, while preserving its technical
evidence. Older failures without atom identities remain readable without inferred
locators. The 0.5 Å threshold, worker potential, defaults and coordinate acceptance
rules are unchanged by this diagnostic/recovery correction.

## Guided preparation and review recovery

New guided plans explicitly use inspection method `templates_v1`: source-reported
issues are merged by exact residue identity with a read-only standard amino-acid
heavy-atom name comparison. Templates come from RDKit's `MolFromSequence`; its
version and the inspection policy are recorded. The 20 standard residue name
sets are independently cross-checked against native PDBFixer templates.

The comparison uses positive-occupancy atom names across observed alternate
locations. It does **not** establish that each alternate conformer is complete;
the separate conformer decision and downstream preservation/geometry guards
remain mandatory. It neither infers hydrogens/OXT nor invents wholly absent
residues, biological termini, nonstandard residues, nucleic acids or cofactors.
OXT is a leaving/terminal atom, not a required atom of every polymer residue;
see the [wwPDB processing policy](https://www.wwpdb.org/documentation/procedure).
The conventional OT1 name satisfies backbone O for this comparison without
renaming or changing the source atom.

Old preparation requests without an inspection method remain `reported_only`;
the default value is omitted from their serialized request to preserve previous
fingerprints. Reopening an old record explicitly requests its old inspection
method. The read-only inspection endpoint defaults to the current method and
accepts an explicit legacy query. This is a versioned diagnostic improvement,
not retroactive proof that old inputs were complete or permission to repair
observed atoms. Every newly inferred issue still requires a scientist decision.

Missing-atom reconstruction is offered only for standard polymer residues, not
arbitrary ligands, metals or other non-polymer components. Retaining a component
does not establish that protein preparation tools can assign its geometry,
protonation or charges. Incomplete retained components need individual review
and an appropriate preparation workflow; they are never removed automatically.
When a component is explicitly removed, its exact-locator observations no longer
require duplicate residue decisions or trigger a repair worker. Redundant old
request entries remain recorded but do not apply to excluded coordinates.
General native coverage and its limits are recorded in
[the receptor workflow matrix](../validation/GENERAL_RECEPTOR_WORKFLOW_2026-10-14.md).

The default guided inspector has three steps: Choose system, Review repairs,
Prepare. Only one is shown at a time, with prerequisite gates and draft-only
grouped repairs/gaps. Advanced controls retain the complete specialist plan,
including legacy methods and optional relaxation. Guided final preparation
requires hydrogens/PDBQT, exact-plan pKa review and a separate confirmation;
switching modes must not reset decisions or implicitly upgrade old records.

The current draft exposes its prerequisites and next action above the viewer.
Any structural-plan change invalidates the pKa review; the next action is a new
analysis, not an automatic retry or a disabled final Apply. Grouped missing-atom
and missing-residue actions fill only explicitly requested draft decisions,
preserve existing Repair/Remove choices and do not select alternate conformers,
cofactors, metals or protonation states. A missing residue left unmodelled does
not gain invented coordinates.

Protonation proposals can be filtered by recorded warnings, proximity, coupling
or tool/prediction disagreement; the complete selected-state list still enters
the final request. Unassessed distances must not be labelled remote. Previous
Meeko evidence may be folded after explicit removal choices, but remains
available and is never reclassified as a successful preparation. Optional
clash relief remains an explicit choice with the same 0.5 Å safety safeguard;
its availability is not a guarantee of correct reconstruction.
