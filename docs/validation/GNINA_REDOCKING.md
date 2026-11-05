# GNINA single-job redocking validation

A completed GNINA single job can be the source of a redocking verdict through
the existing M7 routes, on the same measurement every other engine uses:

```text
GET  /api/v1/validation/redocking/references?source_kind=gnina_job&source_id=…
POST /api/v1/validation/redocking
```

This unit measures previously recorded poses and adds no new docking run or
frozen GNINA reference case. The Validation interface accepts completed GNINA
single jobs and presents their individual scores. See the GNINA redocking section of ADR-027 for the
decision and `docs/scientific/REDOCKING_VALIDATION.md` for the scientific
contract.

## What the measurement does and does not change

- The RMSD is the existing symmetry-aware heavy-atom RMSD computed **in place**.
  Nothing is superimposed, docked, minimized or re-oriented.
- The reference is an immutable crystallographic extraction from the receptor's
  own original structure, or a byte-identical reimport identified by source
  SHA-256 rather than by PDB or ligand name. Local imports and prepared or
  minimized conformers are not references.
- Reference and pose bytes must match their recorded SHA-256 **and** size. The
  pose is checked against the reference molecular graph; the scientist must
  confirm that the chosen reference and docking ligand represent the intended
  same molecule and chemical state. The graph check alone does not establish
  stereochemical identity.
- GNINA's poses are measured in the engine's own mode order, which is its
  descending CNN pose score. The minimized affinity never reorders them, so
  `ranking_success` stays a statement about the ranking GNINA produced.
- A verdict may carry the dimensionless CNN pose score and the predicted CNN
  affinity in pK as separate optional fields. The kcal/mol field remains the
  minimized empirical affinity for every engine. No field pools scores across
  engines.
- Repeatability is recorded as **not assessed** for a GNINA source, not as
  `false`. Verdicts written earlier keep the boolean they were recorded with.
- The verdict's provenance retains the identities the job recorded for its own
  executable, docking receptor, prepared ligand and conformer, with its CNN
  scoring mode, CNN model, compute selection and pose ordering.

## Verification

`backend/tests/test_gnina_redocking.py` covers, with no scientific executable
launched:

- a completed GNINA job measured in CNN order while the energy order disagrees —
  the highest CNN score sits deliberately beside the weakest minimized affinity,
  so a validator that re-sorted by energy would report the opposite verdict;
- the kcal/mol, CNN score and CNN affinity axes staying separate per pose;
- repeatability recorded as not assessed, and an earlier verdict's boolean still
  loading unchanged;
- the retained executable, receptor, ligand and conformer identities and the CNN
  configuration in the verdict's provenance;
- running, failed and canceled jobs refused as sources, by both the reference
  listing and the measurement;
- a changed pose, a changed reference, and a truncated pose padded back to the
  recorded size, each refused with no verdict written;
- a reference from a different original structure refused, and absent from the
  reference listing, by source SHA-256;
- a pose that is not the reference molecule refused rather than measured;
- another project's GNINA job not being a validation input;
- the real API: the `gnina_job` reference listing and `POST`, a rejected
  campaign-shaped `source_kind`, the stored verdict reopened, and project Trash
  moving the GNINA result together with its dependent verdict.

The molecules and poses are retained real artifacts — the crystallographic RV2
pose from 7AQF as Ankora preserved it, and two poses AutoDock-GPU actually
produced against it. The job identities and each mode's CNN score, CNN affinity
and minimized affinity are **explicitly synthetic routing metadata**, chosen so
that CNN order and energy order disagree. They are not GNINA measurements and
imply no GNINA docking result.

### Recorded adapter format check

The retained real GNINA 1.3.3 CPU output `gnina_real_1hsg_mk1.pdbqt` was read
through the redocking adapter against the conformer GNINA was given,
`gnina_input_1hsg_mk1.sdf`, on 2026-11-04 with RDKit 2025.09.6. Both recorded
modes mapped onto the reference graph at 45 heavy atoms each, and the in-place
RMSD to that input conformer measured:

| Recorded mode | In-place RMSD to the input conformer |
|---|---:|
| 1 | 26.199 Å |
| 2 | 27.245 Å |

These numbers establish that GNINA's own PDBQT output — with its `REMARK`,
`ROOT` and `BRANCH` records and AutoDock atom types — is measurable by this
adapter. The input conformer is the recorded docking input, not a
crystallographic extraction, so they are a measurement of the retained fixtures
and **not** a redocking verdict about anything.

## Limits

- A one-case WSL CUDA integration check against an original crystallographic
  reference is recorded in `LINUX_GNINA_REDOCKING.md`; it does not establish
  general predictive performance.
- No GNINA reference case is frozen and GNINA campaign export is not implemented.
- Repeat behavior remains unassessed, consistent with the Results catalog.
- Native Linux workstation acceptance remains pending, as for the rest of the
  GNINA port. Windows behavior is unchanged: no GNINA records exist there.
