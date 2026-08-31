# PIK3CD 6OCO/M5V independent execution

This is the post-freeze execution record for the protocol whose immutable inputs and
pre-run acceptance criteria are fixed in
`reference_cases/PIK3CD_6OCO_M5V.manifest.json` (evidence SHA-256
`7fe1ac4cc8aa1fb46569d5e8bce77b376fab3138e01238efa4d23197e25e8cfb`).
Nothing in this document changes the frozen docking box, ligand state, engine
parameters, seeds, repeat counts, or RMSD interpretation.

## Receptor preparation accepted after preserved failures

The first receptor attempt, `6e8b77a1-c942-4c2c-b055-c514d20ac81d`, exposed an
implementation defect before protonation. Although the mmCIF inspection identified
120 observed-residue missing-atom issues, their zero-occupancy `_atom_site` rows were
still serialized into the PDBFixer input. PDBFixer consequently reported 120 requested
residues, zero matched residues, no new atoms, and no relaxation. The selected and
repaired PDB plus raw stdout/stderr remain preserved; this attempt is not a receptor
result.

After the explicit-repair boundary was corrected and committed, the identical frozen
plan was retried as `0ca5c010-bc95-403a-9233-d802cc311dc3`. PDBFixer matched all 120
requested residues, added 295 atoms, and completed the requested 200-iteration
restrained relaxation. Its maximum pre-existing-atom displacement was 0.300268 Å,
below Ankora's fixed 0.5 Å rejection threshold; the minimum new-atom pair distance
improved from 1.391916 Å to 2.443930 Å.

PDB2PQR 3.7.1/PROPKA 3.5.1 then ran at pH 7.4 with AMBER and exited zero, but Ankora
rejected the derivative with `PDB2PQR_UNAPPROVED_HEAVY_ATOM_CHANGE`: PDB2PQR added
`OXT` to `VAL A:1031`. That residue is the last observed chain-A residue, has no
reported missing-atom issue, and is 24.780 Å from crystallographic M5V. The scientist
subsequently authorized only this exact terminal completion before another retry; the
machine-readable amendment is
`reference_cases/PIK3CD_6OCO_M5V.amendment-001.json`. No docking-ready receptor is
accepted yet. The complete PDB2PQR/PROPKA logs, intermediate files, and structured
`failure.json` remain under the rejected attempt.

| Rejected-attempt artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| selected receptor PDB | 599805 | `5dbd9d9fa1431a722acfb72c14263c9930579cceec55afb4012fec2033e283c4` |
| repaired receptor PDB | 608786 | `47bf5940327a9b853621baca5af0f68e0f94e4d46360ebe0466615b9e00d1550` |
| restrained relaxed receptor PDB | 608786 | `19a4f73b325ea307659239a5118c63511cf9c7195a7d31b982ad34a6f0439407` |
| rejected protonated receptor PQR | 1067351 | `017494f3630ca327ea2ad0204140c2804a3103c3010713d698aafaae53735507` |
| rejected protonated receptor PDB | 1232714 | `51dcf4aa8a599dd0ccb7f609496e78f50cafda362b9e1e044a82fce3b589912c` |

These hashes identify preserved failure evidence; they are not approved receptor
inputs and must not be used for docking.

The first post-amendment attempt, `4b22df41-2719-4a5c-bac8-e94c6cc12891`,
successfully passed repair, relaxation, PDB2PQR/PROPKA, and the exact OXT
postcondition. Meeko then exited nonzero, but the optional connectivity diagnostic
encountered PDB2PQR's real compact four-digit residue token `A1000` and raised a raw
`ValueError` before the primary Meeko execution could be persisted. All intermediate
receptor files and PDB2PQR/PDBFixer logs remain in the attempt directory; it has no
accepted record and must not be used for docking. The parser now reads PDB/PQR fixed
columns first, and a diagnostic failure can no longer mask the primary tool failure.

