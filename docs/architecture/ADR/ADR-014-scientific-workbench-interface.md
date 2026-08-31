# ADR-014: Scientific workbench interface

- Status: Accepted
- Date: 2026-08-20

## Decision

Ankora uses a fixed-viewport scientific workbench rather than a document-style scrolling page. The persistent shell contains application menus, project and backend context, a stateful workflow navigator, a central scientific work area, a contextual inspector, a compact status strip, and an expandable activity center. The workflow and inspector may be collapsed or resized; data-heavy regions own their scrolling so the molecular viewer and primary decisions remain in context.

Receptor review uses a viewer-and-residue-table workbench. Ligand preparation explicitly separates single-compound and virtual-screening modes; screening uses a sortable, searchable, configurable scientific grid with source-stable row identity. Long decision sequences use progressive-disclosure inspector stages without hiding blockers or scientific evidence.

The interface is built from shared semantic color, spacing, typography, density, focus, status, and surface tokens. Dark, light, and Windows-following themes are explicit user choices. Color never carries scientific state alone: state also has text and/or an icon. Iconography is semantic and consistent. Keyboard focus must remain visible, controls must retain accessible names, and progress must expose determinate values whenever totals are known.

## Consequences

New milestone screens must compose the existing shell and design tokens instead of adding independent page chrome or arbitrary colors. Global page scrolling, several nested scrollbars in one task lane, scientific table cells below the documented minimum type size, and hidden error recovery are regressions. Background and batch operations report into the shared activity center, while detailed commands, provenance, warnings, and tool readiness remain inspectable without crowding the main workspace.

The implementation remains evolutionary: later docking, results, validation, and export work may extend the components, but must preserve the workbench hierarchy and explicit scientific decision boundary.
