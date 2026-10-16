# Engineering corrections — 2026-10-15

## Ligand derivative project ownership

Confirmed four hardcoded `default` paths in ligand state, conformer, filter-run
and PDBQT persistence. All now use the project root captured when the store is
constructed, preserving the existing layout for the legitimate `default`
project. Preparation-status locks are keyed by their project-specific path.

Five synthetic storage regressions exercise all four derivative families with
the same identifiers in three different projects, project graph visibility,
cross-project read rejection and context capture. The focused storage/project/
ligand gate passed 16 tests. These are ownership tests, not chemical results.
Historical misplaced artifacts were not moved, rewritten or assigned guessed
ownership; any recovery requires explicit evidence and a separate migration.
