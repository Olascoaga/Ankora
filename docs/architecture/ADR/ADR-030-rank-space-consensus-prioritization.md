# ADR-030: Rank-Space Consensus Prioritization (`PC-Q`, `PC-ECR`, `PC-L2`)

- **Status:** Proposed (M0 Frozen Contract for v0.2)
- **Date:** 2026-11-18
- **Baseline:** frozen `v0.1.0-beta.2` commit `36f1c0e9b11adb579920437d23298472ac948bcf`
- **Amends:** [`DOCKING_POLICY.md`](../../scientific/DOCKING_POLICY.md) — specifically the *Cross-engine non-pooling and rank-agreement rules* section, and **only** to admit explicit, opt-in **rank-space / quantile** consensus artifacts. Raw engine scores remain strictly separate result models and **native units are never averaged, normalized, rescaled, or pooled**.
- **Extends:** `ADR-015` (AutoDock4 scoring family), `ADR-027` / `ADR-028` (Linux GNINA family), `ADR-011` (stale derivative propagation)
- **Installer size delta over frozen baselines:** `0` bytes (no new executables, no new Python distributions; `scipy==1.18.0` and `numpy==2.5.2` are already pinned in both `requirements/windows-py312.in` and `requirements/linux-py312.in`)
- **Scope:** Library-scale hit prioritization across scoring families within a single project that already shares one prepared receptor, one finalized binding site, and one applied selection manifest. Single-ligand job surfaces, per-engine pose ordering, and all existing per-engine result models are unchanged.

## Context

At the frozen baseline, `DOCKING_POLICY.md` states that Ankora "**never** averages, normalizes, or merges scores across scoring functions into a combined consensus number." That rule exists for a sound reason: AutoDock Vina `1.2.7` and AutoDock4 `4.2.6` report `kcal/mol` on *different* empirical functional forms with different reference states, AutoDock-GPU `1.6` is an accelerator of the AutoDock4 family rather than an independent function, and GNINA `1.3.3` reports a dimensionless `CNNscore`, a neural `pK` (`CNNaffinity`), and the `CNN_VS` product. Averaging those native quantities would manufacture a number with no defined unit and no defined reference state, and `ADR-028` already forbade exactly that.

The rule as written, however, also forecloses a distinct and scientifically defensible construction: discarding the native units entirely and combining only **within-family rank positions** measured against a fixed reference population. Rank-space consensus does not assert that one family's `kcal/mol` is commensurate with another's; it asserts only that "this compound sits in the top `x%` of *this* family's own distribution on *this* receptor and *this* box," which is a statement each family can make independently about itself. Exponential consensus ranking of this kind is an established primary-source method (Palacio-Rodríguez *et al.*, *Sci. Rep.* 2019, `10.1038/s41598-019-41594-3`).

Three further constraints shape the contract:

1. **Platform asymmetry.** Windows 11 x64 ships two independent scoring families (Vina-family empirical and AutoDock4-family empirical). Linux `x86_64` additionally ships the GNINA neural family. A consensus definition that silently changes membership per platform would make Windows and Linux rankings incomparable while presenting them under one label.
2. **Flexibility-dependent order-statistic bias.** A consensus built from each compound's *best* pose is a best-of-`K` order statistic. Its expectation grows with `K`, and `K` grows with rotatable-bond count, so an uncapped construction systematically rewards flexible compounds for being flexible rather than for being concordant.
3. **Selection-bias risk.** Any fitted consensus weighting evaluated on the same data that selected it reports an optimistically biased performance estimate (Cawley & Talbot, *JMLR* 11, 2010). A fitted variant therefore cannot be promoted on in-sample evidence.

## Decision

### 0. Exact boundary of the amendment to `DOCKING_POLICY.md`

The cross-engine non-pooling rule is narrowed, not withdrawn. After this ADR:

- Raw per-family observations (`Vina`/`Vinardo` `kcal/mol`, AutoDock4 cluster energies, GNINA `CNNscore` / `CNNaffinity` / `CNN_VS` / `minimizedAffinity`) remain **separate, independently stored, independently displayed result models**. No native-unit arithmetic crosses a family boundary — ever.
- The **only** permitted cross-family aggregate artifacts are the explicitly opt-in, dimensionless rank-space quantities defined below (`PC-Q`, `PC-ECR`, `PC-L2`), which are computed from **rank positions against a hash-locked reference panel**, never from native scores.
- Consensus is **off by default**. Absent an explicit scientist request carrying a `RankingMethod`, Ankora produces exactly the per-engine results it produces at the frozen baseline.
- No consensus quantity is ever labelled, exported, or reported as an experimental affinity, a predicted affinity, or a probability of activity. `PC-Q` is a concordance coordinate, not a measurement.
- The existing Spearman `rho` / Top-`N` overlap comparison between Vina and AutoDock4 CPU campaigns (`EngineComparisonService`) is unaffected and remains a *comparison*, not a merge.

### 1. `PC-Q` — Pose-Concordant Quantile Consensus (`0`–`100`, dimensionless)

`PC-Q` is evaluated **Pose-First, Molecule-Second**. Every scoring function contributes at one fixed 3D geometry, the per-pose consensus value is completed there, and **only then** is the result reduced to the parent compound. This ordering is load-bearing and is not an implementation detail: reducing each function to its *own* most favorable pose before combining would merge observations taken at different geometries, so two functions favoring poses `7 Å` apart could contribute to a single number describing no physical complex that was ever evaluated.

For each **parent compound** `i`:

1. **Retained medoids.** Take the parent's retained cluster medoids `c` (at most `K_max` per `E2`, from complete-linkage clustering at `<= 2.0 Å` per `E3`).
2. **Same-geometry evaluation.** Evaluate **every** admitted scoring function `j` at that **same** 3D medoid geometry via `--score_only`, in the shared receptor/box context verified by `E4`. No function re-docks, re-minimizes, or re-poses the medoid; `s_icj` is function `j`'s value for parent `i` at medoid `c`.
3. **Per-function parent-weighted midrank quantile.** Map the oriented value `d_j · s_icj` to `q_j(d_j s_icj) ∈ [0, 1]` against the hash-locked `ReferencePanelArtifact` (`E1`), where `d_j = ±1` is the fixed orientation constant of function `j` (`d_j = -1` for ascending `kcal/mol` empirical functions, `d_j = +1` for descending GNINA neural outputs per `DOCKING_POLICY.md`), chosen so that larger `d_j · s_icj` is always more favorable and `q_j = 1` is the most favorable end of the panel.

   Each panel parent `l` contributes **total weight `1`**, distributed evenly across its own `K_l` retained medoids, so the quantile is the parent-weighted midrank empirical CDF:

   ```text
   q_j(x) = (1 / N_R) · Σ_l (1 / K_l) · Σ_{k=1..K_l} ( 1[d_j·s_lkj < x] + ½ · 1[d_j·s_lkj = x] )
   ```

   over the `N_R` parents of the reference panel. The `½` term is the midrank tie correction: ties receive the average of their tied rank positions, so ties neither create nor destroy ordering information. The `1/K_l` factor is what prevents a parent carrying many retained medoids from reshaping the distribution against which every other compound is measured.
4. **Within-block aggregation.** Aggregate inside each methodological family block `b`:

   ```text
   Q_icb = Σ_{j ∈ b} a_bj · q_j(d_j s_icj),   with   Σ_{j ∈ b} a_bj = 1
   ```

   Within the `vina_vinardo` block, `a = (1/2, 1/2)` when both `vina` and `vinardo` are enabled, and `a = 1` for a single enabled function. Averaging *within* the block before weighting *across* blocks is what guarantees that adding `vinardo` never double-votes the Vina-family empirical form against `autodock4` or `gnina_neural`: the block's total vote is fixed by `W_b` regardless of how many of its functions ran.
