# Responsive workbench layout validation — 2026-09-07

## Scope

This record validates the UI-only Gate D layout contract. It does not execute,
alter, or reinterpret a scientific calculation.

The former pose-interaction rules combined a monitor-width breakpoint, a
viewport-height breakpoint, two independent column scrollbars, and later
screen-specific overrides. That made reachability depend on the monitor and on
which rule happened to win. The replacement has two explicit boundaries:

- the application shell classifies the effective CSS viewport as `wide`,
  `medium`, or `small`;
- pose-interaction review composes from the actual center workspace width and
  leaves vertical document scrolling to the Results workspace.

## Layout matrix

The live local React application was rendered in the in-app Chromium browser
against the real local backend. Values below are observed CSS pixels. At every
size the root shell exactly matched the viewport, all five application menus
remained visible, and both `html` and `body` reported zero horizontal and
vertical overflow.

| Viewport | State | Center workspace width | Center workspace height |
|---|---|---:|---:|
| 960×680 | small | 516 px | 587.2 px |
| 1280×800 | medium | 748.1 px | 697.2 px |
| 1920×1080 | medium | 1384 px | 977.2 px |
| 2560×1440 | wide | 2000.7 px | 1337.2 px |

The 960×680 visual smoke additionally confirmed that File, Workflow, Tools,
View, and Help remain visible; workflow and inspector retain independent
scrolling; and the center viewer, primary open action, last-receptor action,
status bar, and panel toggles remain reachable without global overflow.

## Windows display scaling

WebView2 exposes display scaling through its effective CSS viewport. The same
live browser path was therefore exercised at the effective sizes produced by
common Windows settings:

| Physical display | Scale | Effective viewport | State |
|---|---:|---:|---|
| 1920×1080 | 125% | 1536×864 | medium |
| 1920×1080 | 150% | 1280×720 | medium |
| 2560×1440 | 125% | 2048×1152 | wide |
| 2560×1440 | 150% | 1707×960 | medium |

All five menus remained visible and global overflow remained zero in each
scaled case.

## Pose-interaction scroll contract

- `.results-interaction-workspace` is the single vertical document-scroll
  owner and keeps a stable scrollbar gutter.
- The 3D viewer column and the structured-evidence column remain in normal
  document flow; neither creates a competing page-level vertical scrollbar.
- The contact table retains a bounded data-region scrollbar because it is a
  wide scientific table, not a second document lane.
- A named CSS container switches the review grid at 980 px of usable workspace
  width. Resizing or collapsing either side panel can therefore change the
  composition without a monitor-specific patch.

## Automated verification

- Nine layout-classifier regressions cover 960×680, 1280×800, 1920×1080,
  2560×1440, both-dimensional boundaries, and 125/150 percent scaling.
- Figure/layout contract tests require one Results scroll owner, normal-flow
  3D/evidence columns, the workspace container query, all three named shell
  states, and the absence of the removed 1450×1100 media-query patches.
- The complete frontend gate passes 245 tests across 34 files, strict
  TypeScript, and the production Vite build.

## Acceptance boundary

Accepted: deterministic layout classification, scaled-view behavior, compact
chrome reachability, side-panel width caps without preference loss, one M9
document-scroll owner, and workspace-width-driven stacking.

This record does not claim touch/mobile support below 960 px or alter the
bounded scrolling required by large scientific tables and inspectors.
