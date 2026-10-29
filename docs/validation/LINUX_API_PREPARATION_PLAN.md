# Linux API preparation and Vina smoke — predeclared protocol

## Purpose and limits

Exercise the real Ankora HTTP API in-process via FastAPI TestClient, backed by
a new isolated project and real Linux scientific tools. This is an engineering
smoke, not GUI/WSLg testing, crystallographic redocking, a biological claim,
a historical benchmark rerun, or native-workstation acceptance. No input is
overwritten and no existing user project is accessed. Results and raw outputs
are retained even if any step fails.

## Fixed development inputs and decisions

- PDBFixer's upstream `tests/data/test.pdb`, a 1VII villin headpiece model,
  SHA-256 `e1fd07976c0e1ed7aeaa2a2733e1334ad9051744bf2fc196812bdf922f08a981`.
  Inspection before this plan found one chain A, no water, no components, and
  no reported or template-detected incomplete residues. All original hydrogens
  and the existing OXT are part of the source; no other repair is authorized.
- Synthetic ethanol SMILES fixture, SHA-256
  `e8aad0bdae1b0bb65afcb6a728823dd0d028c9988d3a34299ce9f3d09c95f92d`.
  This molecule is explicitly synthetic and has no known binding pose here.
- Receptor decision: select chain A; remove any waters (the inspected source
  has none); no component or issue actions; no repair, relaxation, overrides,
  or authorized new terminal heavy atoms; use `templates_v1`; PDB2PQR/PROPKA
  at pH 7.4 with AMBER and Meeko receptor PDBQT generation enabled. If the
  source, inspection, tool, or plan is rejected, record the failure and stop;
  do not silently change the plan.
- Ligand decision: accept the inspected state; generate ETKDGv3 with seed
  20261029 and MMFF94s, maximum 500 iterations; use Meeko Gasteiger PDBQT.
- Fixed manual box: center `(0.024, 0.405, 1.075)` Å and size
  `(20, 20, 20)` Å. The center is the rounded center of the input model's
  heavy-atom bounding box, determined before execution; it is not a pocket
  prediction or evidence of binding.
- AutoDock Vina 1.2.7 Linux x86-64 executable SHA-256
  `f31f774f723bba7bbe6e9d1c47577020eea9a8da16424284c043d22593570644`;
  custom parameters: CPU 2, seed 20261029, exhaustiveness 2, at most 3 poses,
  RMSD separation 1 Å, energy range 3 kcal/mol, timeout 1 minute.

## Acceptance and evidence

Record all API requests and responses, tool/version identities, exact input
hashes, raw tool output and persisted artifacts in a create-only evidence
directory. The original imported structure and ligand bytes must remain
unchanged. The API must create a docking-ready receptor, a prepared ligand,
the exact binding site and one terminal successful Vina job with 1–3 valid
persisted poses. Any tool failure, missing stage, timeout or hash discrepancy
is a failed smoke, not a reason to tune the above protocol. No score or pose
geometry is an acceptance threshold. Tool outputs remain in the project data
directory, whose root is separate from any user project.

The planned run will be appended below after execution.
