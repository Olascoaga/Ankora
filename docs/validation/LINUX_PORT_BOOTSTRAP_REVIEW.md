# Linux bootstrap integration review — 2026-10-28

## Accepted bounded result

The real Linux Tauri application opens through WSLg and renders imported PDB and
mmCIF structures using Mol*. Claude implemented the backend launcher, Gemini
implemented the desktop configuration, and Codex reviewed, tested and integrated
their separate branches. This is ADR-026 development gate 1, not scientific
Linux parity, a Linux installer or native-workstation release acceptance.

The independent Linux source starts at `e233788`, with the separately documented
eight-file Obsidian snapshot. Windows source, pending installer work, projects,
private continuity and installed applications were not modified. No public push
was performed.

## Source review and checks

- Carried frontend baseline: 334 tests / 41 files, type check and build passed.
- Desktop changes: 336 tests / 42 files, type check and build passed.
- Rust: formatting, three unit tests plus binary/doc tests, and strict Clippy
  across all targets passed. Cargo lock unchanged, compilation capped at four
  jobs, separate Linux compilation cache.
- Integrated backend launcher/API/structure tests: 73 passed. The initial API
  test assumed Windows; the corrected test checks the actual supported host
  without changing production platform reporting.
- Review caught non-finite startup/cleanup waits. NaN, infinity and nonpositive
  values now fail before process launch, with regression coverage.
- Launcher Ruff and strict mypy passed. Existing unrelated formatting in
  `test_api.py` was preserved; its whole-file formatting check remains non-green.
- Root npm commands forward explicit Linux dev/build actions. Existing Windows
  commands remain unchanged; no package dependency or package lock changed.
- The generated Linux capability schema is ignored as a build product.

See `LINUX_BACKEND_BOOTSTRAP.md` and `LINUX_DESKTOP_BOOTSTRAP.md` for the individual
unit evidence and explicit limitations. The existing React act/NaN notices,
Mol* chunk-size warning and Starlette/httpx deprecation remain visible.

## Real native application acceptance

Environment: Ubuntu 24.04 WSL2/WSLg, Python 3.12.3, Rust 1.99.1, Node 24.19.0,
npm 11.17.0, GTK 3.24.41 and WebKitGTK 2.52.6. The Python bootstrap environment
passes `pip check`; it is not yet the release-grade scientific Linux lock.

1. The real `tauri:dev:linux` command started an owned uvicorn API on
   `127.0.0.1:8765`, Vite on `127.0.0.1:1420`, and a native Linux executable.
   The workbench reached connected state without a manual Retry.
2. Windows capture of the WSLg surface returned an unrelated occluding surface;
   that image was rejected as application evidence. Native acceptance instead
   used official `tauri-driver` 2.1.0 and the matching WebKitGTK WebDriver.
   Both driver listeners were verified bound to localhost only.
3. WebDriver reported `browserName=wry`, `browserVersion=0.55.1`,
   `platformName=linux`, and `acceptInsecureCerts=false`. It drove the actual
   compiled application and the real API, without mocked responses or DOM data.
4. Imported tracked, explicitly synthetic `synthetic_m1.pdb`: TST1, nine atoms,
   four residues. The native screenshot visibly contains atoms and bonds.
5. Imported tracked, explicitly synthetic `synthetic_m1.cif`: SYN1, four atoms,
   two residues. The native screenshot visibly contains the new structure.
6. Both views reported a live WebGL 2.0 context, 700×525 drawing buffer,
   `contextLost=false`, renderer `WebKit WebGL`. Error/CSP listeners installed
   after the first view recorded no errors during the second import. Both
   screenshots were visually inspected. No CSP relaxation was applied.
7. All test data and raw launcher/WebDriver outputs remain isolated under
   ignored local logs. Fixtures and imported coordinates were not modified.
   No preparation, minimization, docking or scientific benchmark ran.
8. The WebDriver session was closed and the owned test launcher and driver were
   stopped. API/frontend cleanup was verified independently from native-window
   cleanup; an earlier CLI interruption required explicitly closing its own
   remaining window. Do not infer complete Tauri process-tree cleanup from the
   backend launcher's narrower guarantee.

Initial default WSLg startup logged Mesa/EGL/Zink warnings. The measured WebGL
context and visible structures establish functionality only; hardware graphics
acceleration and performance were not certified. No driver installation or
unverified graphics workaround was applied.

## Next boundary

Linux scientific environment and executable discovery, process cancellation,
then bounded real CPU preparation/docking/redocking/interaction checks. GPU
engines need independent runtime acceptance. Complete offline packaging and
native Linux workstation tests remain later gates. GNINA/Vina-GPU and chemistry
changes are outside this bootstrap.
