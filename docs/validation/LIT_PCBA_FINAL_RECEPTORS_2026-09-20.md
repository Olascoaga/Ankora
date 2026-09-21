# LIT-PCBA final receptor production record

Protocol ID: `LIT_PCBA_ANKORA_VS_V1`

Execution date: 2026-09-20 (America/Mexico_City; manifest timestamp is UTC)

Status: **six final receptors and six receptor PDBQT files completed; no
ligand preparation, docking, score, or enrichment metric executed**.

## Frozen inputs and execution boundary

This create-only run consumed the previously frozen six structural plans and
the scientist-confirmed protonation review without changing either one. The
accepted review SHA-256 is
`4d01857a5ef7df41eeb8a81ffd76a32d1d0292057562323e16dbd42d6c7743f4`.
It covers 449 proposals: 443 source defaults and six explicit TP53 zinc-site
overrides. The run used six bounded workers, one per receptor template.

The public, path-free result is
`reference_cases/LIT_PCBA_ANKORA_VS_V1.final-receptors.json`, with internal
manifest SHA-256
`b617361c059c9c07b27010c34a3429a86eec355ecd6e27fe69172a7642a1636e`.
Raw commands, stdout/stderr, intermediate structures, immutable records, and
all output files remain in ignored local validation storage. Every retained
file is named by relative path, byte count, and SHA-256 in the public manifest.

The production path recorded PDBFixer 1.12.0, OpenMM declashing through the
PDBFixer worker 1.12.0, PDB2PQR 3.7.1, PROPKA 3.5.1, Meeko 0.7.1, and Ankora's
versioned Gemmi selector and PQR compatibility formatter.

## Completed derivatives

| Target | Role | PDB | Proposals | Overrides | PDBQT bytes | PDBQT SHA-256 |
|---|---|---|---:|---:|---:|---|
| ESR_antago | primary | 5UFX | 68 | 0 | 182979 | `77dbd42747cdac91ce94a4fba8782bff79e3de8e935c3e24bd33d50fa0854507` |
| ESR_antago | alternate | 2IOG | 74 | 0 | 190755 | `ba91ddaf3ac41be8bd09ea763959c6282c12a63637cedf06a374cdd0fe2cd0e7` |
| PPARG | primary | 3B1M | 82 | 0 | 204525 | `f55ce237caa5d5d875fa0ca9e6eebcba8393a932f5eb6a1891289f443a9d4410` |
| PPARG | alternate | 5Y2T | 82 | 0 | 205578 | `68cf4c016d4658b959289a2cf496089b2a5b7adeef204b9b8729043ae7b829e1` |
| TP53 | primary | 3ZME | 71 | 3 | 154062 | `d5bb582133dc80b21d11658baf098b1993ee2cbe3ea64b8c28a1ce242397efc8` |
| TP53 | alternate | 5O1I | 72 | 3 | 155115 | `3e0a0dce6cef4cba32021c7f6b30dd802731c7dc8e04fa4668891e266bed4b97` |

All six final records report `docking_ready`. Their PDBQT atom-type sets pass
the existing AutoDock4 receptor preflight. The two TP53 records contain exactly
the accepted HIE A:179 and CYM A:238/A:242 overrides, and the independently
observed written histidine state remains HIE. No protocol value was selected or
changed after seeing a docking result because none existed.

## Independent verification

The checker recomputes the manifest digest, requires the exact accepted review,
requires six unique completed templates and all 449 decisions, checks every
required preparation stage, re-hashes every retained local file when the
evidence root is supplied, parses every PDBQT atom type, and reruns the
AutoDock4 receptor-type preflight. The completed evidence passed this check.

Two unsuccessful setup attempts named the wrong local archive and stopped
before scientific execution. A later complete run produced all six scientific
derivatives but its new verifier incorrectly required a written-state label for
all PROPKA groups, although that field is intentionally specialized for exact
histidine tautomer observation. That evidence was retained locally and no
public success manifest was written. The verifier was corrected without
relaxing exact HID/HIE/HIP output checks; the clean subsequent 6/6 run produced
the manifest above.

## Next scientific boundary

This record authorizes no retrospective changes and makes no performance or
biological claim. The matching 11,412-parent preparation plan was subsequently
frozen under SHA-256
`b6370eb32566e84ba569460f35efe5e89bdff12172609d92f203f51edd0d48e1`.
Its loss-preserving execution and complete reconciliation are now required.
Docking, scores, and enrichment metrics remain prohibited until that boundary
closes.
