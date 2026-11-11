# ADR-028: GNINA `CNN_VS` Hit Prioritization, `refinement` Mode, and Built-In Default Ensembles on Linux

- **Status:** Accepted
- **Date:** 2026-11-11
- **Extends:** `ADR-027` (`ADR-027-linux-gnina.md`)
- **Scope:** Linux science runtime (`gnina_job`, `gnina_screening`, `ResultCatalogService`, `CampaignExportService`, `MethodsReportService`, `ResourceArbiter`, and Desktop GNINA/Results surfaces). Windows-native scientific execution remains unchanged.

## Context

`ADR-027` integrated GNINA `1.3.3` (`master:6fe1ce2`, official standalone x86-64 Linux binary SHA-256 `3340c1f49cd3c7c84d8699182a1c6af13c7fa2a22448d1204640446106f72172`) under a deliberately narrow initial slice: `cnn_scoring = "rescore"`, single built-in model `cnn_model = "dense_1_3"`, prepared `.pdbqt` inputs with `--addH 0 --stripH 0`, and descending `CNNscore` ordering.

Now that GNINA single-ligand docking, multi-ligand virtual screening (`gnina_screening`), `Results` catalog projection, `Methods` reporting, portable `Export` bundles, startup interruption recovery, and recoverable `Trash` are operational and verified on Linux, two scientifically important capabilities deferred by `ADR-027` are ready to be introduced:

1. **`CNN_VS` (`CNNscore × CNNaffinity`) virtual-screening hit prioritization** (McNutt et al., *J. Cheminform.* 2021, `10.1186/s13321-021-00522-2`), which resolves top-end `CNNscore` saturation (`~0.98–1.00`) across multi-ligand screening campaigns by weighting pose confidence by predicted affinity (`pK`), while keeping within-ligand pose ranking (`mode = 1..N`) strictly ordered by `CNNscore`.
2. **CNN gradient local optimization (`cnn_scoring = "refinement"`) and built-in default CNN ensembles**, enabling poses to be locally refined against combined 3D CNN and empirical gradients and scored by GNINA's multi-model ensembles rather than a single network alone.

Before locking this contract, Ankora executed a predeclared empirical probe (`scripts/validate_linux_gnina_cnn_modes.py`, documented in `docs/validation/LINUX_GNINA_CNN_MODES.md`) against the pinned GNINA `1.3.3` binary on `1HSG/MK1`. That probe established five ground-truth constraints:

1. **CLI Ensemble Selectors in GNINA `1.3.3`:** Passing `--cnn default` fails closed (`exit_code = 1`, `Usage error: Invalid model name: default`). Inspection of `CNNTorchScorer` in the `1.3.3` binary together with `--score_only` mathematical verification (`abs_diff < 7e-6` on `CNNscore`, `CNNaffinity`, and `CNNvariance`) proved that:
   - **Omitting `--cnn`** invokes GNINA 1.3's built-in **3-model** knowledge-distilled default ensemble: `("dense_1_3", "dense_1_3_PT_KD_3", "crossdock_default2018_KD_4")`.
   - **Passing `--cnn default1.0`** invokes GNINA 1.0's built-in **5-model** ensemble: `("dense", "general_default2018_3", "dense_3", "crossdock_default2018", "redock_default2018_2")`.
2. **PDBQT Score Tag Inventory:** When docking prepared `.pdbqt` ligands (`--addH 0 --stripH 0`), GNINA `1.3.3` emits only `REMARK minimizedAffinity`, `REMARK CNNscore`, and `REMARK CNNaffinity` per `MODEL` block (and only those three SDF properties when `--out .sdf` converts a PDBQT torsion tree). Neither `REMARK CNN_VS` nor `REMARK CNNaffinity_variance` is emitted in PDBQT output.
3. **Coupling of `minimizedAffinity` Under `refinement`:** Under `cnn_scoring = "refinement"`, GNINA optimizes coordinates using combined CNN and empirical gradients and evaluates the empirical Vina term at the resulting CNN-refined geometry. On `1HSG/MK1` (`cuda_refinement_dense_1_3_pdbqt`), top-ranked poses with `CNNscore = 0.9807` and `CNNaffinity = 8.17 pK` recorded `minimizedAffinity = +4.14 kcal/mol` (and up to `+28.14 kcal/mol` in `default_1_3_ensemble` lower modes) because CNN-preferred closer interatomic contacts cross Vina's hard steric repulsion wall. Under `refinement`, `minimizedAffinity` is therefore **not** an independent empirical energy check.
4. **CUDA vs CPU Scaling:** On `1HSG/MK1` (`exhaustiveness = 4, num_modes = 5`), CUDA `rescore` completed in `26.1 s` (`dense_1_3`) to `27.7 s` (`default1.0`), and CUDA `refinement` completed in `133.6 s` (`5.1×`, `dense_1_3`), `294.1 s` (`11.3×`, `default_1_3_ensemble`), and `431.1 s` (`16.5×`, `default1.0`) while preserving exact Meeko ligand topology and stereochemistry. By contrast, CPU-only `refinement` (`--no_gpu --cpu 4`) exceeded `600 s` on a single ligand even at `exhaustiveness = 2`.
5. **WSL2 / Linux VRAM Telemetry:** Under WSL2 WDDM (`NVIDIA GeForce RTX 5050 Laptop GPU`), per-process `nvidia-smi --query-compute-apps=used_gpu_memory` reports `[N/A]`, whereas device-level `nvidia-smi --query-gpu=memory.total,memory.used,memory.free --format=csv,noheader,nounits` accurately reports total and free MiB (`8151 MiB` total, `+151` to `+255 MiB` peak delta per GNINA CUDA process).

