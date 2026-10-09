# Updated private-beta Windows installer — 2026-10-09

## Scope and source identity

The scientist accepted the viewer/interactions corrections and requested a new
complete installer. The desktop is built from source commit
`3941ed7bfac8b85fad244fd0f97871f73dc42ca0`, including the lossless interaction
presentation and development-loader repairs. See
[presentation evidence](INTERACTION_PRESENTATION_2026-10-09.md) and
[viewer evidence](DEVELOPMENT_VIEWER_INTEROP_2026-10-09.md).

The desktop was rebuilt with the explicit Tauri `build --no-bundle` option.
The existing create-only compactor then uses the previously verified compact
scientific payload and a 64 MiB solid-LZMA dictionary. The frozen backend,
engines, models, corresponding sources, licenses and offline WebView2 input are
unchanged. No scientific adapter, dependency lock, analysis, coordinate or
recorded result is modified. Models are restored offline during installation
as documented in [compact packaging](COMPACT_WINDOWS_INSTALLER_2026-10-09.md).

| Compiled input | SHA-256 |
| --- | --- |
| Updated native desktop | `26b405094cf09bfe487bccf89ff917917a33257b75ae8934dc67bfd9bc04df56` |
| Unchanged frozen backend | `0ede581a24b7c081687b08b19f82c327dcaff6ea7cdf5aefceff5155dda61dd3` |

## Preservation

The original complete candidate and its original NSIS build copy must retain
SHA-256 `e5b794fda5d92bca80692bb50fd3e20b726ca5bed0ba2c70573462487aa921ce`.
The previous compact candidate must retain
`4eac355618ebc8bde71adb17cec50b0bb6ee6761a009dd1ff81d952060a7174a`.
All three are explicitly protected by the compactor's before/after hashes.
Generated packages, absolute local paths and raw evidence remain ignored.

## Verification

- Frontend: 279 tests in 38 files passed; strict TypeScript, production bundle
  and optimized native Windows desktop build passed.
- Packaging/integrity: 24 focused backend tests passed. Rust formatting,
  tests/doc-tests and strict Clippy passed. Existing React fixture notices,
  large-chunk advisory and native linker notice remain non-failing.
- Complete staged legal/scientific payload verification passed.
- Production interaction presentation gate passed: explicitly synthetic
  32-contact fixture, three exact residue/subtype groups, 32 table rows,
  all-contact expansion and type filtering at 1280×800, 1536×864 and 1920×1080.
  There were no viewer, JavaScript or CSP errors. This is a presentation test,
  not a detector, affinity or experimental benchmark.
- Public-path and public-validation-status checks passed.

The installer smoke now optionally runs `-InteractionSmoke` against the actual
installed WebView after the startup/PDB/mmCIF gate. The interaction helper's
`--cdp` mode accepts only an explicitly launched localhost WebView and rejects
remote endpoints and mixed development/installed modes. Shipping configuration
does not enable debugging or relax CSP; replay requests must remain read-only.

## Package and installed acceptance

The separate complete compact candidate is **939,894,676 bytes** (939.89 MB /
896.35 MiB), 17.50% smaller than the original full installer. Its SHA-256 is
`96e4bd373391b517f2c659bdeea1688bc5466d05f3b6f260fd23c4288c61da11`.
All three protected old installers were rehashed unchanged after compilation
and again after installed acceptance.

The actual new NSIS package was installed in the guarded create-only test
directory, with Python/Conda/scientific developer tools removed from `PATH`:

- Installed desktop and frozen-backend hashes match the compiled inputs above.
  The complete legal/scientific inventory passed verification; all seven
  deduplicated P2Rank models were restored and verified offline.
- The real first launch reached the workbench without pressing Retry. A
  separate intercepted reload recovered automatically from two simulated
  connection refusals on the third health probe. Both splash images decoded.
- Actual **installed WebView2 155.0.4283.45** rendered synthetic PDB and mmCIF
  fixtures in Structure and Receptor, with no viewer/page errors or CSP
  violations. A captured Receptor screenshot was visually inspected and
  contains molecular geometry. These intercepted fixtures test rendering,
  not RCSB availability or chemical preparation.
- The same installed WebView passed the synthetic M9 presentation gate:
  **32 atomic contacts, three exact residue/subtype groups**, complete table,
  summary/all-contact switching and subtype filtering. Diagram bounds and
  saving controls passed at **1280×800, 1536×864 and 1920×1080**. The captured
  3D view visibly draws contact geometry. No viewer/page errors or CSP
  violations occurred; the captured served CSP contains no `unsafe-eval`.
  This fixture is not a real detector analysis or biological benchmark.
- The installed frozen backend passed **10/10 native scientific adapter
  smokes** in a spaced, non-ASCII output directory. Raw commands, versions,
  tool hashes and outputs remain local. Manifest SHA-256:
  `45b9f8711c2540532ec17452ae6dea09fd492d440747a971cf5e4b046bc39594`.
- Closing the test desktop released port 8765. NSIS uninstall succeeded and
  removed the isolated test application directory; project data was not deleted.

Raw ignored acceptance evidence: `compact-interactions-01`,
`installed-smoke-b1dc22d7e1ee4e53b30c1ecaa7688bf0`,
`frontend-smoke-1791581826308` and `interaction-ui-smoke-1791581842423`.
The standalone production-browser regression is
`interaction-ui-smoke-1791581003674`. No raw personal paths are published here.

Reproduce the installed gate with `scripts/smoke_windows_installer.ps1`, explicit
new installer and developer-test Python paths, and
`-FrontendSmoke -InteractionSmoke -ScientificMatrix`. Existing registered Ankora
installations or an occupied API port block the complete test instead of being
replaced or terminated. The private candidate is checksum-indexed by
`scripts.prepare_windows_release`; a manifest does not imply a public release.

## Release limits

This is a private, unsigned beta candidate, not a signed public release. No tag,
push, publication or expert outreach is authorized by this rebuild. Clean-VM
offline/no-existing-WebView installation, upgrade, signing and a wider hardware
matrix remain separate release gates. The prior clean-Windows user report does
not substitute for testing these new bytes.