5. **Per-pose consensus.** Combine blocks with the fixed, published weights of the selected variant:

   ```text
   S_ic = 100 · Σ_b W_b · Q_icb
   ```

   | Variant id | Blocks and weights `W_b` | Platforms |
   | --- | --- | --- |
   | `pcq-core-v1` | `W = (1/2, 1/2)` over (`vina_vinardo`, `autodock4`) | Windows 11 x64 **and** Linux `x86_64` |
   | `pcq-neural-v1` | `W = (1/3, 1/3, 1/3)` over (`vina_vinardo`, `autodock4`, `gnina_neural`) | Linux `x86_64` only |

6. **Molecule-second reduction.** Only now reduce to the parent compound:

   ```text
   PC-Q(i) = S_i = max_{c <= K_max} S_ic
   ```

   The selected medoid `c* = argmax_c S_ic` is **recorded**, so the reported parent value always points at the one concrete pose that produced it. Exact ties in `S_ic` are broken by the `E3` medoid tie-break rule (lowest canonical coordinate hash), keeping the selection bitwise reproducible.

- The `vina_vinardo` block holds both scoring functions of the same engine, which is why they share one block rather than occupying two: they are two scoring functions of one engine, not two independent methodological families. Which functions were enabled is recorded explicitly in provenance. *(Vinardo is not implemented at the frozen baseline; its availability is a separate v0.2 implementation gate and adds `0` bytes, being a `--scoring` selection of the already-shipped AutoDock Vina `1.2.7` executable.)*
- `pcq-neural-v1` runs **always compute and record `pcq-core-v1` alongside** on Linux, so every Linux consensus artifact carries a Windows-comparable core value. A `pcq-neural-v1` value is never compared against a `pcq-core-v1` value from another run.
- The weights are **fixed constants of the variant id**, not tunable parameters. Changing a weight requires a new variant id and a new ADR; it must never be an adjustable control in the UI.
- Equal weighting is a declared prior of ignorance, not an empirical claim that the families are equally informative. Any evidence-driven reweighting lives exclusively in `PC-L2`.

### 2. `PC-ECR` — Exponential Consensus Ranking (`tau = 0.05`, separate scale and column)

`PC-ECR` aggregates the same per-family rank positions through the exponential consensus kernel (`10.1038/s41598-019-41594-3`) with a frozen `tau = 0.05`, i.e. a decay constant of `sigma = tau × N_panel` rank positions, which concentrates the aggregate on each family's top `~5%` instead of weighting the whole rank range uniformly as `PC-Q` does.

- `tau` is **frozen at `0.05`** for v0.2 and is not a user control.
- `PC-ECR` is stored and displayed in its **own column on its own scale** (`E5`). It is never averaged with `PC-Q`, never rescaled onto `0`–`100`, and never presented as a refinement or correction of `PC-Q`. They are two aggregations with two different sensitivity profiles, reported side by side.
- `PC-ECR` and `PC-Q` disagreeing on an ordering is a real and reportable scientific observation, not a defect to be resolved by picking a winner.

### 3. `PC-L2` — Strictly convex non-negative L2 logistic calibration (gated, not shipped by default)

`PC-L2` is the only *fitted* consensus variant and is **not promoted by default**.