The identical plan was then retried as
`5041f5a4-1a01-43a2-8f80-2d7b9baad5b6`. This time Ankora preserved the primary
`MEEKO_CONNECTIVITY_FAILURE`, exact command, exit code, stdout, stderr, and a
structured `failure.json`. Meeko 0.7.1 itself failed before chemical parsing: its
whitespace tokenizer read PDB2PQR's fixed-column `A1000` token as a residue number,
then tried to read the X coordinate `7.742` as the fallback residue number. The
diagnostic consequently listed residues 1000–1031, but this list is a shared format
failure, not evidence that those 32 residues have invalid connectivity and not a
scientific reason to remove them.

The preserved PDB2PQR PQR is 1,067,351 bytes with SHA-256
`d57f339757d16c1cabeae2734bb5d7bd47f94051ff470638f6845c0fdbcb1922`.
Before the next identical retry, Ankora now writes a separate, hashed Meeko-input PQR
that inserts one ASCII separator between the nonblank chain and each compact
four-digit residue field. On this exact preserved input that rule affects 536 atom
records and produces 1,067,887 bytes with SHA-256
`539886b26e0bb386d256d5cdd84304ad788c9027b813dd0126a7bd963f36144c`.
Coordinates, charges, radii, atom/residue identities, line endings, and the original
PQR remain unchanged. The intermediate and its format-only provenance are recorded
as an explicit receptor output; no residue is renumbered or removed.

The otherwise identical plan then completed as receptor
`33f431a3-73a9-4858-a3f0-0026bef9d2d6` with status `docking_ready`. PDBFixer 1.12.0
matched all 120 requested observed residues and added 295 atoms. The restrained
200-iteration relaxation used 50.0 kcal/mol/Å², moved no pre-existing atom more than
0.254857 Å, and increased the minimum new-atom pair distance from 0.635378 Å to
2.446671 Å. PDB2PQR 3.7.1/PROPKA 3.5.1 completed at pH 7.4 with AMBER and applied
only authorized `A|VAL|1031||OXT`.

The exact Meeko-input transformation changed 536 compact four-digit atom records;
recomputing it from the retained PDB2PQR PQR reproduced the recorded bytes exactly.
Meeko 0.7.1 exited zero, wrote one rigid receptor PDBQT, and produced no stderr. The
accepted protonated PDB contains only chain A, 930 residues and 15,033 atoms (7,518
hydrogens), including exactly one OXT at VAL A:1031 and no waters or M5V. The rigid
PDBQT contains 9,162 atom records across the same 930 residue identities; Meeko's
normal nonpolar-hydrogen merging explains why its atom count is lower than the
explicit-hydrogen PDB.

| Accepted receptor artifact | Artifact ID | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| selected PDB | `3cde9262-1d88-4051-bbb0-a7c2c211a059` | 599805 | `5dbd9d9fa1431a722acfb72c14263c9930579cceec55afb4012fec2033e283c4` |
| repaired PDB | `fa0ee585-bb76-4b74-bbf1-4405e17636d9` | 608786 | `94bbf1a72efa1fb698c264cf99ccb28f2c9b6a91af648e03dadb845db0d6a66e` |
| restrained relaxed PDB | `83824085-5452-4311-b9aa-2e50b95da546` | 608786 | `4f1f66edac08fa62761d552e06e75765610f5a8ac344f022d47a9517063c6018` |
| canonical protonated PQR | `83067e92-1618-4d54-9e86-872475e472e4` | 1067351 | `243671f4fae21877d5b75a5628e5f3f744b5e4f83ed55aa4e62a2e12b18e2f0c` |
| display protonated PDB | `76905948-78c0-4ef3-85cd-9a19e2957ab0` | 1232714 | `4770f1a1ff9581201fa7963e39d9cafd73255168860ea3b351bfebaec47d66d6` |
| exact Meeko-input PQR | `b03a0e1e-3a99-4ab4-85c2-8bf5a2420522` | 1067887 | `8e7270ad172af2e829948c65772d0c4b861d291e45d1220d66f4ba564a7a7a4a` |
| accepted rigid receptor PDBQT | `d6cfd680-60ab-41c1-b1b0-3e2cfe412805` | 742122 | `cbf1f70c42dff930f1e1c6913842d4ded0d0d8f52959791438beac3a3cfceccd` |

