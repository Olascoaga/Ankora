# ADR-025: Versioned topology-guarded receptor reconstruction

Status: accepted for the bounded Windows regression described below; not a
general validation of reconstructed side-chain conformations.

## Context

The installed 7AQF failure retained geometrically inferred excess valence after
17 explicit PDBFixer repairs. Removing successive affected residues changes the
scientific system and is not a reconstruction algorithm. The previous optional
elastic clash-relief stage can also exceed its observed-atom displacement limit.

## Decision

Expose `topology_guard_v3` as an explicit repair method in new UI requests.
Requests without this field, historical records and restored historical plans
retain `legacy`; their canonical serialized decision shape stays unchanged.
Never upgrade a historical receptor or rewrite its outputs in place.

The worker requires PDBFixer 1.12.0 because it wraps a private force-field
boundary. It uses seed 20261014 by default and OpenMM Reference, recording both
and the actual OpenMM version. Native heavy-atom bond equilibrium lengths,
angles and torsions remain. Bonds involving reconstructed atoms have harmonic
strength at least 300000 kJ mol−1 nm−2. Native massless observed atoms remain
fixed during reconstruction. Replace only the bounded soft steric force with
`1.0*(0.22/r)^12` in kJ/mol and nm, exclude direct bonds only, and retain the
native interaction group involving new atoms. These are versioned construction
parameters, not a calibrated receptor energy model or docking score.

Before protonation, compare observed identities/coordinates at written PDB
precision, inferred intra-residue heavy connectivity with standard topology
(missing and excess bonds), and rebuilt CA / ILE–THR CB chirality with native
templates. The optional separate elastic relaxation remains opt-in and retains
its existing 0.5 Å observed-heavy-atom limit; its output receives the same
connectivity/chirality checks. Blank insertion codes are normalized between
OpenMM and Gemmi; nonblank insertion codes remain part of atom identity.

After hydrogenation, check the normalized PQR with Meeko's own residue parser
and inter-residue bond finder, including during protonation preview. A missing
parser or unreadable result is a failure, not evidence of correct geometry.
Meeko still reads PDB2PQR charges; no charge, pH, residue-removal or tautomer
fallback is introduced. Final Meeko conversion remains a separate required
acceptance gate for `docking_ready`.

## Evidence and limitations

See [the native regression record](../../validation/RECEPTOR_TOPOLOGY_GUARD_2026-10-14.md).
Two preliminary candidates failed and were retained: a wall-only variant
stretched ARG A:300 enough to split inferred connectivity, and exact bond
constraints are incompatible with massless observed atoms. The final protocol
was defined before its successful paired execution, not selected from docking
scores. There was no seed or steric-wall parameter search.

This is not loop modelling, rotamer validation, full protein minimization,
equilibration, or proof of biological correctness. Geometry checks are bounded;
unusual residues/cofactors and inconsistent source coordinates can still fail
and need scientific review. No automatic deletion or retry is permitted.

Same-machine repeat hashes are measured evidence only. OpenMM explicitly does
not promise universal identical output from a shared seed across platforms;
the [OpenMM random-number documentation](https://docs.openmm.org/latest/userguide/theory/05_other_features.html#random-numbers-with-stochastic-integrators)
and [custom-force API](https://docs.openmm.org/latest/api-python/generated/openmm.openmm.CustomNonbondedForce.html)
describe these boundaries. The tested runtime version is recorded, not silently
upgraded to the documentation site's latest version.
