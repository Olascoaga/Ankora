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

The retained protonated PDB files show `HD1` on HIS A:179 in both original
TP53 previews. ND1 is the deposited zinc-contact atom at 2.009 A in 3ZME and
2.010 A in 5O1I, so the automatic neutral tautomer protonates the coordinating
nitrogen. This is a blocking result, not a review preference.

Ankora now exposes exact HID and HIE selection before PDB2PQR optimization and
AMBER assignment, and independently verifies the state written to both PDB and
PQR. A pre-result, hash-bound verification requested HIE at HIS A:179 for only
the two TP53 templates. The full production preparation path completed 2/2
review-only reruns; both PDB and PQR outputs contain `HE2`, omit `HD1`, and
therefore leave the zinc-coordinating ND1 unprotonated. The frozen request is
`reference_cases/LIT_PCBA_ANKORA_VS_V1.tp53-tautomer-verification.spec.json`
(SHA-256 `2751b5b9b721c20ea72a743008b248fb19fb7f3b892f95defc5bc3bea24fce30`).
The path-free result manifest is
`reference_cases/LIT_PCBA_ANKORA_VS_V1.tp53-tautomer-verification.json`
(internal manifest SHA-256
`2ac5f7abdc65d116cc1b209cb6b6421ace83a480f03cd43b39363dc3c2be7826`).
No docking score was seen before freezing or executing this verification.

## Complete protonation decisions accepted

The path-free review
`reference_cases/LIT_PCBA_ANKORA_VS_V1.protonation-decision-review.json`
now covers every one of the 449 frozen proposals under confirmed review
SHA-256
`4d01857a5ef7df41eeb8a81ffd76a32d1d0292057562323e16dbd42d6c7743f4`.
The scientist accepted 443 recorded defaults and exactly six overrides:

- HIE at HIS A:179 in both 3ZME and 5O1I, using the independently verified
  written-PDB/PQR state that leaves zinc-coordinating ND1 unprotonated.
- CYM at CYS A:238 and CYS A:242 in both 3ZME and 5O1I.
- The already predicted CYM default at CYS A:176 is called out explicitly in
  both templates rather than being hidden inside the bulk default policy.

This is a proposed benchmark model for the deposited zinc-bound structures,
not a universal claim about all Cys3His centers. The deposited 3ZME/5O1I
geometries independently show the same tetrahedral Cys176-His179-Cys238-
Cys242 shell. The original p53 core-domain structure established this
structural zinc site ([Cho et al., 1994](https://doi.org/10.1126/science.7801121)).
A combined structural survey and quantum analysis found that most surveyed
Cys3His PDB geometries were consistent with all-thiolate coordination while
also warning that experimental resolution cannot exclude every thiol/thiolate
mixture ([Simonson and Calimet, 2002](https://doi.org/10.1002/prot.10200)).

The executable checker expands the bulk-default rule against the immutable
source manifest, verifies that all 449 proposals are covered exactly once,
requires the separate HIE output evidence, and exposes only the three accepted
overrides belonging to the exact template being prepared. The confirmation is
recorded independently from the proposal and the complete artifact is
re-hashed.

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

## Review gate completed; final receptor production now recorded

The scientist confirmed the complete 443-default/six-override plan before any
docking score existed. The review now reports `final_creation_authorized:
true`, and directed verification returns exactly HIE at HIS A:179 plus CYM at
CYS A:238/CYS A:242 for either TP53 template. This authorization was limited
to create-only final receptor and receptor-PDBQT production from the frozen six
structural plans. That exact production has now completed 6/6 without ligand
preparation, docking, scores, or enrichment metrics. The separate execution
record is `LIT_PCBA_FINAL_RECEPTORS_2026-09-20.md`, and its path-free
manifest is
`reference_cases/LIT_PCBA_ANKORA_VS_V1.final-receptors.json`. No post-result
protocol change or biological claim has been generated.