The repeated pre-acceptance attempts also show that PDBFixer's initial placement of
missing atoms is not byte-deterministic in this tool version: the repaired and
relaxed coordinate hashes differed across retries while every structured plan and
acceptance boundary remained the same. Ankora therefore does not claim bitwise
reproducibility of receptor reconstruction. The exact accepted receptor artifacts
above are now the frozen common inputs for all downstream engines and will not be
regenerated per engine.

## Common M5V ligand lineage completed

The frozen neutral S/S state `7e9f0b74-4fc9-4338-975d-101d5b2c2620` was prepared
independently of its crystallographic coordinates. RDKit 2025.09.6 generated a pool
of 20 ETKDGv3 conformers with seed `20260819`; MMFF94s with the frozen 500-iteration
limit selected conformer 7 and converged from 133.495104 to 106.598827 kcal/mol.

- Conformer: `69efca0b-3fc4-4fe4-be6e-8360dde51373`
- SDF: 3,868 bytes, SHA-256
  `98f82ceb5743f31d22ad9c7b47249358802e89f71072ca20be99c6a0488245c9`
- Formula/formal charge/stereochemistry: C21H17ClN6, neutral, two assigned and zero
  undefined stereocenters

Meeko 0.7.1 processed exactly one molecule with explicit Gasteiger charges and wrote
one PDBQT without stderr or skipped/error records.

- Preparation: `c303fdf4-a770-44c6-94ca-657b0b917591`
- PDBQT: 2,693 bytes, SHA-256
  `d8ae862c0282bc0f2caae023960b622478c5413ce0cb9aedf739395a604bbf75`

This is the one common ligand lineage intended for Vina, AutoDock4 CPU, and
AutoDock-GPU. It is a docking input, not a binding or biological result. The common
receptor and ligand inputs are complete; no docking engine has run for this case yet.

## Frozen binding site completed

Binding site `3e327a7e-8824-4362-971f-fb63f9eb17c6` was created directly from the
immutable crystallographic M5V A:1101 coordinates with the pre-frozen 5.0 Å padding.
Ankora independently resolved center `(39.319, 13.427, 33.9225)` Å and size
`(21.598, 17.002000000000002, 15.307000000000002)` Å, numerically identical to the
pre-run protocol. It names accepted receptor `33f431a3...`, source structure
`5ba86431...`, has no warnings, and is not stale. Its 1,976-byte record has SHA-256
`9dab88d81a7c186f298861055b27af6cad84fb9945333987dbc8f467428063d1`.

The box was not entered manually, inferred from a predicted pocket, or adjusted after
viewing a docking result. No docking engine had run when this record was created.

## Common AutoGrid map set completed

AutoGrid 4.2.6 generated immutable map set
`fb6cfbce-de3d-40f6-8129-893bc825d265` from the accepted receptor PDBQT,
binding-site record, and exact common M5V preparation. Its identity key is
`635febbc0e8d6da73d23ae30855622c87187ad21c0ca2f6c1a49a2a8491db7cc`.
The executable SHA-256 is
`797efce687d1ae82df59726461e0e1966b3d8edb0f8b187f982fa1ab0c12da9e`
and the exact GPF SHA-256 is
`43e03e470da32ff55e0067532c753b944c182cbb30cc7cb2481078a35202b190`.

The frozen 0.375 Å spacing realizes `58 × 46 × 42` intervals and physical dimensions
`(21.75, 17.25, 15.75)` Å around the unchanged requested center. Receptor atom types
are `A, C, HD, N, NA, OA, SA`; compatible M5V types are `A, C, Cl, N, NA`. AutoGrid
exited zero after 14.39 s with empty stdout/stderr and a recorded `Successful
Completion`. The set contains five affinity maps, electrostatic/desolvation maps,
field/grid files, the GPF/log, and a byte-identical receptor PDBQT. There are no
warnings or incompatible ligands.

