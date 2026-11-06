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
CNN-ranked pose only after checking the single-job request, tool, receptor,
prepared ligand and conformer identities against the campaign, preserved input
hashes and the published pose hash. It is not yet
wired into a campaign; the future caller must also validate the applied filter
selection and prepared-ligand identities. The verifier does not run GNINA.

The separate selection verifier checks the applied manifest's bytes, hash and
size against the saved filter record, including selected order, evaluations,
chemical-state identities, filter settings and counts. Missing or inconsistent
evidence is rejected, while a consistent empty selection has its own error. It
does not yet start a campaign or validate prepared ligand artifacts.

The typed campaign contract records selected entries in selection order and
links each attempted entry to an individual GNINA job without copying scores
or asserting that the link has been verified. Terminal counts, status and
progress are checked for internal consistency; the compact progress header
does not contain the library. A completed entry names the selected chemical
state and pins both its PDBQT and conformer identities and hashes. This model
is not persistence or execution.

An independent preparation verifier checks that a prepared entry, PDBQT and
conformer name the selected ligand and chemical state, point to one another,
and still match their recorded sizes and hashes. It reports a failure without
modifying artifacts. The future orchestrator must obtain the state from the
verified selection and the preparation entry from the matching project/library.

Project-scoped campaign storage now retains the verified applied selection as a
create-only snapshot and updates individual entries and counters transactionally
in SQLite. Compact progress and revision-based entry reads do not load the
entire library. Publishing a successful entry requires the matching single GNINA
job, exact prepared inputs and preserved pose; terminal outcomes remain frozen.
Synthetic tests cover isolation, ordering, concurrency, failure, cancellation,
tampering and a small applied filter selection on Linux and Windows. The
synthetic engine fixture does not validate scientific docking performance.
The store is not wired to campaign orchestration or a campaign API.

The storage layer provides an atomic interruption transition for an abandoned
campaign. It preserves completed entries, checks linked completed jobs before
recovering their poses, marks unverifiable or unfinished entries explicitly and
does not retry them. The campaign remains failed after interruption even if it
retains successful entries. Calling this transition requires the runtime to have
established that the previous owner is no longer active. Project startup now
reconciles abandoned GNINA screenings after reconciling their GNINA jobs. The
activity panel shows recovered counts and does not offer a screening retry
until that operation is implemented.

A library preflight now resolves every selected compound in selection order,
retaining an explicit failure for missing or inconsistent source records and
unprepared or altered derivatives while leaving verified neighbors queued.
The preflight result and its pinned manifest have been exercised together with
the campaign store using a synthetic library; no GNINA process was started.

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
