# Changelog

All notable project changes are recorded here.

## Locked Windows scientific environment - 2026-09-08

- Bound the validated native Conda stack to exact win-64 builds and channel
  SHA-256 values, and the CPython 3.12 dependency graph to exact Windows wheels
  and SHA-256 values.
- Added a static/runtime verifier that rejects missing hashes, version drift,
  non-Windows runtimes, and machine-local paths; CI and the local verification
  script now enforce the static contract.
- Added a create-only locked-environment bootstrap that refuses to mutate an
  existing environment and installs Ankora itself without re-resolving its
  scientific dependencies.

## Explicit responsive workbench layouts - 2026-09-07

- Replaced implicit width/height overflow exceptions with named wide, medium,
  and small shell states computed from the effective CSS viewport, including
  Windows display scaling.
- Preserved all five application menus at the 960 px minimum while capping the
  visible workflow and inspector widths and retaining each user's wider-panel
  preference for when space returns.
- Made Results the only vertical document-scroll owner for pose-interaction
  review and switched its one/two-column composition from monitor breakpoints
  to the center workspace's usable width.

## Methods in Results - 2026-09-07

- Exposed the exact record-derived Methods report in each selected Results
  campaign, including single-ligand records that have no campaign-bundle action.
- Kept copying as a repeatable action and moved success into a transient live
  confirmation that clears automatically instead of permanently relabeling the
  button.

## Distinguishable campaign bundles - 2026-09-07

- Upgraded new campaign exports to format 3 with separate campaign, exact-input,
  and export-event identities plus an optional scientist-assigned presentation
  name that does not alter scientific evidence.
- Made project folders and ZIP filenames self-distinguishing with the campaign,
  short input hash, second-resolution timestamp, and short bundle hash; repeated
  exports can no longer present as identical files.
- Kept format-2 bundles and their historical `campaign_bundle.zip` downloads
  readable without inventing identities for old records.

## Consistent scientific and date formatting - 2026-09-07

- Centralized presentation of scientific quantities with a locale-neutral dot
  decimal and narrow-space digit grouping, so one panel cannot mix Windows
  locale commas with invariant energies, distances, masses, or coordinates.
- Standardized application dates in English with local 24-hour time while
  preserving invalid recorded timestamps literally instead of inventing a
  replacement value.
- Migrated the workflow shell, receptor, ligand, binding-site, docking,
  Results, validation, and export views to the shared formatting contract.

## Shared accessible dialogs - 2026-09-06

- Added one modal-dialog boundary with explicit initial focus, trapped forward
  and reverse keyboard navigation, Escape handling, background isolation, and
  restoration of the caller's prior accessibility state.
- Migrated Results deletion and the Methods preview to the shared boundary.
  Successful deletion restores focus to the Results workspace when its opener
  no longer exists; an in-progress destructive operation cannot be dismissed.

## Durable execution ownership and startup recovery - 2026-09-04

- Added durable owner/heartbeat leases for Vina, AutoGrid, AutoDock4 CPU, and
  AutoDock-GPU jobs and campaigns.
- Reconciled queued, running, or cancel-requested work at backend startup as an
  explicit interrupted failure while preserving raw partial evidence.
- Preserved every terminal per-ligand result in an interrupted campaign and
  marked only unfinished entries as interrupted; no partial work directory is
  silently reused.
- Exposed the startup reconciliation summary through the local typed API so a
  subsequent interface increment can offer explicit retry-as-new actions.

## Purpose-labelled Vina sampling protocols - 2026-09-04

- Added explicit Screening, Pose refinement, and Custom purposes to new Vina
  single-ligand and library requests while retaining their exact numerical
  controls.
- Made scientist edits relabel the setup as Custom and invalidate the previous
  confirmation; the backend rejects mismatched named presets.
- Kept historical campaigns unlabeled rather than inferring intent, and made
  Methods output state that a protocol label is not convergence or
  publication-suitability evidence.

## Exploratory search-space guardrails - 2026-09-04

- Kept the full-protein box as Binding Site's universal non-persistent preview,
  while requiring a backend-enforced explicit acknowledgement before a new
  blind whole-receptor site can be finalized.
- Added the AutoDock Vina 27,000 A^3 large-volume warning as structured single
  and library campaign evidence, including the exact volume, selected
  exhaustiveness, and unchanged-parameter statement.
