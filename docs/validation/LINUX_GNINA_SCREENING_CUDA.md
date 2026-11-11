# GNINA CUDA virtual-screening and mid-campaign cancellation checks — predeclared

## Protocol

These two bounded WSL engineering checks exercise GNINA 1.3.3 CUDA screening and
active GPU cancellation through Ankora's real localhost HTTP API. Neither run is
a scientific benchmark, prospective virtual-screening validation, WSLg graphical
acceptance, or native bare-metal Linux workstation acceptance.

### Common preconditions

Verify the declared SHA-256 digests of the official GNINA 1.3.3 Linux binary,
the prepared 1HSG exploratory receptor, and the tracked 100-compound RDKit NCI
sample (`resources/examples/real_screening_library_100/nci_real_100.sdf`).
Independently enumerate NVIDIA GPUs through `nvidia-smi`; require exactly one
unambiguous GPU at logical index `0` and zero active GPU compute processes
before each sub-run begins. Copy the prepared 1HSG project into fresh,
create-only directories and never alter the source project.

### Sub-run 1 (`screening-api-cuda-01`): 11-molecule NCI CUDA screening

Import `nci_real_100.sdf` (100 records) and apply the declared `demostracion`
medicinal-chemistry filter plan (`require_lipinski=True`,
`max_lipinski_violations=1`, `require_veber=True`, `require_ghose=True`,
`require_muegge=True`, `minimum_qed=0.3`, `pains_policy="exclude"`,
`brenk_policy="exclude"`, `duplicate_policy="exclude"`), requiring the exact 11
eligible NCI compounds. Generate independent `ETKDGv3` + `MMFF94s` conformers
(`seed=20261029`) and prepare `Meeko` PDBQTs for all 11 compounds.

Through `POST /api/v1/docking/gnina/screenings`, launch a GNINA CUDA screening
on device `0` with two CPU threads per job, `seed=20261029`,
`exhaustiveness=1`, `num_modes=2`, and `timeout_minutes=3`. Poll to completion
and require:

1. Campaign status `completed` with `(selected, succeeded, failed, canceled) == (11, 11, 0, 0)`.
2. Every completed entry linked to a distinct child `gnina_job` carrying the
   campaign UUID, matching input hashes, and the pinned GNINA binary SHA-256.
3. Every child job reporting `execution.gpu_process_observed == True` with both
   `requested_gpu_uuid` and `observed_gpu_uuid` equal to the enumerated GPU UUID
   (confirming process-level GPU observation, not per-layer CNN execution).
4. Non-overlapping serial execution intervals across all 11 jobs.
5. Descending `CNNscore` pose ordering on every job and exact SHA-256 matches
   across every published pose PDBQT download via HTTP (`1 <= len(poses) <= 2`
   per completed job).
6. Complete release of active work leases and CPU/GPU resource allocations, plus
   unchanged source project hashes.

### Sub-run 2 (`screening-api-cuda-cancel-01`): active GPU mid-campaign cancellation

In a second create-only directory, import and prepare the two-molecule synthetic
library (`CCO` ethanol, `CCN` ethylamine) with `seed=20261029` and `Meeko`.
Launch a GNINA CUDA screening with `exhaustiveness=128`, `num_modes=2`, and two
CPU threads so the first molecule remains active long enough for live GPU
inspection. Poll `nvidia-smi` and process metadata until the first child job's
GNINA process is actively observed on the enumerated GPU inside its unique job
directory, then issue `POST /api/v1/docking/gnina/screenings/{campaign_id}/cancel`.
Require:

1. Terminal campaign status `canceled` with `(selected, succeeded, failed, canceled) == (2, 0, 0, 2)`.
2. First child job ended `canceled` with zero published poses and preserved raw
   execution files; observed GPU PID exited cleanly.
3. Second entry ended `canceled` without ever creating or launching a child
   GNINA job (`gnina_job_id is None`).
4. Zero remaining GPU compute processes, released CPU/GPU resource allocations,
   and unchanged source project hashes.

Write create-only `evidence.json` files for both sub-runs even on failure, and
never overwrite or retroactively edit criteria after observing outcomes.

## Observed run: screening-api-cuda-01

The isolated 11-compound NCI WSL CUDA screening completed through Ankora's HTTP
API on `NVIDIA GeForce RTX 5050 Laptop GPU`. All 100 records of
`nci_real_100.sdf` imported cleanly, the `demostracion` filter selected the
exact 11 eligible molecules, all 11 conformers (`ETKDGv3` + `MMFF94s`) and
`Meeko` PDBQTs prepared cleanly, and all 11 child GNINA 1.3.3 CUDA jobs
succeeded serially without overlapping execution intervals. Every child job
reported process-level GPU observation matching the enumerated physical GPU
UUID, descending `CNNscore` pose ordering, and exact SHA-256 verification across
every retrieved pose download. All active work leases and CPU/GPU allocations
were released and the source project remained unchanged. Retained create-only
`evidence.json` SHA-256:
`9662bd482fa2a7c93fbf22ad5b9d22dc98b4c0aa0011d4c9774e898e30c3ddac`.

## Observed run: screening-api-cuda-cancel-01 (harness query-parameter error)

The first cancellation attempt failed in the test client harness with HTTP 422
because `GET /api/v1/docking/gnina/screenings/{campaign_id}/entries` requires
the `after_revision` query parameter. FastAPI shutdown cleanly terminated the
running background worker, left zero GPU compute processes, and left the source
project unchanged. The untouched create-only failure record is retained at
`screening-api-cuda-cancel-01/evidence.json` with SHA-256
`35966ba98c32510357780d9be10c5e7128679e93f7f8b267c023e55381663a3d`.

### Predeclared follow-up (`screening-api-cuda-cancel-02`)

Run the identical two-molecule active-GPU cancellation protocol in a new
create-only directory (`screening-api-cuda-cancel-02`) via
`scripts/validate_linux_gnina_screening_cuda_cancel.py`, passing
`?after_revision=0` when polling campaign entries while preserving every
acceptance criterion from Sub-run 2 unchanged.

