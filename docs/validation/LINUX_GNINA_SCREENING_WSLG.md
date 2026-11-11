# GNINA WSLg native desktop screening check — predeclared

## Protocol

This bounded WSL2/WSLg graphical engineering check exercises `GninaScreeningWorkspace`
inside the compiled Linux Tauri (`wry` / WebKitGTK) application against Ankora's
real localhost FastAPI backend, Vite frontend, Mol* WebGL viewer, and the
official GNINA 1.3.3 CUDA binary on the local RTX 5050 GPU. It is not a
scientific virtual-screening benchmark, Linux installer test, or native
bare-metal Linux workstation acceptance (ADR-026 Gate 3).

### Preconditions

1. Verify the declared SHA-256 digests of the official GNINA 1.3.3 Linux binary
   and the preserved `screening-api-cuda-01` evidence and project tree. Copy
   `screening-api-cuda-01/data` into a fresh, create-only directory
   (`logs/linux-gnina-investigation/v1.3.3/wslg-screening-ui-01/data`) and
   verify after teardown that the source tree digest is unchanged.
2. Require active WSLg display variables (`DISPLAY` or `WAYLAND_DISPLAY`),
   Linux ELF binaries for `ankora-desktop`, `tauri-driver`, and
   `WebKitWebDriver`, free loopback ports `8765`, `1420`, `4444`, and `4445`,
   and one unambiguous NVIDIA GPU at logical index `0` with zero active GPU
   compute processes.

### Interactive execution and acceptance criteria

1. Start an owned `scripts/dev_linux.py` session serving `ANKORA_DATA_DIR` on
   `127.0.0.1:8765` and `127.0.0.1:1420`, then start `tauri-driver` on
   `127.0.0.1:4444` (`--native-port 4445`) and verify all four listeners are
   bound exclusively to loopback addresses.
2. Open a W3C WebDriver session against `ankora-desktop` and require
   `browserName == "wry"`, `platformName == "linux"`, and
   `acceptInsecureCerts == False` under the strict Linux Tauri CSP (no
   `unsafe-eval`). Attach window `error`, `unhandledrejection`, and
   `securitypolicyviolation` listeners immediately.
3. Through real UI controls only:
   - Reopen the saved 1HSG prepared receptor (`Reopen last receptor`).
   - Open `Ligand` -> `Virtual screening`, select the project's imported
     `nci_real_100.sdf` library from `Imported libraries`, and confirm the
     applied 11-molecule `demostracion` selection hydrates as `11 / 11`
     prepared.
   - Open `Binding site`, choose `Co-crystallized ligand` (`MK1 B:902`, `4 Å`
     padding), preview the box, and click
     `Define this binding site and continue to Docking`.
   - In `Docking`, select `GNINA · screening`, set `Compute` to `cuda`,
     `CPU threads = 2`, `Seed = 20261029`, `Exhaustiveness = 1`,
     `Maximum poses = 2`, and `Timeout / molecule (min) = 3`, acknowledge the
     GNINA scoring notice, and click `Dock 11 prepared molecules`.
4. Observe live campaign execution to terminal `completed` (`11 / 11`
   succeeded) and every finished molecule's individual job read (`Every finished
   molecule's job has been read`, clicking `Read scores from …` if any remain
   unread), and require:
   - Distinct table headers and populated numeric values for
     `Top CNN score (dimensionless)`, `CNN affinity (pK)`, and
     `Minimized affinity (kcal/mol)`, with no cross-engine pooling.
   - Expanding a completed compound row reveals its poses ordered by descending
     `CNN score`; clicking `Pose 1` loads the pose alongside the prepared
     receptor in Mol* with a live WebGL 2.0 context (`contextLost == False`,
     positive drawing-buffer dimensions).
5. At both `1280×800` and `960×680` window rectangles, require zero horizontal
   document overflow (`scrollWidth <= clientWidth + 1`), visible unclipped
   workspace and inspector regions, native WebDriver PNG screenshots saved in
   the create-only run directory, and zero recorded JS, unhandled-promise, or
   CSP errors.
6. Close the WebDriver session, terminate only the owned driver and launcher
   sessions, verify ports `8765`, `1420`, `4444`, and `4445` are free and zero
   GPU compute processes remain, and write create-only `evidence.json` even on
   failure.

## Observed run: wslg-screening-ui-01 (harness selector mismatch)

The native Linux `wry` (`0.55.1`) Tauri desktop window opened cleanly over WSLg
against loopback-only `uvicorn`, Vite, and `tauri-driver` listeners, reopened
the saved 1HSG receptor, hydrated the 11-molecule `nci_real_100.sdf` selection,
defined the `MK1` co-crystallized binding site, and opened `GNINA · screening`.
The test script then failed at parameter entry because it queried
`input[aria-label='Modes']` instead of the rendered label
`input[aria-label='Maximum poses']`. Owned teardown freed all four ports, left
zero GPU compute processes, and left the source tree digest unchanged. The
untouched create-only failure record is retained at
`wslg-screening-ui-01/evidence.json` with SHA-256
`de4ebf995cf6b31530cee687842070ca317b5cdc6dff8ff988a00bcd3c84172f`.

### Predeclared follow-up (`wslg-screening-ui-02`)

Run the identical WSLg interactive protocol in a new create-only directory
(`logs/linux-gnina-investigation/v1.3.3/wslg-screening-ui-02`) targeting
`input[aria-label='Maximum poses']` while keeping every acceptance criterion
unchanged.

## Observed run: wslg-screening-ui-02 (premature wait-predicate match)

The campaign launched cleanly on CUDA (`NCI-20` completed with two descending
`CNN score` poses `0.6464` and `0.5684` while `NCI-22` was running), captured
`1280-running.png`, and expanded `NCI-20`. The harness wait condition matched
`11 / 11` against the static `11 / 11 selected molecules prepared` text in
Section 1 after the first molecule completed, before the remaining 10 molecules
finished (`—`). Owned teardown cleanly stopped the running campaign, freed all
four ports, left zero GPU compute processes, and left the source tree digest
unchanged. Retained create-only `wslg-screening-ui-02/evidence.json` SHA-256:
`048eff98a38140bd4a28b960f5f9a35943b2d0291e5f660d8c551bfb53135b75`.

### Predeclared follow-up (`wslg-screening-ui-03`)

Run the identical WSLg interactive protocol in create-only directory
`logs/linux-gnina-investigation/v1.3.3/wslg-screening-ui-03`, waiting until the
active `Cancel campaign` control disappears (terminal campaign status
`completed`) and all 11 compound rows display read numeric scores before
auditing the table, Mol* WebGL 2.0 context, and `1280×800` / `960×680` layouts.