## Decision

### 1. `CNN_VS` Persistence, Provenance, and Pose Ordering

- `GninaPoseResult` adds:
  - `cnn_vs: float | None = Field(default=None, allow_inf_nan=False)`
  - `cnn_vs_source: Literal["engine_emitted", "derived_from_recorded_axes"] | None = None`
  - `cnn_affinity_variance: float | None = Field(default=None, ge=0, allow_inf_nan=False)`
- Model validation enforces `(cnn_vs is None) == (cnn_vs_source is None)`.
- `parse_gnina_pdbqt` accepts optional `REMARK CNN_VS` and `REMARK CNNaffinity_variance` if emitted by a future or custom GNINA build while still requiring `{"minimizedAffinity", "CNNscore", "CNNaffinity"}` on every `MODEL`.
- At job publication (`GninaDockingService`), if raw parsing found `REMARK CNN_VS`, `cnn_vs` is persisted with `cnn_vs_source = "engine_emitted"`; otherwise `cnn_vs = pose.cnn_score * pose.cnn_affinity` is persisted with `cnn_vs_source = "derived_from_recorded_axes"`. `cnn_affinity_variance` is persisted only when emitted by the binary and remains `None` otherwise; Ankora never fabricates dispersion estimates.
- Historical `record.json` files created before `ADR-028` deserialize cleanly with `cnn_vs = None, cnn_vs_source = None, cnn_affinity_variance = None` and are **never** mutated on disk.
- Within-ligand pose ordering (`mode = 1..N`) remains strictly descending `CNNscore` (`guard_pose_publication`).

### 2. Per-Campaign `hit_ranking_metric` and Non-Positive `CNNaffinity` Sign Guard

- `GninaScreeningRequest` and `GninaScreeningCampaignRecord` add:
  - `hit_ranking_metric: Literal["cnn_score", "cnn_vs"] = "cnn_score"`
- Defaulting `hit_ranking_metric` to `"cnn_score"` guarantees that pre-existing `gnina_screening` records load and export in identical rank order without retroactive alteration.
- When `hit_ranking_metric == "cnn_vs"`, between-ligand prioritization across `ResultCatalogService` (`best_molecule`, `primary_cnn_vs`, `list_compounds`), `CampaignExportService` (`results.csv` `rank` and `manifest.json` `table.ranking_metric`), `MethodsReportService`, `GninaScreeningWorkspace`, and `ResultsWorkspace` ranks completed molecules by descending mode-1 `cnn_vs` (breaking exact ties by applied `selection_order`).
- `CampaignExportService` increments `ankora_export_format` from `3` to `4` and adds `gnina_cnn_vs`, `gnina_cnn_vs_source`, and `gnina_cnn_affinity_variance` columns to both `_HEADER_GNINA_POSES` and `_HEADER_GNINA_SCREENING` (blank when `None` on historical pre-`ADR-028` records, while `_verify_gnina_source` verifies `cnn_vs` against `cnn_score * cnn_affinity` or raw `REMARK CNN_VS` whenever `pose.cnn_vs is not None`).
- **Sign-ambiguity guard:** Because `CNN_VS = CNNscore × CNNaffinity` becomes negative when `CNNaffinity < 0` (`K_d > 1 M`) and inverts `CNNscore` monotonicity among negative-pK decoys (e.g., `0.10 × (-1.0) = -0.10` ranks above `0.90 × (-1.0) = -0.90`), `GninaScreeningStore.finalize_campaign` inspects verified mode-1 poses of completed entries whenever `hit_ranking_metric == "cnn_vs"`. If one or more completed molecules have `cnn_affinity <= 0`, it appends a `StructuredWarning` (`code = "GNINA_CNN_VS_NONPOSITIVE_AFFINITY"`) to the terminal campaign state in `campaign_state.sqlite3` (never rewriting `record.json`). This warning is surfaced across the Screening UI, Results Catalog, Methods report, and Export `README.txt` / `manifest.json`.

### 3. `cnn_scoring = "refinement"`, Built-In Ensembles, and Model Provenance

- `GninaDockingParameters` widens:
  - `cnn_scoring: Literal["rescore", "refinement"] = "rescore"`
  - `cnn_model: Literal["dense_1_3", "default_1_3_ensemble", "default1.0"] = "dense_1_3"`
- `build_gnina_arguments`:
  - Passes `["--cnn_scoring", parameters.cnn_scoring]`.
  - Omits `--cnn` when `parameters.cnn_model == "default_1_3_ensemble"` so GNINA `1.3.3` loads its built-in 3-model default ensemble without triggering `Invalid model name: default`.
  - Passes `["--cnn", parameters.cnn_model]` for `"dense_1_3"` and `"default1.0"`.
