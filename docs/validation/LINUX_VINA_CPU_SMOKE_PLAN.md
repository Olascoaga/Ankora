# Linux CPU AutoDock Vina engineering smoke — plan (2026-10-28)

**Status: predeclared; not yet executed.** The coordinator runs it after this
plan is committed and appends the observed outcome. This record must not be
edited to fit a result.

## Purpose and limits

This bounded ADR-026 gate 2 check runs Ankora's real Vina adapter on Linux:
`probe_vina`, the `BindingBox`/`VinaDockingParameters` models, `execute_vina`
(argument array, no shell, owned POSIX process session) and
`parse_vina_poses`. It records exact, traceable evidence.

It is a **command, pose and traceability smoke only**:

- not a redocking, an efficacy or affinity estimate, a scientific validation,
  a historical benchmark rerun, a GPU check, or validation of the full
  service/application path;
- the inputs are development fixtures with no known binding mode;
- the deliberately small protocol below must not be tuned once scores are seen;
- Vina scores remain computational estimates in kcal/mol, not experimental
  affinities.

## Fixed inputs (new development smoke fixtures)

The fixtures come from the coordinator's create-only native-tool smoke
evidence; they are read only and never modified. Machine-specific locations
are deliberately not recorded here.

| Role | Origin | SHA-256 |
| --- | --- | --- |
| Receptor PDBQT | Upstream PDBFixer test fixture 1BHL → PDBFixer explicit repair → PDB2PQR/PROPKA → Meeko 0.7.1 receptor preparation (`prepared_receptor.pdbqt`) | `21067a2249a5f3f4cc7cb83280b2d2ba1c70bf0b2b0c7a29a94e63c6e72d13b5` |
| Ligand PDBQT | Explicitly synthetic ethanol (`synthetic_ethanol.smi`) → existing ETKDGv3, seed 20260908, MMFF94s → Meeko 0.7.1 (`ligand.pdbqt`) | `23544379c6b5c396e043f2bce0cc8677987ff930159da505e3afa65e5bb04182` |
| Pocket source | P2Rank 2.5.1 predictions for the same upstream receptor (`source_receptor.pdb_predictions.csv`) | `42574b705d8a1d6e0fd3a122b05b879e3cc5855bc30b6aa32c777d9eec458e7b` |

Supporting identities from the same create-only evidence (not inputs to Vina):

- upstream receptor fixture copy: `7ff77930c706778d5009d49fe314d36829fb24b42392c9ca76a49b91301f228f`;
- generated PQR: `2070d6fea9836110903a5804935d0ebbf1cf15df8cd2c04b28bffe8b186f7d18`;
- synthetic ligand source: `e8aad0bdae1b0bb65afcb6a728823dd0d028c9988d3a34299ce9f3d09c95f92d`;
- smoke manifest: `57744f25ad68edfd87e0acbf0b1940e7d30275ca1f9e344587d74a81e59d0602`.

The receptor, ligand and pocket digests above match the hashes recorded in that
manifest.

## Fixed protocol

- **Engine:** official Linux AutoDock Vina 1.2.7 x86-64 ELF, SHA-256
  `f31f774f723bba7bbe6e9d1c47577020eea9a8da16424284c043d22593570644`.
  - It must be discovered through Ankora's `probe_vina`, whose version check
    must report 1.2.7.
  - The executable bytes must match that digest.
  - The host must be Linux x86_64.
- **Box:**
  - Centre: the rank-1 P2Rank pocket centre, copied exactly from the pinned
    CSV: `(-23.7785, 40.9869, 25.9487)` Å. The script re-reads it from the
    verified copy.
  - Sides: 20.0 × 20.0 × 20.0 Å.
- **Parameters** (`sampling_protocol=custom`):

  | Setting | Value |
  | --- | --- |
  | seed | 20261028 |
  | cpu_threads | 2 |
  | exhaustiveness | 2 |
  | num_modes | 3 |
  | min_rmsd | 1.0 Å |
  | energy_range | 3.0 kcal/mol |
  | timeout | 1 minute |

  Vina's verbosity is the adapter's fixed `1`.

## Procedure (`scripts/validate_linux_vina_smoke.py`)

The command is:

```text
python scripts/validate_linux_vina_smoke.py \
  --receptor <prepared_receptor.pdbqt> --ligand <ligand.pdbqt> \
  --pocket-predictions <source_receptor.pdb_predictions.csv> --output <new directory>
```

It proceeds as follows:

1. **Refuse an existing output.** Exit 2, and write nothing. Otherwise create
   the directory with `exist_ok=False`. From then on, every outcome is written
   create-only to `evidence.json`.
2. **Verify the host** is Linux x86_64.
3. **Verify and copy inputs.** Each input's SHA-256 must match this plan. The
   exact bytes are copied create-only to `inputs/` and re-verified, and the
   rank-1 pocket centre is checked against the declared box centre.
4. **Identify Vina.** Probe it, then require version 1.2.7 and the pinned
   executable SHA-256.
5. **Run Vina once** with `execute_vina` on the verified copies, with
   `--out vina_out.pdbqt` in the new directory.
6. **Record the run:**
   - the exact command array, exit code, cancel/timeout flags, and stdout and
     stderr (raw text files plus their hashes);
   - the raw Vina PDBQT, never rewritten, with its hash;
   - for each pose parsed by `parse_vina_poses`: mode, Vina score as reported,
     RMSD bounds, and block SHA-256;
   - the box, parameters, host, plan identities and the score-interpretation
     guard.
7. **Report the status.** It is `completed` only when Vina exits 0, is neither
   canceled nor timed out, and its output parses. Anything else is recorded as
   `failed`, with its stage and structured details (exit 1). No score is
   produced by the script itself.

## Engineering acceptance for this smoke

The smoke is accepted if:

- the identities match;
- exactly one Vina run completes within the timeout;
- the raw output parses into 1–3 sequential poses;
- all hashes and streams are recorded.

Pose geometry and score values are recorded but are **not** acceptance
criteria.

## Pre-run checks (synthetic tests only; Vina not run)

`backend/tests/test_linux_vina_smoke.py` uses SYNTHETIC fixtures and fake adapter
callables only; no real Vina or network is used. It covers:

- refusal of an existing output and of a drifted or missing input;
- wrong host and wrong executable identity;
- the exact box and parameter construction and the resulting Vina arguments;
- preservation of raw output, poses and streams on success;
- structured evidence for nonzero exits, timeouts, unparseable output and a
  changed pocket centre;
- agreement between the script's pinned hashes and this plan.

Observed results (Ubuntu 24.04 WSL2, locked `ankora-dev` Python 3.12.13):

- `pytest backend/tests/test_linux_vina_smoke.py backend/tests/test_vina_adapter.py`:
  21 passed (18 new tests and the 3 existing adapter tests).
- **Ruff:** passed with the project configuration (`backend/pyproject.toml`).
  The script lives outside `backend/`, so it is checked with that configuration
  passed explicitly.
- **Strict mypy:** passed on the script and test.
- **Public-path and validation-status checks:** passed.
- **Preflight on the real immutable inputs** (Vina not probed or run):
  - The script was run with a probe that stops immediately.
  - The receptor, ligand and pocket SHA-256 digests and the rank-1 centre
    matched this plan.
  - Evidence went to an ignored local directory.

## Observed run

Pending coordinator execution. Append the command outcome, the evidence SHA-256
and the observed facts below this line without editing the plan above.