- Added volume-aware Vina guidance that recommends a focused site or a recorded
  sensitivity series without silently choosing a sampling parameter.

## M9 pose interactions, figures, and Results management - 2026-08-27

- Added exact-pose ProLIF analysis across Vina and AutoDock4 CPU/GPU records, with immutable structured contacts, skeletal 2D diagrams, Mol* residue focus, and recorded publication-figure export.
- Added durable campaign navigation plus recoverable individual and bounded group removal into project Trash, preserving shared scientific inputs and dependent evidence as one transaction.
- Upgraded campaign bundles to format 2: a portable ZIP now includes matching immutable pose-interaction records, figure manifests, available rendered figure files, and SHA-256 indexes without recomputing scientific evidence.
- Accepted the post-M9 route: close v0.1, validate an independent 6OCO/M5V system, implement real projects/stale propagation, complete Export/Trash recovery, harden library chemical states, and then package Windows releases.

## M3-M5 accepted and M6 Results contract - 2026-08-26

- Synchronized the primary project handoff, README, scope, scientific policies,
  and ADR-015 with the completed AutoGrid, AutoDock4 CPU, and AutoDock-GPU code.
- Recorded explicit scientist acceptance of M3 Ligand Preparation, M4 Binding
  Site, and M5 Docking as implemented, without implying experimental protocol
  validation.
- Defined M6 Results as a durable project-level explorer over existing jobs,
  campaigns, poses, AutoDock clusters/runs, failures, provenance, and compatible
  Vina/AutoDock4 rank comparisons. Redocking Validation follows as M7; Export
  and Interactions follow as M8.

## P2Rank verified against a real local install - 2026-08-21

- Installed a JVM (Eclipse Temurin 21) and P2Rank 2.5.1 locally and ran real pocket detection against the docking-ready 7AQF receptor end to end, closing the one remaining unverified piece of M4.
- Fixed a real CSV-parsing bug the real execution surfaced: the real P2Rank CLI pads its predictions-CSV header for column alignment, which the original parser (built against an unpadded example file) did not handle.

## M4 Binding Site: all four sources, interactive box, P2Rank pocket detection - 2026-08-21

- Added an explicit, create-only binding-site definition stage (workflow step 4), gated on a docking-ready receptor.
- Added an interactive, editable 3D box rendered live in the Mol* viewer (`setDockingBox`), backed by Mol*'s own `BoxShape3D`/`ShapeRepresentation3D` state transforms, shared across all four sources.
- Added the `co_crystallized_ligand` source: pick the originally co-crystallized ligand, get a box computed from its real atom coordinates padded by a configurable margin; the box remains editable afterward, and any adjustment is saved as its own explicit new binding site rather than mutating the suggestion.
- Added the `manual` source as its own tab: define a box from scratch by explicit center/size coordinates, live-rendered as the numbers change.
- Added the `full_protein_blind` source: a box covering every atom of the docking-ready prepared receptor, padded by a configurable margin, with an honest exploratory-cost warning shown before the action.
- Added the `pocket_detected` source: detects candidate pockets with P2Rank (switched from the originally-planned fpocket, which has no supported native-Windows install path) and ranks them by druggability; picking a candidate only previews its box in the same editable widget — nothing is created until explicitly confirmed. P2Rank's own execution has not been verified against a real install.
- Added `p2rank` to scientific-tool discovery (now 8 tools total).

## Custom descriptor-based ligand filter rules - 2026-08-20

- Added user-buildable custom library-filter rules from any already-computed descriptor (MW, cLogP, HBD/HBA, TPSA, rotatable bonds, molar refractivity, atom/ring counts, QED), with a comparison operator and a Required/Informative toggle, alongside the four fixed named rules (Lipinski/Veber/Ghose/Muegge), whose published thresholds remain non-editable for scientific citability.

## Scientific-audit remediation and virtual-screening decision workflow - 2026-08-20

