# ADR-027: GNINA docking on Linux

Status: accepted by the scientist, 2026-10-29.

> **Current status note (2026-11-12):** Several incremental subsections below preserve historical milestone states from `2026-10-29` through `2026-11-11`. Full Linux `GNINA 1.3.3` support—including the single-ligand and multi-ligand screening desktop UIs, redocking Validation UI, `ProLIF` pose interactions, Crossref-cited `Methods`, Export v4, `CNN_VS` hit prioritization, CUDA `refinement`, built-in CNN ensembles ([ADR-028](ADR-028-gnina-cnn-vs-refinement-ensemble.md)), and the 1-click offline GNINA CUDA 12.8 runtime pack ([ADR-029](ADR-029-linux-offline-distribution.md))—is now implemented in source. Bare-metal physical Linux workstation attestation (`ADR-029` Gate `D6`) remains pending; see [`PLATFORM_STATUS.md`](../../product/PLATFORM_STATUS.md).

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

GNINA jobs have a distinct project-scoped store and score-bearing schema. The
project Results catalog may project them under a separate GNINA scoring family;
CNNscore is dimensionless and must never populate the kcal/mol field or be
ranked across engines. Pose files
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

## GNINA catalog projection

The single-job catalog shows the engine's top CNNscore, CNNaffinity in pK and
the same pose's minimized affinity in kcal/mol as separate quantities. The
primary ordering is descending CNNscore; it is not the minimum energy. A
completed GNINA job counts as succeeded when it has validated published poses.
Its persisted box is used as recorded, and reproducibility remains not assessed
until GNINA-specific repeat evidence is implemented. Existing score fields and
the order of Vina and AutoDock results remain unchanged. A GNINA job may be
moved to project Trash through the same all-or-nothing result removal operation.
The catalog can reopen the saved poses and calculate ProLIF interactions for an
exact GNINA pose after checking the recorded input identities. GNINA-specific
single-job and multi-ligand screening campaign (`gnina_screening`) exports
preserve the original engine evidence, pinned library selection manifest,
campaign snapshot and SQLite state sidecar, per-molecule child job records and
poses, generated `methods.md` and available recorded analyses; see
`docs/validation/GNINA_EXPORT.md`. Single-job redocking validation is
implemented as described below. The
isolated WSL CUDA pose interaction engineering check is recorded in
`docs/validation/LINUX_GNINA_INTERACTIONS.md`.

## GNINA Methods report

Accepted by the scientist, 2026-11-04. This supersedes the earlier position that
the Methods route fails closed for GNINA. The recorded engineering checks that
observed that fail-closed behavior, including `catalog-cuda-01`, remain valid
evidence of what was true when they ran and are not revised.

A GNINA single job renders its own Methods section, written only from that job's
record. It must never be produced by the Vina or AutoDock4 renderer: no
Lamarckian genetic algorithm, no AutoGrid maps, no Vina energy range, no
AutoDock clustering, and no pooled or cross-engine ranking.

The section reports the engine version, executable hash and architecture, the
seed, exhaustiveness, maximum modes and minimum inter-mode RMSD filter, the CNN
scoring mode with the built-in model named specifically, the prepared-PDBQT
hydrogen policy with addition and stripping both disabled, and the compute
policy including the absence of device fallback. The search box is taken from the
docking record rather than the binding-site artifact, because a site can be
superseded after a run; the site record contributes the box's derivation only
while it still names the same receptor and the same box.

The dimensionless descending CNN pose score, the predicted CNN affinity in pK
and the minimized empirical affinity in kcal/mol are reported as three distinct
quantities with their units and directions, and the section states that the
ranking did not use the minimized affinity. All three are engine predictions;
none is a measured affinity, evidence of biological activity, or comparable with
another engine's score. A CUDA observation is reported as confirming that the
engine's process was seen on the device, not that every network operation ran
there.

