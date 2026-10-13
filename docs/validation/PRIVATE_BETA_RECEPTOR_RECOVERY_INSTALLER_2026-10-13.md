# Private-beta receptor recovery installer — 13 October 2026

## Scope and compiled identity

The scientist authorized pushing the accepted recovery correction and generating
a new complete installer. Public `main` was verified at source commit
`8e3fb7c4192435cc54bac686481a663ec137851f` before compilation.
See [source recovery validation](RECEPTOR_RELAXATION_RECOVERY_2026-10-13.md).

Both the desktop and frozen backend were rebuilt. A read-only inspection of the
backend's embedded archive confirms that the normalized diagnostic guard
bytecode matches the accepted source exactly. This is a code-identity check,
not a new receptor calculation. The OpenMM worker, potential, defaults and
0.5 Å acceptance limit are unchanged. No original scientific record is modified.

| Compiled input | SHA-256 |
| --- | --- |
| Native desktop | `8fbd4b4b359df48d97108258763e29e2b1ba4407c6d52530121703a77d30ed72` |
| Frozen backend | `b82d75b43ab4b718c71b219ca7cd4df819e1e66fad4092d5f098a964454a783d` |

The existing locks verify 36 Conda packages, 74 Python packages and seven
packaging tools. The reviewed scientific payload, seven P2Rank models,
corresponding sources, legal inventory and signed offline WebView2 input remain
unchanged. The new resource-file census matches the previous complete tree;
legal assembly verifies 664 components and 124 indexed files.

## Package and preservation

The new complete compact package is **939,924,353 bytes** (939.92 MB).
SHA-256: `93f5ca75a85c92797561479b58cfeb7a69ed77d868b7158f1d25362d2d5ce284`.
It uses the previously accepted offline model deduplication and 64 MiB
solid-LZMA compression. No supported tool, model or source archive is omitted.

The original complete candidate and NSIS copy, previous compact candidate and
previous interaction-beta candidate were explicitly protected and rehashed
unchanged during compilation and after installed acceptance. Outputs are
create-only and separate from those delivered packages.

## Installed acceptance

- Source gate: 741 backend tests and 285 frontend tests across 39 files passed
  in the preceding recovery unit. Packaging follow-up: 38 focused tests passed,
  including the opt-in installed-recovery wiring regression. Ruff and PowerShell
  parsing pass. Native formatting, release tests, strict Clippy and desktop
  compilation pass. Dependency/chunk/linker notices remain visible.
- The actual NSIS installed in a guarded isolated directory. Installed desktop
  and backend hashes match the compiled inputs. All ten supported tools are
  detected with developer Python/Conda/scientific directories removed from PATH.
  Complete installed legal/tool integrity and offline model restoration pass.
- Actual installed WebView2 **155.0.4283.45** reaches the workbench on first
  launch without Retry. An intercepted reload recovers after two simulated
  connection refusals, both splash images decode, and Mol* renders synthetic
  PDB/mmCIF structures in both Structure and Receptor. No viewer, page or CSP
  errors occur; the served CSP contains no `unsafe-eval`.
- The explicitly synthetic tolerance-error UI verifies original-residue 3D
  inspection, visible displacement, folded advanced settings, previous-plan
  labeling and an escapable checked relaxation option at 1280×800 and 960×680.
  There is no page horizontal overflow and exactly one intercepted preparation
  request: recovery does not trigger an automatic calculation. The captured
  laptop error panel was visually inspected. This is not real chemical evidence.
- Installed M9 presentation passes with 32 synthetic atomic contacts, three
  exact subtype groups, full contact/filter handling and reachable diagrams/
  saving at 1280×800, 1536×864 and 1920×1080, without CSP or viewer errors.
- The installed frozen backend passes **10/10 native scientific adapter smokes**
  in an isolated spaced/non-ASCII output directory. Manifest SHA-256:
  `05dde36c7883d912b8519820fd6a4b6264c5befb167cf9ce89a79d0c92202ad5`.
  The PowerShell 5 UTF-8 label is decoded as a mojibake non-ASCII sequence;
  this still exercises a non-ASCII path, not the intended accented spelling.
- Closing the test application releases the API port. NSIS uninstall succeeds
  and removes only the isolated test installation; project data is preserved.

Reproduction: `scripts/smoke_windows_installer.ps1` with explicit new installer
and test Python paths, `-ReceptorRecoverySmoke -InteractionSmoke -ScientificMatrix`.
The recovery switch includes the startup/PDB/mmCIF gate. Debugging remains
loopback-only in the test child's environment, not in shipping configuration.

Ignored local evidence includes `compact-receptor-recovery-01`,
`receptor-recovery-resources-01`, `user-guide-receptor-installer-20261013`,
`installed-smoke-30ea4e3bd3804821b606e2983aad9415`,
`frontend-smoke-1791926175673` and `interaction-ui-smoke-1791926193756`.

## Release limits

This is a complete offline **unsigned private beta**, not a public release.
Clean-VM/no-existing-WebView installation, upgrade, signing and wider hardware
acceptance remain separate gates. Current testing reused existing Evergreen
WebView2. Successful recovery controls do not guarantee that an arbitrary
repaired receptor will pass the unchanged geometric safeguards.

The create-only `private-beta-receptor-recovery-candidate` is checksum-indexed
with the exact compiled source commit, lock identities and unsigned/
publication-ineligible state using `scripts.prepare_windows_release`.
Independent verification passed for the exact file census, every checksum,
source/tree identity, locks and `NotSigned`/`publication_ready=false` state.
No tag, public release, signing identity or expert outreach is created.
