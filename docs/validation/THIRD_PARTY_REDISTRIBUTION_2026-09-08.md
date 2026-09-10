# Third-party redistribution validation — 2026-09-08

## Scope

This record closes adversarial-remediation Gate E item 24d for the Ankora
0.1.0 Windows installer: identify what the installer actually redistributes,
retain the applicable license and notice texts, provide version-specific source
locations where reciprocal licenses require them, and prove that those files
arrive in the installed application. It is an engineering compliance record,
not a substitute for legal advice.

Release signing, publication, and release-asset checksums remain Gate E item
24e. This review does not authorize bundling any external docking engine.

## Inventory boundary

`scripts/generate_third_party_notices.py` uses four independent sources of
evidence:

1. PyInstaller's `Analysis-00.toc` selects Python distributions whose modules,
   data, hooks, or bootloader are actually copied into the frozen backend.
2. Those copied paths are intersected with exact Conda package file manifests,
   so native DLL/runtime providers are included while unrelated packages in the
   scientific environment are excluded.
3. The installed non-development `package-lock.json` closure conservatively
   covers the minified frontend. This may retain notices for a production
   package later removed by tree-shaking, but can never omit a production
   package merely because its name disappeared during minification.
4. Cargo metadata selects the normal dependency graph for
   `x86_64-pc-windows-msvc`; build-only and development-only crates are not
   presented as shipped runtime components.

The accepted inventory contains 543 component records:

- 71 Python distributions selected by the frozen-backend analysis;
- 21 Conda/native runtime providers owning copied files;
- 206 installed web production packages;
- 244 normal Rust dependencies linked for Windows x86-64; and
- the NSIS 3.11 installer stub.

The Python and Conda categories intentionally overlap where a Python
distribution and its native package layer carry distinct provenance or notice
material. The machine-readable identity is category, normalized component name,
and exact version. No generated file contains a development-machine path.

## License and source handling

Every installer contains, below its `legal/` resource directory:

- `ANKORA_LICENSE.txt` — Ankora's MIT license;
- `THIRD_PARTY_INVENTORY.json` — component/version/license/source/evidence and
  license-document hashes;
- `THIRD_PARTY_NOTICES.txt` — a component index and 1,452,000+ bytes of
  deduplicated upstream license and notice text; and
- `SOURCE_AVAILABILITY.txt` — version-specific source locations for LGPL-,
  GPL-exception-, and MPL-covered components and the corresponding Ankora
  application/rebuild source location.

LGPL components remain separately represented in the PyInstaller onedir
runtime. Ankora ships its complete MIT application source and deterministic
build recipe, imposes no restriction on replacement or reverse engineering for
debugging modified LGPL libraries, and records exact source/release locations.
MPL-covered Python and Rust components receive the same version-specific source
availability. PyInstaller's upstream license and special exception are retained
verbatim; the exception permits distributing its generated executable under
Ankora's chosen license. NSIS's complete `COPYING` file, including compression
module terms, is retained as generation input and in the consolidated notices.

The governing upstream references consulted for this boundary were the
[GNU LGPL license index](https://www.gnu.org/licenses/),
[Mozilla MPL 2.0 executable-form requirements](https://www.mozilla.org/en-US/MPL/2.0/FAQ/),
[PyInstaller licensing terms and bootloader exception](https://www.pyinstaller.org/en/v4.10/license.html),
[NSIS license appendix](https://nsis.sourceforge.io/Docs/AppendixI.html), and
[Microsoft's WebView2 distribution guidance](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution).

## Deliberate exclusions

AutoDock Vina, AutoGrid4, AutoDock4, AutoDock-GPU, GNINA, and P2Rank are not
inside the application or installer. Ankora can discover and execute separately
installed copies, but the user remains responsible for acquiring them under
their own terms. The inventory generator and installed smoke test both reject
any record that would present one of these names as a bundled component.

Tauri's `downloadBootstrapper` mode also does not embed the WebView2 Evergreen
Runtime or bootstrapper. When WebView2 is absent, the installer obtains the
Microsoft bootstrapper at installation time; accordingly neither is claimed as
an Ankora-redistributed component.

## Enforcement and acceptance

- `scripts/test.ps1` and Windows CI perform a static check that web and Rust
  records exactly match their current lock/normal graphs, every Python record
  remains explainable by the locked Windows runtime, all referenced license
  hashes exist in the notices, reciprocal entries have source locations, and
  external tools remain excluded.
- `scripts/build_windows_installer.ps1` runs the generator after PyInstaller and
  uses `--check`; dependency or frozen-file drift stops packaging instead of
  silently rewriting the reviewed notice payload.
- `scripts/smoke_windows_installer.ps1` requires all four legal files in the
  installed directory, parses the inventory, rechecks external-tool exclusion,
  and verifies representative LGPL/MPL source entries before launching Ankora.
- Unit tests fix the machine-neutral inventory contract and prove that an
  external engine cannot enter the bundled-component set.

Gate E item 24d is accepted when the rebuilt installer passes that installed
smoke and the complete repository verification gate remains green. The next
release task is 24e: checksum-indexed/signable release artifacts and publication
automation; it must not weaken or regenerate this inventory after signing.

## Executed evidence

On the authoritative Windows x86-64 machine, the generator reproduced the
reviewed 543-component inventory byte for byte after a clean PyInstaller
analysis. The four legal resources total 1,741,125 bytes. The rebuilt
`Ankora_0.1.0_x64-setup.exe` is 103,492,506 bytes with local acceptance SHA-256
`cc7a2feba3ee2d3a75bbc4b6cb29d1f0053451482c58d934d862d0455066b283`.

The installer smoke applied that artifact to an isolated current-user
directory, verified and parsed every installed legal file, confirmed the
external-tool exclusion, launched the bundled backend with Python and Conda
absent from `PATH`, observed the packaged runtime identity, stopped the backend
with the desktop, and uninstalled successfully. The first cold launch exposed
a race with the previous 30-second test ceiling: backend logs showed a healthy
server immediately after the harness timed out. The bounded ceiling is now 60
seconds to allow Windows application-control/antivirus inspection of a newly
installed unsigned scientific runtime; the repeated clean smoke passed in
26.7 seconds. This timing allowance changes no product startup behavior.
