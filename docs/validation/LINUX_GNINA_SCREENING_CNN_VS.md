# GNINA CUDA `CNN_VS` + `default_1_3_ensemble` screening and frozen legacy compatibility check — predeclared

## Protocol

`scripts/validate_linux_gnina_screening_cnn_vs.py` exercises per-campaign
`hit_ranking_metric="cnn_vs"` hit prioritization (`CNNscore × CNNaffinity`),
the built-in 3-model GNINA 1.3 ensemble (`cnn_model="default_1_3_ensemble"`),
Export v4 manifest/CSV integrity, and non-mutating backward compatibility with
pre-`ADR-028` screening artifacts through Ankora's real localhost HTTP API.
This is a bounded WSL2 engineering check, not native bare-metal Linux
workstation acceptance, WSLg graphical acceptance, or a prospective virtual
screening benchmark.

### Preconditions

Verify declared SHA-256 digests of the official GNINA 1.3.3 Linux binary
(`3340c1f49cd3c7c84d8699182a1c6af13c7fa2a22448d1204640446106f72172`), the
prepared `1HSG` receptor, the tracked 100-compound NCI sample
(`resources/examples/real_screening_library_100/nci_real_100.sdf`,
`bc45046a563b7d34fb823c2b35da6d70b88af05e422a9f54022453f7b68fee0d`), and the
frozen pre-`ADR-028` records `screening-api-cuda-01/evidence.json`
(`9662bd482fa2a7c93fbf22ad5b9d22dc98b4c0aa0011d4c9774e898e30c3ddac`) and
`screening-api-cuda-cancel-02/evidence.json`
(`461beaba3a75fa11a4cff711f6ca5e7e4ab9ba4ca0afd413d12b742ce57281dc`). Require
one unambiguous NVIDIA GPU at logical index `0` and zero active GPU compute
processes before launching.

### Sub-check 1: 11-compound NCI CUDA screening with `hit_ranking_metric="cnn_vs"` and `default_1_3_ensemble`

In a create-only project copy, import `nci_real_100.sdf` (`100` records), apply
the `demostracion` medicinal-chemistry filter plan (`11` eligible compounds),
generate `ETKDGv3 + MMFF94s` conformers (`seed=20261029`), prepare `Meeko`
PDBQTs, and submit `POST /api/v1/docking/gnina/screenings` with
`hit_ranking_metric="cnn_vs"`, `compute="cuda"`, `device_index=0`,
`cpu_threads=2`, `seed=20261029`, `exhaustiveness=2`, `num_modes=3`,
`cnn_scoring="rescore"`, `cnn_model="default_1_3_ensemble"`, and
`timeout_minutes=5`. Require:

1. Terminal campaign status `completed` with `(selected, succeeded, failed, canceled) == (11, 11, 0, 0)`,
   `hit_ranking_metric == "cnn_vs"`, and persisted 3-member
   `cnn_model_identity` (`["dense_1_3", "dense_1_3_PT_KD_3", "crossdock_default2018_KD_4"]`,
   `cli_argument=None`).
2. Every child `gnina_job` omits `--cnn` on the CLI, observes its live GPU
   process on the enumerated GPU UUID, executes serially without overlapping
   intervals, orders intra-ligand modes by descending `CNNscore`, persists
   `cnn_vs == cnn_score * cnn_affinity` (`cnn_vs_source == "derived_from_recorded_axes"`),
   and matches SHA-256 across all downloaded pose PDBQTs.
3. `ResultCatalogService` reports `hit_ranking_metric == "cnn_vs"`, sets
   `primary_cnn_vs` to the campaign's maximum top-pose `CNN_VS`, labels
   `compounds.value_label == "CNN_VS (higher ranks first)"`, and orders
   compound rows by `(-top_pose.cnn_vs, selection_order)`.
4. `MethodsReportService` (`GET .../methods`) produces zero gaps, cites the 3
   `default_1_3_ensemble` member networks and `--cnn` omission, states
   descending `CNN_VS` (`CNNscore × CNNaffinity`) prioritization, and contains
   zero overclaim substrings.
5. `CampaignExportService` (`POST /api/v1/exports/campaigns`) writes an Export
   v4 bundle (`ankora_export_format == 4`, `table.ranking_metric == "gnina_cnn_vs"`,
   `engine.cnn_model_identity`), orders `results.csv` by descending
   `gnina_cnn_vs` with `gnina_cnn_vs_source == "derived_from_recorded_axes"`,
   verifies every `source_files.files` digest byte-for-byte inside the ZIP, and
   releases all active work leases, GPU slots, and reserved VRAM.

### Sub-check 2: non-mutating backward compatibility on frozen `screening-api-cuda-01`

Copy `screening-api-cuda-01/data` into a separate temporary directory without
touching the frozen original. Verify that the pre-`ADR-028` campaign loads with
default `hit_ranking_metric == "cnn_score"` and `cnn_model_identity is None`,
renders `compounds.value_label == "CNN score (higher ranks first)"` in identical
descending `CNNscore` order, and exports cleanly under `ankora_export_format == 4`
with `table.ranking_metric == "gnina_cnn_score"`, `"cnn_model_identity"` absent
from `manifest.engine`, and blank `""` `gnina_cnn_vs` / `gnina_cnn_vs_source`
cells across all 11 CSV rows (confirming no unrecorded values are fabricated on
legacy records). Confirm all frozen files and `evidence.json` SHA-256 digests
remain unchanged.

