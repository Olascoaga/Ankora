# M2 Receptor Preparation acceptance evidence

Date: 2026-08-19
Authoritative platform: Windows 11 x64

## Acceptance criteria

- [x] Produce a read-only receptor inspection report before transformation.
- [x] Require explicit chain, water, component, and per-residue decisions.
- [x] Block unresolved manual-review items and incomplete decision sets.
- [x] Create unique immutable derivatives while leaving the source byte-identical.
- [x] Integrate selective PDBFixer repair without automatic loop building.
- [x] Integrate PDB2PQR/PROPKA with explicit pH and force field.
- [x] Expose residue-level PROPKA pKa proposals before final protonation.
- [x] Keep predicted, tool-default, and scientist-selected states distinct.
- [x] Flag binding-site, metal-proximal, near-pH, and coupled-group proposals.
- [x] Apply only tool-validated explicit residue overrides and record them.
- [x] Integrate Meeko receptor preparation while preserving PQR charges.
- [x] Record output hashes, tool versions, exact commands, provenance, and raw logs.
- [x] Preserve structured diagnostics and raw output when an external tool fails.
- [x] Prevent PDB2PQR from silently repairing heavy atoms outside the explicit plan.
- [x] Display original, prepared, and overlay modes behind the Mol* adapter.
- [x] Complete the prepared-only visual review of the scientist-approved 7AQF derivative.

The scientist reviewed the corrected prepared-only view and explicitly accepted receptor `5916893f-16b9-4d54-bafa-c8c03bf7c7b7` on 2026-08-19. Ankora did not choose chain, component, solvent, or residue-repair policy on the scientist's behalf.

## Synthetic contract evidence

`backend/tests/fixtures/synthetic_m1.pdb` is an explicitly synthetic contract fixture. It exercises a polymer, water, a ligand, a metal, an alternate location, a missing atom, and a reported missing residue. Automated tests verify that every issue is exposed, decisions are complete, water and Zn can be removed while the ligand is retained, one alternate label is selected, and the original bytes remain unchanged. A simulated PDB2PQR failure verifies preservation of raw stdout/stderr and `failure.json`; these strings are test evidence, not experimental output.

An isolated real PDBFixer 1.12.0/OpenMM 8.5.2 smoke repaired the explicitly selected missing `CB` of synthetic ALA A:1. The worker reported one requested and one matched residue and wrote an 809-byte temporary PDB. The temporary output was inspected and removed; it is tool-integration evidence, not a scientific result.

## Installed tool-chain smoke

The dedicated `ankora-dev` environment contains PDBFixer 1.12.0, OpenMM 8.5.2, PDB2PQR 3.7.1, PROPKA 3.5.1, Meeko 0.7.1, and RDKit 2026.3.5. PDB2PQR/PROPKA and Meeko were exercised on the upstream PDBFixer test structure `1BHL.pdb`, not on the Ankora reference case. PDB2PQR produced a 158,551-byte PQR and a 184,590-byte protonated PDB. Meeko, invoked with `--charge_model read`, confirmed that it read structures and partial charges from PQR and produced a 115,182-byte PDBQT. Temporary outputs were removed after inspection.

This smoke establishes executable compatibility and exposed a real adapter defect: without `--charge_model read`, Meeko reported its default Gasteiger model. The adapter and command-contract test now require `read` explicitly.

## Residue-level protonation review

Ankora now requires a PROPKA proposal review before creating a protonated
receptor. The preview executes the exact current structural plan in an isolated
temporary store and becomes stale whenever a chain, component, issue decision,
repair-relaxation setting, reference, pH, force field, or terminal-addition
authorization changes. The final derivative reruns the plan and retains its own
structured prediction/decision record and raw tool evidence; preview output is
never promoted into an immutable receptor record.

Each row separately records the PROPKA pKa-derived state, the PDB2PQR/AMBER
default, the selected state, and whether the scientist overrode the default.
The UI flags residues near the selected reference, within 4.0 A of a retained
metal, within one pKa unit of the target pH, or in a coupled titration group.
These flags request review and never change a state automatically. States that
PDB2PQR 3.7.1 cannot apply through AMBER remain visible as limitations and are
not selectable. See ADR-017.

Synthetic regressions verify prediction/decision separation, active-site and
metal warnings, terminal AMBER restrictions, and every supported pKa-branch
direction. A real isolated Windows run on the saved 365-residue 7AQF receptor
used PDB2PQR 3.7.1 and PROPKA 3.5.1, returned 95 structured prediction rows,
and preserved its PQR, protonated PDB, and raw log for inspection. A second
temporary run explicitly selected HIP for HIS A:3 and recorded both the
original predicted pKa and the forced branch used by PDB2PQR. Both temporary
workspaces were inspected and removed; they are adapter-integration evidence,
not accepted receptor derivatives or experimental protonation assignments.

## Recorded 7AQF inspection

The M1 reference original remains tied to SHA-256 `79fd3b96adca6bdbe17ded6e9c693534007ae2cb0538739044788754b7c6faac`. With RV2 A:401 selected as reference, M2 reported chains A/B, one non-water component, 481 waters, and 56 residue-level issues. Twenty-six issues belong to chain A. ARG A:271 reports missing `CD`, `CG`, `CZ`, `NE`, `NH1`, and `NH2`; its nearest observed atom is 47.2613 Å from RV2, so it is classified remote under the recorded 8.0 Å cutoff.

These are read-only parser observations for the exact original hash.

## First scientist-directed 7AQF attempt

The scientist selected chain A, removed 481 waters and RV2 A:401 from the receptor derivative, explicitly left all 26 reported chain-A issues unchanged, enabled PDB2PQR/PROPKA at pH 7.4, and requested Meeko PDBQT. The run was preserved under receptor failure ID `a5005300-37bb-4720-b3f8-03c81a4230bc`.

