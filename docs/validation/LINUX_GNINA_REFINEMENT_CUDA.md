# GNINA CUDA `refinement` mode, built-in `default_1_3_ensemble`, and VRAM arbiter check — predeclared

## Protocol

`scripts/validate_linux_gnina_refinement_cuda.py` exercises GNINA 1.3.3 CUDA
pose refinement (`cnn_scoring="refinement"`), the built-in 3-model GNINA 1.3
ensemble (`cnn_model="default_1_3_ensemble"`), and `ResourceArbiter` GPU VRAM
accounting through Ankora's real localhost HTTP API on isolated copies of the
prepared `1HSG/MK1` project. This is a bounded WSL2 engineering check, not
native bare-metal Linux workstation acceptance, WSLg graphical acceptance, or a
multi-target scientific benchmark.

### Preconditions

Verify the declared SHA-256 digests of the official GNINA 1.3.3 Linux x86_64
binary (`3340c1f49cd3c7c84d8699182a1c6af13c7fa2a22448d1204640446106f72172`),
the prepared `1HSG` receptor, the `MK1` inspected chemical state, minimized
conformer, and Meeko PDBQT, plus the frozen `redocking-cuda-01/evidence.json`
record (`7696efa2f3aa405d3991fd241f4dcb206a0bd5afbf23ec129162addbe70bdfea`).
Independently enumerate NVIDIA GPUs via `nvidia-smi`; require exactly one
unambiguous GPU at logical index `0` and zero active GPU compute processes
before each GPU sub-run.

### Sub-check 1: fail-closed admission gates

1. Submit `POST /api/v1/docking/gnina/jobs` with `compute="cpu"` and
   `cnn_scoring="refinement"` (`timeout_minutes=15`); require HTTP `422`.
2. Submit `POST /api/v1/docking/gnina/jobs` with `compute="cuda"`,
   `cnn_scoring="refinement"`, and `timeout_minutes=9`; require HTTP `422`.
3. Configure `ANKORA_RESOURCE_GPU_MEMORY_TOTAL_BYTES=1073741824` (`1 GiB`) and
   submit `compute="cuda"`, `cnn_scoring="refinement"`,
   `cnn_model="default_1_3_ensemble"` (`2 GiB` VRAM claim); require HTTP `422`
   with `code == "RESOURCE_REQUEST_EXCEEDS_CAPACITY"` reporting
   `details.resources.gpu_memory_bytes.requested == 2147483648` and
   `capacity == 1073741824`.

### Sub-check 2: end-to-end CUDA `refinement` + `default_1_3_ensemble` single job

Copy `1HSG/MK1` into an isolated directory and submit `POST /api/v1/docking/gnina/jobs`
with `compute="cuda"`, `device_index=0`, `cpu_threads=2`, `seed=20261029`,
`exhaustiveness=4`, `num_modes=5`, `cnn_scoring="refinement"`,
`cnn_model="default_1_3_ensemble"`, and `timeout_minutes=15`. Require:

1. Terminal status `completed` with `1 <= len(poses) <= 5`.
2. Recorded CLI command omits `--cnn` while passing `--cnn_scoring refinement`,
   and `job.cnn_model_identity` persists `selector="default_1_3_ensemble"`,
   `cli_argument=None`, and the 3 verified member networks
   `["dense_1_3", "dense_1_3_PT_KD_3", "crossdock_default2018_KD_4"]`.
3. `execution.gpu_process_observed == True` with both `requested_gpu_uuid` and
   `observed_gpu_uuid` matching the independently enumerated GPU UUID.
4. Descending `CNNscore` pose order; every pose persists
   `cnn_vs == cnn_score * cnn_affinity` with
   `cnn_vs_source == "derived_from_recorded_axes"` and
   `cnn_affinity_variance is None`; every downloaded pose PDBQT matches its
   recorded SHA-256 and reconstructs the exact input `MK1` isomeric canonical
   SMILES through Meeko + RDKit.
5. In-place heavy-atom symmetry-aware crystallographic redocking measurement
   through `POST /api/v1/validation/redocking` (`threshold_angstrom=2.0`)
   matching direct `in_place_rmsd` calculations within `1e-8 Å`, with
   `bitwise_reproducible is None`.
6. Catalog (`GET /api/v1/results/campaigns?scoring_family=gnina`), Methods
   (`GET /api/v1/results/campaigns/gnina_job/{job_id}/methods` with zero gaps,
   3-member ensemble identity, and `refinement` non-independence disclosure),
   and Export v4 (`POST /api/v1/exports/campaigns` with
   `ankora_export_format == 4`, `engine.cnn_model_identity`, `results.csv`
   `gnina_cnn_vs` columns, `README.txt` ensemble + refinement notes, and safe
   ZIP paths).
7. Full release of active work leases, GPU slots (`0`), and reserved VRAM (`0`).

### Sub-check 3: active-GPU cancellation under `cnn_scoring="refinement"`