The 10,071-byte structured record has SHA-256
`b92b4898b08e6325cf80eee5014d490bebc97d0d40e91a32d3dc52e363406a63`.
This one map set is frozen for AutoDock4 CPU and every AutoDock-GPU repeat; it will
not be regenerated per engine or repeat. No docking result existed when it was
created.

## Vina execution and exact repeat completed

AutoDock Vina 1.2.7 completed jobs
`bad5d41e-a87a-4218-8064-57f6e9acc5a9` and
`7f36d5df-2708-418b-b164-3531f42441fa` with the exact common receptor and ligand,
the frozen box, one CPU thread, seed `20260823`, exhaustiveness 8, nine modes,
minimum inter-mode RMSD 1.0 Å, and energy range 3.0 kcal/mol. Both executions exited
zero with empty stderr in approximately 21 seconds.

Both jobs retained the same 26,667-byte combined output, SHA-256
`25ab1b3e4e8d30b6def749b5149ea0faecba4438585eb12110b2c6ae80377356`.
Every one of the nine separated pose artifacts is byte-identical across jobs. Their
Vina score sequence is `-8.807, -8.377, -8.011, -7.627, -7.464, -7.427, -7.347,
-7.307, -7.113` kcal/mol. The structured records are 13,489 bytes each; their hashes
differ because job identity/timestamps are provenance:

- primary: SHA-256 `3c129b0c73eef16b37231155509ad56d77e49af6dbd38d94142c9cc441bd8618`
- exact repeat: SHA-256 `2aeba3a92ba95d59b98981eeb4f51f7341a78ab357f43000fbf4a88447a5b25d`

This establishes bitwise reproducibility of Vina's pose outputs for this exact local
build and protocol. The reported inter-mode RMSD bounds measure distance from Vina's
best mode, not crystallographic recovery; no recovery claim is made until the frozen
M7 in-place symmetry-aware comparison is recorded.

## AutoDock4 CPU execution and exact repeat completed

AutoDock 4.2.6 CPU jobs `e01e29a6-a956-47c2-813a-923dc1bcfd19` and
`f5edcfe7-613a-4f14-98b4-81e98c3211f4` reused exact map set `fb6cfbce...` and common
M5V PDBQT. Each ran 10 LGA searches with population 150, 2,500,000 evaluations,
27,000 generations, seeds `20260824/20260824`, and 2.0 Å clustering. Both exited
zero after approximately 184 seconds with empty stdout/stderr and logged successful
completion. Their exact DPF is byte-identical, SHA-256
`82509a48837a13ec0ea358af4f238d713b9d87a6a01e78db447097d076b3f4f1`.

Both jobs produced the same three clusters and the same ten byte-identical run poses:

| Cluster | Lowest / mean energy (kcal/mol) | Population | Runs |
| ---: | ---: | ---: | --- |
| 1 | -6.03 / -5.98 | 5 | 10, 2, 8, 7, 6 |
| 2 | -5.96 / -5.90 | 2 | 3, 4 |
| 3 | -5.84 / -5.83 | 3 | 1, 5, 9 |

The DLG files differ only in run metadata/timing (76,610 versus 76,608 bytes; hashes
`f5414715...` and `4218040c...`), while all scientific run-pose hashes, energies,
cluster assignments, and populations match exactly. The 10,936-byte record hashes
are `bd305e265774b10e13f524b6bea4c7e0b4fce5299007224f1e70b62f89909a40`
and `899e460cd276bb5cb4d2d03d70216a64db11a91739fa008f0657bdd4ad11c773`.
This is exact same-seed reproducibility of the parsed scientific result for this CPU
build. Energies remain AutoDock4 binding energies and are not compared numerically to
Vina scores; crystallographic recovery remains pending M7.

## AutoDock-GPU six-repeat population completed

