# LIT-PCBA Vina Windows path incident — 2026-09-23

Protocol ID: `LIT_PCBA_ANKORA_VS_V1`

Status: **two production launches were stopped as infrastructure-only failures;
neither produced a completed pose, benchmark score, sensitivity result, metric,
local completion manifest, or public result manifest**.

The immutable amendment is
[`reference_cases/LIT_PCBA_ANKORA_VS_V1.amendment-002.json`](reference_cases/LIT_PCBA_ANKORA_VS_V1.amendment-002.json).

## What happened

The frozen plan and all 11,302 ready scientific inputs passed their hash checks.
Vina 1.2.7 then rejected the long absolute receptor or ligand paths before
docking. The output showed a rapid common `VINA_EXECUTION_FAILED` pattern, so
the operator stopped the run instead of allowing the same infrastructure error
to consume every row.

The first retained ignored run root contains 10,092 started rows: 9,982 terminal
docking failures, 98 correctly retained preparation failures, and 12 started
rows without terminal evidence at forced shutdown. There are zero completed
scored rows.

The first correction staged the inputs beneath the new run root. A second
launch then exposed a distinct working-directory defect: the staged ligand and
output paths were still relative, while the Vina adapter intentionally changed
its working directory to the output folder. Vina therefore reinterpreted those
paths beneath that folder and could not open the ligand. The operator again
stopped the common failure pattern. That second retained root contains 5,738
started rows: 5,681 terminal docking failures, 46 correctly retained
preparation failures, and 11 started rows without terminal evidence. It also
contains zero completed scored rows.

Both roots are technical incident evidence only and must never be resumed,
promoted, or used for performance analysis.

## Corrective boundary

The frozen receptor and ligand bytes, boxes, Vina executable, seed, sampling
parameters, scheduling, parser, ranking rule, and failure policy do not change.
The executor instead copies each already verified PDBQT byte-for-byte beneath
the new create-only run root, verifies byte count and SHA-256 again, resolves
every input, output, stdout, and stderr path absolutely before entering the
worker directory, and invokes Vina with those bounded absolute paths. A
preflight rejects an unsafe run-root depth before the first entry attempt
starts.

The corrected executor must receive a new readiness hash and pass its full
software gate before a new production root may launch. The failed root remains
local; only a complete independently verified corrected result may become
public evidence.
