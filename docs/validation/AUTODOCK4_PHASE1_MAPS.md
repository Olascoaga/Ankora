# AutoDock4 Phase 1 immutable map sets — 2026-08-24

## Outcome

Phase 1 passed on the authoritative Windows 11 x64 development machine. The
production `AutoGridMapService` generated a complete immutable map set from real
7AQF artifacts through the real `autogrid4.exe`, preserved every map plus the
GPF/GLG evidence as create-only artifacts, and reused the identical map set on a
second request instead of recomputing it.

This validates grid generation, map persistence, and cache identity. It does not
enable AutoDock4 docking, which still needs the typed DPF contract and DLG
parsing (Phase 2).

## Real run

Inputs were the accepted docking-ready 7AQF receptor
`01beb9cf-1079-4c03-9ee7-2f058a8bbb5d`, the co-crystallized-ligand binding site
`cfb3d5cd-8c8a-456e-9607-b7abe57fcfb5`, and the applied filter selection
`57fd00c7-5c0f-4550-8be5-46fd9810b607` of library
`e128e700-1249-461a-9b12-c061d3706601`.

- Map set `ebb2a3b0-ca05-4621-bae2-90c08cce9cbc`, identity key
  `8ef92125eaddb2fc72f2e02b4917b39486bef60cf87c91ebd216c5b258edacd4`.
- AutoGrid 4.2.6 (x86) was probed rather than assumed, and reported its own
  ceilings: 20 receptor types, 14 ligand types, 16 maps, 1025 grid points.
- Requested box `21.597 × 19.870 × 19.317 Å` discretized to `58 × 54 × 52`
  intervals at 0.375 Å, realizing `21.75 × 20.25 × 19.50 Å`. No axis shrank.
- Receptor atom types `A C HD N NA OA SA`; compatible ligand union
  `A C Cl F HD N NA OA S SA` (ten affinity maps, below the reported limit).
- 283 selected rows, 282 prepared, 281 compatible, 2 explicitly incompatible.
- AutoGrid exit code 0 in 12.31 s with `Successful Completion` logged; total
  service wall time 20.45 s including preflight over all 283 rows.
- 17 create-only artifacts totalling 16.07 MiB: ten affinity maps, the
  electrostatic and desolvation maps, the field and grid-point files, and the
  receptor copy, GPF, and GLG retained as evidence.

These intervals, realized dimensions, atom-type union, incompatible rows, and
total evidence size match the independently recorded Phase 0 measurements in
`AUTODOCK4_PHASE0_WINDOWS.md` exactly.

## Explicitly incompatible rows

Both remain visible in the record rather than being dropped from the campaign,
and neither had its atom types coerced:

| Row | Molecule | Reason |
| --- | --- | --- |
| 142 | Compound 143 | No completed Meeko PDBQT preparation. |
| 194 | Compound 195 | Stock AutoDock4 4.2.6 cannot parameterize Meeko macrocycle glue types `CG0`/`G0`. |

## Cache identity

Re-requesting the identical map set returned the same `map_set_id` with
`reused_existing_map_set = true` in 0.69 s rather than regenerating it, against
20.45 s for the original run.

Identity covers the receptor PDBQT hash, box, spacing, intervals, realized
dimensions, receptor and ligand atom-type unions, smoothing, dielectric, and the
AutoGrid version and executable hash. It deliberately excludes `timeout_minutes`,
which bounds how long Ankora waits rather than what AutoGrid computes.

A regression test pins the case that motivated including spacing and intervals
rather than realized dimensions alone: a 20 Å box realizes exactly 20 Å at both
0.5 Å and 0.25 Å spacing, so identity keyed on covered volume would have served
half-resolution maps in response to a fine-grid request. Removing those fields
reproduces that collision.

## Acceptance boundary

Accepted: probed AutoGrid identity and limits, grid discretization against those
real limits, GPF generation, real map generation, create-only artifact
persistence with hashes, GLG/raw evidence retention, explicit incompatible rows,
and reuse by exact scientific identity.

Not yet accepted: DPF generation, AutoDock4 CPU docking, DLG parsing and
clustering, library scheduling, redocking validation, AutoDock-GPU execution, and
any user interface for map sets. Map generation is currently a synchronous
service call; the full-protein box measured 5 min 22.88 s in Phase 0, so a
long-running box needs the asynchronous job pattern before a UI drives it.

---

# AutoDock4 Phase 2 groundwork: real DLG anchors — 2026-08-24

ADR-015 required the `.dlg` parse target to be confirmed against real output
before any parser was written. That prerequisite is now satisfied.

## Real docking run

The Phase 1 map set `ebb2a3b0-ca05-4621-bae2-90c08cce9cbc` was docked against
the real prepared ligand Compound 1
(`c5cde40c-b56d-49e3-ad64-a48e27c6e837`, atom types `NA N A HD`, `TORSDOF 0`)
using the real `autodock4.exe` 4.2.6 with `ga_run 3` and explicit seeds. The
run exited 0 and logged `Successful Completion`.