Receptor and ligand preparations are described only while the stored artifacts
still hash to the values GNINA recorded. A mismatch, a missing artifact, a
preparation belonging to another ligand, or a removed record is an explicit gap
naming the failed check. An unfinished job reports its status and recorded
failure and publishes no score, affinity prediction or pose. Repeat behavior
stays not assessed until GNINA-specific repeat evidence exists.

### Crossref-verified GNINA citation and screening campaign Methods

Updated 2026-11-11. GNINA's primary publication (`10.1186/s13321-021-00522-2`:
McNutt AT, Francoeur P, Aggarwal R, Masuda T, Meli R, Ragoza M, Sunseri J, Koes
DR. *GNINA 1.0: molecular docking with deep learning*. Journal of
Cheminformatics 2021; 13(1):43) was verified directly against Crossref DOI
metadata and registered in `tool_citations.py` under `"GNINA"`, so both single
jobs and screening campaigns render a numbered reference in `## Software` and
`## References`.

Multi-ligand GNINA screening campaigns (`gnina_screening:<campaign_id>`) render
a dedicated `Methods` report via
`GET /api/v1/results/campaigns/gnina_screening/{campaign_id}/methods`, never
sharing Vina or AutoDock4 prose. In addition to the receptor, search-box,
engine-identity, CNN-scoring, hydrogen-policy and GPU-observation invariants of
single-job GNINA, the campaign renderer verifies the pinned selection manifest
SHA-256 and selection order (`verified_screening_selection`), checks every
recorded entry's stored `conformer.sdf` and `ligand.pdbqt` bytes against
`entry.conformer_sha256` and `entry.ligand_sha256`, verifies every completed
child job and published pose (`verified_campaign_entry_job`), documents
sequential execution (`worker_count = 1`), distinguishes preflight refusals from
engine failures, and reports the top-ranked compound by descending `CNNscore`
(ties broken by selection order) alongside its separate `CNNaffinity` (pK) and
`minimizedAffinity` (kcal mol⁻¹).

## GNINA single-job redocking validation

Accepted by the scientist, 2026-11-04. This supersedes only the position that
GNINA-specific redocking is unavailable. The backend measurement exists; no UI
entry point, frozen GNINA reference case or native-workstation acceptance
follows from it.

A completed GNINA single job is admitted as a source of the existing M7
measurement, unchanged: symmetry-aware heavy-atom RMSD computed in place against
an immutable crystallographic extraction from the receptor's own original
structure, or a byte-identical reimport identified by source SHA-256 rather than
by PDB or ligand name. Reference and pose bytes must match their recorded
SHA-256 and size, and the pose must be the reference molecule. Nothing is
docked, minimized or re-oriented by the measurement.

The poses are measured in GNINA's own mode order, which is its descending CNN
pose score. They are never re-sorted by the minimized affinity, so
`ranking_success` remains a statement about the ranking GNINA actually produced.
`source_kind` gains `gnina_job`, and a validated pose may carry the
dimensionless `cnn_score` and the predicted `cnn_affinity_pk` as separate
optional fields. `binding_energy_kcal_mol` remains the engine's minimized
empirical affinity in kcal/mol for every engine, including GNINA, which did not
rank by it. No field pools or compares scores across engines; presentation
labels them.

`bitwise_reproducible` becomes nullable. A GNINA verdict records null, meaning
repeat behavior has not been assessed for this engine, which is a different
statement from `false`. Verdicts recorded earlier keep the boolean they were
written with and stay readable without rewriting.

The verdict's provenance retains the identities the source job recorded for
itself — executable, docking receptor, prepared ligand and conformer SHA-256,
the CNN scoring mode and model, the compute selection and the pose ordering — so
it names the exact run it judged. A job that is not completed is refused rather
than measured, as are a changed pose or reference and a pose that is not the
reference molecule, and no verdict is written in those cases. Sources are
project-scoped: another project's GNINA job is not a validation input. Moving a
GNINA result to project Trash moves its dependent verdicts with it, through the
same all-or-nothing operation.

A verdict concerns one configuration on one reference system. It is not
validation of GNINA, of the CNN model, or of any other target.
