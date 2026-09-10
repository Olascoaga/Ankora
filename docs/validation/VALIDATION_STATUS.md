# Public validation status

<!-- Generated from VALIDATION_STATUS.json; checked by CI. -->

Last synchronized: `2026-09-10`

## Implemented scientific workflow

The implemented and accepted workspaces are M1-M9.
Implementation breadth is not evidence of scientific generality; the frozen cases below
define the current validation boundary.

## Frozen reference cases

| Reference case | Status | Records | Artifacts | Evidence SHA-256 |
|---|---|---:|---:|---|
| [SERPINE1 7AQF / RV2](reference_cases/SERPINE1_7AQF_RV2.md) | `frozen_with_known_gaps` | 26 | 54 | `03d525417e7455dc40354648877a050675fdd8d5fcd1275c547fd007873cdd00` |
| [PIK3CD 6OCO / M5V](reference_cases/PIK3CD_6OCO_M5V_RESULTS.md) | `completed` | 29 | 122 | `c62d8d2e7f813c1a4799dfad3c264d3cfbeca48918979c53e2653e12c396f1dd` |

## Recorded conclusions

- **SERPINE1 7AQF / RV2:** Retrospective evidence is frozen, but the Vina run lacks an in-place crystallographic RMSD verdict and the CPU/GPU comparison did not use one common ligand chemical state. This case does not establish transferability.
- **PIK3CD 6OCO / M5V:** The pre-registered case is complete. Vina was a 2.0596 Å near miss; AutoDock4 CPU sampled a 1.2274 Å pose but first recovered at rank 5; none of six AutoDock-GPU repeats recovered below the fixed 2.0 Å boundary.

## Claims not established

- Two single-ligand reference systems do not validate virtual-screening enrichment, cross-target performance, affinity prediction, or biological activity.
- Vina scores and AutoDock4 binding energies are different quantities and are not compared on one numerical scale.
- The completed 6OCO/M5V protocol does not determine the dominant physiological ligand microstate or quantify sensitivity to receptor preparation, search box, seed, or sampling.

## Next validation boundary

Freeze and execute multi-target virtual-screening benchmarks with actives and decoys or inactives, report EF1%, BEDROC, ROC-AUC, and PR-AUC, and measure sensitivity to chemical state, receptor, box, seed, and sampling without relaxing the frozen protocol after observing results.
