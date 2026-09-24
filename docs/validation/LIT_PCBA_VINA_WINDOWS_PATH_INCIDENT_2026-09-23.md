# LIT-PCBA Vina Windows path incident — 2026-09-23

Protocol ID: `LIT_PCBA_ANKORA_VS_V1`

Status: **the first production launch was stopped as an infrastructure-only
failure; it produced no completed pose, benchmark score, sensitivity result,
metric, local completion manifest, or public result manifest**.

The immutable amendment is
[`reference_cases/LIT_PCBA_ANKORA_VS_V1.amendment-002.json`](reference_cases/LIT_PCBA_ANKORA_VS_V1.amendment-002.json).

## What happened

The frozen plan and all 11,302 ready scientific inputs passed their hash checks.
Vina 1.2.7 then rejected the long absolute receptor or ligand paths before
docking. The output showed a rapid common `VINA_EXECUTION_FAILED` pattern, so
the operator stopped the run instead of allowing the same infrastructure error
to consume every row.

The retained ignored run root contains 10,092 started rows: 9,982 terminal
docking failures, 98 correctly retained preparation failures, and 12 started
rows without terminal evidence at forced shutdown. There are zero completed
scored rows. This root is technical incident evidence only and must never be
resumed, promoted, or used for performance analysis.

## Corrective boundary

The frozen receptor and ligand bytes, boxes, Vina executable, seed, sampling
parameters, scheduling, parser, ranking rule, and failure policy do not change.
The executor instead copies each already verified PDBQT byte-for-byte beneath
the new create-only run root, verifies byte count and SHA-256 again, and invokes
Vina with those bounded paths. A preflight rejects an unsafe run-root depth
before the first entry attempt starts.

The corrected executor must receive a new readiness hash and pass its full
software gate before a new production root may launch. The failed root remains
local; only a complete independently verified corrected result may become
public evidence.
