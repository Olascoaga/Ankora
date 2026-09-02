# Ligand preparation policy

M3 begins by preserving a ligand reference before generating any state or conformer.

## Crystallographic extraction

- The scientist selects an exact component locator: component name, author chain, sequence number, and insertion code.
- Coordinates come only from the observed component in the immutable source structure.
- Bond orders and elements come from the `_chem_comp_atom` and `_chem_comp_bond` categories deposited in the same mmCIF.
- Extraction produces a new create-only SDF artifact; it never edits the structure or receptor.
- Missing topology, incomplete topology coverage, formula mismatch, or alternate coordinates stop extraction with a structured error.
- When atom-level formal charges are absent, Ankora records `LIG_FORMAL_CHARGE_INFERRED`; it does not present inferred valence as deposited charge evidence.

## Molecular descriptors

- Ankora reports average molecular weight in `g/mol` and monoisotopic exact mass in `Da`; the units remain visible in the interface.
- Descriptor calculation uses the inspected RDKit molecule and does not imply that protonation, tautomer, salt, or stereochemical alternatives have been enumerated.

## Local compound import and inspected state

- SDF and SD-style MOL files may contain multiple molecule records; SMI/SMILES files may contain multiple non-empty lines. A plain MOL record remains a valid one-compound library.
- A local library import is bounded to 100 MB and 10,000 records in the current desktop slice. This is a local guided-screening boundary, not a claim of million-compound or remote/HPC throughput.
- The exact library byte stream is immutable and has its own filename, format, size, hash, UUID, and provenance. Every successfully parsed record also receives an independent compound/state identity linked to its zero-based library index.
- Parse or sanitization failure is recorded per source record. One invalid molecule does not erase valid records or abort their later processing.
- The local file bytes are immutable and retain their own filename, format, size, and hash.
- RDKit parsing/sanitization produces a separate canonical inspected-state SDF with its own UUID and hash. This state does not replace the original file.
- The library table reports record index, source name, canonical isomeric SMILES, formula, average molecular weight, MMFF final energy when available, and per-molecule status. MMFF energy is preparation evidence in `kcal/mol`; it is not a docking score or binding-energy prediction.
- Files without authoritative 3D coordinates are labeled as such; a 2D connectivity preview is not described as a 3D conformer.
- Undefined tetrahedral stereocenters and disconnected components are structured blockers. Ankora enumerates the inspected choices, requires the scientist to retain an exact component and select an exact stereoisomer when applicable, and writes the result as a new immutable state.
- Component order, formulas, formal charges, heavy-atom counts, canonical SMILES, selected indices, and the parent state are recorded. Ankora never silently retains the largest fragment or chooses a stereoisomer.

## Independent 3D generation

Library inputs pass through an explicit 2D cleaning stage before any 3D generation:

- The default `general_oral` preset uses Lipinski and Veber as eligibility gates. Lipinski permits at most one violation by default; Veber requires no more than 10 rotatable bonds and TPSA no greater than 140 Å².
- QED is always calculated as a ranking descriptor and has no default cutoff. Ghose and Muegge are always evaluated but remain informative unless the scientist enables them as gates. Their exact thresholds and every individual violation are stored, not collapsed into an unexplained pass/fail value.
- PAINS and Brenk substructure catalogs are evaluated before screening. Their default policy is `review`, so an alert is visible and retained without automatically excluding the molecule. The scientist may explicitly change either policy to `exclude` or `ignore` (record only).
- Exact canonical-isomeric-SMILES duplicates are detected in source order. The default excludes later repeats and records the first matching ligand UUID; `review` and `keep` remain explicit alternatives.
- Disconnected components and undefined stereochemistry remain `Needs decision` and receive no provisional descriptor-based eligibility. Resolving one creates a new state and invalidates any previously applied filter selection.
- Filter changes first produce a read-only preview. Preparation remains disabled until the scientist confirms that exact preview and Ankora writes a create-only JSON selection manifest containing the RDKit version, plan, descriptors, rule violations, alerts with matched atom indices, duplicate links, exclusions, state UUIDs, and selected ligand UUIDs.
- The original library and every inspected/resolved state remain immutable. ETKDG/MMFF/Meeko batch processing consumes only the ligand UUIDs in the applied manifest; it never processes a provisional table selection.
- Descriptor/rule evaluation and selected-ligand preparation use bounded local parallel workers. The default uses the available logical processors minus one, capped by molecule count. Source-order duplicate decisions are applied after parallel descriptor work, so concurrency cannot change which earlier UUID is authoritative.

