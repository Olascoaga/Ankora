# ADR-019: Purpose-labelled Vina sampling protocols

- Status: Accepted
- Date: 2026-09-04

## Context

Vina exposes sampling controls rather than a universal definition of a
scientifically sufficient run. A single unlabeled default makes a fast library
screen, a focused pose-refinement calculation, and an edited experiment look
equivalent even though their intended use differs. Conversely, naming a preset
"publication quality" would imply convergence that no fixed parameter set can
establish across receptors, ligands, and search spaces.

Historical Ankora campaigns already contain exact Vina parameters but no
purpose label. Inferring a purpose from those values would rewrite their
scientific meaning after execution.

## Decision

New Vina single-ligand and library requests record one explicit sampling
purpose:

- `screening`: exhaustiveness 8, at most 9 modes, 1.0 A minimum inter-mode
  RMSD, and a 3.0 kcal/mol energy range;
- `pose_refinement`: exhaustiveness 32, at most 20 modes, 1.0 A minimum
  inter-mode RMSD, and a 5.0 kcal/mol energy range;
- `custom`: the exact scientist-edited values.

The named values are starting protocols, not validated convergence criteria.
CPU/thread allocation, random seed, and timeout remain independent explicit
controls. Editing any of the four sampling fields relabels the request as
`custom` and invalidates the previous confirmation. The backend rejects a
named protocol whose exact values do not match its recorded definition, so a
client cannot retain a misleading label.

Historical records without `sampling_protocol` remain valid and are described
as unlabeled. Ankora does not infer screening or refinement intent from their
numbers. Methods output reports the recorded purpose, when present, and states
that the label is not evidence of convergence or publication suitability.

## Consequences

- Scientists can distinguish high-throughput triage from focused
  pose-refinement intent without losing exact numerical controls.
- Edited settings remain first-class and honestly labeled.
- Existing campaigns remain readable without invented metadata.
- Publication suitability still requires system-specific, recorded sensitivity
  and convergence evidence; choosing a named protocol does not satisfy that
  requirement.
