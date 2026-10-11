# Illustrated user-guide verification: 7AQF / RV2

- Date: 2026-10-09
- Final documentation build and closure: 2026-10-11
- Starting source: `f33f220`
- Scope: private-beta user manual, real screenshots, print layout and documentation tests.
- Scientific implementation and installer payload: unchanged.
- Public release, signing and expert outreach: not performed. The scientist
  authorized the documentation commit and source push on 2026-10-11.

## Acceptance criteria

1. Replace every pending figure with a real, captioned application capture.
2. Document 7AQF/RV2 from immutable source through receptor decisions, explicit
   ligand state, conformer minimization, box, docking, interactions and exports.
3. State current UI limitations rather than inventing controls or results.
4. Separate a new tutorial execution from preserved historical validations.
5. Inspect every PDF page, check links/assets/captions and exclude personal paths.
6. Preserve original project data and the already delivered installer.

## Execution boundary

The current frontend was exercised through the local browser with the packaged
scientific backend and private tools. An isolated, Git-ignored reference-project
copy was used. Original 7AQF imports, accepted receptor, historical engine jobs,
redocking validations and raw scientific outputs were not altered. The 26
reference records and 54 artifacts were checked when assembling that copy;
legacy trashed Vina evidence was reopened only in the copy. The separate
clean-machine/installed acceptance remains
[PRIVATE_BETA_INTERACTIONS_INSTALLER_2026-10-09.md](PRIVATE_BETA_INTERACTIONS_INSTALLER_2026-10-09.md).

All 19 new images are real screenshots, not synthetic illustrations. Some are
pixel-exact crops to enlarge relevant controls and remove personal destination
paths; no UI labels, molecules or scientific values were redrawn or retouched.
The first six overview captures used the wider workbench; later detail captures
used the normal 1280 x 720 browser viewport. Raw captures and tutorial outputs
remain local under `build/user-guide-*/`, excluded from Git.

## Preserved reference inputs

| Input | Identity / observation |
|---|---|
| Deposited structure | 7AQF, X-ray, 1.77 A, 6266 atoms / 1218 residues / 1 model |
| Original mmCIF SHA-256 | `79fd3b96adca6bdbe17ded6e9c693534007ae2cb0538739044788754b7c6faac` |
| Accepted receptor | `72ff70a2-b373-4f59-b162-5bbc3a471b6e` |
| Receptor decisions | Chain A; remove 481 waters and RV2 A:401; 17 observed-residue repairs; 9 absent residues left unchanged |
| Receptor preparation | pH 7.4, AMBER, PDB2PQR 3.7.1 / PROPKA 3.5.1; Meeko 0.7.1 |
| Restrained relaxation | 50 kcal/mol/A squared; maximum 200 iterations; observed maximum displacement 0.38 A |
| Docking receptor SHA-256 | `83379bb5f78dcebc64df92e8b50c35bb81879913dc01e36024517a2be4604da0` |
| Analysis receptor PDB SHA-256 | `3fc201d458eeed347fd498d3173a0a1e8ae487c918f7669769b09c1223371799` |

The receptor was reopened, not newly prepared. Its historical protocol is not
evidence of exercising the newer expanded PROPKA-review controls. The original
and copied mmCIF hashes were rechecked at closure and agree.

## Newly executed single-ligand tutorial

| Stage | Recorded identity / result |
|---|---|
| Extracted RV2 parent | `557b3a9e-b049-4118-b73f-ef3b691a18ab`; neutral; 384.775 g/mol; 27 heavy atoms |
| Explicit ionization | Dimorphite-DL 2.0.2, pH 7.4; selected anion, charge -1; 383.767 g/mol |
| Independent conformer | `e7da693a-d5c7-447a-b2bf-c0635fa3022d`; RDKit 2025.09.6; ETKDGv3 pool 20; seed 20260819 |
| Minimization | MMFF94s, maximum 500 iterations, converged; 145.390 to 49.212 kcal/mol; delta -96.179 |
| Conformer SHA-256 | `8e0dc4618ef37456d064ecc5493d8b47eeeacb83d9e79b61b19d0edc9b7d6708` |
| Meeko preparation | `4c02124a-6e37-4460-a528-bac9e20731ef`; Meeko 0.7.1; Gasteiger charges |
| Ligand PDBQT SHA-256 | `760f3a289dd45e02ba71c6f04d66dd03c0cfaa6cc0873531fe562ea388cffc69` |
| Finalized box | `edebd876-72c7-4430-bb39-4ac9e88f6caa`; co-crystal RV2 A:401; padding 5 A |
| Box center / size, A | 35.4305, -2.9670, -0.7905 / 21.597, 19.870, 19.317 |
| Vina job | `a831ae9d-c208-4f62-9679-9ecab1699a18`; AutoDock Vina 1.2.7; completed |
| Engine protocol | Screening purpose; CPU 1; seed 20260823; exhaustiveness 8; modes 9; min inter-mode RMSD 1 A; range 3 kcal/mol; timeout 360 min |
| Recorded timing | 22:02:23.459 to 22:03:00.688 UTC, about 37 s; not a performance promise |
| Pose 1 SHA-256 | `350b4a21f35df6aa9143dab3170c5078f3aacb31e5b08c6a6b5e4021c29baccc` |

