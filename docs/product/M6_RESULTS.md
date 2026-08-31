# M6 Results workspace

- Status: Implemented; recoverable campaign management added 2026-08-27
- Date: 2026-08-26
- Depends on: scientifically accepted M3-M5 records
- Followed by: M7 Redocking Validation, M8 Export, then M9 Pose Interactions

## Purpose

M5 already displays results while a docking job is being configured or
monitored. M6 is not another docking screen. It is the durable project-level
place to reopen, inspect, filter, compare, and understand every preserved
docking result after execution, including after an application restart.

The workspace must answer four questions without reconstructing scientific
facts in the frontend:

1. Which exact experiment produced this result?
2. Which compounds completed, failed, were canceled, or were incompatible?
3. Which native poses, clusters, and runs support the displayed ranking?
4. Where do two genuinely different scoring families agree or disagree?

## Scientific boundaries

- A docking score is a computational ranking value, not experimental affinity.
- Vina and AutoDock4 scores remain on different scales and are never averaged,
  normalized into a combined number, or called a consensus score.
- AutoDock4 CPU and AutoDock-GPU are two search backends of one scoring family,
  not independent scientific votes.
- Vina results remain pose-native. AutoDock4 results remain cluster/run-native.
  The Results workspace may normalize navigation and identity, but it may not
  flatten away cluster population or fabricate Vina-style modes for AutoDock.
- Existing PAINS/Brenk findings, rule evaluations, descriptors, preparation
  energy, and exclusions are inherited from the immutable M3 manifest. M6
  displays them beside docking outcomes; it does not silently recalculate a
  different library filter after seeing the scores.
- Comparisons are allowed only when receptor, finalized binding site, and
  applied selection manifest match exactly. Single-ligand comparisons require
  the same receptor, site, ligand, and prepared-ligand artifact.
- M6 does not calculate crystallographic RMSD or declare protocol success.
  Those belong to M7.

## Source of truth

M6 reads the records already owned by the execution services:

- Vina single jobs and library batches;
- AutoGrid map-set identity where applicable;
- AutoDock4 CPU single jobs and library batches;
- AutoDock-GPU single jobs and `--filelist` library campaigns;
- immutable receptor, binding-site, ligand, conformer, PDBQT, library, and
  selection-manifest records referenced by those jobs;
- raw command/parameter files, stdout/stderr, GLG/DLG, hashes, warnings,
  failures, poses, clusters, runs, provenance, and tool/device identities.

The result catalog is a read model over those records. It must not copy pose
files, rewrite a DLG, mutate a campaign, or create a second scientific truth.
Any persisted catalog index is rebuildable metadata and must reference the
authoritative record IDs and hashes.

Campaign management is a separate operation over the authoritative trees, not
an exception to the read model. Removing a result moves its complete directory
to project Trash; no scientific record is edited into a half-deleted state.

## Experiment identity

Every list/detail response must expose enough identity to prevent accidental
cross-experiment interpretation:

- job or campaign ID and creation/completion timestamps;
- single-ligand or virtual-screening mode;
- scoring family and execution backend;
- exact executable version/hash and GPU device when applicable;
- receptor ID, receptor output artifact ID, and receptor SHA-256;
- binding-site ID and exact center/size;
- ligand/preparation IDs for single jobs;
- library ID, filter-run ID, manifest artifact ID, and manifest SHA-256 for
  screening campaigns;
- complete search protocol summary and a link to its native parameters;
- terminal and partial status counters without dropping failed rows.

## Workspace layout

The screen extends ADR-014 rather than introducing new page chrome.

### Left workflow rail

Results becomes available when at least one durable docking job or campaign
exists. Its summary reports the number of completed campaigns and the most
recent result-bearing engine/backend. Opening Results never launches work.

### Campaign browser

A compact project catalog supports:

- single-ligand versus screening filtering;
- scoring family and backend filtering;
- receptor, binding site, library, status, and date filtering;
- explicit labels such as `Vina 1.2.7`, `AutoDock4 4.2.6 · CPU`, and
  `AutoDock4 · AutoDock-GPU 1.6`;
- restoration of completed, partial, failed, canceled, and incompatible work;
- deterministic default ordering by newest creation time, never by best score
  across incompatible engines.

