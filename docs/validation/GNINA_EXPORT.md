# GNINA portable export (single job and screening campaign)

A completed Linux GNINA single job (`gnina_job`) or multi-ligand screening
campaign (`gnina_screening`) can be exported from Results or Export as a CSV,
manifest, `README.txt`, `methods.md` report and portable ZIP.

- **Single job (`gnina_job`):** Each CSV row is one pose in the engine's
  recorded CNN order (`row = "pose"`). The export does not invent library,
  filter-run or selection columns and does not imply a virtual-screening
  campaign or assessed repeatability.
- **Screening campaign (`gnina_screening`):** Each CSV row is one selected
  molecule (`row = "molecule"`). Docked molecules are ranked `1..succeeded` by
  descending top-pose `gnina_cnn_score` with exact ties broken by applied
  selection order; preflight-refused and engine-failed molecules remain in the
  table unranked (`rank` blank) in selection order with blank score columns and
  their recorded failure codes.

In both forms, dimensionless `gnina_cnn_score` (0–1), predicted
`gnina_cnn_affinity_pk` (pK) and `gnina_minimized_affinity_kcal_mol` (kcal/mol)
remain three separate columns; none is measured affinity or evidence of
biological activity, and none shares a scale with AutoDock Vina or AutoDock4.

The single-job ZIP carries the recorded receptor, prepared ligand, conformer,
original raw poses, each published pose, execution output, job record, and
matching recorded interaction analyses, figures and redocking validations where
available. A matching crystallographic reference is included only if its
recorded identity, size and SHA-256 verify; an unavailable or altered reference
produces an explicit manifest warning.

The screening-campaign ZIP (`gnina_screening`) carries the shared prepared
receptor (`inputs/receptor.pdbqt`), pinned applied filter selection manifest
(`inputs/selection_manifest.json`), immutable creation snapshot
(`campaign/record.json`), terminal SQLite state database
(`campaign/campaign_state.sqlite3`), every verified completed child job's
prepared ligand, conformer, raw poses, logs, job record and published poses
under `jobs/<gnina_job_id>/`, any attempted failed child job's record and logs,
the rendered `methods.md` (citing McNutt et al., `10.1186/s13321-021-00522-2`),
and matching recorded M9 interaction analyses and figures.

Required source artifacts, pinned selection manifests and execution logs must
match their recorded hashes and states before any export directory is created,
otherwise export fails closed (`409 EXPORT_SOURCE_INCOMPLETE` or
`409 EXPORT_SOURCE_TAMPERED`). A digest calculated at export time is identified
as `export_time_digest_only`; it does not establish a historical hash. Raw logs
and command records may contain local paths and should be reviewed before
sharing.

Synthetic regression tests in `backend/tests/test_gnina_export.py`,
`apps/desktop/src/tests/ExportWorkspace.test.tsx` and
`apps/desktop/src/tests/ResultsWorkspace.test.tsx` cover both single-job and
multi-ligand screening source integrity, 3-axis score separation, tie-breaking
and unranked failure rows, alongside an isolated `tmp_path` verification copy of
the recorded 11-compound 7AQF/NCI WSL CUDA screening campaign
(`screening-api-cuda-01`). Predeclared single-job checks are documented in
`LINUX_GNINA_EXPORT.md` and `LINUX_GNINA_EXPORT_REFERENCE.md`. These checks do
not establish scientific performance or acceptance on a native Linux
workstation.
