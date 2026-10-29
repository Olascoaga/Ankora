# ADR-027: GNINA docking on Linux

Status: accepted by the scientist, 2026-10-29.

## Decision

Add GNINA as a distinct docking engine in the Linux edition of Ankora. GNINA
remains unavailable in the native Windows edition. This supersedes only the
GNINA deferral in ADR-015 and the exclusion of new scoring from the initial
Linux port unit in ADR-026; it does not alter the Windows release contract.

## Scientific and engineering contract

- Run GNINA behind a versioned backend adapter, never in the frontend. Track
  executable hash, version, full command, input identities, search box, seed,
  computational resources, CNN mode and model, and raw stdout/stderr/output.
- Preserve independently prepared receptor and ligand inputs; document and
  test any format conversions and protonation assumptions. Never silently
  change structures or coerce ambiguous atom mappings.
- Preserve GNINA's own pose ordering and separate empirical energy, CNN pose
  score and CNN affinity prediction as named fields. Their directions, units
  and models must be explicit. No prediction is experimental affinity, and no
  numbers are pooled with Vina or AutoDock4 as if on a common scale.
- Begin with the `rescore` mode; additional modes and custom models need their
  own recorded semantics. Preserve upstream defaults explicitly and identify
  the actual built-in model/ensemble and executable version, not just `CNN`.
- A detected executable or reported device is not proof that GPU inference
  ran. Validate CPU and CUDA paths separately; resource reservations,
  cancellation and honest failure reporting are mandatory. Do not silently
  fall back from requested GPU execution to CPU.
- Use isolated synthetic inputs and previously recorded public reference
  cases only in predeclared engineering checks. Keep frozen evidence immutable.
  Successful runs or redocking on one structure are not universal validation.
- Integrate results, exact poses, interactions, redocking, export and Methods
  only when their cross-engine scientific contracts are implemented and tested.
  A feature is not complete until code, tests and recorded evidence exist.
- GPU/runtime/architecture and licensing/redistribution requirements must be
  resolved separately before a Linux installer is called complete. Linux WSL
  evidence does not replace native-workstation acceptance.

## Delivery sequence

1. Verify official GNINA 1.3.3 Linux executable identity and a bounded real
   CUDA run against isolated inputs; record the actual output format and errors.
2. Implement and validate Linux-only discovery, adapter, typed GNINA scores,
   input and pose handling against the observed outputs. Keep Windows unchanged.
3. Add a durable, cancellable single-ligand service and API with immutable
   artifacts, resource control and exact provenance; exercise real and error
   paths before exposing it in the UI.
4. Integrate a Linux-only workspace, results and pose inspection, followed by
   library campaigns with progress, redocking, interactions and exports.
5. Test WSLg, Windows regressions and native Linux workstation; review licenses,
   model redistribution and runtime size before packaging.
