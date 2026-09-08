# M9 Pose interaction workspace

- Status: accepted and closed on 2026-08-28
- Date: 2026-08-26
- Depends on: M6 Results and preserved M5 pose artifacts
- Scientific contract: `docs/scientific/POSE_INTERACTION_POLICY.md`

## Purpose

Turn a selected docking pose into an inspectable, reproducible interaction
record and a publication-oriented 2D interaction diagram without confusing a
geometric contact map with experimental binding evidence.

## Product flow

1. Open a durable result in Results and select a molecule.
2. Expand its native Vina poses or AutoDock4 clusters/runs.
3. Select one exact pose/run and inspect it with the receptor in Mol*.
4. Run or reopen the interaction analysis for that exact pair.
5. Review the ligand-centered 2D diagram, structured interaction table,
   detector evidence, and warnings.
6. Select a contact to focus its receptor residue in Mol*.
7. Save the exact displayed 2D diagram or 3D view as a recorded publication figure in the project or a scientist-selected folder.

The first implementation lives inside Results. Individual figures can be saved
as SVG/PNG/TIFF/PDF with journal-scale width and DPI plus a project-retained
manifest. Campaign export format 3 includes the immutable interaction JSON,
figure manifests, and still-available rendered figure files in a portable ZIP.
It distinguishes the source campaign, exact inputs, and export event; legacy
format-2 bundles remain readable. The bundle indexes the copied bytes by SHA-256
and never recomputes an analysis or redraws a figure; a historical external file
that is no longer present is listed explicitly as unavailable.

## Interface defaults

- No analysis runs merely because a molecule row became visible.
- The primary action names the selected pose/run and detector.
- Contacts use a restrained, color-blind-conscious palette and never rely on
  color alone; every connector has an interaction label or symbol.
- The ligand uses a publication-style skeletal depiction: carbon vertices and
  hydrogens are implicit, heteroatoms are labelled with conventional colors,
  and single/double/triple/aromatic bonds remain distinguishable. The complete
  explicit atom evidence stays in the interaction table.
- The table is the complete evidence view. The diagram may collapse repeated
  visual edges only when it displays their count and preserves every row.
- Empty results say that no supported contacts met the recorded profile, not
  that the ligand has no interactions.
- Technical details contain hashes and detector parameters; the default view
  emphasizes pose, residue, type, and geometry.
- When multiple immutable analyses exist for one pose, the scientist can choose
  the exact recorded analysis rather than silently receiving only the latest.

## Delivery slices

1. Typed pose/run inventory across Vina, AutoDock4 CPU, and AutoDock-GPU.
2. Immutable ProLIF analysis adapter, store, API, integrity checks, and tests.
3. Results drill-down with pose selection, Mol* overlay, 2D diagram, table, and
   residue focus.
4. Recorded figure export for the vector interaction diagram and raster 3D view.
5. Campaign-bundle integration with exact records, figures, and hashes.
6. Final native visual/export and Trash acceptance. Completed; see
   `docs/validation/M9_POSE_INTERACTIONS.md`.
