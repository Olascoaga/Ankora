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
