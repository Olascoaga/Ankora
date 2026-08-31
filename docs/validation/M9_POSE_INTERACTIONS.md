# M9 Pose Interactions acceptance evidence

- Status: accepted and closed
- Acceptance date: 2026-08-28
- Platform: Windows 11 x64
- Tested code baseline: `751da37`
- Scientific contract: `docs/scientific/POSE_INTERACTION_POLICY.md`

## Accepted boundary

M9 interprets one exact preserved docking pose as geometric contact evidence. It
does not report experimental affinity, biological activity, mechanism, or an
energy decomposition. The structured immutable analysis is authoritative; the
2D diagram, table, Mol* focus, saved figures, and combined PDB are views or
exports of that recorded evidence.

The accepted result families are AutoDock Vina, AutoDock4 CPU, and
AutoDock-GPU. Native engine semantics remain distinct: Vina modes are not
renamed as AutoDock4 clusters/runs, and scores from different scoring families
are not merged.

## Real preserved-pose evidence

Live Windows-backed review reopened all three implemented result paths:

- AutoDock-GPU campaign `a36d490c-1b91-4674-8075-9f31fbbad3c9`, Compound 231,
  Cluster 1/run 1, pose artifact `3ef82c77-17ac-40da-92aa-f891a67d5d98`, and
  immutable ProLIF analysis `a011df8c-38a5-4afa-a61d-2f7281f7240e` with 13
  structured contacts;
- AutoDock4 CPU job `bdef5443-02c1-4d67-9ea9-d6f32e8a9890`, including two
  preserved analyses and a selected record with 33 structured contacts;
- Vina campaign `693d3c55-ee89-4089-8cff-a77e6dc8ec23`, Compound 187, Mode 1,
  which created immutable analysis `de66d321-661c-4c27-8144-c6a6f64f8812`
  with 20 structured contacts.

Each path exposed its exact pose/run identity, detector/version, skeletal 2D
diagram, complete structured contact table, receptor context, and residue
focus. Closing the analysis restored the campaign and catalog without
recomputation.

## Responsive review and figure evidence

The scientist reviewed the corrected native layout on a 1917 x 996 laptop and
a 2551 x 1382 monitor and explicitly accepted the complete scroll path. Browser
measurements also covered 1280 x 720 and 1900 x 1000. The 3D and evidence
columns remain side by side where useful, return to one complete workspace
scroll on short screens, and stack without overlap at the narrow breakpoint.

The preserved Compound 231 analysis saved SVG, PNG, TIFF, and PDF evidence at
85 mm and 300 dpi with valid format signatures. Figure
`866a0567-4154-46c4-9e9a-f201819d6d97` records the later reachability smoke
(49,798-byte SVG and 117,677-byte 1004 x 692 PNG) without rerunning ProLIF.

## Exact-pose PDB evidence

After replacing the stale backend, the live Results interface saved project
export `1b13150f-9cf8-4461-945b-48638312c417` and displayed its exact path,
size, and SHA-256. A second real write exercised an explicit existing working
folder and created export `50a37909-a47e-45a1-982a-57affc2e04ff`.

Both writes produced the same 480,218-byte PDB with SHA-256
`44779de947a9fe3b4d0932ae409b94bb12f9125937fc91e0b35e425063ff701d`.
The explicit-folder copy and its project-retained manifest agree. Gemmi reopened
the file as one model, two chains, 371 residues, and 5,915 atoms. Chain A holds
the receptor; chain Z holds one `UNL` residue with the 26 ligand atoms. The PDB
contains a terminal `END` record. PyMOL and Chimera were not installed on this
station, so no external-viewer launch is claimed; the file-format, identity,
hash, and Ankora/Mol* checks are the recorded acceptance evidence.

## Results lifecycle and portable evidence

- Real campaign export `c80c5d50-b375-4169-a8d1-0429cf128938` contains 25
  result rows, one matching immutable interaction analysis, four saved figures,
  and 12 ZIP entries. Every indexed file matched its recorded byte count and
  SHA-256; warnings and unavailable files were both zero. Export did not invoke
  ProLIF or a renderer.
- The live Results UI selected two of 19 preserved campaigns, displayed their
  exact identities and the required acknowledgement, then canceled. All 19
  remained active.
- Individual and two-record Trash transactions passed through the typed API on
  labelled synthetic isolated project trees. Campaign-owned M7/M9 dependents
  moved under recoverable operation manifests; shared receptor, ligand,
  binding-site, map, and export artifacts remained present. No real campaign
  was removed for acceptance.

## Authoritative verification

`scripts/test.ps1` passed on 2026-08-28:

- 352 backend tests;
- Ruff;
- strict mypy across 92 source files;
- 179 frontend tests across 23 files;
- strict TypeScript and the production Vite build;
- Rust formatting, strict Clippy, unit tests, and doc tests;
- optimized native Windows Tauri build at
  `apps/desktop/src-tauri/target/release/ankora-desktop.exe`.

The non-failing notices were the existing Starlette/httpx deprecation, React
`act(...)` warnings in the AutoDock4 library test, transitive browser module
externalization and Mol* chunk-size notices, and MSVC linker output.

## Acceptance result

All seven criteria in `docs/scientific/POSE_INTERACTION_POLICY.md` are
satisfied. M9 and the implemented v0.1 functional scope are closed. This does
not claim that an arbitrary docking protocol is experimentally validated, that
AutoDock-GPU is bitwise reproducible, or that the application has completed
Windows installer/signing and third-party redistribution review.