AutoDock-GPU 1.6 jobs `e59074fc-220b-4b12-9e4a-d83637c2f506`,
`8a410345-5aca-4ab8-859c-7fc4b5b53e4d`,
`0e272735-7a8f-4509-a5ed-f5aca16b352d`,
`4b79460a-32a0-44a1-a768-456a57ec7d45`,
`202a115d-7821-4ddb-a567-9232b2f42a1d`, and
`0d7e3fc3-d767-484e-a629-f9d56ce79d09` reused exact map set
`fb6cfbce...` and common M5V PDBQT. Every job used 10 runs, population 150,
2,500,000 evaluations, ADADELTA local search, disabled heuristics and autostop,
seeds `20260826/20260826/20260826`, 2.0 Å clustering, and device 1. The recorded
device is `NVIDIA GeForce RTX 5050 Laptop GPU`; the x86_64 Release executable
SHA-256 is
`be21dd5dea36a391e3d77286cd8a5bf18b080306d32c7178c56f0a9e4f373bbf`.

All six jobs completed successfully in 4.547–4.625 seconds. Each raw stderr
contains the compiler message `3 warnings generated.` and each stdout ends with
`All jobs ran without errors.`; both streams and every DLG/run pose remain
preserved. The job-level non-reproducibility warning cites Ankora's earlier
six-repeat device calibration spread of 0.13 kcal/mol. That historical capability
measurement is not substituted for this case's directly observed 0.03 kcal/mol
spread.

| Job | Best cluster lowest / mean energy (kcal/mol) | Population | Runs | Record SHA-256 | DLG SHA-256 |
| --- | ---: | ---: | --- | --- | --- |
| `e59074fc...` | -6.88 / -6.87 | 3 | 9, 4, 7 | `d366e47a17760d051bbd70889b17a524bc84968406dfb72d314686666d29b3b2` | `9856496fa59f3079cd176aa2819c1ea112faa902bd058b9f917e2cc7e1fc78e9` |
| `8a410345...` | -6.88 / -6.88 | 2 | 10, 9 | `a345a10056c01a7f8f827226f1bef244137baa85093c5cecdd08d6a6e019dc60` | `8c7848c27932caaa2c2c09839a89611dc4b3557f40313b9a0c5a880bea710216` |
| `0e272735...` | -6.87 / -6.67 | 2 | 2, 5 | `f6354145edb657960428ab1a6a636f1a0c9d5625178deaa8271a4a653ae6eeb8` | `4aebc4ab4c07428ce5abbda35eac04c91e44f182f60dd5a8c83480d04bf145c0` |
| `4b79460a...` | -6.88 / -6.80 | 4 | 7, 3, 10, 5 | `036fde4c18b2a2842be4194d6e8d01f146acdabc0bd7945651ed2a6114898cbb` | `311fd21f65c99c536f74ce25a660e5b23d9c5b3b955a11047e4807101b28ff64` |
| `202a115d...` | -6.89 / -6.87 | 5 | 9, 8, 4, 7, 2 | `94ed509802f9381c6e474f1053c8a0cadceb336a255e834bae264f358e027342` | `ea350eeeebce3643ae9e81f6d6561c106ee842278b7aa0641caebc43d5859b6a` |
| `0d7e3fc3...` | -6.86 / -6.72 | 4 | 4, 9, 2, 8 | `753d6540d07ed8f071b74e6aa097165a31b84e119b114f3770d0bc5a91d04f01` | `1aabcddc227b15f96bb2f569cad69a76ecb664cf2e2201f8f076c869bd1598e4` |

Across repeats, best-cluster lowest energy has mean -6.8767 kcal/mol,
population standard deviation 0.0094 kcal/mol (sample standard deviation 0.0103),
and range -6.89 to -6.86 kcal/mol. Best-cluster population ranges from 2 to 5
with mean 3.33. All six jobs produced two clusters; their ten pose hashes and
cluster membership vary between repeats. This is direct evidence of the expected
stochastic GPU population, not a failed reproducibility check and not a claim that
GPU scores can be compared numerically with Vina scores. Crystallographic sampling
and ranking remain unclassified until the frozen M7 RMSD measurements are recorded.

## Frozen crystallographic redocking measurements completed

