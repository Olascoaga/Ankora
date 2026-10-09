# Complete compact Windows candidate — 2026-10-09

## Scope and preservation

The scientist requested a second, smaller offline installer, leaving the
delivered 1,139,221,308-byte installer unchanged. Its SHA-256 remains
`e5b794fda5d92bca80692bb50fd3e20b726ca5bed0ba2c70573462487aa921ce`.
Neither that candidate nor its original NSIS build copy may be overwritten.
This work does not authorize a public release, signing identity, or new engines.

The new desktop includes the [cold-start and strict-CSP viewer fixes](PACKAGED_UI_REPAIR_2026-10-08.md).
No scientific protocol, coordinate, model or engine version changes.

## Lossless size reduction

The original package already used solid LZMA. A 64 MiB dictionary alone produced
a 1,112,999,108-byte trial (2.30% smaller), without altering resources. This trial
is not the final candidate.

All seven P2Rank `model.zst` files also occur, byte-identically, in the already
shipped immutable P2Rank corresponding-source ZIP. The compact variant stores
that ZIP once and restores the seven runtime files during installation. Their
combined uncompressed size is 207,438,741 bytes. Nothing is fetched online.

The installation-only frozen-backend worker checks the pinned source ZIP and
scientific-payload manifest hashes, reads seven explicitly named entries (never
extract-all), enforces containment and a per-file size bound, verifies each
model's runtime hash before publishing it, and refuses to replace modified
existing models. An installation failure stops NSIS with an error. This worker
does not start the API or run a scientific calculation. Original source archive
bytes, notices, all models, and all engines remain available after installation.

The compactor uses a create-only output directory, checks the generated NSIS
shape and full resource-file census, verifies the staged legal/tool inventory,
captures build-input hashes, and rechecks explicitly protected old installers.
The inherited uninstall list still includes the restored model files. It never
calls Tauri's default bundler, which would overwrite the old setup executable.

## Implementation verification

- Complete backend suite: 726 tests passed; two subsequently added create-only/
  compiler-failure protection tests also passed. Focused materialization and
  compactor coverage: 18 tests. Fixtures are explicitly synthetic bytes.
- Ruff clean; strict mypy passes on 138 source files.
- Frontend: 257 tests / 36 files; TypeScript, production build and optimized
  Windows desktop build passed. Production Chromium rendering regression passed.
- Actual newly frozen worker restored all seven real pinned models in an
  isolated directory and verified their SHA-256 identities successfully.
- Generated complete legal inventory: 664 components / 124 indexed files.
- Generated compact NSIS embeds the same signed, pinned offline WebView2 input.

## Delivered candidate and installed acceptance

The separate compact candidate is **939,900,409 bytes** (939.9 MB / 896.36 MiB),
199,320,899 bytes smaller than the original: **17.50% reduction**. Installed
capabilities and source/model content are unchanged; this reduces download size,
not the required installed scientific payload.

SHA-256:
`4eac355618ebc8bde71adb17cec50b0bb6ee6761a009dd1ff81d952060a7174a`.

The actual NSIS package was installed in a create-only test directory with
Python/Conda/scientific developer tools removed from `PATH`:

- Complete installed legal inventory and exact scientific tool/model hashes
  passed verification. All seven deduplicated models were restored automatically.
- The installed desktop launched its own frozen backend and reached the
  workbench without pressing Retry.
- Actual installed **WebView2 155.0.4283.45** passed the production UI regression:
  a separate reload with two simulated connection refusals recovered on the third
  health request; both splash images decoded; the real Mol* renderer displayed
  synthetic PDB/mmCIF fixtures in Structure and Receptor. All four stages passed,
  with no viewer/page errors and zero CSP violations. The actual served desktop
  CSP was captured and contains no `unsafe-eval`. A receptor screenshot was
  visually inspected. Mock API replies test rendering, not RCSB connectivity or
  chemistry; the initial installed launch used the real bundled backend.
- The installed frozen runtime passed **10/10 native scientific adapter smokes**
  with a spaced, non-ASCII output path. Evidence manifest SHA-256:
  `bb73458beb8d1a69ce6c311ef6df915385c90da0ff94355a3e31f060835776d6`.
- Closing the desktop released port 8765. The test installation was uninstalled
  successfully; project data was not deleted. Both original installer copies
  retain their original SHA-256.

Native UI acceptance is now exercised by
`scripts/smoke_windows_installer.ps1 -FrontendSmoke -ScientificMatrix` with explicit
installer and developer-test Python paths. The script temporarily exposes a
loopback-only WebView debugging endpoint in its child environment, never in
shipping configuration. The UI gate uses synthetic routes only after checking
the actual first launch and does not create user scientific artifacts.

This is a locally verified **unsigned candidate**, not a public release.
Clean-VM/no-existing-WebView offline installation, upgrade, display/hardware
matrix and signing remain separate release gates. Existing Evergreen WebView2
was reused in this developer-machine test; embedding its offline installer was
independently hash/signature-verified, not mistaken for installing it on a clean VM.

## Reproduction

Build the current desktop using `npm run tauri:build` (no bundling). Freeze the
backend into a new build directory, copy the reviewed scientific tools, and
generate the complete legal payload using the existing packaging helpers. Stage
those as `backend/` and `complete-legal/` beneath a new resources directory.
Use `python -m scripts.compact_windows_installer --help` to select the previously
generated full NSIS script, NSIS compiler, new resources/output directories and
both original installer paths to protect. Pass `--deduplicate-resources` and a
64 MiB dictionary. Any changed generated resource census requires review rather
than silently omitting files. All local paths/evidence remain ignored build data.
