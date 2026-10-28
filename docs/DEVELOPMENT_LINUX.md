# Linux port work plan

The scientist authorized the Linux port on 2026-10-28. See ADR-026.

## Source baseline

The independent Linux checkout starts from public-lineage commit `e233788`.
The accepted working Obsidian UI is carried into Linux as a separate source
snapshot, preserving the Windows checkout and its uncommitted work. The snapshot
contains only the eight existing UI/design files; Windows installer experiments,
private memory, build products and scientific projects are excluded.

## Initial unit — development bootstrap

- **Claude / backend:** implement a Linux development launcher and focused tests.
  Own `scripts/dev_linux.py`, `backend/tests/test_linux_dev.py` and
  `docs/validation/LINUX_BACKEND_BOOTSTRAP.md`. Select an explicit or project
  Python interpreter, verify API identity/readiness, fail clearly on occupied
  ports, retain startup errors, and clean up only owned subprocesses on exit.
  Launch commands as arrays, bind localhost, keep existing chemistry unchanged.
- **Gemini / desktop:** own `apps/desktop/package.json`, Linux Tauri configuration,
  platform-specific Rust compatibility, focused configuration/Rust tests and
  `docs/validation/LINUX_DESKTOP_BOOTSTRAP.md`. Add explicit Linux development
  commands consuming Claude's launcher. Preserve Windows commands/configuration,
  installed backend behavior, CSP and current appearance. No Linux installer
  claim in this unit.
- **Codex / review:** owns this plan, ADR, policy, environment setup and integration
  evidence. Review each diff and relevant tests before integration. Resolve
  shared-file changes sequentially. No automatic pushes or co-author trailers.

The launcher interface is `python3 ../../scripts/dev_linux.py` from the desktop
package directory. It owns a backend plus `npm run dev` from the repository root,
using the existing API port 8765 and frontend port 1420. Python selection:
`ANKORA_PYTHON_PATH`, active non-base Conda, project `.venv`, or a named
`ankora-dev` environment; an invalid explicit selection must fail clearly.
Do not silently reuse another running backend or kill unrelated listeners.

## Acceptance

1. Linux frontend tests, type check and production build pass on the carried UI.
2. Launcher tests prove startup/readiness, collision handling and owned cleanup.
3. Linux Rust formatting/tests/check or build passes with real GTK/WebKit deps.
4. A real Tauri window opens through WSLg; an imported tracked structure fixture
   is visible in Mol*. Record actual rendering/runtime, screenshots and errors.
5. Confirm the Windows checkout has exactly its original dirty-file set and
   preserved source bytes. Record any checks not executed rather than claiming
   Windows packaging or native workstation acceptance.

## Later units

Scientific Linux parity and lock, CPU engines and cancellation, independent GPU
acceptance, then complete offline packaging and native workstation validation.
Each bounded completed unit gets relevant tests, tracked evidence and a small
commit. Private coordination logs and memory stay ignored.