M7 measured every retained pose from both Vina jobs, both AutoDock4 CPU jobs,
and all six AutoDock-GPU jobs against the exact 28-heavy-atom crystallographic
M5V SDF, SHA-256
`d1f7ec02ca9a2c1d1a70570db427bbcc4ce10c6be20a959acf2cd4aaf56f7f45`.
RDKit 2025.09.6 computed symmetry-aware heavy-atom RMSD in place; no pose was
superimposed before measurement. The frozen recovery boundary is 2.0 Å inclusive.

| Validation | Source | Top-1 (Å) | Best top 5 (Å) | Best overall (Å) | First recovered | Recovered | Outcome | Record SHA-256 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `7616172a...` | Vina `bad5d41e...` | 2.0596 | 2.0596 | 2.0596 | — | 0/9 | not recovered | `e81193a56a9fecf33a61cf8738f0855c0bd518359e84237827019493ac878ab4` |
| `78090f86...` | Vina `7f36d5df...` | 2.0596 | 2.0596 | 2.0596 | — | 0/9 | not recovered | `701597d35dcc5306e06e8e2d8eefae9811330192e8904a5f06396cbe31cb89a2` |
| `9e7c2949...` | CPU `e01e29a6...` | 3.7640 | 1.9284 | 1.2274 | rank 5 | 3/10 | recovered, misranked | `26a9457fef34bda79cc25132fa5b87237be97631898147e0243433f6e831b7c2` |
| `1ef8db6d...` | CPU `f5edcfe7...` | 3.7640 | 1.9284 | 1.2274 | rank 5 | 3/10 | recovered, misranked | `cab57ac1760f600833c9100713c43933d6597e8ae3ff84370bdb7aa732dc5c08` |
| `f57dd240...` | GPU `e59074fc...` | 7.9009 | 3.7442 | 3.7301 | — | 0/10 | not recovered | `22eb21f31972b05a843b9af1cb0b6612eb4ba6d12144ace9d1304074f3499923` |
| `7389b525...` | GPU `8a410345...` | 7.9117 | 3.7440 | 3.7351 | — | 0/10 | not recovered | `2effeae6bd0516f87b8337b5d3bfe86e588bd0a5354083dfc9f8a34a8b293b7f` |
| `efed35eb...` | GPU `0e272735...` | 7.9194 | 3.7452 | 3.7402 | — | 0/10 | not recovered | `385998530c110987c6ed1f33f9fbe9e4e9fba3f9c61965c165dce756ab3f339c` |
| `fb7bae51...` | GPU `4b79460a...` | 7.9025 | 3.7378 | 3.7378 | — | 0/10 | not recovered | `c317539efb161b62e965cfcdf374493c0833a22c1c6f7798dccf48fc3374a54a` |
| `a7bc7949...` | GPU `202a115d...` | 7.8968 | 7.8968 | 3.7382 | — | 0/10 | not recovered | `880fbc9d9a5cc1c0b69bdb9ae8997e4946ae8048e07c9af5154163f6b0267006` |
| `ea79fd0f...` | GPU `0d7e3fc3...` | 7.9102 | 3.7460 | 3.7350 | — | 0/10 | not recovered | `a68a5e543a53fabce8f3c01dbce620e9ffd5e6b72396f6f3068451a26040f2b3` |

Vina's primary and exact repeat reproduce all nine RMSDs exactly. Its top-ranked
mode is also its closest mode at 2.0596 Å, only 0.0596 Å outside the pre-frozen
boundary; the boundary is not relaxed after observing this near miss. AutoDock4
CPU's exact repeat reproduces every RMSD and verdict. CPU sampled three poses under
2.0 Å, but its top-ranked run 10 is 3.7640 Å; the first recovery is rank 5/run 6
at 1.9284 Å and the closest is rank 6/run 3 at 1.2274 Å. Its structured verdict is
therefore `recovered_but_misranked`, not an undifferentiated pass.

No GPU repeat sampled below 2.0 Å. Their top-ranked poses occupy the same distant
family at 7.8968–7.9194 Å, while their closest poses occupy another family at
3.7301–3.7402 Å. Accordingly all six outcomes are `not_recovered`; stochastic
variation did not change the verdict in this six-repeat population. These findings
do not compare engine energy scales or establish general engine superiority. Under
the frozen protocol, only CPU now requires M9 analysis: its top-ranked pose and its
different first-recovering pose.

