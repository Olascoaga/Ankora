# Redocking validation

Redocking validation (`M7`) consumes an immutable crystallographic ligand extraction and an already-preserved single-ligand docking result, records a create-only verdict beside rather than inside that result, computes configurable symmetry-aware heavy-atom RMSD **in place** without coordinate superposition, and reports Top-1 RMSD, best Top-5 RMSD, best overall RMSD, first pose under threshold, `sampling_success`, and `ranking_success` separately.

The default threshold is `RMSD <= 2.0 Å`. Passing means only that the evaluated engine and protocol recovered the crystallographic placement on that reference structure under the recorded criterion; it does not establish prospective affinity prediction or cross-target generality.

## Input admission and desktop workflow

Both the **Validation** desktop workspace and the typed localhost API accept completed individual results from **AutoDock Vina `1.2.7`**, **AutoDock4 `4.2.6` CPU**, **AutoDock-GPU `1.6`**, and (on Linux) **GNINA `1.3.3`** (`source_kind = "gnina_job"`). Multi-ligand virtual-screening campaigns are not individual redocking inputs. The scientist first executes the single-ligand run in **Docking**, then selects that completed result, a compatible crystallographic reference extraction, and an explicit RMSD threshold in **Validation**. No new docking run is launched during validation.

New measurements require a preserved 3D crystallographic ligand extracted with an exact residue locator from the receptor's own original structure (or a byte-identical reimport matched by source SHA-256 rather than by PDB code or ligand name). Local SDF/SMILES imports and prepared or minimized conformers are rejected as crystallographic references. Reference and pose bytes must match their recorded SHA-256 and byte length, and heavy-atom counts and molecular graph topology must agree; any mismatch fails closed without writing a verdict.

Reference listing is project-scoped and paginated. Historical validation verdicts remain readable without rewriting them or rerunning benchmarks. Single-run RMSD does not establish engine repeatability; recorded repeatability metadata reflects the source engine contract rather than a conclusion of one RMSD calculation.

## GNINA single-job redocking semantics (Linux)

On Linux, completed `GNINA 1.3.3` single jobs (`rescore` or CUDA `refinement`, single model or built-in CNN ensemble under `ADR-027` and `ADR-028`) are selectable directly in the **Validation** UI and measured through the identical in-place symmetry-aware heavy-atom RMSD path:

- **Native CNN ranking order:** GNINA poses are evaluated strictly in GNINA's own mode order (descending `CNNscore`), never re-sorted by `minimizedAffinity`, so `ranking_success` judges the ranking GNINA actually produced.
- **Separate score fields:** Validated GNINA poses carry dimensionless `cnn_score` and predicted `cnn_affinity_pk` beside—never inside—`binding_energy_kcal_mol` (`minimizedAffinity` in `kcal/mol`). None of these fields is pooled across engines or treated as experimental affinity.
- **Honest repeatability state:** `bitwise_reproducible` is recorded as `null` (*not assessed*) for GNINA verdicts rather than `false`, preserving older boolean records untouched.
- **Complete provenance & Trash atomicity:** Verdict provenance retains the exact GNINA executable SHA-256, receptor/ligand/conformer SHA-256 identities, `cnn_scoring` mode, `cnn_model` identity, compute backend, and pose ordering. Moving a GNINA job to recoverable project `Trash` moves its dependent redocking verdicts in the same atomic transaction.

Engineering verification on `1HSG / MK1` under WSL2 is recorded in [`docs/validation/LINUX_GNINA_REDOCKING.md`](../validation/LINUX_GNINA_REDOCKING.md) and [`docs/validation/GNINA_REDOCKING.md`](../validation/GNINA_REDOCKING.md). No public frozen GNINA benchmark case has been added to `VALIDATION_STATUS.json`, and bare-metal Linux workstation attestation (`ADR-029` Gate `D6`) remains pending.