In a separate isolated directory, launch a `refinement` + `default_1_3_ensemble`
CUDA job with `exhaustiveness=64` so gradient refinement remains active on the
GPU. Poll `nvidia-smi` and `ResourceArbiter.snapshot()` until the child `gnina`
process is observed on the enumerated GPU inside its job working directory while
`gpu_memory_reserved_bytes == 2147483648` (`2 GiB`), then issue
`POST /api/v1/docking/gnina/jobs/{job_id}/cancel`. Require terminal status
`canceled`, zero published poses, `execution.canceled == True`, exited `gnina`
process, zero remaining GPU compute processes, and released GPU slots and VRAM.

## Observed run: `refinement-cuda-01` (harness assertion mismatch before GPU launch)

The initial harness run aborted inside Sub-check 1 before launching any GNINA
process because the script checked `details.field` and `3 GiB` instead of
`ResourceArbiter`'s structured `details.resources.gpu_memory_bytes` payload and
`gnina_claim`'s `2 GiB` (`2,147,483,648` bytes) reservation for
`refinement` + ensemble. No source or frozen file changed. Retained create-only
`refinement-cuda-01/evidence.json` SHA-256:
`d84687d0d045a04a68c11307f80bc1e8c28bdd814ed397bfcbe1bf8efb8d77f7`.

### Predeclared follow-up (`refinement-cuda-02`)

Match `details.resources.gpu_memory_bytes.requested == 2147483648` (`2 GiB`) in
Sub-check 1 and Sub-check 3 while keeping every acceptance criterion unchanged,
writing to create-only directory `refinement-cuda-02`.

## Observed run: `refinement-cuda-02`

All three sub-checks completed cleanly on `NVIDIA GeForce RTX 5050 Laptop GPU`:

- **Sub-check 1 (fail-closed gates):** CPU `refinement` returned HTTP `422`;
  `timeout_minutes=9` returned HTTP `422`; `1 GiB` configured VRAM capacity
  returned HTTP `422` `RESOURCE_REQUEST_EXCEEDS_CAPACITY` (`requested: 2 GiB`,
  `capacity: 1 GiB`).
- **Sub-check 2 (`refinement` + `default_1_3_ensemble` single job):** Completed
  in `284.74 s` (`4.75 min`) with `--cnn` omitted, `--cnn_scoring refinement`,
  verified GPU process observation on `GPU-4fec5c6f-e22d-45ac-5898-743b25fe83b6`,
  exact Meeko/RDKit `MK1` topology across all 5 poses, zero Methods gaps, and a
  verified `18`-file Export v4 bundle (`29782e4cc2bf1e3773fda978e023c3e178e5ed9e8aa524933886e480895c6a18`).

| Mode | `CNNscore` | `CNNaffinity` (pK) | `CNN_VS` | `minimizedAffinity` (kcal/mol) | In-place crystal RMSD (Å) |
|---:|---:|---:|---:|---:|---:|
| 1 | 0.6862 | 8.7810 | 6.0256 | -9.3926 | 9.441 |
| 2 | 0.6526 | 8.1313 | 5.3066 | -0.4250 | 9.197 |
| 3 | 0.5986 | 7.8717 | 4.7124 | +2.5786 | 2.924 |
| 4 | 0.5874 | 8.0776 | 4.7447 | -0.3869 | 11.059 |
| 5 | 0.5808 | 7.6549 | 4.4461 | +12.6768 | 10.868 |

Modes 3 (`+2.58 kcal/mol`) and 5 (`+12.68 kcal/mol`) directly illustrate why
Ankora's Methods and Export v4 reports disclose that `minimizedAffinity` under
`cnn_scoring="refinement"` is evaluated on coordinates locally optimized against
combined CNN and empirical gradients rather than serving as an independent
empirical energy check. On this single `1HSG/MK1` case (`exhaustiveness=4`,
`num_modes=5`), `refinement` + `default_1_3_ensemble` measured `9.441 Å` Top-1
RMSD and `2.924 Å` best RMSD (`not_recovered` at `2.0 Å`), whereas the earlier
`redocking-cuda-01` `rescore` + `dense_1_3` check (`exhaustiveness=1`,
`num_modes=2`) measured `3.685 Å` Top-1 RMSD and `0.938 Å` best RMSD
(`recovered_but_misranked`). Neither single-system engineering run establishes
general pose-recovery performance across targets or search budgets.

- **Sub-check 3 (active-GPU `refinement` cancellation):** Observed live `gnina`
  GPU process (`PID 159013`) while `ResourceArbiter` held `2,147,483,648` bytes
  (`2 GiB`) of reserved VRAM; `POST .../cancel` transitioned the job to
  `canceled` with `0` published poses, terminated the GPU process, left zero
  active GPU compute processes, and returned `gpu_slots_allocated == 0` and
  `gpu_memory_reserved_bytes == 0`.
- Source project files and frozen `redocking-cuda-01/evidence.json` remained
  byte-identical. Retained create-only `refinement-cuda-02/evidence.json`
  SHA-256:
  `91f0689882f96a7cd75bf6defa2b8d22573fd68025383190e0848b2ab6650f61`.
