# GNINA virtual-screening implementation plan

GNINA is currently available on Linux for a single explicitly prepared ligand.
This plan adds a separately recorded library campaign without changing the
single-job scientific contract or suggesting that a campaign already exists.
Native Windows remains unchanged; native Linux workstation acceptance and
packaging are separate work.

## Contract

- A campaign consumes one immutable, applied filter selection and its exact
  prepared ligand states, together with one recorded receptor and binding box.
  Validate identities, hashes and stale state before use. Every selected entry
  must remain represented in selection order, including preflight failures.
- Each actual execution must retain its own GNINA job identity and raw inputs,
  outputs, tool version, command, device and execution evidence. No incomplete,
  failed or canceled execution may publish poses. Do not overwrite an attempt
  or silently rerun it on restart.
- GNINA ranks its poses by CNNscore. Report CNNscore (dimensionless), predicted
  CNNaffinity (pK) and minimized empirical affinity (kcal/mol) separately;
  predictions are not measured binding affinities. Never combine ranking scales
  across engines or silently rank by a different field.
- Persist progress as entries finish. Distinguish queued, running, failed,
  canceled and successful entries, including interruption and partial results.
  Cancellation must reach active subprocesses and leave their evidence intact.
  Reconcile work leases and resource reservations on every terminal path.
- Reuse the existing GNINA service and global CPU/GPU admission policy. Its
  present executor runs one job at a time; do not promise concurrent ligands
  until bounded CPU and GPU scheduling is explicitly implemented and tested.
  No silent GPU-to-CPU fallback; GPU process observation does not prove that
  every neural-network operation ran on the GPU.
- An exposed campaign needs coherent Results, pose inspection, Methods,
  interactions, export, deletion and redocking behavior. Unsupported actions
  must remain visibly unavailable rather than being mislabelled as single jobs.

## Delivery and acceptance

Preparatory regression: a synthetic queued GNINA job canceled behind an active
job never launches its own process or publishes poses, and releases its
resource reservation. The existing single-job service tests pass in Linux and
Windows. This test does not implement a campaign or test a real GPU process.

The independent screening-evidence verifier projects the first recorded
CNN-ranked pose only after checking the single-job request, tool and receptor
identities, preserved input hashes and the published pose hash. It is not yet
wired into a campaign; the future caller must also validate the applied filter
selection and prepared-ligand identities. The verifier does not run GNINA.

The separate selection verifier checks the applied manifest's bytes, hash and
size against the saved filter record, including selected order, evaluations,
chemical-state identities, filter settings and counts. Missing or inconsistent
evidence is rejected, while a consistent empty selection has its own error. It
does not yet start a campaign or validate prepared ligand artifacts.

1. Implement project-isolated typed campaign and entry persistence with atomic
   updates, immutable identities, explicit lifecycle invariants and synthetic
   tests. This is a foundation, not an executable workflow.
2. Add backend orchestration and localhost API: resolve every manifest entry,
   start verified single jobs under resource control, persist incremental
   progress, and exercise cancellation, failure, restart and isolation. Test
   changes against existing Windows behavior as well as Linux.
3. Integrate the Linux-only user workflow and results, with clear score units,
   live progress and explicit supported actions. Exercise narrow-window and
   failure states as well as success.
4. Before a real execution, record a bounded, isolated engineering protocol.
   Preserve source inputs and raw outputs; test more than one selected molecule
   and independently verify count, scores, progress, cancellation and resource
   release. Preserve failures as evidence and never rewrite a frozen result.
5. Complete portable evidence support and verify the workflow in WSLg and on a
   native Linux workstation before any Linux release claim. A small real run is
   engineering evidence for that case, not a general scientific benchmark.

Commit each completed, tested unit with tracked documentation; keep private
project memory outside Git. GNINA virtual screening is not complete until the
implementation, tests, acceptance criteria and recorded evidence all exist.
