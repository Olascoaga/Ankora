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
     `CPU threads = 2`, `Seed = 20261029`, `Exhaustiveness = 1`, `Modes = 2`,
     and `Timeout / molecule (min) = 3`, acknowledge the GNINA scoring notice,
     and click `Dock 11 prepared molecules`.
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
