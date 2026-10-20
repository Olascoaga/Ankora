# Slim private-beta installer (Option A) — 20 October 2026

## Deliverable

The scientist authorized a push and a rebuild of the ~400 MB Option A
installer so that it carries the Anchoring startup screen. The package is the
same product as the 17 October slim build, rebuilt from current sources.

| Artifact | Size (bytes) | SHA-256 |
| --- | --- | --- |
| `Ankora_0.1.0_x64-setup.exe` | 426,941,199 (407.16 MiB) | `5465308ec6343acfa0c755e7e4619604af09cbc12738a138f3c75f928b065ae2` |
| `Ankora_0.1.0_x64-sources-companion.zip` | 243,736,647 | `46367eb873f5ccdb81589b26222750302b2f92b4d0b6fc3b6e5000642efc7c04` |
| Desktop executable (input) | — | `895f98ca869f028bbb2e89515db388b5a58091cd9eca2189a2a24e0d715a4eda` |
| Frozen backend executable | — | `2ddf97d0f99050ca8fb1915128dd6f58c3609a37e1c76f279433e6f95a3f4c6c` |

Location: `build/windows-runtime/private-beta-slim-20261020`.

- **Checksums.** All 11 `SHA256SUMS` entries verify.
- **Scientific payload.** Its SHA-256 is unchanged
  (`b118aefb…df7f7b08`, variant `ankora-vecmath-1.5.2-default-alphafold-v1`).
  The companion archive is byte-identical to the 17 October one.
- **Earlier installers.** Both are preserved and hash-checked by the builder:
  - `private-beta-20261015`: `f8cd152e…c46a701`
  - `private-beta-slim-20261017`: `ac1924e1…bc743193`

## Source identity

The installer is built from **`06ddaae`** (pushed to `origin/main`) plus
uncommitted working-tree changes.

`06ddaae` contains:

- the Anchoring startup screen (`3293587`);
- the pre-splash removal (`402fdb4`);
- the redocking fixes (`e9f4ca8`, `f332d6f`).

The uncommitted changes are the pending Obsidian Instrument theme and the
slim packager, exactly as in the 17 October slim build:

- The `git diff HEAD --binary` over `apps/desktop/src`, `backend/packaging`,
  `scripts/complete_windows_legal.py` and `docs/design/UX_FOUNDATION.md` has
  SHA-256 `668832b6…edd3a27`.
- The untracked `scripts/build_slim_windows_installer.py` has SHA-256
  `c327aacb…f576c0`.

These changes are not yet committed, so this build is not reproducible from a
single commit. The 17 October slim build had the same limitation.

## Build and gates

- **Environment.** The `ankora-dev` runtime matches the Windows locks: 36 Conda
  packages, 74 Python packages and 7 packaging tools.
- **Frozen backend.** PyInstaller 6.22.2 used the pending slim spec, writing
  into new `dist-slim-20261020` and `pyinstaller-slim-20261020` folders. All
  **122 frozen `ankora_backend` modules** are structurally equal to the current
  source compiled at `optimize=1`.
  - As a control, the 17 October slim build differs in exactly the five
    modules that changed since then: redocking RMSD, routes, ligand store,
    redocking schemas and redocking validation. The rebuild was therefore
    required.
- **Desktop.** Built with `tauri build --no-bundle`. The only notice is the
  known MSVC linker message.
- **Frontend.** 41 files and 334 tests pass, typecheck passes, and the
  production build passes.
- **Packaged-frontend smoke** (`frontend-smoke-1792538456133`). It ran against
  the embedded `dist` under the strict CSP with `script-src 'self'`, using
  synthetic API fixtures:
  - cold start after two refused health probes;
  - the startup screen shows no images, all five rows are answered
    (`ok, ok, notice, ok, ok`; the notice is the synthetic 0/11 tools fixture)
    and the scene canvas is drawn;
  - the screen hands over to the workbench;
  - Mol* loads Structure and Receptor for both PDB and mmCIF;
  - no CSP violations and no unmocked requests.
- **Packaging tests.** 76 tests pass, including the slim installer tests.

## Payload acceptance

Evidence: `payload-acceptance-slim-20261020`. These checks ran on the exact
staged payload that NSIS compressed (`installer-resources-slim-20261020`):

- Complete legal and scientific payload verification passes.
- The frozen backend was started in packaged mode with `PATH` reduced to the
  Windows directories. It reports `Bundled Python 3.12`, Python 3.12.13 and
  `app_mode=packaged`. All ten supported tools are available, and the port is
  released afterwards.
- The native scientific matrix passes for **10/10 adapters**, with versions,
  commands and raw outputs retained. Manifest SHA-256:
  `c86fa3acb06ebfabac723a9104da1e7fb359bb24fd81b6077a5a64d99701dda0`.
  GNINA remains deferred, not a hidden eleventh adapter.

## Not performed

The installed NSIS smoke was **not run**. An Ankora installation is
registered for this Windows user (`%LOCALAPPDATA%\Ankora`), and
`smoke_windows_installer.ps1` deliberately refuses to install over an existing
registration. That installation was not touched. The following therefore
remain unverified for this exact executable:

- silent install and uninstall;
- WebView2 inside the installed shell;
- installed byte identities.

This remains an **unsigned Windows 11 x64 private beta**, with no tag and no
public release. No scientific behavior changed for packaging.