- **Fail-closed CUDA requirement for `refinement`:** `GninaDockingParameters` rejects `compute == "cpu"` when `cnn_scoring == "refinement"` (`ValueError` / HTTP 422). Ankora never silently downgrades `refinement` to `rescore` and never switches `cpu` to `cuda`.
- **Minimum per-job timeout floor & campaign duration warning:** `GninaDockingParameters` requires `timeout_minutes >= 10` when `cnn_scoring == "refinement"`. `admit_screening` records a `StructuredWarning` (`code = "GNINA_SCREENING_REFINEMENT_DURATION_BUDGET"`) when admitting a `gnina_screening` campaign with `cnn_scoring == "refinement"` so the expected multi-minute per-ligand wall-clock budget is explicit in campaign provenance.
- **Explicit ensemble member provenance (`GninaCnnModelIdentity`):** `GninaJobRecord` adds `cnn_model_identity: GninaCnnModelIdentity | None = None` recording:
  - `selector`: `"dense_1_3" | "default_1_3_ensemble" | "default1.0"`
  - `cli_argument`: `"dense_1_3" | None | "default1.0"`
  - `member_names`: exact tuple of built-in Torch models evaluated (`("dense_1_3",)`, `("dense_1_3", "dense_1_3_PT_KD_3", "crossdock_default2018_KD_4")`, or `("dense", "general_default2018_3", "dense_3", "crossdock_default2018", "redock_default2018_2")`)
  - `member_count`: `1 | 3 | 5`
  Membership resolution is pinned fail-closed to the verified GNINA `1.3.3` binary SHA-256 (`3340c1f49cd3c7c84d8699182a1c6af13c7fa2a22448d1204640446106f72172`) so unverified binaries cannot claim unverified built-in ensemble members.

### 4. VRAM Resource Arbiter Axis (`gpu_memory_bytes`)

- `ResourceClaim` and `ResourceAllocation` add `gpu_memory_bytes: int = Field(default=0, ge=0)`.
- `ResourceSchedulerSnapshot` adds `gpu_memory_total_bytes: int | None = None`, `gpu_memory_reserve_bytes: int = Field(default=0, ge=0)`, and `gpu_memory_reserved_bytes: int = Field(default=0, ge=0)`.
- `ResourceArbiter` discovers device VRAM capacity via `nvidia-smi --query-gpu=memory.total,memory.free --format=csv,noheader,nounits` when an unambiguous single NVIDIA GPU is present (`gpu_memory_reserve_bytes = 512 MiB` when total VRAM `>= 2 GiB`).
- When `claim.gpu_memory_bytes > 0` and `gpu_memory_total_bytes` is known, `ResourceArbiter.validate` rejects claims exceeding usable VRAM with `RESOURCE_REQUEST_EXCEEDS_CAPACITY` (`resources.gpu_memory_bytes`), and `_fits` gates concurrent GPU allocations by both `gpu_slots` and `gpu_memory_bytes`.
- Claims with `gpu_memory_bytes == 0` (all Vina, AutoGrid, AutoDock4, AutoDock-GPU, and CPU GNINA workloads) bypass VRAM capacity checks completely, preserving 100% compatibility on Windows and CPU-only hosts.
- GNINA resource claims remain `2.0 GiB` host RAM on `rescore + dense_1_3` for backward compatibility, increase host RAM to `2.5 GiB` for ensemble or `refinement` runs, and claim `1.0 GiB` (`rescore + dense_1_3`), `1.5 GiB` (`rescore` ensembles or `refinement + dense_1_3`), or `2.0 GiB` (`refinement` ensembles) of `gpu_memory_bytes` on CUDA.

### 5. Scientific Reporting of `minimizedAffinity` Under `refinement`

- Under `cnn_scoring == "rescore"`, `Methods` and `Export` continue to describe `minimizedAffinity` as the empirical energy of empirical-minimized poses subsequently rescored by the CNN.
- Under `cnn_scoring == "refinement"`, `MethodsReportService`, `CampaignExportService` (`manifest.json` and `README.txt`), `GninaWorkspace`, and `GninaScreeningWorkspace` state explicitly that pose coordinates were optimized against combined 3D CNN and empirical gradients, so `minimizedAffinity` was evaluated on CNN-refined geometry (where closer CNN-favored contacts may yield higher or positive empirical energies in kcal/mol) and is **not** an independent empirical energy check.
- `Methods` and `Export` name all recorded `cnn_model_identity.member_names` rather than summarizing an ensemble only by its CLI alias.

## Non-Goals

- Custom user-supplied `.pt` / `.model` weight files (`--cnn_model`) remain out of scope.
- `cnn_scoring` modes `"none"`, `"metrorescore"`, `"metrorefine"`, and `"all"` remain out of scope until separately benchmarked.
- Cross-engine consensus scoring or pooling GNINA `CNNscore`, `CNNaffinity`, `CNN_VS`, or `minimizedAffinity` with AutoDock Vina or AutoDock4 scores remains strictly forbidden under `DOCKING_POLICY.md`.