## Frozen conditional M9 interaction analyses completed

Only AutoDock4 CPU sampled below 2.0 Å, so the pre-run rule required two M9
records from the primary CPU job: its top-ranked cluster-1/run-10 pose and its
different first-recovering rank-5/run-6 pose. No Vina or GPU interaction analysis
was created merely to fill a table, because those engines did not satisfy the
frozen condition.

Both analyses used ProLIF 2.2.1, profile `ankora-default-v1`, and a 6.0 Å vicinity
cutoff. They reference the exact protonated receptor PDB SHA-256
`4770f1a1ff9581201fa7963e39d9cafd73255168860ea3b351bfebaec47d66d6`
and independently generated conformer SHA-256
`98f82ceb5743f31d22ad9c7b47249358802e89f71072ca20be99c6a0488245c9`.
Neither record has a warning.

| Analysis | Exact pose | Pose SHA-256 | Contacts | Contact summary | Record SHA-256 |
| --- | --- | --- | ---: | --- | --- |
| `f0b40692-4088-42eb-998f-99f51a53e137` | top-ranked, cluster 1 / run 10, 3.7640 Å RMSD | `3406a5b498980b19b11d6beffff811065b386128788cd2e902e021a043cfc46f` | 33 | 31 hydrophobic; 2 ligand-acceptor H-bonds | `3be7364af49458885a7ab9fb4b66d9d0e67fe90498f9f3ef914c624b511ed4e7` |
| `4cfe1c68-ad02-4d03-8314-d7067d31867e` | first recovered, rank 5 / cluster 1 / run 6, 1.9284 Å RMSD | `e2c72c8974e0f3b440e3736b22d0f7767506a15d29a52c6ca6f77e5e6f9e9c5f` | 41 | 39 hydrophobic; 1 ligand-acceptor H-bond; 1 edge-to-face π-stack | `9bcf2c5fd76533d8b6167e725293490419590b01edb4c730c1507b0c21f42a8b` |

The top-ranked pose contacts MET A:752, TRP A:760, LYS A:779, TYR A:813,
VAL A:828, PHE A:908, and ILE A:910; its H-bonds are reported to LYS A:779 and
VAL A:828. The first-recovering pose contacts MET A:752, TRP A:760, TYR A:813,
VAL A:828, MET A:900, PHE A:908, and ILE A:910; its H-bond is to VAL A:828 and
its edge-to-face π-stack to TYR A:813. These are detector-reported geometric
contacts for two exact poses, not affinity measurements or evidence that the
misranked pose is biologically correct.

## Completed result package frozen and verified

The post-run specification
`reference_cases/PIK3CD_6OCO_M5V_RESULTS.spec.json` names the complete accepted
lineage: 29 immutable structured records and 122 hash-verified scientific
artifacts. It retains every pose from both Vina jobs, both AutoDock4 CPU jobs,
and all six AutoDock-GPU populations rather than selecting only the favorable or
closest poses. The generated manifest and human-readable matrix have evidence
SHA-256
`c62d8d2e7f813c1a4799dfad3c264d3cfbeca48918979c53e2653e12c396f1dd`.

The freezer's independent `--check` reproduced that hash and verified every
record identity, artifact byte count, and artifact SHA-256 without invoking a
scientific executable. The original pre-run specification and its evidence hash
`7fe1ac4cc8aa1fb46569d5e8bce77b376fab3138e01238efa4d23197e25e8cfb`
remain unchanged. The case is closed under its frozen 2.0 Å recovery boundary:
Vina is a documented near miss, AutoDock4 CPU samples but misranks recovered
poses, and none of the six GPU repeats recovers M5V. No result was discarded and
no parameter, box, chemical state, or threshold was tuned after observation.
Absolute machine roots in copied display fields are replaced deterministically
with portable placeholders; exact source-record and artifact hashes still bind
the unmodified private evidence bytes.