The parameter file was produced by the production `render_autodock4_dpf`, so the
renderer's exact byte output — not an approximation of it — is what AutoDock4
accepted. Both files are preserved as test fixtures
(`autodock4_real_compound1.dpf` / `.dlg`).

## Anchors confirmed in real output

| Anchor | Form | Use |
| --- | --- | --- |
| `RANKING` | `rank sub-rank run energy clusterRMSD referenceRMSD RANKING` | The machine-readable per-run record, AutoDock's documented "Grep Pattern" and the equivalent of Vina's `REMARK VINA RESULT`. |
| `CLUSTERING HISTOGRAM` | `Clus \| Lowest \| Run \| Mean \| Num \| bars` | Cluster rank, representative run, and population. The decorative `#` bars are ignored. |
| `DOCKED: ` prefix | Every pose line | Stripping the prefix recovers a standalone PDBQT `MODEL`…`ENDMDL` block. |
| `USER Run = N`, `Estimated Free Energy of Binding` | Inside each block | Ties each conformation to its run and energy. |
| `Successful Completion` | Once | Real verdict; AutoDock can exit 0 on an incomplete run. |

`FINAL DOCKED STATE` does not appear in 4.2.6 output and is not used.

Parsed result for this run: 2 clusters over 3 runs. Cluster 1 holds runs 3 and 2
at -3.40 kcal/mol (cluster RMSD 0.00 and 0.11 Å); cluster 2 holds run 1 at
-3.16 kcal/mol. Pose energies agree with the independent ranking table, and the
parser rejects a log whose ranking and conformations describe different runs.

## Acceptance boundary

Accepted: the DPF renderer's real acceptance by AutoDock4, and cluster-native
parsing of real DLG output.

Not yet accepted: no docking job service, store, API, or UI exists. Nothing runs
AutoDock4 through Ankora yet; this is the contract those will be built on.

---

# Asynchronous map generation — 2026-08-24

Map generation was synchronous, which the Phase 1 record flagged as the blocker
for any UI: the full-protein box takes 5 min 22.88 s. It now runs as a
cancellable background job following the pattern the Vina adapter established.

## Design

Validation stays synchronous. An unusable request fails immediately with a
structured error instead of becoming a queued job that could never succeed, and
an identical prior map set returns as an already-completed job without running
AutoGrid at all.

Progress lives in a separate mutable `AutoGridMapJobRecord`, written atomically
so a poll landing mid-update never reads a torn file. The immutable
`AutoGridMapSetRecord` is still written exactly once, at the end. That
separation is what makes cancellation safe: the store treats a directory
without `record.json` as an incomplete run, so an abandoned job can never be
found by identity lookup and served as a usable map set.

AutoGrid runs one at a time. It is memory and CPU heavy and a campaign needs one
map set at a time, so runs serialize rather than competing.

## Real cancellation

The full-protein box `02d298cd-82a3-42ad-b6fa-358badec0502` was started against
the real `autogrid4.exe`, allowed to run for 20 s, then canceled.

| | |
| --- | --- |
| Queued (synchronous validation) | 0.56 s |
| Status while running | `running` / `generating_maps`, intervals `158 × 228 × 184` |
| Terminal state after cancel | `canceled`, 21.22 s total against 5 min 22.88 s uninterrupted |
| Published map set | none (`map_set_id` is null) |
| Orphan `autogrid4.exe` processes | none — the whole process tree is killed |
| Evidence retained | 17 partial files, 19.89 MiB, with no `record.json` |
| Identity cached afterwards | no — a later request regenerates |

## Known consideration

A canceled run's partial maps are kept deliberately as evidence and are
referenced by the job record, so they are not orphaned silently. They are also
not small: a canceled full-protein run can leave hundreds of megabytes. There is
no purge surface yet, so accumulated abandoned runs are currently the
scientist's to remove.

## Acceptance boundary

Accepted: asynchronous generation, polling, cancellation with process-tree
termination, structured failure and timeout evidence, and the guarantee that a
canceled or failed run is never reusable as a map set.

Not yet accepted: no frontend consumes these endpoints, and no AutoDock4 docking
job service exists.

---

# AutoDock4 CPU docking job service — 2026-08-24

Phase 2's docking service now runs AutoDock4 through Ankora. It consumes an
already-generated immutable map set rather than producing one, so grid
generation and docking stay separate explicit decisions.

## Real end-to-end run

Docked the real prepared ligand Compound 1 against the real Phase 1 map set
`ebb2a3b0-ca05-4621-bae2-90c08cce9cbc` through the production service and the
real `autodock4.exe` 4.2.6, with `ga_runs=5` and explicit seeds.

