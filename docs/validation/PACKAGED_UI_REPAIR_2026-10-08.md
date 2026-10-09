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
