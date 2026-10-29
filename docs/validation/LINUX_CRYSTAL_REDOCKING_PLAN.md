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

## Observed run — 2026-10-29 UTC

The isolated WSL2 run stopped at receptor preparation as required by the
predeclared protocol; **no docking or redocking was performed**. API import,
inspection and extraction succeeded, and the extracted reference SHA-256 was
`0dfcb7d3d6024bbe5572c990ff57fdd38e46cfe20b928acb8601bae3ad550982`.
The extraction reported `LIG_FORMAL_CHARGE_INFERRED` because the source did not
provide atomic formal charges; the calculated and deposited formulas matched.

PDB2PQR attempted to add `OXT` to PHE A:99 and PHE B:99. Neither was authorized
in this plan, so the API correctly returned HTTP 422 with
`PDB2PQR_UNAPPROVED_HEAVY_ATOM_CHANGE` and rejected the derivative. The
template-based inspection had reported no issues. This exposes a limitation of
that inspection for this input: it did not flag the terminal additions later
proposed by PDB2PQR. This observation is not a claim about all structures.

Evidence JSON SHA-256:
`000318151effd33e41b0b421706b2d92313e4c211087cdd25778e2544fa731e9`.
The isolated project retains the full API evidence, failure record, PDB2PQR
stdout and stderr, and rejected PDB/PQR derivatives. No existing project was
used. Source inspection and extraction succeeded; the engineering smoke as a
whole did not pass. This result does not establish redocking accuracy.

The runner's fixed requests and output-isolation guards were tested with
synthetic inputs alongside the existing redocking tests: 36 tests passed on
Linux. A new protocol with explicit decisions would be needed for any later
calculation; the present failed run and this protocol must remain unchanged.