- Fixed a false-positive heavy-atom identity rejection for routine PDB2PQR protonation-variant residue renames (HID/HIE/HIP and equivalents).
- Changed ligand conformer generation to embed a pool of 20 ETKDGv3 conformers and keep only the lowest-energy one, and added descriptor caching to library filtering.
- Added a persisted per-library preparation status so a virtual-screening batch does not redundantly reprocess already-prepared ligands and shows an explicit completion state.
- Added Dimorphite-DL physiological-pH protonation as an explicit, confirmable stage between chemical-state resolution and conformer generation.
- Added opt-in receptor clash relaxation after PDBFixer repair (purely repulsive OpenMM potential, 0.5 Å tolerance on previously observed atoms), fixed two physics bugs found during real-data testing, and fixed a native BLAS/LAPACK conflict crash in the development environment.
- Fixed two real production bugs in the relaxation tolerance check found on a real receptor: a wrong pre-repair comparison baseline that falsely rejected newly reconstructed side chains, and a missing 1-3 nonbonded repulsion term that let a newly placed side chain collapse onto itself and crash Meeko's PDBQT conversion.
- Fixed a virtual-screening table row only being selectable via its name button, and resolving one ligand's chemical state forcing the whole applied filter selection to be redone.
- Added multi-select and bulk "keep largest fragment" / "exclude" actions for needs-decision ligands, and a workspace-level notice that appears as soon as a filter preview shows needs-decision ligands rather than being buried in a collapsible panel or gated behind an applied selection that structurally never contains them.
- Fixed `applyFilters()` discarding all batch-preparation results on every re-apply, which would have hidden already-completed work when re-applying to include newly resolved ligands.
- Fixed the per-ligand inspector showing "Pending" for already-completed ligands restored from persisted status instead of a live batch run, by lazily fetching their conformer/PDBQT records.
- Lowered the default ligand minimization iteration ceiling from 500 to 200.

## Tool visibility and navigation correction - 2026-08-20

- Made executable discovery search the active Python environment's `Scripts`, root, `Library/bin`, and `bin` directories without executing candidates, so Conda console tools remain visible even when activation did not populate `PATH`.
- Exposed the backend Python environment in system readiness and added an in-app scientific-tool rescan action with environment-specific missing-state language.
- Changed the development launcher to reject an already occupied Ankora backend port instead of silently accepting a stale backend from another Python environment.
- Isolated workflow-copy styling from the numbered state indicator, removing inherited fixed dimensions, borders, and accent color that caused navigation labels to overlap.

## Professional scientific workbench foundation - 2026-08-20

- Replaced the document-style desktop layout with a fixed-viewport workbench containing application menus, project context, resizable/collapsible workflow and inspector panels, a compact status strip, and an expandable activity center.
- Added semantic dark/light/system themes, comfortable/compact density, shared typography/spacing/status tokens, coherent SVG iconography, visible keyboard focus, and mutually exclusive application menus.
- Changed receptor review to a Mol* plus residue-table workbench with issue filters, bulk form actions, viewer-linked residue focus, and a concise contextual plan summary.
- Split ligand preparation into explicit single-ligand and virtual-screening modes and upgraded the library to a searchable, sortable, column-configurable scientific grid with stable source order and explicit units.
- Converted long ligand decisions into progressive numbered stages and connected real receptor, ligand, and multicore batch operations to shared indeterminate/determinate activity reporting.
- Accepted ADR-014 and documented the reusable interface contract for later binding-site, docking, results, validation, and export milestones.

## M3 virtual-screening library filtering - 2026-08-20

- Added pre-3D RDKit descriptors and explicit Lipinski, Veber, Ghose, Muegge, and QED evaluation for every resolved library state.
- Added configurable PAINS/Brenk review or exclusion policies plus source-order exact duplicate detection.
- Added a read-only filter preview, an explicitly confirmed immutable JSON selection manifest, and provenance linking the exact plan, state UUIDs, RDKit version, results, and selected ligand UUIDs.
- Changed library preparation so ETKDG/MMFF/Meeko can process only an applied filtered subset; provisional, excluded, and unresolved rows cannot enter the batch silently.
- Expanded the screening table and inspector with cLogP, QED, compact rule results, alerts, summary counts, policies, and manifest evidence.
- Parallelized independent filter evaluation and selected-ligand ETKDG/MMFF/Meeko batches with a recorded worker budget derived from the local logical processor count.

## M3 Ligand Preparation foundation - 2026-08-19

