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

Point 26 begins with the pre-result
[`LIT_PCBA_ANKORA_VS_V1`](VIRTUAL_SCREENING_BENCHMARK_PROTOCOL.md) contract.
It freezes a three-target LIT-PCBA cohort, loss-preserving and tie-aware metric
definitions, AutoDock Vina settings, and one-factor sensitivity boundaries.
The protocol is not yet a completed screening benchmark and is not listed as
completed evidence in `VALIDATION_STATUS.json`. Its source, receptor, and ligand
input boundaries are now executed and verified; no docking or enrichment
result exists. The exact LIT-PCBA AVE-unbiased source bytes and three-target
population are acquired, hashed, reconciled, and frozen in a path-free input
manifest.
The [2026-09-11 acquisition record](LIT_PCBA_SOURCE_ACQUISITION_2026-09-11.md)
documents the successful maintainer-source acquisition, the pre-result
Amendment 001 distinguishing the AVE-unbiased population from the differently
sized `full` archive, and why a processed nine-target candidate did not satisfy
the frozen cohort or chemical-state contract. No benchmark run was made. The
tested source inspector fails closed on source and amendment identity, census,
template pairing, archive safety, duplicates, parse loss, and cross-label
conflicts. The frozen population contains 176 active and 11,236 inactive
evaluation units with no losses or conflicts at source inspection.
The [2026-09-14 template record](LIT_PCBA_TEMPLATE_SELECTION_2026-09-14.md)
then freezes primary 5UFX/3B1M/3ZME and alternate 2IOG/5Y2T/5O1I holo
templates by a resolution-first rule across all 36 source pairs. The choice
reproduces offline from a hash-bound RCSB metadata snapshot and source-member
identities. Numerical boxes and 96 hash-selected sensitivity parents are now
frozen in `LIT_PCBA_ANKORA_VS_V1.geometry-sentinels.json`; the manifest
rebuilds from the exact archive and never reads a docking score. The six
official RCSB mmCIF files and their direct, no-superposition coordinate-frame
evidence are frozen in `LIT_PCBA_ANKORA_VS_V1.structures.json`: every source
ligand heavy atom maps exactly to one official co-crystal residue, and more
than 98% of source receptor heavy atoms match same-element official coordinates
for every template. Six explicit structural requests are
frozen in `LIT_PCBA_ANKORA_VS_V1.receptor-plans.json`: chain/component,
missing-residue, missing-atom, source-aligned altloc, terminal-OXT,
relaxation, pH, and force-field choices are all fixed before execution. Source
protein MOL2 bytes are used only to identify the exact retained alternate
coordinates and will not be treated as if Ankora had produced a reviewed,
docking-ready receptor. Six structured PDB2PQR/PROPKA previews have now
completed and are frozen in
`LIT_PCBA_ANKORA_VS_V1.protonation-previews.json`: 449 proposals were retained
and 102 carry focused-review flags. The TP53 Cys3-His zinc sites were called
out for deliberate review. In both
TP53 previews the automatic neutral HIS179 tautomer protonated the ND1 atom
that contacts zinc at approximately 2.01 A. Exact HID/HIE control and
independent PDB/PQR output-state verification are now implemented. A frozen,
pre-result request reran both TP53 templates with HIE at HIS179 through the
full production path; both outputs wrote HE2, omitted HD1, and left ND1
unprotonated. The request and 2/2 result are frozen in
`LIT_PCBA_ANKORA_VS_V1.tp53-tautomer-verification.spec.json` and
`LIT_PCBA_ANKORA_VS_V1.tp53-tautomer-verification.json`. The scientist then
accepted all 443 source defaults plus six explicit TP53 overrides: HIE at
HIS179 and CYM at CYS238/CYS242 in both templates. The create-only final run
reproduced all 449 decisions and produced six docking-ready receptors and six
PDBQT files. Its path-free, hash-bound record is
`LIT_PCBA_ANKORA_VS_V1.final-receptors.json`; no ligand preparation, docking,
score, or enrichment metric was part of that receptor phase. The complete 11,412-parent
loss-preserving preparation plan is now frozen in
`LIT_PCBA_ANKORA_VS_V1.ligand-preparation-plan.json` under SHA-256
`b6370eb32566e84ba569460f35efe5e89bdff12172609d92f203f51edd0d48e1`.
It fixes exact imported states, source-only deterministic ETKDGv3 seeds, the
20-member conformer pool, MMFF94s convergence policy, Meeko/Gasteiger, and
explicit retention of every failure. The create-only production execution now
closes all 11,412 rows in
`LIT_PCBA_ANKORA_VS_V1.ligand-preparation.json`, under manifest SHA-256
`d7704f66118820974a6c55a0a5fcc366ac33c5738db3af9672a77eadb74a3ab0`:
11,302 prepared PDBQTs, 107 unresolved exact states, and three ETKDGv3 failures.
All 110 non-prepared parents remain in the future worst tie. The
[execution record](LIT_PCBA_LIGAND_PREPARATION_RESULTS_2026-09-23.md) documents
the class/target census and independent evidence re-hash. The exact primary
Vina campaign is now frozen in
`LIT_PCBA_ANKORA_VS_V1.vina-primary-plan.json`, under manifest SHA-256
`31862a168e737d2d6d81ab9ce5eba3b316eb31225318300237b140a99c020feb`.
It binds every terminal row to the exact receptor, box, executable, scheduling,
restart, and parser identities without reading a score. The
[plan record](LIT_PCBA_VINA_PRIMARY_PLAN_2026-09-23.md) closes that pre-result
boundary. Docking remains prohibited until the create-only, incremental, safely
resumable executor consuming this plan is implemented and verified.

M0 validation is limited to contract tests and a documented desktop smoke path. M1 adds explicitly synthetic parser/API fixtures plus a recorded, hash-bound RCSB structure-import smoke; neither establishes receptor-preparation or docking validity.

See `M1_STRUCTURE_WORKSPACE.md` for the complete M1 criteria and recorded evidence.

## M0 manual smoke test

1. Install prerequisites and run `scripts/bootstrap.ps1`.
2. Run `npm run tauri:dev`.
3. Confirm the desktop window opens and the Structure workspace is visible.
4. Confirm Backend reports connected and the backend version is shown.
5. Confirm Vina and GNINA each display detected or not found without being executed.
6. Stop the application and confirm the local backend process exits.
