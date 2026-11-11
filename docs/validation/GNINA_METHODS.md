# GNINA Methods report

Completed GNINA single jobs and multi-ligand GNINA screening campaigns write the
Methods section their own records support, through the same Results interface
and routes as the other engines:

- `GET /api/v1/results/campaigns/gnina_job/{job_id}/methods`
- `GET /api/v1/results/campaigns/gnina_screening/{campaign_id}/methods`

Single-job Methods previously failed closed with `GNINA_METHODS_UNAVAILABLE`;
that behavior is superseded by ADR-027. Historical engineering checks that
recorded the earlier fail-closed behavior, including `catalog-cuda-01` in
`LINUX_GNINA_CATALOG.md`, remain unchanged for the state they observed.

## What the section reports

Written from the GNINA job or screening campaign record alone, never from
another engine's renderer:

- **Engine identity** — version, executable SHA-256, and native x86-64 Linux
  architecture, plus sequential `worker_count = 1` execution for screening
  campaigns (one independent GNINA job per prepared entry in selection order).
- **Search protocol** — the fixed seed, exhaustiveness, maximum binding modes,
  and minimum inter-mode RMSD filter.
- **CNN configuration** — the recorded scoring mode and built-in model named
  specifically rather than as "CNN".
- **Hydrogen handling** — independently prepared PDBQT inputs with hydrogen
  addition and stripping both disabled, so the engine neither added nor removed
  hydrogens; recorded protonation is described when the inputs are verified.
- **Library selection and per-entry preparations (screening campaigns)** —
  library import counts, RDKit filter criteria, PAINS/Brenk/duplicate policies
  and filter census are described only when the stored filter manifest still
  matches the SHA-256 and selection order pinned on `campaign.selection`;
  per-entry conformer and PDBQT protocols are described only when stored bytes
  match `entry.conformer_sha256` and `entry.ligand_sha256`, while preflight
  refusals (`gnina_job_id is None`) are reported explicitly without inventing
  unrecorded preparations.
- **Compute policy** — CPU threads with GPU disabled, or the requested CUDA
  logical device, and in both cases that Ankora never falls back between devices.
- **Search box** — taken from the docking or campaign record itself, because a
  binding-site artifact can be superseded after a run. The site record supplies
  the box's derivation only while it still names the same receptor and the same
  box numerically.
- **Crossref-verified GNINA citation** — `tool_citations.py` registers GNINA 1.0
  verified directly against Crossref metadata (`10.1186/s13321-021-00522-2`:
  McNutt AT, Francoeur P, Aggarwal R, Masuda T, Meli R, Ragoza M, Sunseri J,
  Koes DR. *GNINA 1.0: molecular docking with deep learning*. Journal of
  Cheminformatics. 2021;13(1):43).

## Score semantics

The GNINA quantities stay distinct, each with its own unit and direction:

| Quantity | Unit | Direction | Role |
|---|---|---|---|
| CNN pose score | dimensionless, 0–1 | higher ranks earlier | within-ligand pose ordering (and default screening ranking) |
| CNN affinity | pK | higher is stronger predicted affinity | prediction |
| CNN_VS (`CNNscore × CNNaffinity`) | pK-weighted | higher ranks earlier | optional campaign-level virtual-screening hit prioritization (`ADR-028`) |
| Minimized affinity | kcal mol⁻¹ | more negative is more favourable | empirical energy prediction |

The section states that the ranking did not use the minimized affinity, so the
top-ranked pose or compound need not be the lowest-energy one. When a screening
campaign records `hit_ranking_metric = "cnn_vs"`, Methods states explicitly that
between-ligand prioritization used descending top-pose `CNN_VS = CNNscore × CNNaffinity`
(while within-ligand modes remained ordered by `CNNscore`), reports all four
quantities for the top-ranked compound, and discloses
`GNINA_CNN_VS_NONPOSITIVE_AFFINITY` whenever any completed compound recorded
`CNNaffinity <= 0` (`K_d >= 1 M`), where negative products invert `CNNscore`
monotonicity among negative-pK decoys. None of these predictions is a measured
binding affinity, none is evidence of biological activity, and none shares a
scale with a Vina score or an AutoDock4 binding energy. No cross-engine pooling
or joint ranking is produced.

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

- Single-case integration checks with preserved WSL CUDA source runs (`catalog-cuda-01`
  for single-job GNINA in `LINUX_GNINA_METHODS.md` and an isolated `tmp_path` copy
  of the 11-compound `screening-api-cuda-01` campaign in `test_gnina_methods.py`)
  pass with zero gaps and Crossref-verified GNINA 1.0 citation rendering. No
  docking was rerun for this unit.
- Native Linux workstation acceptance remains pending, as for the rest of the
  GNINA port.
