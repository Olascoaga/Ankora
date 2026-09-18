# LIT-PCBA receptor protonation preview record

Protocol ID: `LIT_PCBA_ANKORA_VS_V1`

Execution date: 2026-09-17 (America/Mexico_City; manifest timestamp is UTC)

Status: **six review-only previews completed; scientist review pending; no
final receptor or receptor PDBQT created**.

## Reproducible boundary

The exact six receptor plans frozen in
`reference_cases/LIT_PCBA_ANKORA_VS_V1.receptor-plans.json` were executed with
the production receptor-preparation path. Each run used PDB2PQR 3.7.1,
PROPKA 3.5.1, pH 7.4, and the AMBER force field. Six independent workers were
used, one per template. Every command, raw stdout/stderr log, intermediate
derivative, tool version, and file hash is retained in ignored local validation
storage. The path-free public manifest is
`reference_cases/LIT_PCBA_ANKORA_VS_V1.protonation-previews.json` with internal
manifest SHA-256
`81d53765255308d761619f781fd37ef49e11fc343d9429a367ec620cd91927aa`.

The manifest records 449 structured proposals. No predicted state differs from
Ankora's default state in this preview. That agreement is not approval: 102
unique proposals carry at least one focused-review flag, and warning categories
overlap.

| Target | Role | PDB | Proposals | Attention | Near site | pKa near 7.4 | Histidine | Metal |
|---|---|---|---:|---:|---:|---:|---:|---:|
| ESR_antago | primary | 5UFX | 68 | 16 | 12 | 4 | 12 | 0 |
| ESR_antago | alternate | 2IOG | 74 | 23 | 18 | 6 | 13 | 0 |
| PPARG | primary | 3B1M | 82 | 17 | 14 | 4 | 5 | 0 |
| PPARG | alternate | 5Y2T | 82 | 16 | 13 | 4 | 5 | 0 |
| TP53 | primary | 3ZME | 71 | 15 | 9 | 3 | 7 | 4 |
| TP53 | alternate | 5O1I | 72 | 15 | 10 | 2 | 7 | 4 |

Across all six templates the flags comprise 76 active-site proximity flags, 49
histidine-tautomer flags, 23 pKa-near-target-pH flags, and 8 metal-coordination
flags. Active-site proximity requests inspection but does not itself justify an
override. Likewise, `HISTIDINE_TAUTOMER_OPTIMIZED_BY_PDB2PQR` records that the
neutral tautomer was chosen by the external tool; it is not evidence that the
choice is correct for a particular catalytic or coordination environment.

## Highest-priority metal review

Both TP53 templates retain the structural zinc and reproduce the same Cys3-His
coordination shell at approximately 2.0-2.33 A.

| Residue | 3ZME prediction | 5O1I prediction | Scientific review question |
|---|---|---|---|
| CYS A:176 | CYM; pKa 6.79 | CYM; pKa 6.76 | Confirm deprotonated zinc ligand. |
| HIS A:179 | neutral auto; pKa 4.00 | neutral auto; pKa 3.99 | Auto placed HD1 on zinc-coordinating ND1; this output cannot be accepted. |
| CYS A:238 | CYS; pKa 11.35 | CYS; pKa 11.34 | Decide whether the structural zinc requires an explicit CYM override. |
| CYS A:242 | CYS; pKa 9.39 | CYS; pKa 9.37 | Decide whether the structural zinc requires an explicit CYM override. |

No default or override has been accepted in the manifest. The exact proposal
rows, distances, coupled groups, warning codes, and allowed states remain in
the machine-readable record so review cannot be reconstructed from this
summary alone.

The retained protonated PDB files show `HD1` on HIS A:179 in both TP53
templates. ND1 is the deposited zinc-contact atom at 2.009 A in 3ZME and 2.010
A in 5O1I, so the automatic neutral tautomer protonates the coordinating
nitrogen. This is a blocking result, not a review preference. Ankora's current
override vocabulary exposes only `HIS_NEUTRAL_AUTO` and `HIP`; it cannot yet
request the alternate neutral histidine tautomer explicitly. Exact HID/HIE
selection plus output-state verification must be implemented and the TP53
previews rerun before either receptor can be accepted.

## Stage-attribution correction discovered during execution

The first create-only attempt retained five completed previews and one explicit
failure. While repairing missing side-chain atoms at the final observed residue
of 5O1I, PDBFixer also applied the already-authorized terminal OXT addition.
The following protonation stage incorrectly treated the now-present OXT as an
invalid duplicate authorization. Ankora was corrected to validate the
authorization against the selected derivative, record terminal additions that
an earlier explicit stage already applied, and pass only still-pending
authorizations to PDB2PQR. Tests cover both the earlier-stage and PDB2PQR-stage
paths. The failed evidence was retained locally; the public manifest was
created only by the subsequent clean 6/6 execution.

## Gate that remains closed

The preview derivatives are review material, not benchmark receptors. Before
creating any final receptor or PDBQT, the scientist must freeze, for every
proposal, either acceptance of the recorded default or an explicit allowed
override. The two TP53 zinc sites additionally require explicit histidine
tautomer support and corrected reruns before that gate can close. No docking
score has been generated or inspected.
