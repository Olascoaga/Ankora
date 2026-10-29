# Linux crystallographic redocking API smoke — predeclared protocol

## Purpose and limits

Test the real Ankora API and native Linux scientific tools in a new isolated
project on WSL2. This is one bounded engineering smoke, not a historical
benchmark rerun, GUI test, scientific comparison, release acceptance or
evidence of general docking accuracy. Do not change the plan based on results.
Preserve failure evidence and do not silently retry with altered decisions.

## Fixed source and decisions

- RCSB structure [1HSG](https://files.rcsb.org/download/1HSG.cif), SHA-256
  `d2ba73b5c4be05c45275571bbb4dd042347927f91c6c05038c0df5d1ce23c268`.
  A read-only template inspection observed chains A and B, 127 waters, the
  sole ligand component `ligand|B|MK1|902|`, and no detected residue issues.
  Preserve the original mmCIF; stop if inspection differs.
- Extract observed MK1, chain B, sequence 902, no insertion code, as an
  immutable reference using the Ankora API. Record extraction warnings.
- Select chains A and B; remove waters and MK1 from the receptor; no repairs,
  relaxation, overrides or additional terminal heavy atoms. Use `templates_v1`,
  PDB2PQR/PROPKA at pH 7.4 with AMBER, and Meeko receptor PDBQT. Record failure
  if preparation rejects these decisions; never change them silently.
- Generate an independent conformer from the extracted chemical state using
  ETKDGv3 seed 20261029 and MMFF94s, maximum 500 iterations. Use Meeko
  Gasteiger PDBQT. Preserve the crystallographic reference unchanged.
- Define the box from the original MK1 residue using Ankora's co-crystallized
  ligand mode with 5 Å padding; record the calculated box.
- Use AutoDock Vina 1.2.7 Linux x86-64, executable SHA-256
  `f31f774f723bba7bbe6e9d1c47577020eea9a8da16424284c043d22593570644`,
  CPU 2, seed 20261029, exhaustiveness 8, maximum 9 poses, minimum separation
  1 Å, energy range 3 kcal/mol, timeout 5 minutes.
- Run Ankora redocking against the extracted reference with a 2 Å threshold.
  Report in-place symmetry-aware RMSDs and distinct sampling and ranking
  outcomes; neither outcome is required to pass the engineering smoke.

## Acceptance and evidence

Retain requests and responses, input and artifact hashes, tool identities and
raw subprocess outputs in a create-only directory outside user projects. Verify
source/reference immutability, saved pose hashes, and that the redocking record
references the actual completed job and reference. Stop at the first failed
stage and retain the evidence. This one case cannot establish scientific
accuracy, native-workstation behavior, or general Windows/Linux equivalence.
