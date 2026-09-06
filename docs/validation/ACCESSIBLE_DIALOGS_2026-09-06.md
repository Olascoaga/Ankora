# Accessible-dialog validation — 2026-09-06

## Scope

This record closes adversarial-audit remediation item 19. It introduces the
shared modal-dialog interaction boundary and migrates the Results destructive
action and Export Methods preview. Other existing dialogs remain explicit
follow-up migrations; this unit does not broaden or alter their product actions.

## Contract

- Dialog content is portalled beside the application root and identified with
  `role="dialog"`, `aria-modal="true"`, and caller-owned accessible labels and
  descriptions.
- Every migrated dialog receives an explicit initial-focus target. Results
  starts on the non-destructive `Keep results` action; Methods starts on
  `Close`.
- Tab and Shift+Tab cycle inside the active dialog. Background application
  roots become inert and leave the accessibility tree until the dialog closes.
- Escape follows the same close path as the visible cancel control. It is
  disabled while a confirmed destructive operation is running.
- Closing restores the exact previously focused opener when it survives. When
  successful deletion removes that opener, focus moves to the stable Results
  workspace instead of falling back to the document body.
- The primitive restores every prior background `inert` and `aria-hidden`
  value rather than assuming that it owned the original state.

## Automated evidence

The shared primitive and migrated workflow tests verify:

1. explicit initial focus and background isolation;
2. forward and reverse focus wrapping;
3. Escape dismissal and exact focus restoration;
4. non-dismissible operation state;
5. accessible Methods labeling and opener restoration; and
6. safe fallback focus after a successful multi-result deletion removes its
   initiating controls.

Verified locally on the Windows-authoritative development machine:

- 494 backend tests;
- Ruff and strict mypy across 116 backend source files;
- 231 frontend tests across 32 files;
- strict TypeScript compilation;
- production Vite build;
- Rust formatting, strict Clippy, unit and documentation tests;
- optimized native Windows application build; and
- public-path sanitation.

Known non-failing toolchain notices remain unchanged: the Starlette/httpx
deprecation, existing React test diagnostics, Vite browser externalizations and
Mol* chunk size, and the MSVC linker message.
