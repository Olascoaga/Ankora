# GNINA Methods report

A completed GNINA single job can write the Methods section its own record
supports, through the same Results interface and the same route as the other
engines: `GET /api/v1/results/campaigns/gnina_job/{job_id}/methods`. The route
previously failed closed with `GNINA_METHODS_UNAVAILABLE`; that behavior is
superseded by the GNINA Methods decision in ADR-027. The engineering checks that
recorded the fail-closed behavior, including `catalog-cuda-01` in
`LINUX_GNINA_CATALOG.md`, are unchanged and remain accurate for the state they
observed.

## What the section reports

Written from the GNINA job record alone, never from another engine's renderer:

- **Engine identity** — version, executable SHA-256, and native x86-64 Linux
  architecture.
- **Search protocol** — the fixed seed, exhaustiveness, maximum binding modes,
  and minimum inter-mode RMSD filter.
- **CNN configuration** — the recorded scoring mode and built-in model named
  specifically rather than as "CNN".
- **Hydrogen handling** — independently prepared PDBQT inputs with hydrogen
  addition and stripping both disabled, so the engine neither added nor removed
  hydrogens; recorded protonation is described when the inputs are verified.
- **Compute policy** — CPU threads with GPU disabled, or the requested CUDA
  logical device, and in both cases that Ankora never falls back between devices.
- **Search box** — taken from the docking record itself, because a binding-site
  artifact can be superseded after a run. The site record supplies the box's
  derivation only while it still names the same receptor and the same box
  numerically.

## Score semantics

The three quantities stay three quantities, each with its unit and direction:

| Quantity | Unit | Direction | Role |
|---|---|---|---|
| CNN pose score | dimensionless, 0–1 | higher ranks earlier | the engine's ordering |
| CNN affinity | pK | higher is stronger predicted affinity | prediction |
| Minimized affinity | kcal mol⁻¹ | more negative is more favourable | prediction |

The section states that the ranking did not use the minimized affinity, so the
top-ranked pose need not be the lowest-energy one. All three are predictions of
this engine for this pose. None is a measured binding affinity, none is evidence
of biological activity, and none shares a scale with a Vina score or an
AutoDock4 binding energy. No cross-engine pooling or joint ranking is produced.

A CUDA observation is reported as confirming that the engine's own process was
seen on the named device — not as proof that every neural-network operation
executed on the GPU.

## Gaps rather than inference

A receptor or ligand preparation is described **only** while the stored artifact
still hashes to the value GNINA recorded for it. Each of these becomes its own
explicit `[not recorded: …]` marker and `gaps` entry naming the failed check:

- the job, receptor, ligand, conformer or binding-site record is gone;
- the receptor artifact the job names is absent from the receptor record;
- a stored artifact no longer matches the recorded hash;
- the prepared ligand record belongs to a different ligand;
- the binding-site record no longer matches the recorded receptor and box;
- a CUDA run has no recorded GPU process observation.

A receptor prepared again after the run is a different receptor, and describing
its protocol would attribute these numbers to inputs that did not produce them.
An unfinished job reports its recorded status and failure code and publishes no
score, affinity prediction or pose.

Repeat behavior is reported as not assessed, consistent with the catalog, until
GNINA-specific repeat evidence is implemented.

## Verification and limits

`backend/tests/test_gnina_methods.py` covers, against explicitly synthetic
fixtures whose highest CNN score sits deliberately beside the weakest minimized
energy so that a renderer confusing the two axes is caught:

- the three score axes and their units, directions and separation;
- no measurement, biological-activity or cross-engine-scale claim;
- engine identity, seed, search parameters, CNN mode and model, and the exact
  recorded box;
- the prepared-PDBQT hydrogen policy;
- CPU and CUDA compute policy, and the bound on what a GPU observation proves;
- an unobserved CUDA run as a gap;
- preparations described only on matching hashes, with tampered receptor,
  ligand and conformer hashes each withholding the protocol;
- a missing receptor artifact, removed records, and a superseded binding site;
- a failed job publishing no numbers;
- a regression that no Vina, AutoDock4 or AutoGrid procedure or tool appears;
- gap-to-marker parity, and the route rendering and refusing an unknown job.

`test_gnina_catalog.py` additionally pins that the route now renders and that
the prose keeps the axes apart. Frontend coverage is in
`ResultsWorkspace.test.tsx`, which pins that a GNINA result offers the Methods
button, and `MethodsPanel.test.tsx`, which pins that the two per-pose quantities
stay separate list items rather than collapsing into the ranking paragraph.

### Outstanding

- A separate single-case integration check with a preserved WSL CUDA source job
  succeeded; see `LINUX_GNINA_METHODS.md`. No docking was rerun for this unit.
- **No GNINA citation is supplied yet.** Ankora holds no reference for GNINA that
  has been resolved against registered DOI metadata, so the Software table
  reports it as having none and the prose tells the author to supply it. Adding
  one requires Crossref verification, not recall; a fabricated citation looks
  correct until a reader follows it. This is a gap in Ankora's citation map, not
  in any campaign's records.
- Native Linux workstation acceptance remains pending, as for the rest of the
  GNINA port.
