# README image provenance

The README shows current development-UI captures of preserved scientific
records. It does not imply that a previously distributed installer has changed.

## Current workflow captures — 20 October 2026

- `readme-banner.svg`: self-contained vector artwork using the current carbon,
  ivory, brass and slate-blue design tokens and Ankora's molecular mark. Its
  abstract molecular decoration is not a calculated structure or result.
- `readme-receptor.jpg`: actual receptor workspace reopening the preserved
  preparation `72ff70a2-b373-4f59-b162-5bbc3a471b6e`, its original 7AQF structure,
  recorded decisions and prepared PDB. Structural inspection is a fresh,
  read-only template comparison, not a new preparation or acceptance of those
  historical decisions for another system.
- `readme-binding-site.jpg`: actual binding-site workspace with a non-persistent
  box preview around crystallographic RV2 A:401, padded by 5 Å on every face.
  The application calculates the preview with its unchanged read-only service;
  no binding-site record is saved and no pocket predictor or docking runs.
  Both full workbench captures use 1920 × 1200 CSS pixels in Edge 155.0.4283.62.
  The isolated replay reports tools unavailable rather than inventing successful
  detection. “Read-only 7AQF review” names the presentation session, not a new
  scientific project.
- `readme-obsidian-interactions.jpg`: actual production-built Results detail
  view, cropped to the interaction workspace from a 2240 × 1400 viewport. A
  read-only replay serves an existing 7AQF receptor, saved Vina pose and ProLIF
  analysis to the unmodified view. Navigation/readiness scaffolding is isolated
  test data and is excluded from the crop; it is not execution evidence.
  The display-only title is “Preserved 7AQF pose”. No contact, coordinate or
  scientific result was generated or edited for the capture.

The preserved analysis is `de66d321-661c-4c27-8144-c6a6f64f8812`, recorded with
ProLIF 2.2.1. It contains **20 atomic contacts**, **three residues** and **four
exact residue/subtype groups**. Summary mode draws one representative per group
while retaining the underlying atomic count. These are geometric contacts, not
independent bonds, measured affinity or biological evidence.

| Replay input | SHA-256 |
| --- | --- |
| Analysis JSON | `a00e99b76820e9859a3e9dc900b26bdd3f1684f9e886025147f2f0789bfef911` |
| Prepared receptor PDB | `3fc201d458eeed347fd498d3173a0a1e8ae487c918f7669769b09c1223371799` |
| Exact pose PDBQT | `310c911861ae7b65c28bb76686037aa61bfa4366c5eaf05e081d8e09f2b403a1` |
| Original 7AQF mmCIF | `79fd3b96adca6bdbe17ded6e9c693534007ae2cb0538739044788754b7c6faac` |
| Saved receptor record | `81e89d848d00296cc7ddd21a589ad7ea9cf5199068b3b748ecced5f6fabc0721` |

The capture reuses the read-only presentation regression in
`scripts/smoke_interaction_presentation.mjs` with those three explicit inputs.
All three hashes were checked before and after the replay. The production CSP
remained enabled; no browser or CSP errors were observed. The contact table,
diagram bounds and reachable save controls also passed at 1280 × 800,
1536 × 864 and 1920 × 1080. No backend service or scientific executable was
started, and no saved record was changed.

These images show the working development tree's Obsidian theme. README
publication does not itself merge pending application-theme or packaging work.

The earlier `guide03-receptor.jpg` and `guide06-binding-site.jpg` remain in the
[illustrated user guide](../USER_GUIDE.md), but are no longer used by the README.
The README deliberately presents scientific workflows rather than a splash or
theme feature tour. Historical preparation choices are not a universal recipe.
