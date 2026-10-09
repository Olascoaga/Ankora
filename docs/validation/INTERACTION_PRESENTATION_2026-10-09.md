# Lossless interaction presentation — 2026-10-09

## Scope and status

Source correction and local automated acceptance complete. Scientist acceptance
in the development application is pending; **no installer was regenerated**.
The previously delivered private-beta installers remain unchanged. This is not
a new scientific validation, clean-Windows installer test, or public release.

The subsequent development-only import failure and its correction are recorded
in [Development viewer interoperability](DEVELOPMENT_VIEWER_INTEROP_2026-10-09.md).
The production checks below did not originally cover Vite's development loader;
both modes now have separate browser gates. Native scientist acceptance remains
pending before generating another installer.

The report concerned dense Vina contacts visible in 3D but not individually in
2D. Inspection found two distinct issues: a summary node obscured the meaning of
atomic multiplicity, and grouping by colour family collapsed different detector
subtypes on the same residue into one label. Neither issue justifies changing
ProLIF's `count=True`, cutoffs, profiles, stored contacts or docking results.

## Acceptance criteria and coverage

- Group by chain, sequence number, insertion code, residue name and exact
  detector type; never group by shared colour. Regressions cover hydrogen,
  aromatic, ionic, halogen and metal subtype pairs.
- A labelled SYNTHETIC fixture with 30 hydrophobic contacts plus donor/acceptor
  on the same residue retains 32 contacts, three summary nodes, `×30`, and all
  32 table rows. Expanding the diagram draws 32 atomic lines. This fixture is a
  presentation test, not a computed chemical result or affinity expectation.
- Summary lines select actual recorded contacts (shortest distance or exact
  selection). Selection of a non-default contact updates both drawings.
- Subtype filtering updates 2D, 3D and table together and clears hidden
  selections. Switching analyses resets filters/detail; empty analyses and
  historical missing endpoints do not fabricate contacts or coordinates.
- SVG captions retain visible/full counts and detail mode. Caption, residue
  nodes and legend fit the frame at 1280×800, 1536×864 and 1920×1080; saving
  controls remain reachable, without workspace horizontal overflow.

## Local real-record replay

The read-only production-browser check replayed saved Vina analysis
`de66d321-661c-4c27-8144-c6a6f64f8812`, Mode 1. It contains 20 contacts:
15 Hydrophobic at LYS A:122, three Hydrophobic at TRP A:139, and one each
HBDonor/HBAcceptor at GLN A:123. The old hydrogen-family grouping yielded
three nodes; the corrected drawing has four separately labelled subtype nodes.
All 20 contacts remain accessible in the detailed diagram and table.

Verified input SHA-256:

| Input | SHA-256 |
| --- | --- |
| Immutable analysis JSON | `a00e99b76820e9859a3e9dc900b26bdd3f1684f9e886025147f2f0789bfef911` |
| Analysis receptor PDB | `3fc201d458eeed347fd498d3173a0a1e8ae487c918f7669769b09c1223371799` |
| Native Vina pose | `310c911861ae7b65c28bb76686037aa61bfa4366c5eaf05e081d8e09f2b403a1` |

All three hashes were verified unchanged after replay. The source was not
recomputed and no API mutation was allowed. API replies were intercepted in an
isolated production Chromium browser, using exact saved analysis/input bytes;
this proves presentation, not live service routing or installed WebView2 behavior.
It does **not** identify or validate the scientist's newly reported 30-contact
Vina pose; that exact pose remains part of manual acceptance.

## Verification

- Frontend: **276 tests / 38 files passed**, including 19 added regressions.
  Existing unrelated React `act`/NaN fixture warnings remain non-fatal.
- TypeScript and production Vite build passed. Existing large-chunk advisory
  remains; no CSP relaxation or dependencies were added.
- Backend pose/interaction integrity and complex-export tests: **14 passed**.
  Initial attempts could not use Windows' default pytest temporary directory;
  a fresh isolated project-local directory resolved the permission issue.
- Public-path and public-validation-status checks passed.
- Production Chromium **151.0.7922.34**, strict CSP without `unsafe-eval`:
  synthetic 32-contact and real 20-contact replays passed all three viewports,
  detailed/filtered counts, source preservation, zero JavaScript errors and
  zero CSP violations. Mol* loaded receptor/pose canvases without viewer errors;
  component tests verify the exact contacts supplied to 3D in both modes.
- Existing delayed cold-start/assets/PDB/mmCIF production gate also passed.

Private raw screenshots/evidence are retained locally under ignored build output:
`interaction-ui-smoke-1791574600038` (synthetic),
`interaction-ui-smoke-1791574656596` (real) and
`frontend-smoke-1791574677750` (startup/PDB/mmCIF).
Private campaign artifacts and machine paths are not part of this commit.

## Reproduction and next gate

After `npm run build`, run `node scripts/smoke_interaction_presentation.mjs` with
the pinned Playwright Chromium installed. CI runs this synthetic regression.
Optional `--analysis`, `--receptor` and `--pose` file arguments replay a local
record; all three are required and receptor/pose hashes must match that record.
The script starts only an isolated localhost static server, never a backend or
scientific process, and rejects mutating API requests.

The scientist should reopen the reported Vina pose in development, check both
hydrogen-bond subtype labels, `×N` counts, **All atom contacts**, type filtering,
table selection and saved SVG. This works with existing analyses and needs no
recalculation. Only after that acceptance should a separate installer be built,
preserving both previously delivered installer artifacts and repeating installed
startup/3D/scientific gates for the new binary.
