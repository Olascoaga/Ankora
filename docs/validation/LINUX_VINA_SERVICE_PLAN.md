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

## Observed result — 2026-10-29

On Ubuntu 24.04 WSL2, the preregistered service job completed with the
identified Vina 1.2.7 executable, exit code 0, and two sequential poses. The
resource arbiter had zero active allocations after shutdown and the work
lease was released. Pose files matched their stored SHA-256 and size. The
original input hashes were checked again and remained the predeclared values.

- Evidence JSON SHA-256: `e1ae29771f7f037b26233869d4bcc1c6247a573dd427bae28f437fd027a63a37`.
- Raw Vina PDBQT SHA-256: `35e1a021702efcfe01d1b5000981c70451d7d6d1e07cbc2779df80ced0b5fd22`.
- Persisted stdout SHA-256: `75ed2951bcf995e6ff313a8dad92eb0f0d93743c2e927b7cb04932944fa3d8cd`; stderr was empty (SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`). Both streams were compared with the saved job record.
- Synthetic smoke-contract and existing Vina service tests: 12 passed; Ruff
  and focused mypy passed. The complete raw output and isolated project are
  retained locally. The service was seeded with labeled fixture records;
  import, preparation, GUI and API flows were not exercised in this run.

## Predeclared integration-branch repeat

The first job above used the service worktree before restoration of the frozen
Vina source. To check the integrated branch after that restoration, run one
additional isolated job under the same pinned fixture identities, parameters,
acceptance criteria and scope, with a new create-only evidence directory.
The Vina source must have the historical SHA-256
`e13e32f5b6c401966debe80fe0049f4ae87f1cc3c8eb31f4566c57c1acc50993`.
The first output remains preserved; neither settings nor score thresholds are
changed. The result is recorded separately below after execution.
