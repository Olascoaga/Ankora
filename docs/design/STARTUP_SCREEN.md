# Startup screen — "Anchoring"

The startup screen is the first record Ankora writes in a session. It shows
what the local backend has actually answered, and nothing else, while a real
binding pocket resolves behind it.

## What is drawn

- **The pocket** is the SERPINE1 cavity around RV2 A:401. It comes from the
  exact `7AQF.cif` that the frozen `SERPINE1_7AQF_RV2` reference case recorded
  (SHA-256 `79fd3b96…c6faac`).
- **The ligand** is RV2 in its deposited pose, from the recorded
  `RV2_A_401.sdf` (SHA-256 `6fa65e2d…195fe4`).
- **The search space** is the frozen co-crystal box, 21.6 × 19.87 × 19.32 Å.
- **The contacts** appear only once RV2 is anchored. They are the deposited
  pose's polar heavy-atom pairs within 3.5 Å: THR 120 (2.59 Å) and GLN 123
  (2.92 Å, 3.20 Å).

`scripts/build_splash_scene.py` generates `apps/desktop/src/assets/splash-scene.json`:

- It verifies both input hashes before writing.
- It records them in the asset's `provenance`.
- `SplashScreen.test.tsx` checks those hashes, the atom count, the box and the
  contacts.

Using the asset needs nothing. Regenerating it needs the recorded artifacts
under `.ankora-data`.

Only the **search motion** before anchoring is illustrative, and the bottom
bezel says so. RV2 anchors when every startup check is recorded. It never
anchors on a failure.

## Startup record

The record has five rows. Each row is bound to the response that proves it.

| Row | Source | Confirmed value |
|---|---|---|
| Backend | `GET /health` | `ankora-backend <version> · <host:port>` |
| Runtime | `GET /system` | `Python <version> · <platform> <arch> · <environment>` |
| Tools | `GET /tools` | `N of 11 detected · GNINA deferred` |
| Recovery | `GET /work/recovery` | `no interrupted work` or `N interrupted runs preserved` |
| Project | `GET /projects` | `<active name> · N projects registered` |

Each row is `pending` until its response arrives:

- **Stamp.** A row is stamped with the seconds since the window opened, the
  first time it leaves `pending`.
- **Notices.** A row becomes a `notice`, never a silent `ok`, in three cases:
  - a non-deferred tool is missing;
  - recovery could not be inspected;
  - interrupted work exists;
  - the project catalog could not be read.
- **Tools.** The tools count matches the workbench's readiness panel. GNINA is
  deferred, so its absence is expected.
- **Project.** The workbench keeps a stand-in catalog until `/projects`
  answers. The record ignores that stand-in and waits for the real answer.
- **Failure.** If the backend never answers within the existing two-minute
  startup deadline:
  - the Backend row fails with `no answer from <host:port>`;
  - the other rows are marked `not checked`;
  - the screen stops with "Stopped — nothing was opened";
  - Retry receives focus;
  - "Copy diagnostics" copies the record lines and the error.

  In the installed application, the screen also names the backend log file,
  `%LOCALAPPDATA%\science.ankora.workbench\logs\backend.stderr.log`.

No version, tool or count is shown before the backend reports it. The screen
never says "all systems nominal".

## First paint

`index.html` draws nothing of its own. Before React mounts, the window shows
only the startup screen's canvas:

- `public/theme-boot.js` is a blocking script loaded from `'self'`. It applies
  the stored theme before the first paint, and accepts only a theme-shaped
  value.
- An `#root:empty` rule paints the body with that theme's `--canvas`.

As a result, no earlier splash, image or theme flash appears ahead of this
screen. The workbench still validates the stored theme.

## Timing and hand-over

- Anchoring starts no earlier than 900 ms after the window opens. Anchoring
  itself takes about 1 s.
- After anchoring starts, the screen holds for 1.5 s, or 0.4 s with reduced
  motion. Then the workbench opens.
- Once every row is recorded, Enter, Escape, Space or a click skips the hold.
- On the way out, the mark flies to the top-bar brand mark. The splash and the
  workbench share one identity.
- Under `NODE_ENV=test` the screen hands over immediately, so application tests
  are not slowed.

## Theme and accessibility

The screen uses only the shared design tokens: `--canvas`, `--accent`,
`--ligand`, `--precision`, `--coordinate-grid` and the related text and line
tokens. The canvas re-reads the palette whenever `data-theme` changes. It has
been verified in Obsidian Instrument, Midnight Laboratory, Cryo-EM Graphite,
Spectra Quartz and Light.

- **Screen readers.** The screen is a modal dialog with a polite live status
  line. Each row reads its value followed by a parenthesised status word.
- **Reduced motion.** `prefers-reduced-motion` removes the search motion,
  the mark drawing and the flight.
- **Hidden window.** The canvas pauses while the window is hidden.
- **Narrow windows.** Values wrap instead of being truncated, down to the
  960 × 680 minimum window.

## Verification

Automated checks:

- `apps/desktop/src/tests/SplashScreen.test.tsx`: record contracts, scene
  provenance, failure, the production hold timing and skipping.
- The full frontend suite, typecheck and `build:web`.

Visual check on 2026-10-20, in the dev app against a local backend, with
headless Edge and SwiftShader:

- the search state and the anchored state;
- the hand-over to the top bar;
- the failure state, with Retry focused;
- two notices: synthetic tool and recovery responses, used only for the
  capture;
- all five themes;
- the 1600, 1280 and 960 px widths.