Campaign selection loads summary metadata first. Large row payloads and raw
evidence are fetched on demand. Opening a card replaces the catalog plane with
that campaign's molecule/energy/pose table and an explicit route back; result
details are never appended beneath the card catalog. A terminal campaign that
is already open has a visible `Delete this result` action; group removal uses
the separate `Select multiple` mode across catalog pages. Removal always
requires a second, selection-specific acknowledgement and executes as one
bounded transaction.

### Main result plane

The central plane has a viewer-linked table and Mol* review area. For screening
campaigns the table preserves source-manifest order as a stable column while
allowing user sorting and filtering by:

- compound index, name, SMILES, formula, molecular weight;
- inherited M3 rules/alerts and preparation energy;
- docking status and failure code;
- engine-native best computational score;
- Vina pose count, or AutoDock cluster count/top-cluster population;
- completion time.

The initial result ordering may use the engine-native most favorable score
inside one campaign. Missing/failed values remain last and every manifest UUID
remains recoverable through status filtering.

A visible synchronized horizontal scrollbar is required. The implementation
must remain responsive at the current 10,000-record library boundary; table
virtualization or equivalent windowing is required before claiming that limit.

### Pose and cluster review

Selecting a row updates Mol* and the contextual inspector.

- Vina: list every preserved mode with score and RMSD bounds; selecting a mode
  overlays that exact pose.
- AutoDock4 CPU/GPU: show clusters first with population and representative
  energy, then expandable constituent runs with both RMSDs and exact pose.
- Viewer state distinguishes receptor, selected pose, crystallographic ligand
  when available, and optional comparison overlays through text plus color.
- A missing or unreadable pose is a structured artifact error; the workspace
  does not substitute another pose silently.

### Inspector and evidence

The right inspector shows compound identity, inherited chemical/preparation
state, current engine-native result, and experiment identity. Expandable
technical evidence exposes exact commands or GPF/DPF settings, hashes, tool and
device identity, raw-output links, warnings, failures, and provenance.

The activity center remains the shared place for warnings and commands. Results
must not pretend a historical campaign is currently running.

## Comparison mode

Comparison reuses the existing scientifically guarded Vina/AutoDock4 service
instead of implementing correlation math in React.

- The user selects two compatible result-bearing library campaigns.
- The backend verifies exact experiment compatibility.
- The summary reports common/succeeded counts, Spearman rank correlation, and
  Top-N overlap with the chosen N.
- The compound table shows the two native ranks and scores in separate columns,
  rank shift, and outcome status. It has no combined or preferred rank.
- Selecting a compound permits pose/cluster overlay while retaining engine and
  backend labels.
- CPU/GPU comparison may be offered as search-repeatability evidence, but must
  be labeled as two backends of one scoring family and kept separate from
  Vina/AutoDock4 scoring-family agreement.

## Backend/API direction

Implement one read-only result-catalog service rather than making the frontend
scan filesystem directories or know every store layout.

Suggested typed surfaces:

- `GET /api/v1/results/campaigns` with pagination and explicit filters;
- `GET /api/v1/results/campaigns/{engine}/{id}` for exact summary identity;
- `GET /api/v1/results/campaigns/{engine}/{id}/compounds` with pagination,
  sorting, filtering, and totals;
- existing engine-native job/batch and pose endpoints remain authoritative for
  detailed evidence and content;
- existing guarded comparison endpoints remain authoritative for rank
  statistics and should be extended only where GPU-backed records require it.
- `POST /api/v1/results/campaigns/trash` removes one to 100 exact catalog IDs
  as one recoverable operation; it is not a frontend filesystem action.

## Campaign removal and Trash

- Completed, failed, and canceled records may be removed; queued, running, and
  cancel-requested work must finish or be canceled first.
- A multiple selection is all-or-nothing. Every ID and status is validated
  before the first directory moves, and a filesystem failure rolls earlier
  moves back.
- The complete campaign/job directory moves to
  `trash/result_campaigns/<operation UUID>/campaigns/...` with an operation
  manifest containing its prior location and full catalog identity.
- M9 pose-interaction analyses and M7 redocking validations that directly name
  a removed result move into the same Trash operation, so no active dependent
  record silently points at missing pose evidence.
- Receptors, ligands, libraries, binding sites, shared AutoGrid map sets, and
  standalone M8 export bundles are never part of result removal.
- Emptying Trash and a scientist-facing restore browser are separate future
  storage-management capabilities. Until then the operation remains
  recoverable from its manifest and retained directories.