- Added immutable crystallographic ligand extraction from observed coordinates and deposited mmCIF atom/bond topology.
- Added typed ligand artifacts, RDKit inspection, hashes, provenance, structured topology/formula/alternate-coordinate failures, and formal-charge inference warnings.
- Added the Ligand workspace, SDF visualization, descriptor summary, synthetic contract coverage, and recorded real RV2 extraction evidence.
- Added molecular weight/exact mass, explicit chemical-state acknowledgement, immutable MMFF94/MMFF94s minimization, energy/convergence evidence, and reference/minimized/overlay views.
- Added immutable one-molecule SDF/MOL/SMILES import, separate compound/state artifacts, missing-3D/stereo/component blockers, and reproducible independent ETKDGv3 plus MMFF conformers.
- Added explicit component retention and tetrahedral stereoisomer selection, each producing a new immutable chemical-state artifact with recorded parent and choice evidence.
- Added versioned Meeko ligand preparation from converged conformers only, visible Gasteiger charges, immutable PDBQT outputs, exact command/version/hash, and preserved raw stdout/stderr or failure evidence.
- Extended local import to multi-record SDF/SD-style MOL and multiline SMILES libraries with immutable source bytes, per-record identities, isolated parse failures, and a table of names, canonical SMILES, formulas, masses, MMFF energies, and statuses.
- Added explicitly confirmed sequential batch preparation: eligible rows continue independently, unresolved chemical states remain visible for scientist decisions, and per-row failures never discard successful derivatives.

## M2 Receptor Preparation implementation - 2026-08-19

- Added read-only receptor inspection with residue-level issues and optional reference-component proximity.
- Added explicit chain, water, component, residue, alternate-location, protonation, and PDBQT decisions.
- Added create-only receptor derivatives, hashes, provenance, raw logs, and structured failure records.
- Added selective PDBFixer, PDB2PQR/PROPKA, and Meeko adapters; Meeko explicitly preserves PQR charges.
- Added original/prepared/overlay Mol* modes and the guided Receptor workspace.
- Installed and smoke-tested the optional Windows tool chain; final 7AQF preparation remains pending scientist-approved decisions.
- Added protonation preconditions and a heavy-atom postcondition after a 7AQF run showed PDB2PQR silently repairing 61 unapproved atoms before Meeko failed at ARG A:300.
- Added explicit bulk controls for repetitive protonation blockers while retaining individual serialized decisions and a separate Apply confirmation.
- Added residue-level Meeko connectivity diagnosis and a guided remove-and-review recovery panel for failed repaired residues.
- Extended Meeko diagnosis to detect multiple inferred inter-residue bonds and map only actionable repaired residues into recovery.
- Classified unexpected single inter-residue contacts separately from peptide and disulfide bonds for guided Meeko recovery.
- Completed the first scientist-directed docking-ready 7AQF derivative and changed post-run review to show the prepared receptor alone, with explicit comparison-mode messaging and an applied-decision summary.
- Added read-only “Reopen last receptor” continuity across application restarts, restoring the exact source, plan, outputs, and prepared view without rerunning scientific tools.
- Recorded explicit scientist acceptance of the prepared-only 7AQF receptor derivative, closing M2 and authorizing M3.

## Process baseline - 2026-08-19

- Consolidated the clean-slate contract into the canonical `CODEX_BOOTSTRAP.md`; the historical alternate filename is now only a compatibility pointer.
- Extended Windows CI and the local verification script with Rust formatting, Clippy, native tests, and a release Tauri build.
- Created the first reproducible Git baseline for the complete M0 + M1 tree.

## M1 Structure Workspace - 2026-08-19

- Added immutable local PDB/mmCIF import and RCSB fetch by PDB ID.
- Added Gemmi structure inspection, stable errors/warnings, metadata, hashes, source records, and provenance.
- Added lazy Mol* visualization, import progress, expandable inspector panels, author-chain and heterogen selection, and solvent summary.
- Added synthetic PDB/mmCIF contract fixtures and complete M1 automated/native validation evidence.

## 0.1.0 - 2026-08-19

- Created the M0 clean-slate repository foundation.
- Added the Tauri, React/TypeScript, and Python local API vertical skeleton.
- Added project governance, architecture decisions, schemas, tests, CI, and memory files.
- Added optional Conda development-environment support.
- Fixed Windows Vite startup around protected parent paths and locked Cargo artifacts.
- Added generated desktop icons and verified the native Tauri application launch.
