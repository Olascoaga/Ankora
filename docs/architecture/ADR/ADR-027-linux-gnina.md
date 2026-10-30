# ADR-027: GNINA docking on Linux

Status: accepted by the scientist, 2026-10-29.

## Decision

Add GNINA as a distinct docking engine in the Linux edition of Ankora. GNINA
remains unavailable in the native Windows edition. This supersedes only the
GNINA deferral in ADR-015 and the exclusion of new scoring from the initial
Linux port unit in ADR-026; it does not alter the Windows release contract.

## Scientific and engineering contract

- Run GNINA behind a versioned backend adapter, never in the frontend. Track
  executable hash, version, full command, input identities, search box, seed,
  computational resources, CNN mode and model, and raw stdout/stderr/output.
- Preserve independently prepared receptor and ligand inputs; document and
  test any format conversions and protonation assumptions. Never silently
  change structures or coerce ambiguous atom mappings.
- Preserve GNINA's own pose ordering and separate empirical energy, CNN pose
  score and CNN affinity prediction as named fields. Their directions, units
  and models must be explicit. No prediction is experimental affinity, and no
  numbers are pooled with Vina or AutoDock4 as if on a common scale.
- Begin with the `rescore` mode; additional modes and custom models need their
  own recorded semantics. Preserve upstream defaults explicitly and identify
  the actual built-in model/ensemble and executable version, not just `CNN`.
- A detected executable or reported device is not proof that GPU inference
  ran. Validate CPU and CUDA paths separately; resource reservations,
  cancellation and honest failure reporting are mandatory. Do not silently
  fall back from requested GPU execution to CPU.
- Use isolated synthetic inputs and previously recorded public reference
  cases only in predeclared engineering checks. Keep frozen evidence immutable.
  Successful runs or redocking on one structure are not universal validation.
- Integrate results, exact poses, interactions, redocking, export and Methods
  only when their cross-engine scientific contracts are implemented and tested.
  A feature is not complete until code, tests and recorded evidence exist.
- GPU/runtime/architecture and licensing/redistribution requirements must be
  resolved separately before a Linux installer is called complete. Linux WSL
  evidence does not replace native-workstation acceptance.

## Delivery sequence

1. Verify official GNINA 1.3.3 Linux executable identity and a bounded real
   CUDA run against isolated inputs; record the actual output format and errors.
2. Implement and validate Linux-only discovery, adapter, typed GNINA scores,
   input and pose handling against the observed outputs. Keep Windows unchanged.
3. Add a durable, cancellable single-ligand service and API with immutable
   artifacts, resource control and exact provenance; exercise real and error
   paths before exposing it in the UI.
4. Integrate a Linux-only workspace, results and pose inspection, followed by
   library campaigns with progress, redocking, interactions and exports.
5. Test WSLg, Windows regressions and native Linux workstation; review licenses,
   model redistribution and runtime size before packaging.

### Single-job persistence foundation

GNINA jobs have a distinct project-scoped store and score-bearing schema; they
are not inserted into the existing Vina or AutoDock result catalog. Pose files
are create-only and cannot be served until a completed record publishes them.
The record requires the engine's descending CNN-score order, exact input hashes,
the executable hash and successful execution evidence. A CUDA record also
requires evidence that the process was observed on a GPU. Such observation
confirms a GPU process was reported, not independently that every neural-network
operation used the GPU. Failure and cancellation do not publish poses. This
foundation alone does not execute jobs or expose an API or UI.

Interrupted GNINA records are reconciled on backend startup as failed, keeping
any partial raw output without publishing it as a pose. Their leases are
reconciled with the existing recovery mechanism. Retrying creates a new attempt
only after explicit acknowledgement and input revalidation.

An internal single-job service now copies and verifies prepared input
artifacts, reserves resources, retains raw tool output, checks each returned
pose against the prepared conformer, and records terminal status. Its tests use
synthetic lifecycle behavior and a previously recorded real-engine pose fixture.
A separate predeclared isolated WSL CPU service run completed and retained
evidence; see `docs/validation/LINUX_GNINA_SERVICE_CPU.md`. The service is now
connected to project lifecycle and typed localhost API routes. CUDA requests
are subject to the single-device identity policy below. The UI, result
catalog and native Linux acceptance remain separate work.

An experimental service-only CUDA gate requires `nvidia-smi` to report a
process whose executable and unique job working directory match the run.
Missing observation fails the job without publishing poses; raw output is kept.
The observed PID and GPU UUID do not prove that every network operation ran on
that device or that a requested logical CUDA index maps to a particular physical
GPU. Predeclared real execution and cancellation succeeded in WSL; see the
corresponding validation records. For the first supported device policy, CUDA
is restricted to logical device 0, exactly one NVIDIA GPU, no MIG and no CUDA
visibility or MPS remapping. The requested physical UUID is recorded and must
match the UUID observed for the process, otherwise no pose is published.
Multi-GPU selection requires a separately validated mapping contract. The
project runtime enables this guarded path, while standalone services retain an
explicit opt-in. Predeclared WSL CPU and CUDA API checks completed; native
workstation and UI acceptance remain necessary.
See [NVIDIA's CUDA environment variables](https://docs.nvidia.com/cuda/cuda-programming-guide/05-appendices/environment-variables.html).