- **Inputs:** the per-function quantile vector `q_j(d_j s_ic*j)` of parent `i` at its **frozen `PC-Q`-selected medoid `c*`** (§1). `PC-L2` never re-docks, re-samples, re-clusters, or re-selects poses; it only reweights quantiles already computed and hash-recorded under `E1`–`E4`, and it inherits the Pose-First geometry rather than choosing its own.
- **Model:** logistic regression of the recorded activity label on that quantile vector, with **non-negativity constraints on every family coefficient** (so no family can enter with a sign that inverts its own documented orientation) and an **L2 penalty**, making the penalized objective **strictly convex** over the non-negative orthant. The optimum is therefore unique and the fit is deterministic and reproducible from the recorded inputs and seed-free solver configuration.
- **Solver:** `scipy.optimize` (already pinned, `scipy==1.18.0`, both platforms), bounded minimization over `[0, ∞)` coefficients. Convergence status, iteration count, and final objective are recorded; non-convergence fails closed and produces no `PC-L2` column.
- **Promotion gate (all conditions required):** `PC-L2` may be promoted over the unfitted variants **only** if a **paired parent bootstrap** shows `Δ BEDROC_20 > 0` against **every** admitted single engine on the **locked Confirmation split**, under the out-of-sample discipline, `1-SE` parsimony rule, and mandatory-null-publication requirements specified in [`ADR-031`](ADR-031-external-benchmark-boundary.md). Fitting and evaluating on the same data is explicitly forbidden (Cawley & Talbot, *JMLR* 11, 2010).
- If the gate is not met, the recorded verdict is *"Insufficient evidence to prefer over baseline"* and `PC-L2` remains unpromoted. That outcome is published, not discarded.

### 4. Invariants `E1`–`E6` (all fail-closed)

#### `E1` — Hash-locked reference panel (`ReferencePanelArtifact`)

- Every quantile is defined **only** relative to an immutable `ReferencePanelArtifact` identified by `reference_panel_sha256`, covering the panel's member compound identities, the per-family values, the receptor/box context, and the tool versions and executable SHA-256 digests that produced it.
- Quantiles are **parent-weighted midranks**: each parent compound contributes exactly weight `1` to the empirical panel distribution regardless of how many microstates, tautomers, or retained pose clusters it owns. Without this, a parent carrying many enumerated microstates would silently reshape the reference distribution against which every other compound is scored.
- `PC-Q`, `PC-ECR`, and `PC-L2` values are comparable **only** within an identical `reference_panel_sha256`. Cross-panel numeric comparison is rejected, not warned about.
- Any change to the receptor, box, selection manifest, or tool identity invalidates the panel and propagates staleness to every dependent ranking artifact per `ADR-011`. Panels are never silently rebuilt under a cached value.

#### `E2` — Pre-evaluation cluster cap `K_max` per parent compound

- At most `K_max` cluster representatives per parent compound enter cross-family evaluation, selected deterministically by the parent's own primary-family ordering before any cross-rescoring occurs.
- **Scientific purpose:** equalizing the best-of-`K` order statistic across compounds of differing rotatable-bond count, so a consensus value reflects concordance rather than conformational enumeration depth.
- **Engineering purpose:** bounding cross-rescoring subprocess calls to `K_max × |families|` per parent, keeping library-scale consensus admissible under the `ResourceArbiter` contract (`ADR-022`).
- `K_max` is an **explicit, required, recorded** field with **no silent default**. This ADR deliberately fixes no numeric value: the recommended setting must be derived from recorded `M5` validation evidence, not asserted here.

#### `E3` — Complete-linkage clustering (`<= 2.0 Å`) with deterministic medoid tie-breaking

- Pose clustering uses **complete linkage** at a `<= 2.0 Å` symmetry-aware heavy-atom RMSD threshold computed **in place, never superposed**, reusing the RMSD contract of [`REDOCKING_VALIDATION.md`](../../scientific/REDOCKING_VALIDATION.md).
- Complete linkage is chosen deliberately over single linkage because it guarantees a hard cluster **diameter** bound: every pair of poses inside a cluster is within `2.0 Å`. Single linkage permits chaining, under which a cluster "representative" can be arbitrarily far from members it nominally represents.
- The representative is the cluster **medoid**. Exact ties are broken deterministically by the lowest canonical coordinate hash, so clustering output is bitwise reproducible from identical inputs and carries no dependence on input ordering or iteration order.

#### `E4` — Fail-closed shared receptor / grid / box hash identity check