Scores for modes 1 through 9, in kcal/mol:
`-7.073, -6.798, -6.715, -6.652, -6.543, -6.526, -6.473, -6.294, -6.245`.
These are recorded outputs, not test expectations invented for the manual.
MMFF values assess within-molecule geometry, not affinity or library rank.
Vina's inter-mode RMSD is not crystallographic-reference RMSD. No new
reference-RMSD verdict or exact-repeat claim is made for this job.

## Interactions, saved files and Methods

- Analysis: `e2b1aa87-9e97-4950-bde9-9e9fb269d210`; ProLIF 2.2.1;
  `ankora-default-v1`; vicinity 6 A; exact tutorial mode 1.
- Structured output: 17 atomic contacts, 5 contacting residues, 8 exact
  residue/subtype groups. Counts: 13 Hydrophobic, 2 HBAcceptor, 1 HBDonor,
  1 Anionic. Summary displays 8 representatives / 17 positioned contacts.
- Hydrophobic filter: 13 / 17 contacts and 4 groups; all-atomic display confirms
  13 displayed / 13 positioned endpoints. Donor and acceptor subtypes remain
  separate in both 2D and 3D despite sharing a color category.
- PDB export: `81c5fc63-cc0b-4acd-9507-25f03e6e1ac3`;
  `ligand_receptor_complex.pdb`, 480421 bytes;
  SHA-256 `b9f17aba7bdc3da55c99b8ea9ceb7b7d9755c4631fdf31daaff8607afe4e3600`.
  Written bytes were rehashed at closure. No docking, minimization, alignment
  or reorientation was performed for export.
- Diagram export: `bc816972-9d6d-4045-b38e-2a784efd3904`, recorded all-contact
  diagram; SVG 86059 bytes and PNG 166494 bytes, 1004 x 692 pixels, 85 mm / 300 dpi.
  SVG SHA-256 `7ef620701067feaf1516c7fe748b4c1e022555c010538bddba0d7ca8970d7cbc`;
  PNG SHA-256 `be49024b13b02c6a6ef7545032a64cac2c54e55effe96d7305f24bd872963a89`.
  Both files appear in the Export catalog with their figure manifest.
- Methods: opened for this exact single-ligand job; 8 cited software entries,
  13 references, no reported provenance gaps. Receptor, box, ligand and engine
  sections were inspected. The copy control is documented; this session did
  not overwrite the user's clipboard. Tool-versus-worker version labels
  still require editorial review before manuscript use.

## Historical validation and explicit limitations

The manual uses the separately frozen
[SERPINE1 reference matrix](reference_cases/SERPINE1_7AQF_RV2.md).
CPU job `bdef5443-02c1-4d67-9ea9-d6f32e8a9890` used neutral RV2:
top-1 RMSD 3.139 A, best top-5 0.490 A, best overall 0.454 A, first recovery
rank 2, 6/10 within 2 A. GPU job `d6cfdfd8-ac07-48f9-bc16-c3982ebe6d94`
used anionic RV2: top-1 10.717 A, best 1.331 A, first recovery rank 2,
9/10 within 2 A. Both are `recovered_but_misranked`, not a matched-state
comparison and not validations of the new Vina job.

Current Validation UI reviews saved records but does not expose creation of a
new one. The manual states this limitation explicitly; the backend capability
does not justify inventing a desktop button. Result-table parent MW and a
legacy "not recorded" state label must not be mistaken for the actual prepared
anion. A single-ligand job has Methods/figure/complex exports but does not
appear in the screening-only campaign-bundle chooser.

The existing 323-record library was reopened only to inspect default filter
controls. No new filtering result, full-library preparation or screening
benchmark is claimed. Lipinski/Veber are required; Ghose/Muegge informative;
QED rank-only; PAINS/Brenk flags; duplicates excluded. Filtering and microstate
decisions still require explicit confirmation. Two automatic inspection
requests remained queued under resource admission; no engine was running when
capture work ended. The owned tutorial services were stopped at closure.

## Documentation verification

- 19 sequential figure assets and matching captions; no pending placeholders.
- Current actions and scientific values checked against UI and structured records.
- Final A4 PDF built with Edge 155.0.4283.45 (PDF creator: 155.0.0.0); 28 pages,
  all rendered with Poppler and visually inspected. Detail captures were corrected when print review exposed
  an incorrect crop. No personal machine paths appear in published figures/text.
- Final PDF: 2263968 bytes; SHA-256
  `a1065e0feb4de038e5d9de462a52d63e4b25b943a746bfb1c8eb1838793ae24e`.
- Relevant documentation-build tests: 14 passed. These include synthetic build
  failures, atomic PDF replacement, image existence, sequential captions,
  internal anchors, scientific caveats and portrait print bounds.
- Ruff for builder/test files: passed. Public validation-status checker: passed
  (2 frozen cases, 1 completed independent case). Public-path checker: passed.
- Full scientific suites and installer were not rebuilt for a documentation-only
  change; their existing acceptance evidence is not represented as a new run.

The source guide, printable PDF, captioned images and this evidence record form
one documentation unit. Private continuity memory and raw tutorial evidence
remain excluded from Git.
