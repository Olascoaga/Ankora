# Midnight Laboratory visual identity validation

Date: 2026-10-05

## Scope

This record covers the shared desktop visual system only. It does not change a
scientific workflow, stored artifact, external-tool invocation, molecular
representation, result, or provenance contract.

## Acceptance criteria

- The default dark theme has a recognizable Ankora identity without relying on
  a screen-local palette.
- The identity remains subordinate to molecular evidence and scientific data.
- Shared semantic colors retain their meaning: green for action/success, amber
  for review, red for blocking/failure, cyan for precision/information, and
  violet for ligand-state evidence.
- The shell remains usable in the existing wide, medium, and small layout
  states, including the Windows-scaled compact viewport.
- The light, blue, amethyst, and Windows-following themes continue to resolve
  every new semantic token.

## Implemented visual contract

- Graphite scientific surfaces and mineral-green primary action.
- Muted-cyan precision guides and a fine coordinate-grid motif.
- A clipped geometric brand mark and a restrained spectral topbar hairline.
- Compact engineered radii for work surfaces, panels, menus, and controls.
- Monospaced section metadata and status labels.
- Shared inset edge treatment across the workflow rail, data panels,
  inspector, molecular viewer frame, and status bar.

## Verification evidence

- Connected-backend visual smoke at a 1280 x 720 CSS viewport: the Structure
  workspace, workflow rail, inspector, topbar, viewer frame, and status bar
  rendered without overlap or hidden controls.
- Connected-backend visual smoke at a 1024 x 720 CSS viewport: the small layout
  retained both side panels and all topbar controls; long workspace titles wrap
  instead of being truncated.
- `npm.cmd --workspace @ankora/desktop run test`: 34 files and 245 tests passed.
- `npm.cmd --workspace @ankora/desktop run typecheck`: passed.
- `npm.cmd --workspace @ankora/desktop run build:web`: passed.

The frontend test run retained existing non-failing React test warnings in the
library and AutoDock4-library suites. The production build retained the known
Mol* bundle-size and browser-externalization warnings. Neither warning class was
introduced by this visual-only change.

## Scientific boundary

The coordinate grid, spectral line, and brand geometry are chrome, never
scientific evidence. They are not drawn inside the Mol* molecular canvas and
must not be used to imply a distance, coordinate, interaction, or measured
quantity.

## Follow-up: hierarchy and entry surface — 2026-10-06

The second visual unit replaces the repeated shell/workspace grid with quiet
surfaces and a bounded entry emblem. It introduces three navigation groups,
two-line step labels, explicit file/fetch entry cards, keyboard focus for the
existing online-source field, and more legible results/inspector typography.
Light-theme semantic colors were darkened without changing their meanings.

Acceptance for this unit requires that both source actions reuse the existing
paths, opening the source menu performs no scientific mutation, saved receptors
still reopen without tool execution, and navigation/status text does not overlap
at the supported compact size. The molecular canvas must retain its controls.

Verification on Windows with the real local backend:

- 960 x 680 CSS viewport, small layout: source menu and navigation usable;
  navigation title/status rectangles do not overlap; every status cell's scroll
  width equals its client width after the overflow fix.
- A saved receptor reopened without preparation. At 960 x 680, the center
  workspace scrolls while the viewer retains a 364 px canvas. Keyboard access
  to the table moved the workspace to its lower section; the table bottom
  remained above the status bar. No scientific decision was applied.
- 1280 x 800 CSS viewport, medium layout: Structure entry inspected in dark and
  light themes; Results catalog inspected in light. Existing campaigns remain
  accessible; opening one showed its preserved molecule table and recorded
  energies.
- 1920 x 1200 CSS viewport, wide layout: four-column Results catalog inspected
  with readable engine, score, metadata, and reproducibility warnings. No
  document-level horizontal overflow in any of the three checked viewports.
- Full frontend suite: 246 tests passed across 34 files, including a new test
  for file selection, explicit source-menu entry, keyboard focus, and absence
  of mutation requests on entry. Existing import, saved-receptor, and ligand
  completion tests remain in the gate.
- TypeScript and production Vite build passed. Existing React fixture warnings
  and Mol* bundle/browser-externalization warnings remain non-failing.

These are browser-rendered checks of the Windows desktop frontend, not a newly
packaged native installer or a complete accessibility audit. No backend logic,
scientific executable, chemical-state protocol, or stored artifact was changed.