| | |
| --- | --- |
| Job | `7d1ea451-aebd-4099-a4f1-94857e0d7bd8` |
| Queued (synchronous validation) | 0.05 s |
| Terminal | `completed` after 5.61 s; AutoDock ran 5.16 s, exit 0, `Successful Completion` |
| Probed limits | 32 torsions, 2048 atoms, 16 maps |
| Ligand | 10 atoms, `TORSDOF 0`, types `NA N A HD` |
| Clusters | 2 over 5 runs — rank 1 at −3.40 kcal/mol (runs 3, 2), rank 2 at −3.17/−3.16 (runs 4, 1, 5) |
| Poses | 5 create-only PDBQT artifacts, each hashed, each opening with `MODEL` |

Cluster membership, per-run energies, and both RMSDs come from AutoDock's own
`RANKING` and `CLUSTERING HISTOGRAM` records, never from console text.

## Design decisions

Maps are hard-linked into the job directory, not copied. A map set is tens to
hundreds of megabytes and AutoDock only reads it, so a link costs no disk and
cannot alter the immutable original; copying is the fallback when a link is
impossible, such as across volumes.

The ligand's atom types are checked against the map set's affinity maps before
AutoDock is launched. An uncovered type is a decision the scientist must resolve
by generating a map set that includes it, not a cryptic tool failure.

The ligand is also checked against the limits AutoDock reports for itself
(torsions, atoms, maps) rather than against hardcoded values.

Results stay cluster-native. Cluster population is evidence of reproducibility —
a large tight cluster means the search kept finding the same solution — so it is
preserved rather than flattened into a Vina-shaped ranked pose list. AutoDock4
energies are never merged with Vina scores into a consensus number.

## Acceptance boundary

Accepted: single-ligand AutoDock4 CPU docking through Ankora, with probed
limits, map-coverage preflight, cancellation, structured failure evidence,
cluster-native results, and create-only pose artifacts.

Not yet accepted: no frontend consumes any of this, there is no library/batch
scheduling across ligands, no redocking validation, and no side-by-side
Vina/AutoDock4 comparison surface.

---

# AutoDock4 library campaigns: real parallel speedup — 2026-08-24

## Why per-ligand, not per-run

`autodock4.exe` 4.2.6 reports `OpenMP multiprocessor support (_OPENMP): no`. One
process uses exactly one core, so a single docking job leaves 15 of this
machine's 16 logical processors idle and there is no thread count to tune.

Measured cost drivers for the real RV2 ligand (30 atoms, `TORSDOF 6`) against
the real map set: cost is linear in both runs and evaluations, at roughly
26 s per run at 2,500,000 evaluations.

| configuration | wall time | best energy |
| --- | --- | --- |
| 10 runs × 2,500,000 evals | 264.5 s | −4.96 kcal/mol |
| 10 runs × 500,000 evals | 46.4 s | −4.47 kcal/mol |
| 10 runs × 250,000 evals | 28.9 s | −4.17 kcal/mol |

Cutting evaluations is therefore **not** free speed — it degrades the result, so
it stays the scientist's explicit parameter rather than a silent optimization.

The independent GA runs inside one job could also be split across processes, but
AutoDock clusters those runs at the end of a single process; splitting them would
force Ankora to recompute the clustering itself. Parallelising per ligand instead
keeps every molecule's clusters exactly the ones AutoDock produced.

## Real campaign measurements

The full applied 283-molecule selection, 2 runs × 250,000 evaluations each,
against the shared map set `ebb2a3b0-ca05-4621-bae2-90c08cce9cbc`:

| parallel ligands | wall time | speedup | docked | failed | best energy |
| --- | --- | --- | --- | --- | --- |
| 1 | 1138.4 s | 1.0× | 281 | 2 | −5.15 |
| 8 | 219.1 s | **5.2×** | 281 | 2 | −5.15 |
| 15 | 194.9 s | 5.8× | 281 | 2 | −5.15 |

The best energy and the succeeded/failed counts are identical across all three,
which is the point: scheduling changed, science did not. The two failures are the
expected ones — Compound 143 has no PDBQT and Compound 195 carries Meeko
`CG0`/`G0` glue types.

Scaling is sublinear and flattens early: 8 workers reach 5.2× rather than 8×, and
nearly doubling to 15 adds only 12%. Eight is close to the useful ceiling on this
machine, so more workers mostly add contention.

## Shared maps cost no disk

Each molecule's job directory needs the maps beside its relative filenames. They
are hard-linked rather than copied: the sampled `receptor.C.map` inode carries
845 links across the map set and every batch ligand directory, so the 4.21 GiB
that a file listing reports for one campaign is a single physical 1.32 MiB map
per atom type.

## Acceptance boundary

Accepted: per-ligand parallel campaigns with bounded workers, per-molecule
AutoDock clustering, isolated failures, progress polling, cancellation, and
create-only poses under each molecule.

Not yet accepted: no frontend consumes the campaign endpoints, and per-run
parallelism inside one molecule remains deliberately unimplemented.
