# Validation strategy

Scientific capabilities require frozen reference cases, recorded source artifacts, explicit configurations, expected evidence, and reproducible results before they are called complete. Synthetic fixtures must be labeled synthetic and may test software behavior, never establish scientific validity.

The existing SERPINE1 7AQF/RV2 evidence is frozen in
`reference_cases/SERPINE1_7AQF_RV2.manifest.json` and rendered as the adjacent
human-readable matrix. It exposes exact-record claims and gaps; it is not a
claim of transferability. The independent PIK3CD 6OCO/M5V inputs and pre-run
protocol are frozen in `reference_cases/PIK3CD_6OCO_M5V.manifest.json` with
evidence SHA-256
`7fe1ac4cc8aa1fb46569d5e8bce77b376fab3138e01238efa4d23197e25e8cfb`.
No docking result contributed to that protocol. Its execution is now complete:
the independent result package freezes 29 records and 122 artifacts with
evidence SHA-256
`c62d8d2e7f813c1a4799dfad3c264d3cfbeca48918979c53e2653e12c396f1dd`.
The fixed 2.0 Å boundary classifies Vina as a near miss, AutoDock4 CPU as
recovered but misranked, and all six AutoDock-GPU repeats as not recovered.
These case-level findings do not establish virtual-screening enrichment,
affinity prediction, biological activity, or cross-target generality. The
3UT3/EMJ case is adversarial and must not alone fail the entire scientific
suite.

`VALIDATION_STATUS.json` is the canonical public status index. Its adjacent
Markdown rendering and the README summary are checked against frozen manifests
by `scripts/check_public_validation_status.py`; CI fails when the public status
or evidence metadata diverges.

M0 validation is limited to contract tests and a documented desktop smoke path. M1 adds explicitly synthetic parser/API fixtures plus a recorded, hash-bound RCSB structure-import smoke; neither establishes receptor-preparation or docking validity.

See `M1_STRUCTURE_WORKSPACE.md` for the complete M1 criteria and recorded evidence.

## M0 manual smoke test

1. Install prerequisites and run `scripts/bootstrap.ps1`.
2. Run `npm run tauri:dev`.
3. Confirm the desktop window opens and the Structure workspace is visible.
4. Confirm Backend reports connected and the backend version is shown.
5. Confirm Vina and GNINA each display detected or not found without being executed.
6. Stop the application and confirm the local backend process exits.
