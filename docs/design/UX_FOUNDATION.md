# Ankora UX foundation

This document is the implementation contract for the professional scientific interface established during M3. It complements ADR-014 and should be reviewed before adding a new workflow screen.

## Information architecture

- The top bar owns application-level actions, project context, connection state, panel visibility, theme, density, and help.
- The left rail communicates workflow state as current, complete, available, or locked. Every implemented step includes a short state summary.
- The center is the scientific work area. It favors a stable molecular viewer plus the data plane needed for the current decision.
- The right inspector owns contextual parameters and explicit decisions. Long workflows use numbered collapsible stages.
- The bottom strip summarizes status, warnings, provenance, and activity. The expandable activity center owns jobs, full warnings, generated commands, tool readiness, and application information.

## Layout and scrolling

- The application shell fills the viewport and must not create a document-level scrollbar at the authoritative desktop size.
- Workflow and inspector widths are independently resizable and collapsible; double-clicking a divider restores its default width.
- The shell reports one of three explicit states from the effective CSS viewport:
  `wide` at 1800×1100 or greater, `medium` at 1180×700 or greater, and
  `small` below that. Both dimensions are required. WebView CSS pixels—not
  physical monitor pixels—are authoritative so Windows 125/150 percent
  scaling selects the same layout as an equivalently sized viewport.
- Medium and small states cap the visible workflow/inspector footprint without
  discarding the user's preferred resized widths. All application menus remain
  reachable at the 960 px supported minimum.
- A screen has one vertical task-lane scroll owner. Long document views use the
  center workspace; bounded tables, inspectors, and code/evidence panes may
  scroll their own data, but two page-level vertical scroll regions must not be
  nested in the same lane.
- Component composition follows usable center-workspace width where side-panel
  resizing matters. Pose-interaction review stacks below 980 px of workspace
  width and uses two columns above it; monitor-width and viewport-height
  exceptions must not be added for that screen.
- Receptor review keeps residue issues in a filterable table below Mol*. Selecting a residue focuses it in the viewer.
- Virtual screening keeps source order visible through a fixed source-index column and exposes search, status filtering, sorting, and optional descriptor columns.

## Visual language

- Use variables from `apps/desktop/src/design-system.css`; do not introduce screen-local palettes for shared states.
- Mint is the primary interaction and success family. Amber indicates review, red indicates blocking/failure, blue indicates information, and violet distinguishes generated ligand state where appropriate.
- Surfaces use restrained elevation and borders; glow is reserved for connection/activity emphasis rather than decoration.
- Scientific values use tabular numerals. Units belong in headers or labels, for example `MW (g/mol)` and `Final MMFF E (kcal/mol)`.
- Scientific quantities use the shared locale-neutral formatter: `.` is the
  decimal mark and large values use a narrow no-break space between groups
  (`102 600`, never `102,600` or `102.600`). This presentation contract is
  independent of the Windows display language and does not alter stored
  numbers. Do not call `toLocaleString` or `toFixed` directly for scientific
  UI values.
- Application dates use one English, day-first, 24-hour formatter in the
  workstation's local time zone (`28 Aug 2026, 12:34`). Stored timestamps stay
  unchanged. If a historical timestamp is invalid, show it literally rather
  than manufacturing a date.
- Dark, light, and Windows-following themes plus comfortable/compact densities are user settings and persist locally when the WebView permits it.

## Interaction and accessibility

- A control must have a visible keyboard focus state and an accessible name.
- Icons accompany meaning; they do not replace state text where ambiguity is possible.
- Menus are mutually exclusive and close after an action or outside click.
- Progress bars expose current/total values for bounded batches; indeterminate animation is used only when no total exists.
- Empty states explain the next valid action. Disabled workflow steps explain their prerequisite in the left rail.
- Errors keep concise recovery near the task and retain expandable technical evidence. Scientific decisions are never applied implicitly as error recovery.
- Modal workflows use the shared dialog boundary. Opening a dialog isolates the
  application behind it from pointer, keyboard, and accessibility-tree access;
  moves focus to an explicit safe control; keeps Tab and Shift+Tab inside; and
  closes with Escape unless a destructive operation is already running. Closing
  restores focus to the opener or to a stable workspace fallback when that
  opener was removed by the completed action. A modal must not implement these
  behaviors independently.
- React rendering failures are contained twice: a workspace failure leaves the
  surrounding navigation and status shell usable, while an application-level
  boundary provides a last-resort recovery screen. Retrying either boundary
  redraws the interface only; it never repeats a scientific command. The
  evidence panel preserves the error name, message, JavaScript stack, component
  stack, and affected project/workspace scope and can be copied for support.

## Adding later milestones

Binding-site, docking, results, validation, and export screens should reuse the shell, status model, activity reporting, inspector stages, scientific grid, and design tokens. A new pattern belongs in the shared design system when it appears in more than one workflow step.
