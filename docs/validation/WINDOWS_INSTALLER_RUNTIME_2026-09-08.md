# Windows installer and bundled runtime validation — 2026-09-08

## Scope

This record closes adversarial-remediation Gate E item 24c only: produce a
Windows installer whose desktop owns a self-contained Ankora Python backend,
and make the WebView2 distribution choice explicit. It does not authorize
redistribution of independently licensed docking engines, sign a release, or
publish an installer.

## Reproducible inputs

- `environment/windows-64.conda.lock` and
  `requirements/windows-py312.lock` define the previously validated Python
  scientific runtime.
- `requirements/windows-packaging.lock` adds seven build-only distributions,
  each pinned to an exact version and SHA-256.
- `backend/packaging/ankora_backend.spec` is the reviewed PyInstaller onedir
  contract. It collects Ankora plus the Python modules and distribution
  metadata required by RDKit, Gemmi, MDAnalysis, ProLIF, PDBFixer, OpenMM,
  PDB2PQR/PROPKA, and Meeko.
- `scripts/build_windows_installer.ps1` refuses an unverified scientific
  environment, regenerates only bounded ignored build directories, smokes the
  frozen backend, and then invokes the Tauri NSIS bundle.

Generated runtime and installer files remain outside Git. The source locks,
packaging recipe, lifecycle implementation, tests, and this evidence record are
the reviewable contract.

## Installed lifecycle and storage

The Windows release desktop launches exactly one bundled
`backend/ankora-backend.exe` from the Tauri resource directory. It binds only
to `127.0.0.1:8765`, rejects an already occupied port instead of trusting an
unrelated process, and receives the desktop PID for orphan prevention. Normal
desktop exit kills and waits for the child; the backend also exits if its
desktop parent disappears unexpectedly.

Installed scientific state lives below Tauri's application-local data
directory in `data/`. Backend stdout and stderr append to files below the
adjacent `logs/` directory. Development continues to use the repository-local
`.ankora-data` store. No personal or machine-specific absolute path is embedded
in the bundle recipe or tracked validation record.

Packaged PDBFixer, PDB2PQR/PROPKA, and Meeko requests route back through
isolated worker modes of the frozen executable. The frontend still never
executes a scientific tool. AutoDock Vina, AutoGrid4, AutoDock4,
AutoDock-GPU, and P2Rank remain external discoveries and are not present in
this installer. The subsequent Gate E item 24d review records and enforces that
boundary in `THIRD_PARTY_REDISTRIBUTION_2026-09-08.md`.

## WebView2 decision

The installer uses Tauri's silent `downloadBootstrapper` mode for the Evergreen
WebView2 Runtime. Windows 11 normally already supplies Evergreen; a machine
without it needs network access during installation. A fixed runtime was
rejected because it would add a large browser payload and transfer browser
security-update responsibility to Ankora, while an offline installer would
also substantially increase the application download.

The existing `--disable-gpu-compositing` browser argument remains a narrow,
measured workaround for the WebView2 151 DirectComposition black-window
regression recorded on the authoritative Windows machine. It does not apply
the broader `--disable-gpu` switch: Mol* WebGL remains hardware accelerated.
The workaround must be retested against later Evergreen releases before it is
removed. No remote application content was added, and the Tauri capability and
CSP boundaries remain unchanged.

## Executed acceptance evidence

The following checks ran on the authoritative Windows x86-64 machine from the
verified locked environment:

1. Static and runtime lock verification accepted 36 Conda packages, 74 Python
   distributions, and seven packaging tools.
2. PyInstaller produced a 3,572-file onedir backend totaling 357,735,220 bytes.
3. With `PATH` restricted to Windows system directories, the frozen backend
   reported `app_mode = packaged`, `python_environment = Bundled Python 3.12`,
   and all five packaged Python tool boundaries available: PDBFixer, PDB2PQR,
   PROPKA, Meeko receptor, and Meeko ligand.
4. Tauri and NSIS produced `Ankora_0.1.0_x64-setup.exe`, 103,341,941 bytes,
   SHA-256
   `30f148feb371cbc2fa9d65f75411819d7601e7c42b7288edbf1da3019930bed5`.
5. The installer was applied silently to an isolated current-user test
   directory with Python and Conda absent from `PATH`. The installed desktop
   launched its bundled backend, the health and system endpoints returned the
   packaged identity, closing the desktop stopped the backend listener, and
   the NSIS uninstaller completed successfully.
6. Backend tests, Ruff, strict mypy, frontend tests and type checking, Rust
   formatting/Clippy/tests, and the non-installer Tauri release build were run
   through the repository verification gate after implementation.

The installer hash above identifies this local acceptance artifact, not a
published or signed release. Gate E item 24e owns checksummed release artifacts,
signing, and publication automation.

## Verdict

Gate E item 24c is accepted: the Windows desktop is installable and owns a
self-contained backend that does not depend on a user's Python distribution.
The subsequent item 24d closes third-party notices and redistribution
decisions. Item 24e (release artifact verification, signing, and publication)
remains open and cannot be inferred from this result.
