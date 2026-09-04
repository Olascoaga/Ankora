# M3 Ligand Preparation evidence

Date: 2026-08-20
Authoritative platform: Windows 11 x64

## Foundation acceptance

- [x] Select an exact crystallographic ligand component.
- [x] Preserve observed coordinates and deposited mmCIF bond orders in an immutable SDF.
- [x] Reject missing/incomplete topology, formula mismatch, and unapproved alternate coordinates.
- [x] Record hash, source locator, RDKit version, structured warnings, and provenance.
- [x] Display the extracted reference separately from generated states or conformers.
- [x] Report molecular weight with units and monoisotopic exact mass.
- [x] Require chemical-state acknowledgement before creating a separate MMFF-minimized conformer.
- [x] Preserve method, iteration limit, energies, convergence, RDKit version, hash, and parent linkage.
- [x] Import local SDF/MOL/SMILES ligand inputs.
- [x] Resolve disconnected components and undefined tetrahedral stereocenters through explicit recorded choices.
- [x] Enumerate bounded protonation and tautomer candidates for screening and require one explicit state selection per parent compound.
- [x] Generate and MMFF-optimize independent conformers with a recorded ETKDGv3 seed.
- [x] Select the lowest-energy converged member of each conformer pool and preserve a visibly blocked nonconverged fallback only when none converge.
- [x] Generate ligand PDBQT from a converged conformer through a versioned Meeko adapter.
- [x] Import multi-record SDF/SD-style MOL and multiline SMILES libraries without losing valid neighbors when one record is invalid.
- [x] Display per-molecule name, canonical SMILES, formula, molecular weight, non-sortable MMFF minimization ΔE as geometry QC, and preparation status while retaining absolute initial/final energy evidence.
- [x] Process every eligible member under one explicitly confirmed parameter set while retaining unresolved and failed members as independent rows.
- [x] Preview Lipinski, Veber, Ghose, Muegge, QED, PAINS, Brenk, and duplicate results before 3D generation.
- [x] Require a separate confirmation that writes an immutable selection manifest before a library batch can begin.
- [x] Limit batch ETKDG/MMFF/Meeko processing to the ligand UUIDs stored in that applied manifest.
- [x] Use a bounded multicore worker budget for independent filter and preparation tasks without changing source order or failure isolation.

## Synthetic contract evidence

`backend/tests/fixtures/synthetic_ligand_source.cif` is explicitly synthetic. It contains three observed ligand atoms and deposited single/double bond topology. Tests verify observed coordinates, bond orders, formula inspection, immutable source bytes, content serving, and independent artifact IDs for repeated extraction with identical hashes.

## Recorded RV2 extraction

The accepted 7AQF original `4c7876f1-d366-4cc2-aeda-0a82fb87a29c` supplied observed RV2 A:401 coordinates plus chemical-component atoms and bonds. Ankora created immutable ligand `4648d9eb-5e6b-4a05-9f9d-3bab2a5d5010`.

RDKit 2026.03.5 reported formula `C19H13ClN2O5`, formal charge 0 from sanitized deposited valence, 27 heavy atoms, four rotatable bonds, three aromatic rings, zero stereocenters, and one crystallographic conformer. The calculated formula exactly matches `_chem_comp.formula`. The SDF SHA-256 is `6fa65e2d76adb3ba91d60a5747e4986d359766c965f29fdf3559203f26195fe4`.

The entry mmCIF omits atom-level formal-charge fields, so the record retains `LIG_FORMAL_CHARGE_INFERRED`. This is an inspection warning, not a claim that charge state selection is complete.

## Recorded RV2 minimization

After explicit acknowledgement of the inspected state, RDKit 2026.03.5 added explicit hydrogens and minimized a new conformer with MMFF94s and a 500-iteration limit. Conformer `e43048ab-79db-4650-90cc-0f949a4bd9f9` converged from 95.8334476 to 56.8186730 kcal/mol. It contains 40 atoms including the same 27 heavy atoms, has molecular weight 384.775 g/mol and exact mass 384.0513 Da, and is stored as a 3,427-byte SDF with SHA-256 `94e19c8ce40510ca775b6dbc26605b8f879f612fdcc706492125556293072064`.

The immutable crystallographic SDF remains unchanged and linked as the sole parent. Automated coverage also verifies state-confirmation blocking, create-only derivative storage, explicit hydrogens, energy reduction, content serving, and visible non-convergence handling.

## Local import contract

Synthetic ethanol fixtures in SDF, MOL, and SMILES form are labeled synthetic and encode the same `C2H6O` graph. Tests verify exact preservation of each original byte stream, distinct compound/state storage, matching molecular weight, absence of authoritative 3D coordinates, and canonical SDF serving. Repeated ETKDGv3 generation with seed `73191` produces distinct conformer UUIDs with identical SDF hashes. Separate synthetic inputs verify that undefined stereocenters and multicomponent salts block generation.

Explicitly synthetic mixed-outcome tests fix the pool-selection boundary: a converged conformer is selected even when a nonconverged member reports a lower final MMFF energy. A second pool in which no member converges preserves only the lowest-energy fallback for review, records zero converged members plus the exact fallback policy in the typed result and provenance, shows a pool-level warning, and remains blocked from Meeko. Historical records lacking those pool-level fields retain only their original selected-outcome statement; Ankora does not invent a retrospective pool census.

Synthetic state-resolution coverage uses the explicitly synthetic `CC(O)F.[Na+]` graph. It verifies that no component is selected before the scientist chooses one, that two tetrahedral stereoisomers are enumerated for the organic component, that the chosen component/isomer creates a new state UUID with one fragment and no undefined stereocenter, and that downstream provenance names that exact state as the conformer parent.