- Before **any** cross-family rescoring (`--batch --score_only` for the Vina family; the AutoDock4-family map-set path; `--score_only` for GNINA on Linux), Ankora verifies exact identity of the shared context across all admitted families: prepared receptor `.pdbqt` SHA-256, box center and size, and the AutoGrid4 map-set identity where the AutoDock4 family participates.
- Any mismatch **fails closed** with a structured error (proposed code `CONSENSUS_SHARED_CONTEXT_MISMATCH`) and produces no consensus artifact. Ankora never rescores across differing receptors, boxes, or map sets, and never "aligns" them.
- The exact cross-rescoring invocations are recorded as argument arrays with captured raw stdout/stderr. Their upstream CLI behavior is subject to a recorded **M1 Gate 0 capability probe** before implementation lands, following the `ADR-028` precedent of empirically probing CLI contracts rather than assuming them.

#### `E5` — Separate scale and column per aggregation

- `PC-Q` (`0`–`100`, dimensionless, `pcq-core-v1` / `pcq-neural-v1` variant id recorded) and `PC-ECR` (`tau = 0.05`, exponential-kernel scale) occupy **distinct columns on distinct scales** in every table, export, and report.
- No display, export, or report ever averages, blends, interpolates, or rank-merges `PC-Q` with `PC-ECR`, or either with a native engine score.
- Every consensus column is emitted with its variant id, its `reference_panel_sha256`, and its exact family membership. A consensus number without that provenance is not a publishable Ankora artifact.

#### `E6` — Two-tier `RankingArtifact` table with an invariant parent denominator

- Every ranking artifact partitions parents into exactly two tiers:
  - `full_profile` — every family required by the selected variant produced a verified observation for this parent.
  - `partial_or_unscored` — one or more required families produced no verified observation (engine-incompatible, failed, timed out, or not run).
- **Denominator invariant:** `total_parents == full_profile_count + partial_or_unscored_count`, enforced in the model, preserving the `DOCKING_POLICY.md` rule that engine-incompatible or failed molecules are retained as explicit rows and never dropped from the campaign denominator.
- Consensus values are computed **only** for `full_profile` parents. A missing family is never imputed, mean-filled, treated as neutral, or back-filled from another family.
- Each `full_profile` parent carries an **inter-family disagreement** measure `D_ic`, defined deterministically as the `W`-weighted RMS dispersion of the block aggregates about the per-pose consensus value, on the same dimensionless `0`–`100` scale:

  ```text
  D_ic = 100 · sqrt( Σ_b W_b · ( Q_icb − S_ic/100 )² )
  ```

  `D_ic` is a **per-pose** quantity, consistent with the Pose-First rule of §1: the block aggregates `Q_icb` and the consensus `S_ic` it compares are all taken at the same medoid `c`. The parent row reports `D_ic*` at the selected medoid `c*` that produced `PC-Q(i)`, so the dispersion always describes the same pose as the value it qualifies. Because `Σ_b W_b = 1` and `S_ic/100` is exactly the `W`-weighted mean of the `Q_icb`, `D_ic` is the weighted standard deviation of the block aggregates — `0` under perfect inter-block agreement and growing as the blocks disagree. A high consensus value built on strong inter-family disagreement is therefore visible rather than hidden by averaging.
- A **separate Search Convergence badge** reports per-family sampling adequacy and is **never folded into** `PC-Q`, `PC-ECR`, `PC-L2`, or `D_ic`. Concordance between families and convergence within a family are independent questions, and `ADR-018` / `ADR-019` already forbid treating purpose-labelled sampling defaults as convergence guarantees.

### 5. M0 contract surface

These invariants bind to the M0 Pydantic contract module `backend/src/ankora_backend/schemas/v02_contracts.py`, whose implementation is a separate M0 deliverable and is **not present at the frozen baseline** `36f1c0e9b11adb579920437d23298472ac948bcf`. This ADR fixes the contract surface that module must expose:

| Contract | Role under this ADR |
| --- | --- |
| `ScoringFamily` | Closed enumeration of the independent methodological family blocks (`vina_vinardo`, `autodock4`, `gnina_neural`) carrying the across-block weights `W_b`; the unit of non-pooling. |
| `ScoringFunctionId` | The exact scoring function(s) enabled within a block (e.g. `vina` and/or `vinardo` inside `vina_vinardo`), carrying the within-block weights `a_bj` that sum to `1`. |
| `RankingEntry` → per-pose fields | The per-medoid `Q_icb`, `S_ic`, and `D_ic` values plus the recorded selected medoid `c*`, so the Pose-First computation is auditable and not just its molecule-second maximum. |
| `ObservationStatus` | Per-parent, per-family observation outcome that drives the `E6` `full_profile` / `partial_or_unscored` partition. |
| `RankingMethod` | Explicit opt-in selector (`pcq-core-v1`, `pcq-neural-v1`, `PC-ECR`, gated `PC-L2`); absence means no consensus is produced. |
| `ScoreObservation` | One family's verified observation for one parent, retaining native units and provenance untouched; quantiles are derived, never written back over it. |
| `RankingEntry` | One parent row carrying its tier, per-family quantiles, consensus columns, and `D_ic`. |
| `RankingArtifact` | The hash-bound table carrying `reference_panel_sha256`, variant id, family membership, both tier counts, and the enforced denominator invariant. |

## Non-Goals

- Pooling, averaging, normalizing, or unit-converting native engine scores across families remains **forbidden** in all forms. This ADR does not relax that.
- Consensus across AutoDock4 CPU and AutoDock-GPU is meaningless and rejected: AutoDock-GPU `1.6` is an accelerator of the AutoDock4 scoring family, not an independent family.
- No consensus quantity is calibrated to, or reported as, an experimental binding affinity, a predicted affinity, or a probability of activity.
- Tunable user-facing consensus weights are explicitly out of scope; weights are constants of a published variant id.
- `tau` sweeps, alternative kernels, and consensus variants beyond the three defined here are out of scope for v0.2.
- Automatic selection among `PC-Q`, `PC-ECR`, and `PC-L2` on behalf of the scientist is out of scope; the selection is explicit and recorded.

## Primary-source references

Bibliographic fields are recorded below only where independently verifiable in this repository or unambiguous from the DOI; remaining identifiers are carried as scientist-supplied and must be expanded under the DOI-verified citation rule of [`METHODS_REPORT_POLICY.md`](../../scientific/METHODS_REPORT_POLICY.md) before they appear in any generated `Methods` output.

- McNutt *et al.*, *J. Cheminform.* 2021 — `10.1186/s13321-021-00522-2` (GNINA; already established in this repository by `ADR-028`).
- Palacio-Rodríguez *et al.*, *Sci. Rep.* 2019 — `10.1038/s41598-019-41594-3` (exponential consensus ranking; the `tau` / `sigma` kernel adopted by `PC-ECR`).
- Cawley & Talbot, *JMLR* 11, 2010 — over-fitting in model selection and the resulting selection bias in performance evaluation (the basis of the `PC-L2` promotion gate).
- `10.1186/s13321-025-00973-x` — **GNINA 1.3** (scientist-supplied), the release line whose pinned `1.3.3` build is the Linux neural family of `ADR-027` / `ADR-028`. This DOI is **not** a DockM8 reference; the external comparison-harness identifier is `PMC13613745`, carried in [`ADR-031`](ADR-031-external-benchmark-boundary.md).
  - *Verification status:* this identifier does **not** appear anywhere in the repository at the frozen baseline `36f1c0e9b11adb579920437d23298472ac948bcf`. The only GNINA DOI recorded in tracked code is `10.1186/s13321-021-00522-2` (`backend/src/ankora_backend/services/tool_citations.py`, rendered by `methods_report.py`). It is therefore carried as scientist-supplied and must be resolved against Crossref registered metadata, and added to `tool_citations.py` if it is to be rendered, before it appears in any generated `Methods` output — per the DOI-verified citation rule of [`METHODS_REPORT_POLICY.md`](../../scientific/METHODS_REPORT_POLICY.md), which requires references be resolved rather than recalled.
