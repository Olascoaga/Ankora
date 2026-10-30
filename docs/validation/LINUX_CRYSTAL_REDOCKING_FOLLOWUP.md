# Linux 1HSG/MK1 exploratory redocking follow-up — predeclared protocol

## Context and interpretation

This is a **new exploratory engineering test**, planned after observing the
failure documented in `LINUX_CRYSTAL_REDOCKING_PLAN.md`. Its terminal-oxygen
decision is informed by that failure and is not a blinded or confirmatory
scientific validation. The original protocol, data and failure remain unchanged.
Neither a favorable nor an unfavorable RMSD establishes general performance.

## Fixed plan before execution

Use the same source bytes, extracted MK1 reference, two chains, component and
water decisions, receptor tools, pH, independent ligand conformer, box derived
from the crystallographic ligand, Vina executable and fixed parameters described
in the earlier plan. The only changed scientific decision is explicit
authorization for exactly `OXT` at PHE A:99 and PHE B:99; no other heavy-atom
change is authorized. These identities were proposed by PDB2PQR in the earlier
failed run and subsequently flagged in read-only source inspection. This is an
explicit test decision, not a recommendation for other receptors.

Perform one run in a separate create-only isolated directory. Record every API
response, warnings, source and pose hashes, unmodified reference, raw execution
outputs and the redocking result or first failure. The source and reference
must remain unchanged. RMSD uses the existing in-place symmetry-aware method,
threshold 2 Å; report sampling and ranking separately without treating either
outcome as an engineering success criterion. Stop on failure and do not alter
this plan based on the result. This is WSL testing, not native-workstation or
general Windows/Linux equivalence acceptance.

## Observed result — 2026-10-29

The exploratory run completed the real API path through receptor preparation,
independent conformer generation, ligand PDBQT, box creation, Vina and Ankora
redocking. Nine pose artifacts were saved and checked against their recorded
hashes. The unchanged extracted crystallographic reference SHA-256 was
`0dfcb7d3d6024bbe5572c990ff57fdd38e46cfe20b928acb8601bae3ad550982`.
The recorded receptor plan authorized exactly OXT at PHE A:99 and B:99.

With the stated 2 Å threshold, in-place symmetry-aware top-1 RMSD was
0.449214103864862 Å and best-overall RMSD was the same. The first recovering
rank was 1 of 9; one pose met the threshold. Both sampling and ranking were
reported as successful for this particular evaluated configuration. This is a
post-failure exploratory case, not a blind or general scientific validation.

- Evidence JSON SHA-256: `d0a5ca8c9bfae80f70b607dec17c18b90bb3efb2348aeb3e913dbbeba732db4b`.
- Raw Vina pose file SHA-256: `d43ae8e0eae509c64f57660e10e9076a07825d0727b620b7c4d306b468829a06`.
- Vina stdout SHA-256: `03bb026d253173f84b4130df777120b696ffb6f332d72da1e69660e8b00bc24f`;
  stderr was empty. Both are retained with the isolated project.
- Ligand extraction reported `LIG_FORMAL_CHARGE_INFERRED`: atom formal charges
  were not deposited, and the inferred neutral valence matched the deposited
  formula. The receptor and redocking records contained no structured warnings.
  During evaluation, RDKit printed repeated warnings that more than one matching
  pattern was found and one was chosen. Those console warnings were observed in
  the execution output; they were not captured in a separate raw log file.

The source, reference, records and raw tool outputs remain in the create-only
isolated project. This did not exercise the graphical interface or establish
native Linux workstation behavior. No earlier frozen benchmark was rerun.