## Local virtual-screening library contract

`backend/tests/fixtures/synthetic_ligand_library.sdf` is explicitly synthetic and contains ethanol and acetone records. The same bytes are tested with both `.sdf` and `.mol` names to cover SD-style multi-record inputs. Tests verify immutable library-source preservation, record order, separate compound/state UUIDs, source indices, canonical SMILES (`CCO` and `CC(C)=O`), average molecular weights (46.069 and 58.080 g/mol), and converged independent ETKDGv3/MMFF derivatives for every eligible row. A separate multiline SMILES case places an invalid record between two valid compounds and verifies two imports plus one preserved row-level failure.

The frontend contract displays names, SMILES, formulas, masses, non-sortable MMFF `ΔE = final - initial`, and row statuses. A batch test includes two eligible molecules and one unresolved multicomponent molecule: both eligible members finish while the unresolved member remains `Needs decision`. The UI labels ΔE as within-molecule geometry QC and retains absolute initial/final energies only as technical evidence; neither representation is a Vina/GNINA score, binding-affinity claim, or valid basis for ranking different compounds.

## Library-filtering contract

The explicitly synthetic filtering fixture contains ethanol, eicosane, a duplicate ethanol, a PAINS-matching rhodanine-like molecule, and an unresolved sodium salt. Tests verify all descriptor families and rule results, default Lipinski/Veber eligibility, informative Ghose/Muegge failures, QED ranking without a default cutoff, Veber exclusion, source-order duplicate exclusion, PAINS review versus explicit exclusion, and a paused multicomponent state. A custom-plan test proves Ghose, Muegge, and QED become gates only when requested.

Applying filters without acknowledgement returns `LIGAND_FILTER_CONFIRMATION_REQUIRED`. With acknowledgement, Ankora recomputes the preview and writes a create-only `selection_manifest.json` with a unique filter-run UUID, SHA-256, RDKit version, exact plan, descriptors, rule violations, alert matches/atom indices, duplicate linkage, dispositions, state UUIDs, and selected ligand UUIDs. API tests reload both the typed record and manifest. Frontend coverage proves the batch stays disabled until application and sends conformer requests only for the two UUIDs in the applied selection.

With a synthetic four-logical-processor budget, backend coverage verifies three parallel filter workers while retaining all five evaluations in source order and assigning the later duplicate to the earlier UUID deterministically. Frontend coverage holds both conformer responses open and verifies that two generation requests are already in flight, proving the batch is concurrent rather than merely displaying a worker count. Worker counts are included in filter manifests and conformer/Meeko provenance parameters.

## Screening-microstate contract

Explicitly synthetic acetylacetone and triethylamine fixtures verify deterministic bounded protonation/tautomer enumeration, structured truncation evidence, create-only selected-state artifacts, and filter rejection when an eligible parent lacks a selection under `enumerated_selection`. API coverage verifies the typed option/selection round trip and records that candidate order is not a population ranking. Frontend coverage requires the scientist to choose and acknowledge one unranked candidate before applying the manifest.

The preparation rollup stores parent-compound ID, exact chemical-state ID, and formal charge. Batch preparation consumes the state ID from the immutable filter evaluation rather than session memory. Vina, AutoDock4 CPU, and AutoDock-GPU preserve that lineage in each result row and reject a prepared PDBQT if its state differs from the manifest. The project result catalog exposes the parent/state identity, and Methods describes the bounds, selection, truncation, and absence of ranking claims.

## Recorded independent RV2 conformer

Ankora removed the crystallographic coordinates from the inspected RV2 graph before embedding. RDKit 2026.03.5 ETKDGv3 used seed `20260819`, added explicit hydrogens, and MMFF94s converged within the 500-iteration limit from 124.6983725 to 45.4020794 kcal/mol. The result is conformer `5975429e-5d9a-4d3e-bf79-245d90c7f933`, a 3,427-byte SDF with SHA-256 `43590ffcdbce0f41abe3c9607fb85a0cdea0ce2823ead104f46904515a7618d5`. It remains a generated docking-input candidate, not a validation result or claim that the ligand state is biologically preferred.

## Recorded RV2 Meeko ligand preparation

Meeko 0.7.1 consumed only the converged independent conformer `5975429e-5d9a-4d3e-bf79-245d90c7f933`. Ankora passed `--charge_model gasteiger` explicitly and preserved the exact Windows argument array and raw output. Meeko reported one input molecule processed, zero skipped, one PDBQT written, and zero errors.

Preparation `382e6572-ca42-45cb-a23e-6eb362a4b5f8` produced `RV2_prepared.pdbqt`, 2,965 bytes, SHA-256 `ee61cd3a707cf013f082d67360c9d570370e17458904461b90dad13dd9b2f50f`. The parent conformer hash remains `43590ffcdbce0f41abe3c9607fb85a0cdea0ce2823ead104f46904515a7618d5`; no upstream artifact was modified. This demonstrates preparation mechanics only and is not docking or redocking validation.

## Verification and acceptance status

- The current full-workspace gate on 2026-09-03 passed 432 backend tests; Ruff
  and strict mypy passed across 101 source files.
- All 207 frontend tests across 27 files passed; strict TypeScript and the
  production Vite build passed.
- Rust formatting, strict Clippy, native tests, and the optimized Windows Tauri
  build passed after the screening-microstate integration.
- The real RV2 extraction, independent conformer, and Meeko PDBQT evidence above are preserved under `.ankora-data`.

M3 is technically complete, including the local virtual-screening library
extension and the later explicit screening-microstate remediation. The
scientist accepted the M3 workflow on 2026-08-26; that acceptance applies to
the recorded mechanics and evidence, not to any unrecorded state choice or a
general biological-validity claim.