## Harness alignment runs (`screening-cnn-vs-cuda-01` through `04`)

Four create-only harness iterations preceded the final clean pass; none altered
any production code or frozen file, and each retained its untouched
`evidence.json`:

- `screening-cnn-vs-cuda-01` (`337a2abab451986d9badbe5803adcf109fb9e32cf94ac3ec7552a7fdfbabb584`):
  script queried `progress["hit_ranking_metric"]` instead of
  `campaign["request"]["hit_ranking_metric"]` (`GninaScreeningProgress` carries
  lifecycle counters only).
- `screening-cnn-vs-cuda-02` (`8fcf29e5b2eaa2d8b66ab62401b51bf18de6d80fc6f0a9231a4485a8953f527d`):
  script matched ``"`CNNscore` × `CNNaffinity`"`` instead of Methods' single
  code span ``"`CNNscore × CNNaffinity`"`` and `manifest["artifacts"]` instead
  of `manifest["source_files"]["files"]`.
- `screening-cnn-vs-cuda-03` (`41402414a2494548fe37be430991f4b123305982789fdaa0b2280213ea5e7745`):
  `n.endswith("manifest.json")` matched `inputs/selection_manifest.json` before
  root `manifest.json` in the ZIP archive.
- `screening-cnn-vs-cuda-04` (`417d983255d3d16bd2e6ea39d973be60bdafb241bb7112d2af02ffe711ec40b5`):
  Sub-check 1 completed end-to-end; Sub-check 2 checked
  `"CNN pose score (higher ranks first)"` instead of Catalog's exact legacy
  label `"CNN score (higher ranks first)"`.

## Observed run: `screening-cnn-vs-cuda-05`

Both sub-checks completed cleanly on `NVIDIA GeForce RTX 5050 Laptop GPU`
(`GPU-4fec5c6f-e22d-45ac-5898-743b25fe83b6`):

- **Sub-check 1 (`CNN_VS` + `default_1_3_ensemble` CUDA screening):** All 11
  eligible NCI compounds completed serially without overlap in `81.32 s` (`33`
  verified pose PDBQTs across 11 child jobs), `--cnn` was omitted on every
  child job while persisting the 3-member `default_1_3_ensemble` identity,
  Methods produced zero gaps, and the `107`-file Export v4 ZIP archive
  (`97f3df2a5ddb54d4e4bc01887a9ea83d3f1eb61f1acb5891964f8e8bae203098`) matched
  every carried source digest byte-for-byte.
- **Empirical `CNN_VS` vs `CNNscore` rank divergence (`rank_order_differs_from_cnn_score == True`):**
  Weighting `CNNscore` by predicted `CNNaffinity` (pK) materially reordered hits
  on the real 11-compound NCI set (for example, `NCI-47` rose from 4th by
  `CNNscore` `0.7849` to 2nd by `CNN_VS` `3.3467` over `NCI-22` `3.3416` and
  `NCI-55` `3.1021`, and `NCI-68` rose from 5th by `CNNscore` `0.7057` to 4th
  by `CNN_VS` `3.1126`):

| `CNN_VS` rank | Compound | `CNN_VS` | `CNNscore` | `CNNscore` rank | `CNNaffinity` (pK) | `minimizedAffinity` (kcal/mol) |
|---:|---|---:|---:|---:|---:|---:|
| 1 | `NCI-76` | 4.3858 | 0.8244 | 1 | 5.3196 | -8.1681 |
| 2 | `NCI-47` | 3.3467 | 0.7849 | 4 | 4.2636 | -5.1052 |
| 3 | `NCI-22` | 3.3416 | 0.7941 | 2 | 4.2079 | -5.9806 |
| 4 | `NCI-68` | 3.1126 | 0.7057 | 5 | 4.4108 | -4.4161 |
| 5 | `NCI-55` | 3.1021 | 0.7898 | 3 | 3.9277 | -6.8688 |

- **Sub-check 2 (frozen legacy compatibility):** Isolated copy of
  `screening-api-cuda-01` loaded with `hit_ranking_metric == "cnn_score"`,
  preserved `"CNN score (higher ranks first)"` ordering, and exported under
  `ankora_export_format == 4` (`table.ranking_metric == "gnina_cnn_score"`,
  archive `ea1ff0f651033d9248846531ea87d2991a95dc143b551194cafd589fbad25cb8`)
  with blank `gnina_cnn_vs` and `gnina_cnn_vs_source` cells on all 11 rows.
- All source project files and frozen `screening-api-cuda-01` /
  `screening-api-cuda-cancel-02` evidence digests remained byte-identical.
  Retained create-only `screening-cnn-vs-cuda-05/evidence.json` SHA-256:
  `7058d3c2258d84e05889de79e7489a59734d9cd8f4e3dd7a61ad7d0452ad1e2d`.