The catalog must use stable opaque cursors or explicit page/limit contracts,
bounded query sizes, and deterministic tie-breaking. It must not return every
pose or multi-megabyte raw log in a campaign-list response.

## Stale and partial records

- Historical results remain inspectable if a newer upstream decision makes
  them stale; the stale reason and superseding identity are visible.
- A partial/canceled GPU campaign keeps completed molecules and labels the
  unfinished denominator honestly.
- A failed campaign remains openable even if it has no successful poses.
- Missing derivative files or hash drift are surfaced as integrity failures,
  not hidden by removing the campaign from history.
- Cleanup of large canceled AutoGrid partials is a separate explicit storage
  policy; removing a result never treats a shared map set as campaign-owned.

## Non-goals

- no new docking execution;
- no redocking RMSD or PASS/FAIL protocol verdict;
- no interaction fingerprinting or 2D interaction diagrams inside the M6
  catalog slice; the approved M9 capability extends Results under
  `docs/product/M9_POSE_INTERACTIONS.md`;
- no CSV/SDF/project-bundle export yet;
- no combined score or automatic hit selection;
- no automatic post-screening chemical exclusion;
- no automatic or background result cleanup;
- no remote, cloud, database-server, or HPC result source.

## Acceptance criteria

M6 is complete only when all of the following hold:

1. Every preserved Vina, AutoDock4 CPU, and AutoDock-GPU single job and library
   campaign can be discovered and reopened after an app restart.
2. Catalog and detail screens always identify scoring family, backend,
   executable version, inputs, protocol, and terminal/partial state.
3. Every selected manifest UUID remains represented, including preflight,
   runtime, cancellation, and compatibility failures.
4. Vina modes and AutoDock clusters/runs retain their native hierarchy and
   viewer-linked exact pose artifacts.
5. Table filtering/sorting/pagination remains deterministic and responsive on
   a synthetic 10,000-row campaign without transferring all pose evidence.
6. Same-experiment compatibility is enforced by backend tests; incompatible
   comparisons fail closed with a structured explanation.
7. No API or UI field can be interpreted as a merged Vina/AutoDock score.
8. Hash drift and missing artifacts produce visible integrity failures.
9. Backend tests, frontend tests, strict typing/lint, production web build,
   Rust checks, and native Windows release build pass.
10. A real Windows smoke reopens at least one Vina campaign and one AutoDock4
    campaign from disk, selects multiple poses/runs, and verifies their engine
    labels and Mol* overlays.
11. Individual and multiple terminal-result removal is explicitly confirmed,
    transactional, recoverable, and carries direct M7/M9 dependents without
    deleting shared inputs or export bundles.

## Implementation slices

1. **M6.1 Catalog contract:** typed campaign summaries, pagination, filters,
   identity/integrity checks, and coverage over all three backends.
2. **M6.2 Results shell:** unlock workflow step 6, campaign browser, durable
   restoration, and exact experiment summary.
3. **M6.3 Compound analysis:** scalable table, inherited M3 evidence, status
   filters, Vina modes, AutoDock cluster/run drill-down, and Mol* linkage.
4. **M6.4 Comparison integration:** compatible campaign selection and guarded
   ranking agreement without merged scores.
5. **M6.5 Acceptance:** synthetic 10,000-row responsiveness contract, current
   full suite, and real Windows Vina/AutoDock4 reopen-and-review smoke.

## Resolved implementation defaults

- Results opens the newest result-bearing campaign, matching existing durable
  recovery behavior, while keeping campaign selection immediately visible.
- Default screening columns are source index, name, SMILES, molecular weight,
  inherited alerts, docking status, engine-native best score, and pose count or
  cluster/population summary. Formula, preparation energy, detailed rules,
  timestamps, hashes, and failure codes remain available through the existing
  column chooser and inspector.
- The first M6 release migrates the scientifically independent Vina/AutoDock4
  comparison. CPU/GPU repeatability remains visible in native campaign evidence
  and becomes a dedicated comparison only after the core workspace is stable.
- Future Export always preserves the complete immutable campaign. If the user
  exports a filtered/sorted Results view, that view becomes a separate manifest
  layered over the complete campaign rather than replacing omitted rows.
- Result management is explicit. `Delete open result` starts the individual
  path for the currently opened terminal campaign. `Select multiple` changes
  cards into bounded multi-select controls for group removal. Both paths repeat
  the exact selection in the destructive confirmation.
