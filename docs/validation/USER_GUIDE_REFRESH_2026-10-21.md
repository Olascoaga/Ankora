# Illustrated manual refresh — 21 October 2026

## Acceptance and scope

The scientist requested the current application appearance, the restored
redocking workflow and a review of missing manual instructions. This unit
updates the Markdown guide, its twenty real UI figures, the PDF builder and
the generated PDF. It does not change chemistry, scientific results, engines,
the application, an installer or the separately hosted website.

The capture uses the working development interface (Obsidian theme, still
pending separately from base commit `6cabd55`), not a newly released installer.
Edge 155.0.4283.62 renders the production-built frontend. A real local backend
serves an isolated copy of the existing 7AQF/RV2 tutorial. Documentation runtime
tool discovery is real, but is not installed-package acceptance.

## Preserved scientific inputs

- Source 7AQF artifact `76f5afae-1f5d-4baa-8359-a7335407abb8`;
  mmCIF SHA-256 `79fd3b96adca6bdbe17ded6e9c693534007ae2cb0538739044788754b7c6faac`.
- Historical receptor `72ff70a2-b373-4f59-b162-5bbc3a471b6e`;
  prepared PDB SHA-256 `3fc201d458eeed347fd498d3173a0a1e8ae487c918f7669769b09c1223371799`.
- Original crystallographic RV2 `557b3a9e-b049-4118-b73f-ef3b691a18ab`,
  neutral parent 384.775 g/mol. The distinct recorded anionic docking state is
  `2a5de54b-bce3-488a-8d9b-45572b58a6df`, 383.767 g/mol.
- Preserved Vina tutorial job `a831ae9d-c208-4f62-9679-9ecab1699a18`,
  nine modes, best score -7.073 kcal/mol; pose-1 SHA-256
  `350b4a21f35df6aa9143dab3170c5078f3aacb31e5b08c6a6b5e4021c29baccc`.
- Its ProLIF analysis `e2b1aa87-9e97-4950-bde9-9e9fb269d210`:
  17 atomic contacts, five residues, eight exact residue/subtype groups;
  hydrophobic filter 13/17 contacts in four groups.
- Figure 9 configures that Vina job and the original reference at 2 Å with
  confirmation **unchecked**. No Vina reference-RMSD verdict was generated.
  Figure 10 separately reopens historical CPU validation
  `179484ac-a6cd-497c-8147-1333955813ff`: top-1 3.139 Å,
  best top-five 0.490 Å and best overall 0.454 Å. These chemical states and
  evidence sets are not a matched-input engine benchmark.
- The illustrative `dbv6.sdf` library has 323 imported records. Its figure is
  current policy controls, not a newly calculated filter or docking outcome.

The original tutorial's **810 files** were SHA-256-censused before and after
capture and remain byte-identical. The isolated copy can create local runtime
leases/catalogs; those are not new chemical results or writes to the original.

### Capture boundaries

GETs use the copied saved records. The capture layer replays only these exact
already-recorded responses to let the UI reopen the corresponding stages:
original extraction, the recorded protonation candidate/state, conformer and
PDBQT preparation. It does not execute the buttons' scientific operations.
The non-persistent binding-box preview is allowed against the copied receptor.
Opening a library automatically requests a filter preview; that request was
explicitly blocked, and the figure crops only the unchanged policy controls.
All other execution POSTs are blocked. No preparation, docking, new ProLIF
analysis, file export or RMSD calculation runs for these figures.

Captures are actual browser/DOM crops, with no recolouring, atom edits or
rewritten scientific labels. Export destination paths and partially clipped
dialog actions are outside the published crops. Historical external-export
records still refer to their original destination; the guide now explicitly
explains why a filename listing does not prove file relocation or availability.

## Documentation corrections

- Eight-stage checklist, project/reopen behaviour and laptop panel/scroll guidance.
- Guided receptor choices and current topology guards, separated from the
  accepted legacy receptor; ARG A:300's observed-coordinate conflict is not
  hidden by claiming that all seventeen repairs now succeed.
- Current single-ligand confirmation/settings labels and separate reference,
  protonated state, independent conformer and PDBQT roles.
- Redocking result/reference/threshold/confirmation steps; compatibility
  checks, saved history and separate sampling/ranking interpretation.
- Existing versus newly created interaction analyses, group multiplicities,
  atom-type filtering and correct figure/PDB saving instructions.
- Methods software table and citations; export-file reachability; current
  virtual-screening policy and progress/resource caveats.
- README/manual links, twenty sequential figure/caption numbers and coordinated
  cover with light print-friendly body pages. Duplicate closing boilerplate was
  removed to avoid a nearly empty last page.

## Verification

- PDF generated with Edge 155.0.4283.62; **30 A4 pages**,
  **2,947,952 bytes**.
