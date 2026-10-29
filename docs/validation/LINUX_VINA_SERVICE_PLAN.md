# Linux Vina service integration smoke — predeclared protocol

This development smoke tests one real `VinaDockingService` job through its
real artifact stores, freshness guard, resource arbiter, lease manager,
execution adapter and pose persistence. It is not a GUI or HTTP test, a
receptor-preparation integration test, redocking, a biological result, or a
native Linux workstation acceptance. The input records are explicitly seeded
development fixtures, not claims that the import/preparation services ran.

The procedure is declared before execution. It never accesses the user's
project directory, modifies historical benchmarks, or overwrites an existing
output directory. The original fixture files remain unchanged. Engine outputs,
job records, logs, lease records, input copies and the evidence report stay in
the newly created isolated output directory. Failed runs are retained.

## Fixed identities and settings

- Receptor: previously generated development-fixture PDBQT, SHA-256
  `21067a2249a5f3f4cc7cb83280b2d2ba1c70bf0b2b0c7a29a94e63c6e72d13b5`.
- Ligand: synthetic ethanol PDBQT, SHA-256
  `23544379c6b5c396e043f2bce0cc8677987ff930159da505e3afa65e5bb04182`.
- P2Rank prediction CSV SHA-256
  `42574b705d8a1d6e0fd3a122b05b879e3cc5855bc30b6aa32c777d9eec458e7b`;
  rank-1 center `(-23.7785, 40.9869, 25.9487)` Å, box `20 × 20 × 20` Å.
- Linux x86-64 AutoDock Vina 1.2.7 executable SHA-256
  `f31f774f723bba7bbe6e9d1c47577020eea9a8da16424284c043d22593570644`.
- Custom settings: CPU 2, seed 20261028, exhaustiveness 2, maximum 3 modes,
  minimum RMSD 1 Å, energy range 3 kcal/mol, timeout 1 minute.

These pins match the previous adapter smoke, but a successful result here is
independent evidence for orchestration and artifact persistence only. No score
or pose geometry is an acceptance threshold.

## Acceptance

One service job must reach `completed`, preserve a successful real execution
and its streams and raw PDBQT, record one to three sequential poses whose
bytes match their hashes, retain unchanged fixture input hashes, and release
its resource and work leases. A failure, timeout, missing output, mismatch,
or preexisting output directory is not a pass. The full service record and
evidence are retained locally; score is a computational estimate, not affinity.

The fixed settings above are not tuned after seeing a result. The observed
outcome is appended after execution without modifying this protocol.
