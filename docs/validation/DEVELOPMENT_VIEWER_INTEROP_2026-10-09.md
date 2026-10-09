# Development molecular viewer interoperability — 2026-10-09

## Scope and reproduced cause

The scientist reported a blank M9 3D view with a missing `create` export from
`mutative/dist/index.js`. The new development-browser regression reproduced
that exact failure before the configuration fix. Previous production-browser
acceptance did not test the development loader; unit tests mock the viewer.

Mol* must remain outside Vite's prebundle so Ankora's reviewed CSP transform
can inspect its source. Two development-specific defects were confirmed:

- Mol* imports a deep CommonJS `mutative` entry, not its ESM package root.
  Its UI markdown chain also contains a CommonJS style parser. Both boundaries
  now use explicit nested dependency prebundling: `molstar > mutative/dist/index.js`
  and `molstar > react-markdown`. This follows Vite's documented
  [excluded-ESM/nested-CommonJS configuration](https://vite.dev/config/dep-optimization-options#optimizedeps-exclude).
- Development module IDs carry `?v=...` cache queries. The CSP transform's
  suffix check previously missed them, so optional MP4 code was still imported
  and safe text interpolation was not substituted. Matching now removes the
  query before checking the physical filename. Upstream source changes still
  fail closed rather than bypassing the review.

No dependency version, scientific adapter, contact detection/profile, analysis,
campaign, coordinate, or result changed. The delivered installers were neither
rebuilt nor overwritten. The production CSP still forbids `unsafe-eval`.

## Acceptance evidence

- **279 frontend tests / 38 files passed**, including configuration coverage
  and both query-free and development-query CSP-transform regressions.
  Existing unrelated React `act`/NaN fixture notices remain non-fatal.
- Strict TypeScript and production Vite build passed. The existing large-chunk
  advisory remains. Public-path and public-validation-status checks passed.
- Pinned Chromium **151.0.7922.34** passed development cold-cache and cached
  reload checks with the SYNTHETIC 32-contact presentation fixture. It retains
  three subtype groups, 32 table rows, all-contact expansion and exact filtering.
- Read-only development replay of saved AutoDock-GPU/M5V analysis
  `779d5950-ea01-4bee-bb93-0ec38324c0ba` passed cold load, cached reload, all-contact
  expansion, filtering, and laptop/monitor checks. The retained record has
  **32 contacts, seven residues and eight residue/subtype groups**. A captured
  3D view visibly contains the ligand and receptor; viewer errors, JavaScript
  errors and CSP violations were all absent.
- Both replays passed at **1280×800, 1536×864 and 1920×1080**, including SVG frame
  bounds and reachable saving controls. The source hashes below were checked
  before and after replay, without invoking ProLIF or any docking tool.
- Production interaction replay and the separate delayed-start/assets/PDB/mmCIF
  Structure/Receptor browser gate also passed under strict CSP.

| Read-only M5V input | SHA-256 |
| --- | --- |
| Analysis JSON | `175281630d44812db94dac53cd47f8dfd95e4aba6045c2101cb4f050816897a8` |
| Analysis receptor PDB | `4770f1a1ff9581201fa7963e39d9cafd73255168860ea3b351bfebaec47d66d6` |
| Native run-1 pose | `b14e2305ed895f9119d8694914f73f0681f4ced4b593bb4504ca59efb6247b0b` |

Raw local evidence is ignored: `interaction-ui-smoke-1791575721030` records the
original failure; `interaction-ui-smoke-1791575946689` the passing synthetic
development check; `interaction-ui-smoke-1791576052006` the passing real replay;
`interaction-ui-smoke-1791576074805` the production interaction check; and
`frontend-smoke-1791576074481` the production startup/Structure/Receptor check.
Intermediate dependency failures are retained locally, not hidden or discarded.

## Reproduction and limits

With frontend dependencies and the pinned Playwright Chromium installed, run
`node scripts/smoke_interaction_presentation.mjs --development`. It loads the
actual Vite configuration with an isolated optimizer cache and an OS-assigned
localhost port. No existing development server or user cache is reused. API
responses are intercepted and mutating requests fail the check. Optional
`--analysis`, `--receptor` and `--pose` arguments replay exact local saved inputs.

The development test server nonces Vite's inline React preamble; it does not
allow inline scripts or eval globally and does not change Tauri's security
configuration. This browser test is not an installed-WebView2 or live-backend
acceptance. Windows CI now includes the synthetic development gate alongside
the production gates; it has not run remotely for this unpushed local unit.

Restart the development application and reopen the existing analysis for native
scientist acceptance. No recomputation is necessary. Only after that acceptance
should a separate new installer be generated, preserving the delivered EXEs.
