# Packaged UI regression repair — 2026-10-08

## User-reported boundary

The scientist reports that the complete installer installs on a clean Windows
machine, but startup initially fails until Retry is clicked and the downloaded
receptor does not render. Screenshots show missing splash artwork and an
`unsafe-eval` CSP violation. This is installation feedback, **not** full clean-
machine scientific/GUI acceptance. It supplements the earlier installed-tool
matrix, which did not exercise the actual production molecular viewer.

## Cold start

The desktop launches its backend asynchronously. The frontend previously made
one immediate health/system/tools attempt. It now probes health every 750 ms,
caps a stalled probe at three seconds, and caps the whole initialization,
including tool discovery, at 120 seconds. Only transport failure and HTTP
502/503/504 retry. Other errors remain visible. Unmount and a replacement attempt
cancel the old work. No scientific operation is retried.

Project catalog, interrupted-work recovery and saved receptor lookup now wait
for the connection. Splash images use build-resolved imports, not development
source paths. Its stable dismiss callback is no longer reset by usage polling.

Six focused startup tests and the existing App/Splash tests pass. Full frontend
verification is recorded with the viewer repair below. The original installer
is not rebuilt or replaced by this source correction.

## Viewer and production gate

The production bundle reproduced the reported CSP error before any molecular
content was requested. A browser exception trace isolated eager initialization
of `h264-mp4-encoder` through Mol*'s MP4 extension. Separately, Mol*'s binding-help
formatter uses `new Function` for text interpolation. Both paths are addressed
without allowing `unsafe-eval`, changing scientific coordinates, or editing
installed `node_modules` files.

The reviewed build adapter replaces only the named-placeholder formatter and
removes the MP4 extension's import/registration before evaluation. Unexpected
upstream source forms fail the build for review. Optional MP4 video export is
not included; molecular display and Ankora figure/PDB exports are unaffected.

Verification on Windows:

- Full frontend: **257 tests across 36 files passed**, including six readiness
  and four CSP adapter tests. Existing unrelated React test warnings remain.
- TypeScript and production build passed.
- Playwright 1.62.1 / Chromium **151.0.7922.34**, localhost production assets,
  configured desktop CSP plus `script-src 'self'`: **passed**. Two refused
  connections recover on the third health request without Retry; both splash
  images decode; the splash dismisses despite resource polling.
- The real Mol* renderer loads the existing, explicitly synthetic PDB and mmCIF
  fixtures in Structure and Receptor: four content requests, four view stages,
  no viewer/page errors and **zero CSP violations**. A captured receptor image
  was also visually checked. API fixtures test UI integration, not chemistry,
  network RCSB availability, or scientific preparation.
- Original delivered installer and its build copy retain SHA-256
  `e5b794fda5d92bca80692bb50fd3e20b726ca5bed0ba2c70573462487aa921ce`.

Reproduce after `npm ci` with `npm run build`, `npx playwright install chromium`,
then `node scripts/smoke_packaged_frontend.mjs`. JSON evidence and screenshots
are written under an ignored, new `build/windows-runtime/frontend-smoke-*`
directory. No running user backend or project artifacts are used. CI/release
workflows now require this production UI gate; no remote run is claimed here.

These are verified **source/bundle fixes**, not a newly delivered installer.
The existing 1.14 GB installer remains intentionally untouched. Include the
fixes in the separately requested optimized installer and repeat installed
clean-Windows UI acceptance. Browser CSP testing does not replace WebView2/
installer validation or the existing scientific native-tool matrix.

Follow-up 2026-10-09: the separate [compact candidate](COMPACT_WINDOWS_INSTALLER_2026-10-09.md)
now includes these fixes and passed the actual installed WebView2 rendering and
startup gate plus the 10/10 installed scientific adapter matrix. The original
1.14 GB installer remains unchanged. Clean-VM acceptance of this new candidate
and signing are still separate gates.
