# Pose-interaction scroll regression — 2026-10-06

## Cause and correction

The M9 component already declared `overflow-y: auto`, but `main.tsx` loads
`design-system.css` after `styles.css`. Its generic `.workspace` rule used an
equally specific `overflow: hidden` shorthand, overriding the document's scroll
contract. At 1280×800, a recorded M5V analysis had a 697 px center viewport,
2,439 px of content, and a diagram starting at y=1,317. The resolved vertical
overflow was `hidden`, leaving no scrollbar to reach the diagram.

The fixed-canvas fallback now uses `:where(.workspace)` with zero specificity.
Document-workspace rules therefore win even when declared in the earlier file.
There is no new breakpoint, nested document scroller, or reduced viewer height.
The 980 px workspace-container boundary still chooses one or two M9 columns.

## Acceptance and live evidence

Checked the Windows frontend in local Chromium against existing backend records.
The M5V GPU analysis was reopened, not recomputed. No docking, new ProLIF
analysis, figure export, or PDB write was invoked during these checks.

| CSS viewport | M9 composition | Observed acceptance |
|---|---|---|
| 960×680 | One column | Central scrollbar works; diagram Save figure button fully visible at the end |
| 1280×800 | One column | PageDown reaches the entire 2D diagram and legend; End reaches Save figure |
| 1536×816 | One column | Scroll remains available; an unanalysed pose's honest empty state is reachable |
| 1920×1200 | Two columns | Both Save figure buttons and Save PDB are fully reachable at the end |

Resolved workspace `overflow-y` is `auto`; the 3D and evidence columns remain
`visible`, without competing document scrollbars. The contact table retains its
bounded scroll region. Checked global overflow is zero on both axes at all four
sizes, and center content does not exceed the center lane horizontally. In the
1280×800 check, the full diagram occupied y=96–584 inside the y=64–761 workspace
after two PageDown actions. Private screenshots are excluded from Git.

## Automated gate and limits

- Added a regression covering the later theme's generic workspace rule, not just
  the earlier M9 stylesheet. It failed on the original overflow declaration and
  passed after the fallback correction.
- Frontend: 247 tests across 34 files passed, including existing scroll-owner,
  container-layout, figure, and result-interaction regressions.
- Strict TypeScript and production Vite build passed. Existing non-failing
  React fixture warnings and Mol* bundle/externalization warnings remain.

This is a CSS-only runtime change. Scientific behavior, stored artifacts,
interaction calculations, and export handling are unchanged. Browser-rendered
Windows verification is not a rebuilt or smoke-tested native installer.