- Independent generation removes every supplied coordinate conformer before embedding.
- RDKit ETKDGv3 runs with a scientist-visible integer random seed and enforced known stereochemistry.
- The embedded molecule receives explicit hydrogens and is minimized with the explicitly selected MMFF94/MMFF94s variant and iteration limit.
- Repeating the same accepted state, seed, embedding method, force field, and iterations produces independently identified artifacts with identical molecular-file hashes in the frozen synthetic contract.

## MMFF minimization

- The scientist must acknowledge the currently displayed formal charge, bond orders, and stereochemistry before minimization.
- Undefined stereocenters block minimization until an explicit state decision resolves them.
- MMFF94 and MMFF94s are separate visible choices. Ankora never silently falls back to UFF or another force field when MMFF parameters are unavailable.
- Explicit hydrogens are added to the derivative and recorded in provenance.
- The starting ligand remains immutable. Every minimization creates a new conformer artifact with its own UUID, SDF, SHA-256, method, RDKit version, iteration limit, initial/final energy, and convergence state.
- For an independently embedded pool, convergence is evaluated before energy. Ankora selects the lowest-final-energy conformer only among converged outcomes; a lower-energy nonconverged geometry cannot displace a converged one.
- If no member of the pool converges, the lowest-final-energy nonconverged outcome may be preserved for inspection only. Its pool size, zero converged count, fallback policy, selected conformer, and warning are recorded, and it is not eligible for Meeko.
- Historical conformer records without pool-level selection evidence remain readable, but the interface does not infer a pool-wide convergence claim from their selected outcome.

## Meeko ligand preparation

- Ligand PDBQT generation accepts only a conformer whose recorded MMFF result is converged.
- Meeko 0.7.1 runs behind the backend adapter with an argument array. The current visible charge model is Gasteiger; it is passed explicitly as `--charge_model gasteiger` rather than inherited as an invisible default.
- The conformer SDF remains immutable. PDBQT content, SHA-256, exact command, Meeko version, stdout, stderr, parameters, and provenance are stored under a new preparation UUID.
- A failed Meeko execution preserves its raw output and structured failure evidence and never yields a docking-ready artifact.

## Boundary of the current slice

Physiological-pH protonation-state enumeration is implemented through Dimorphite-DL as an explicit, scientist-confirmed chemical-state decision. The pH range, precision, candidate set, chosen candidate, parent state, formal charge, tool version, and provenance are recorded; the scientist may also explicitly retain the as-drawn state. Tautomer enumeration is not implemented. Neither protonation enumeration nor the present disconnected-component/stereochemistry resolver claims to identify a biologically preferred state. A generated PDBQT is a docking input, not a validation result or binding claim.

Batch preparation is an explicitly confirmed, bounded-parallel repetition of the visible ETKDGv3 seed, MMFF variant, and iteration limit for each UUID in an applied filter manifest. The worker count is visible and recorded in each generated conformer/Meeko request. Molecules with unresolved components or stereochemistry pause at `Needs decision`; excluded molecules remain visible and unprocessed; selected molecules continue, and failures remain isolated to their rows. Ankora does not silently select a salt fragment, stereoisomer, protonation state, tautomer, or alert policy in order to complete a batch.
