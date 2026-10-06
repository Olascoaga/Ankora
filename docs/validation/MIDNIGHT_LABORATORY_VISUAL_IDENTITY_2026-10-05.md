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
