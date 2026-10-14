# Topology-guarded receptor repair — 2026-10-14

## Acceptance contract

Repair the retained failing 7AQF chain-A plan without deleting its 17 incomplete
observed residues, moving observed heavy atoms during reconstruction, inventing
loops, changing protonation/charge policy, or modifying historical artifacts.
Preserve legacy request serialization and workers unless the new method is
explicit. Reject missing/excess repaired connectivity and rebuilt stereochemical
inversion; preserve raw final-tool evidence and method/version identity.

## Native Windows evidence

The untouched deposited mmCIF SHA-256 is
`79fd3b96adca6bdbe17ded6e9c693534007ae2cb0538739044788754b7c6faac`.
The exact selected PDB matches the original failing attempt:
`62987da61fe858e579a9dc85d1aac94258e9e13cee40117b681aac88f171cae6`.
Original artifact hashes were verified unchanged after the isolated runs.

The predeclared plan retains chain A, removes waters and RV2, repairs LYS
28/80/104/288; GLN 107/174/257/303/312; ASP 231; GLU 244/313/350/351;
ARG 271/300; ILE 342. Nine absent-residue observations remain unmodelled.
No observed residue was removed. Optional elastic relaxation is off.
Hydrogenation uses pH 7.4, AMBER and no residue-state override; Meeko uses
`--read_pqr --charge_model read`. This reproduces the tested plan, not a
recommendation for every target or a blanket acceptance of pKa predictions.

Runtime: PDBFixer 1.12.0, OpenMM 8.5.2 / Reference, PDB2PQR 3.7.1, PROPKA
3.5.1, Meeko 0.7.1, RDKit 2025.9.6 and Gemmi 0.7.5.

Two independent adapter-level preparations passed all gates with identical
artifact bytes on this machine. Full-service preview/final preparations from
an isolated copy of the original mmCIF also passed: 98 pKa proposals, final
`docking_ready`, and the same hashes. The final service repetition records
method, seed, OpenMM version, force parameters and successful PQR connectivity
verification in provenance. Final record:
`ae1bd68e-5531-47d4-80a3-58513ca75fbe`.

| Output | SHA-256 |
| --- | --- |
| Repaired PDB | `fa85407f23845c7efd4fb53db73dad432568ef1e5a1d8f70be92696cb0d548c1` |
| Protonated PQR / normalized Meeko input | `84b0b700b066f9b2e3e928aefd716fc02fccc74ee05642b133c6fbfa5fa5c699` |
| Protonated PDB | `0c74f998830c38e8267da04328e3ca196eed40923d77e4fc04cf0aff387644b0` |
| Receptor PDBQT | `03fc0d90e003556ae71ec635bcfc018dd4aea7af8460610c5439a773313f2afd` |

The local pre-run plans, rejected candidate source snapshots, raw outputs,
stdout/stderr and create-only repetition folders remain ignored, not uploaded
with personal paths. Candidate 1 failed final Meeko template matching after an
ARG A:300 bond stretched to 2.027 Å; this exposed the need to check missing as
well as excess inferred bonds. Candidate 2 failed before positions because
OpenMM disallows constraints to massless atoms. Candidate 3 strengthens the
native harmonic bond terms instead. No docking or score-based optimization ran.

A subsequent QC implementation regression compared blank insertion codes as
`" "` versus `""`, falsely marking standard bonds as unexpected. Normalization
fixed it; blank and nonblank insertion-code cases now have dedicated tests.
The failed preview was not represented as a successful receptor.

## Automated checks and boundaries

Synthetic mutation tests, explicitly not biological references, check observed
atom displacement, missing/extra heavy bonds and mirrored rebuilt chirality.
A native template-derived ALA repair preserves observed atoms and a retained
zinc component. Additional tests cover insertion identity, unsupported-library
refusal, worker method/seed/platform verification, required-parser failure,
legacy serialized decisions and method-specific Methods prose.

No historical 6OCO benchmark was rerun or relabelled as evidence for this method.
This is a bounded 7AQF repair regression and synthetic safety regression, not
a broad receptor-preparation benchmark, metal parameterization validation,
cross-machine reproducibility claim or proof of a physically optimal rotamer.
Final Meeko acceptance does not establish those properties.

Windows automated gate: full backend suite passed 757 tests before the final
required-parser exception regression; the final focused receptor/Methods suite
passes 80 tests, including that additional case. Ruff is clean and strict mypy
passes 139 source files. The full final-tree gate is recorded in the guided
workflow acceptance record after integration. Existing Starlette/httpx warning
is not a scientific-tool failure. No remote CI run is claimed here.

The existing installed beta and installers remain unchanged. Scientist testing
of the new source workflow precedes any separately authorized installer build.