PDB2PQR 3.7.1 exited successfully but its raw log revealed that it automatically added 61 missing heavy atoms despite the explicit `Leave unchanged` decisions. It also reported that ARG A:300 could not be debumped. Meeko then rejected the PQR because residue A:300 matched no template and had five missing/five excess hydrogens plus excess inter-residue bonds. The structured failure code is `MEEKO_CONNECTIVITY_FAILURE`; stdout, stderr, command, PDB2PQR log, intermediate PDB/PQR, and `failure.json` remain preserved.

This attempt is a failed validation case, not an accepted receptor. It exposed a semantic defect more important than the terminal Meeko error: the protonation stage had performed unapproved heavy-atom reconstruction. Ankora now blocks protonation while observed missing-atom, alternate-location, or nonstandard-residue issues remain `Leave unchanged`, lists the blockers in the UI/API, and verifies after PDB2PQR that the heavy-atom identity set did not change. `PDB2PQR_UNAPPROVED_HEAVY_ATOM_CHANGE` rejects any remaining unexpected change even if the executable exits successfully.

The blocker panel now offers explicit bulk form actions for the repetitive 7AQF case: repair all currently repairable missing-atom blockers with PDBFixer, remove all removable blockers, or disable protonation. A bulk choice writes the same per-residue decisions as individual menus and does not run a transformation; the scientist must still review the populated plan and press Apply separately. Alternate-location repair is deliberately excluded because it requires a specific label.

The second scientist-directed attempt, failure ID `e301ddeb-7b9e-4267-9860-0a7cb042f49e`, explicitly repaired the 17 missing-atom blockers. PDBFixer/PDB2PQR completed, but Meeko/RDKit rejected invalid residue-local connectivity in ASP A:231, LYS A:288, and ARG A:300. Their recorded distances from RV2 A:401 are 32.1507 Å, 25.1791 Å, and 23.1994 Å. The preserved PQR reproduces all three failures through Meeko's residue parser. Ankora now returns those residue locators as structured error details, lists them with their reference distances, highlights their decision menus, and offers a separate button that marks only those decisions `Remove`; a new Apply confirmation remains required.

The next attempt, failure ID `5cdba498-d5bf-4b4f-8403-bec929d2c58b`, passed residue-local valence checks but exposed two inferred bonds between GLY A:230 and repaired ASP A:231. The normal peptide C–N distance is 1.335 Å; reconstructed ASP OD1 lies 1.363 Å from GLY O and Meeko therefore infers an additional O–O connection. Ankora's diagnosis now also calls Meeko's structured inter-residue bond finder and reports both members of any pair with multiple inferred bonds. Only residues that map to an actionable inspection issue are offered in the removal control, so this case points the scientist to repaired ASP A:231 rather than silently modifying GLY A:230.

Failure ID `4cc2fa52-6fcb-44d2-a3ac-4d3b1f61285a` then exposed a single nonlocal inferred bond: THR A:296 backbone O lies 0.933 Å from repaired ARG A:300 HH21. This is neither a peptide C–N connection nor a CYS SG–SG disulfide. The structured detector now records atom names (`O-HH21`) and reports the pair, while the UI recovery maps only the existing ARG A:300 missing-atom issue into the removal plan.

## Successful scientist-directed 7AQF derivative

The scientist's revised plan completed as immutable receptor `5916893f-16b9-4d54-bafa-c8c03bf7c7b7` with status `docking_ready`. It selected chain A, removed all 481 waters and RV2 A:401, repaired 12 explicitly selected missing-atom residues, removed ASP A:231, GLN A:257, ARG A:300, GLU A:313, and ILE A:342, retained the recorded missing-residue observations unchanged, protonated at pH 7.4 with AMBER, and generated PDBQT through Meeko 0.7.1.

Direct Gemmi inspection confirms that this is not visually or structurally identical to the immutable original. The original contains chains A/B, 1,218 residues, 6,266 atoms, 481 waters, RV2, and the five later-removed residues. The selected derivative contains only chain A, 365 residues, 2,858 atoms, no waters, no RV2, and none of those five residues. The repaired derivative has 2,903 atoms, while the displayed protonated PDB has 5,802 atoms including 2,899 hydrogens. The final `prepared_receptor.pdbqt` is 284,958 bytes with SHA-256 `e5b0adc629daa7e77814822c500aff640e67b97dcc0697d30769a34b47701024`.

All five stage artifacts, exact commands, versions, parameters, provenance, and raw logs remain under the receptor record. The final visual review initially appeared unchanged because Ankora automatically opened the original and prepared structures together: the original's waters and removed components remained visible in the comparison. The review flow now opens the prepared receptor alone after success, summarizes the applied removals/repairs, and labels Overlay as an opt-in comparison that also shows original-only content.

The latest successful receptor can also be reopened after an application restart. The API discovers the newest persisted `record.json`; the desktop then loads its exact `source_artifact_id`, restores all recorded decisions and outputs, and enters prepared-only review. Automated coverage proves that this path performs only GET requests and never repeats PDBFixer, PDB2PQR/PROPKA, Meeko, or derivative creation. Empty projects return the structured `RECEPTOR_HISTORY_EMPTY` response and show no misleading resume control.

## Visual evidence

The M2 interface was exercised against the live Windows-native app and local API. After loading 7AQF, the Receptor step exposed RV2 reference selection, chain A/B choices, explicit solvent/component controls, all residue decisions, pH/PDBQT controls, tool readiness, and original/prepared/overlay viewer modes. Chain A with RV2 as reference showed the 26 relevant issues and the recorded ARG A:271 distance. The successful request above completed and the app received its docking-ready record. Prepared is now the automatic review mode; Original and Overlay remain explicit alternatives.