- PDF SHA-256: `c760ea12836c094ff893a09562a5d17a5548f6d09bb426e0b220ccf30fe83905`.
- All pages rendered with PDFium and visually inspected, including cover,
  figures/captions, tables, reference software labels and final-page layout.
- All twenty figures checked for the current appearance and personal-path
  exposure. Extracted PDF text has no personal absolute paths or placeholders.
- 29 focused manual/README tests pass, including sequential figures, links,
  recorded figure hashes, current redocking instructions and safe PDF replacement.
- Relative documentation links are rewritten to their public repository URLs.
  All six external PDF links are HTTPS, with zero local-file annotations.
  Tests reject private/escaping link targets. All thirty rendered pages remain
  pixel-identical after this link-only correction.
- Ruff passes for the touched builder/tests; public-path and frozen
  scientific-status checks pass. No full application or installer regression
  claim is made for this documentation-only unit.

## Figure identity index

| File | Pixels | SHA-256 |
| --- | --- | --- |
| `guide01-readiness.jpg` | 1920 × 220 | `6260dbe052e0af93b5520d35ba31c59b4a5c91c3698e5a9fa332b4a65546c19f` |
| `guide02-structure.jpg` | 1920 × 1200 | `567b34cf99610b9cd19d92d9cba8a43cba0f7ddcbd94916717a2867fc7e3d62a` |
| `guide03-receptor.jpg` | 1920 × 1200 | `e4d45b7785e6719eff0c9217b1012d18f6322c1c6f2408ae151be70e74e0ede4` |
| `guide04-rv2.jpg` | 1920 × 1200 | `f2fe110cc12a966eb41353e6755ee2ab51a68364e5884c53fdf8e44014ab8784` |
| `guide05-prepared-ligand.jpg` | 1920 × 1200 | `71cd5eab7c5806d4ab7d729eb8f02e23bf154486a71ce8c96a75a6a63c2b3fa5` |
| `guide06-binding-site.jpg` | 1920 × 1200 | `46a2b9f56ff67b4a43b15371a9300d235435f95578d956049d24031f554b0086` |
| `guide07-vina-settings.jpg` | 522 × 136 | `bb0c1e30f9a6f477f4c63640587e797e850758e585766af54d133525b249e329` |
| `guide08-results-catalog.jpg` | 1352 × 1103 | `9aa9e4133e7c1a9a5de858b5cbe3bf29968fa993372095df3c0bb90dff120490` |
| `guide09-redocking.jpg` | 1297 × 656 | `e2d039f96ff5a7b9822ecddcf908bc87d8064f137426f81366e4002f4006224d` |
| `guide10-vina-completed.jpg` | 1920 × 1200 | `ed2f9b4e6cb21a0c3bf935c33f9616e811411b595aa984808577dcf63fbda0bb` |
| `guide11-interactions.jpg` | 1672 × 1303 | `e2aff2b4d702ee1a1b092d2faf4e5c9dce657fd59b4bf519fe9ec6242532bac2` |
| `guide12-diagram-detail.jpg` | 865 × 525 | `fe1c0bec77001d505e6e71dba86d8f71dcec97cd931da2c164ca0ae169d55f0b` |
| `guide13-contact-filter.jpg` | 1672 × 1303 | `5a3ffa166e653c9ee37350c7d5978cc510ff77065fe53ed482371ee7911ea8d2` |
| `guide14-save-figures-pdb.jpg` | 709 × 329 | `ec293ab47b31541a62ea462063a68eb46ef0765e25ee1bfac90e0740b57798a7` |
| `guide15-save-diagram.jpg` | 867 × 221 | `2e4a376db1de6a39a7c1f2d6795701d0def98466494cf0414cd839b5cf1410d5` |
| `guide16-methods.jpg` | 560 × 702 | `4c21d9cd7d82d8455bcba3523c814628fa3a1ebd9ac10a5535111694a4b03026` |
| `guide17-methods-references.jpg` | 522 × 553 | `602c3a5451331b58a334f78eeb45ad4491b7068f114115bc28802adbeb193c8a` |
| `guide18-exported-files.jpg` | 320 × 127 | `7637b989dc31589ebf28d1151854df4d94c6db2d64646ca0e373d2ad6da72216` |
| `guide19-library-filters.jpg` | 327 × 457 | `5f604ff7d8bbe18a955a670f7aa589af81927bd9b26cb9965ef61c65611da3c3` |
| `guide20-redocking-setup.jpg` | 1297 × 457 | `0b777839d31936b928ef4906f2375e37f2e7851d9a8498b07307a2e0aa2b814d` |

The earlier [9 October tutorial acceptance](USER_GUIDE_7AQF_2026-10-09.md)
remains historical evidence, not the current interface contract.
