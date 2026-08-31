# Pose interaction analysis policy

- Status: accepted and closed on 2026-08-28
- Date: 2026-08-26
- Default detector: ProLIF 2.x
- Scope: one preserved docking pose against its exact prepared receptor

## Scientific meaning

An interaction diagram is a geometric interpretation of one docking pose. It
is not experimental evidence, a binding-energy decomposition, or proof that a
contact is favorable. Ankora must always show the docking engine, pose/run,
receptor, detector, detector version, and detector parameters beside it.

The interaction record, rather than the drawing, is the source of truth. The
drawing and table are two views over the same structured contacts. Ankora must
not parse another application's rendered diagram or infer contacts in React.

## Exact inputs

An analysis is valid only when all of the following are resolved from one
durable result record:

- the exact receptor output artifact and recorded SHA-256 used for docking;
- the exact ligand preparation and its topology-bearing minimized conformer;
- the exact engine-native pose artifact and recorded SHA-256;
- the result catalog identity, molecule identity, and pose or run identity.

PDBQT is authoritative for pose coordinates but not by itself for bond orders.
Ankora reconstructs the ligand from Meeko's embedded SMILES and atom map, then
validates that topology against the exact minimized SDF that produced the
recorded ligand preparation. Failure to establish the same canonical isomeric
topology is a structured error; a different ligand or a guessed topology must
never be substituted.

The receptor representation supplied to the detector must derive from the
same immutable receptor preparation used for docking. Its identity and hash
are retained even when a format conversion is required for analysis.

## Default interaction vocabulary

The first release records ProLIF's structured residue/atom metadata for:

- hydrogen-bond donor and acceptor contacts;
- hydrophobic contacts;
- face-to-face and edge-to-face aromatic stacking;
- cation-pi and pi-cation contacts;
- anionic and cationic contacts, displayed together as ionic/salt-bridge
  evidence when the complementary partner is present;
- halogen-bond donor and acceptor contacts;
- metal-donor and metal-acceptor contacts.

Van der Waals contacts are excluded from the default diagram because their
density obscures the more interpretable contact classes. Water bridges are
only eligible when the prepared receptor explicitly retains the participating
water. Users may later request a different explicit detector profile; Ankora
must record it as a separate immutable analysis.

Distances, angles, atom indices, and residue locators are preserved whenever
the detector supplies them. A missing optional geometric value remains null;
it is never fabricated from a label.

## Persistence and provenance

Every completed analysis is create-only and stores:

- an analysis UUID and creation time;
- catalog, engine, result, molecule, pose/run, receptor, ligand preparation,
  and conformer identifiers;
- input artifact IDs and SHA-256 values;
- detector name/version and the exact interaction profile;
- structured contacts and non-fatal warnings;
- a provenance event linking every input and the analysis record.

Re-running the same pose creates another record. Historical analyses remain
inspectable if upstream state later becomes stale. Hash drift or a missing
artifact fails closed and is surfaced as an integrity error.

## Presentation

The Results workspace provides:

- explicit pose/run selection before analysis;
- a readable 2D ligand-centered SVG whose glyphs are generated from the
  structured record and use standard skeletal conventions: bonded carbon
  vertices and hydrogens are implicit, heteroatoms are labelled, and bond
  multiplicity is retained;
- a sortable interaction table with type, residue, distance, angle, and atoms;
- selection linking from a diagram contact or table row to the same residue in
  Mol*;
- a visible legend, detector identity, warnings, and the statement that these
  are geometric pose contacts rather than measured affinities.

The diagram may simplify layout, including anchoring a contact recorded on an
explicit hydrogen to its bonded heavy atom, but it may not change the recorded
atom indices, merge distinct residues, invent missing contacts, or hide
duplicate contact evidence from the table.

## Acceptance criteria

1. Vina poses and AutoDock4 CPU/GPU runs resolve through one typed result API.
2. The selected pose coordinates are combined only with the exact matching SDF
   topology; mapping and hash failures are explicit and tested.
3. ProLIF is invoked through a backend adapter, its version and parameters are
   recorded, and no scientific executable or detector runs in the frontend.
4. Analysis records are immutable, reload after restart, and preserve complete
   structured contact metadata and provenance.
5. The 2D diagram and table render from the same API record and can focus the
   selected receptor residue in Mol*.
6. Tests use clearly labelled synthetic structures with geometry chosen to
   exercise known contact types; no expected scientific result is invented
   from a live database or network response.
7. The complete backend/frontend/Rust/native suite and a Windows smoke analysis
   over at least one real preserved pose pass before the milestone is closed.

Acceptance evidence is recorded in
`docs/validation/M9_POSE_INTERACTIONS.md`.
