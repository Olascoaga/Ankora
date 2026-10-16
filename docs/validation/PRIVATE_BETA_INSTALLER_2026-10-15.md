# Complete private-beta installer — 15 October 2026

## Deliverable and source identity

The scientist authorized push, a complete Windows installer, and retirement of
previous local installers after acceptance. Source commit
`66959d3162bdcf6822afea6f8cbe24375a63e542` was pushed and independently confirmed
on `origin/main` before compilation. It includes the corrections recorded in
[engineering correction evidence](ENGINEERING_CORRECTIONS_2026-10-15.md).

| Artifact | SHA-256 |
| --- | --- |
| Installer | `f8cd152e2d1687c5d0ee188a3e273334f043426d0309e8e5beae0b0c4c46a701` |
| Installed desktop | `e5e4f2223c23d4e589595d91ac582426425f108c25df7a2d08ff2c9bcd53ae87` |
| Installed backend | `c78eb3f37ef97f4cd6103598b570ca33f67ec3e1b9d8a497d743ee9fdaf80f3d` |

The installer is **939,929,818 bytes** (939.93 MB), named
`Ankora_0.1.0_x64-setup.exe`. The checksum-indexed local distribution is
`build/windows-runtime/private-beta-20261015`. The installer contains the complete
supported scientific runtime, tools, corresponding sources, notices, Java and
the signed offline WebView2 input. No supported component was removed to reduce
size. Compression uses the accepted source-archive model deduplication and
64 MiB solid LZMA policy.

## Build and source gates

- The active native Conda runtime matches all locked requirements: 36 Conda,
  74 Python and seven packaging packages. No scientific dependency was upgraded.
- Both the Windows desktop and frozen backend were rebuilt. All **122 frozen
  Ankora module code objects** match the current source compiled at the same
  optimization level, after normalizing embedded source filenames.
- Backend: **867 tests passed** in 262.07 seconds. Frontend: **310 tests across
  40 files passed**. Packaging: **71 tests passed**. Ruff, mypy on **141 source
  files**, TypeScript, production build, native formatting, the native release
  test and strict Clippy passed. Existing third-party deprecation/chunk/linker
  notices remain visible; no warning was converted into a scientific claim.
- Complete legal assembly verifies **664 components and 124 indexed files**.
  The generated resource census must cover the exact isolated distribution
  tree. Unused resource directories are not silently added to the package.
- Frozen API acceptance removes the missing-atom header from a labelled
  synthetic fixture. Template inspection identifies the missing alanine CB,
  legacy header-only inspection does not invent that observation, and the
  original imported bytes and SHA-256 remain unchanged. This exercises RDKit's
  dynamically loaded template function inside the frozen executable.

## Actual installed acceptance

The real NSIS package installed into the guarded test directory. Installed
desktop/backend hashes match the compiled inputs above. The test application
ran with Python, Conda and developer scientific directories removed from PATH.

- All ten supported tool entries are available, and the installed legal/tool
  integrity checks and offline P2Rank model restoration pass.
- Installed WebView2 **155.0.4283.45** reaches the workbench on actual first
  launch without Retry. Synthetic connection refusals recover on reload. Both
  splash images decode; real Mol* renders synthetic PDB and mmCIF fixtures in
  Structure and Receptor without viewer, page or CSP errors. No `unsafe-eval`
  permission is added.
- The guided three-step receptor controls, recovery and changed-plan guidance
  remain reachable at **960×680 and 1280×800**. No calculation starts from wizard
  navigation, focusing a residue or editing a recovery draft. Recovery requires
  a fresh explicit review. The laptop wizard capture was visually inspected.
- Interaction presentation retains **32 synthetic atomic contacts** and three
  exact subtype groups. Diagram fitting and figure-save controls pass at
  1280×800, 1536×864 and 1920×1080 without viewer/CSP errors. These are UI fixtures,
  not experimentally measured interactions or a detector benchmark.
- The installed backend passes **10/10 native scientific adapter smokes**, with
  versions, commands and raw outputs retained. Native manifest SHA-256:
  `cc26dbd174ff1c1ca661e556074a92513e252a169a1253434a2be02297c4469c`.
  GNINA remains explicitly unsupported, not a hidden eleventh passing adapter.
- Closing the application releases the API port. The test installation
  uninstalls successfully without deleting project data.

Reproduction uses `scripts/smoke_windows_installer.ps1`, explicit installer and
test-Python paths, and `-ScientificMatrix -InteractionSmoke
-ReceptorGuidanceSmoke -ReceptorWizardSmoke`. The new opt-in UI switches include
the original recovery/startup gate. Debugging is loopback-only and scoped to
the test child; no shipping debug configuration is introduced.

Release preparation and independent verification pass for the exact file
census, every checksum, source/tree identity, locks and signature state.
Ignored evidence includes `gemini-fixes-20261015`, `compact-20261015`,
`installer-resources-20261015`, `installed-smoke-86835c38e6344268a57989526999b51f`,
`frontend-smoke-1792123106804` and `interaction-ui-smoke-1792123130921`.

## Retirement and limits

Only after installed acceptance, **eight previous local installer EXEs**,
totalling **7,081,503,266 bytes**, were moved to the Windows Recycle Bin. Their
paths, sizes and hashes remain in private local evidence. Historical manifests
and validation records remain historical evidence, not current distributable
packages. Original structures, project data, scientific outputs, source
companions and development inputs were not deleted.

This remains an **unsigned Windows 11 x64 private beta**:
`NotSigned`, `tag_verified=false`, `publication_ready=false`. No public release,
tag, signing identity or outreach was created. Clean-VM/no-existing-WebView,
upgrade and broader GPU/hardware acceptance remain separate gates. These
adapter/UI checks neither rerun frozen benchmarks nor guarantee that every
receptor will pass preparation. Scientific choices and geometric safeguards
remain explicit and unchanged.
