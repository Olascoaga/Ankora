# ADR-032: Explicit Semi-Flexible Ligand Control, Bounded Receptor Side-Chain Flexibility, and Pose-Complex Identity

- **Status:** Proposed (M0 Frozen Contract for v0.2)
- **Date:** 2026-11-18
- **Baseline:** frozen `v0.1.0-beta.2` commit `36f1c0e9b11adb579920437d23298472ac948bcf`
- **Amends:** the scope boundaries of [`CODEX_BOOTSTRAP.md`](../../../CODEX_BOOTSTRAP.md), [`RECEPTOR_PREPARATION_POLICY.md`](../../scientific/RECEPTOR_PREPARATION_POLICY.md), and [`LIGAND_PREPARATION_POLICY.md`](../../scientific/LIGAND_PREPARATION_POLICY.md) to admit the two explicit, opt-in semi-flexible controls defined below. All existing rigid-receptor and default-torsion behavior is preserved unchanged as the default.
- **Extends:** `ADR-004` (immutable originals), `ADR-005` (traceable derivatives), `ADR-011` (stale propagation), `ADR-015` (AutoDock4 / AutoGrid4), `ADR-027` / `ADR-028` (Linux GNINA)
- **Platforms:** Windows 11 x64 **and** Linux `x86_64` (GNINA-specific paths remain Linux-only per `ADR-027`)
- **Installer size delta over frozen baselines:** `0` bytes — `0` new executables and `0` new Python distributions. Both capabilities are explicit argument-array and option surfaces over the already-shipped, already-hash-verified `Meeko 0.7.1` (pinned in both `requirements/windows-py312.in` and `requirements/linux-py312.in`), `AutoDock Vina 1.2.7`, `AutoGrid4`/`AutoDock4 4.2.6`, `AutoDock-GPU 1.6`, and Linux `GNINA 1.3.3`.

## Context

At the frozen baseline every docking run is rigid-receptor, and ligand torsion handling is whatever `mk_prepare_ligand` produces by default: the ligand adapter passes only `-i`, `-o`, and `--charge_model`. Two consequences follow.

**Ligand side.** Meeko's default macrocycle handling breaks macrocyclic rings open and inserts `CG0`/`G0` glue pseudoatoms to sample ring conformations. `DOCKING_POLICY.md` records the hard consequence: stock AutoGrid4 `4.2.6` is limited to `14` ligand affinity-map atom types and **does not parameterize** `CG0`/`G0`, so any macrocycle is retained as an explicit engine-incompatible row for the whole AutoDock4 family — Ankora correctly refuses to coerce pseudoatoms to carbon or to drop the molecule from the campaign denominator. The scientist therefore currently has no route to dock a macrocycle on the AutoDock4 family at all, and no route to express "treat this scaffold as rigid" for any ligand. There is also no recorded effective `TORSDOF`, even though torsional degrees of freedom are the single largest driver of search difficulty.

**Receptor side.** Rigid-receptor docking cannot represent pocket side chains that are known to reorganize on binding. The common and defensible middle ground — a small, explicitly chosen set of pocket side chains free to rotate about their `chi` torsions while the backbone stays fixed — is supported natively by all four engines but is not exposed. Enabling it is not a free improvement: it adds search degrees of freedom, it changes what an AutoGrid4 map set must contain, and it means a "pose" is no longer a ligand alone but a **coupled ligand + moved-side-chain complex**. Every downstream consumer that currently assumes a pose is a ligand against a fixed receptor — the `Mol*` viewer, physical pose validity (`M3`), interaction fingerprints (`M4`), rank-space consensus (`M5`, [`ADR-030`](ADR-030-rank-space-consensus-prioritization.md)), and `Export` — becomes wrong unless that coupling is made an explicit, hash-bound identity.

## Decision

Both capabilities are **explicit, opt-in, and off by default**. Absent an explicit spec, v0.2 reproduces frozen-baseline behavior exactly.

### 1. Explicit Semi-Flexible Ligand Control (`LigandFlexibilitySpec`, `Meeko 0.7.1`)

#### 1.1 Explicit `macrocycle_policy`

`MacrocyclePolicy` is an explicit, recorded, two-valued choice with **no silent default substitution**:

| Policy | Meeko behavior | Consequence |
| --- | --- | --- |
| `"flexible_pseudoatoms"` | Meeko's default macrocycle ring-opening with `CG0`/`G0` glue pseudoatoms | Samples ring conformations. Remains **engine-incompatible for the whole AutoDock4 family** under the stock AutoGrid4 `14`-type ligand limit documented in `DOCKING_POLICY.md`; the molecule is still retained as an explicit incompatible row and never dropped from the denominator. |
| `"rigid_input_conformation"` | `--rigid_macrocycles` | Keeps the macrocyclic ring at its prepared input conformation, emitting **no** `CG0`/`G0` glue pseudoatoms. This legitimately unlocks macrocycles for `AutoGrid4` / `AutoDock4` / `AutoDock-GPU` **without any atom-type coercion**, because the pseudoatoms are never created rather than being relabelled. |

- The `"rigid_input_conformation"` unlock is a **scope trade, not a free win**, and must be reported as such: ring conformational sampling is surrendered, so the result is conditional on the prepared input ring conformation being relevant. Ankora records that conditionality in `Methods` and `Export` rather than presenting the macrocycle as fully sampled.
- Ankora never selects a macrocycle policy on the scientist's behalf, and never switches policy to make a molecule engine-compatible.

#### 1.2 Selective bond and scaffold rigidification

- `--rigidify_bonds_smarts` with its paired `-b` bond-index arguments expresses "hold these matched bonds rigid," enabling explicit scaffold rigidification driven by a recorded SMARTS pattern.
- Every supplied SMARTS pattern and bond-index pair is recorded verbatim in provenance. A pattern that matches nothing is reported as a structured outcome, never silently ignored.

#### 1.3 Explicit `--flexible_amides` toggle

- **Off by default.** Enabling it emits a structured planarity warning, because amide bonds are conjugated and substantially planar; freeing them samples geometries that are usually chemically unrealistic. The warning is recorded with the request, not merely displayed.

#### 1.4 Recorded effective `TORSDOF`

- The effective `TORSDOF` actually present in the produced `.pdbqt` is parsed and recorded on every ligand preparation, under every policy and rigidification combination. This makes the search-difficulty consequence of each explicit flexibility choice auditable, and gives `M1` onward a recorded quantity rather than an inferred one.

#### 1.5 Explicit derivative `--local_only` pose refinement

- `--local_only` local pose refinement in `Vina 1.2.7` and `GNINA 1.3.3` is exposed only as an **explicit, traceable derivative** of an existing recorded pose under `ADR-005`, never as a silent post-process of a docking run.
- The parent pose, the refined pose, and the refinement invocation are all retained; the parent is never overwritten, consistent with `ADR-004`.

### 2. Bounded Receptor Side-Chain Flexibility (`ReceptorFlexSpec`, `>= 1` pocket residue, `1`–`4` recommended)

#### 2.1 Explicit visual selection and hard rejections

- `ReceptorFlexMode` defaults to rigid. Side-chain flexibility (`sidechain_flex`) requires **at least `1`** explicitly selected pocket residue in the `Mol*` viewer — an empty selection is rejected, never silently treated as rigid — recorded as fully qualified residue locators (chain, residue number, insertion code, residue name). The **recommended** budget is `1`–`4` residues and `<= 12` added `chi` torsions; that ceiling is a *recommendation enforced by warning*, not a hard cap, exactly as specified in §2.2. A selection exceeding `> 4` residues or `> 12` added `chi` torsions is accepted and executed as selected, emitting `DOCKING_FLEXRES_DOF_HIGH`; Ankora never truncates the selection to fit the recommendation.
- **Hard rejections** (`422`, never a warning, never a silent drop):
  - `GLY` — no rotatable side chain to free.
  - `ALA` — no `chi` torsion.
  - `PRO` — side chain is covalently closed onto the backbone; freeing it is not a side-chain rotation.
  - `CYX` — disulfide-bonded cysteine; moving it would break a recorded covalent bond.
  - Duplicate locators, and locators that do not resolve uniquely in the prepared receptor.

#### 2.2 Degree-of-freedom budget

- **Recommended budget:** `1`–`4` residues (minimum `>= 1`, per §2.1) and `<= 12` added `chi` torsions.
- Exceeding the budget — `> 4` residues **or** `> 12` added `chi` torsions — emits the structured warning `DOCKING_FLEXRES_DOF_HIGH` carrying the exact residue count and added-torsion count, and the run proceeds with the selection as made. Ankora **never** silently truncates or otherwise reduces the selection, and never raises search effort to compensate — consistent with `ADR-018` / `ADR-019`, which forbid Ankora from adjusting sampling controls on the scientist's behalf.
- The warning exists because added side-chain torsions multiply the search space against a fixed exhaustiveness: the same sampling budget spread over more degrees of freedom is a *less* converged search, not a better model.

#### 2.3 Immutable `Meeko -f` split

- Receptor preparation with `sidechain_flex` produces an **immutable paired split** via `mk_prepare_receptor -f`: `receptor_rigid.pdbqt` (everything held fixed) and `receptor_flex.pdbqt` (the moving side chains).
- Both members are hashed, stored immutably, and bound together with the `flex_residues` selection. Neither is ever edited in place; any change to the selection produces a new derivative pair and propagates staleness to dependents per `ADR-011`.

#### 2.4 Cross-engine execution

| Engine | Flexible-side-chain invocation | Platform |
| --- | --- | --- |
| `AutoDock Vina 1.2.7` | `--flex` | Windows + Linux |
| `AutoDock4 4.2.6` | DPF `flexres` | Windows + Linux |
| `AutoDock-GPU 1.6` | `--flexres` | Windows (`OpenCL`) + Linux (`CUDA 12`) |
| `GNINA 1.3.3` | `--flex` / `--out_flex` | Linux only |

- All invocations are constructed as argument arrays, never shell strings.
- **M1 Gate 0 verification requirement.** Every upstream CLI surface named in this ADR — the `Meeko 0.7.1` ligand flags (`--rigid_macrocycles`, `--rigidify_bonds_smarts`/`-b`, `--flexible_amides`), the `mk_prepare_receptor -f` split, and each engine's flexible-side-chain flag including `GNINA 1.3.3 --flex` / `--out_flex` — must be confirmed against the pinned executables by a recorded `M1 Gate 0` capability probe before implementation lands, following the `ADR-028` precedent of empirically probing CLI contracts (where `--cnn default` was found to fail closed) rather than assuming documented behavior. Any flag that does not behave as specified here blocks the corresponding path rather than being worked around.
- `AutoDock-GPU` flexible-side-chain runs inherit the existing non-bitwise-reproducibility notice (`DOCKING_GPU_REPRODUCIBILITY_UNVERIFIED`), and CPU incompatibility is never reclassified as GPU compatibility.

### 3. Invariant `E7` — `AUTOGRID_FLEXRES_MAP_MISMATCH` (fail-closed)

- An `AutoGrid4` map set used with `sidechain_flex` **must** be built strictly on `receptor_rigid.pdbqt`, with the moving side-chain atoms **excluded** from the grid.
- The map set is **hash-bound to the pair `(receptor_rigid_sha256, flex_residues)`**, and that binding is checked before every AutoDock4-family run.
- Reusing a full-receptor map set — including a correct, previously valid map set built before the residues were freed — **fails closed** with `AUTOGRID_FLEXRES_MAP_MISMATCH`. No regeneration is attempted silently and no warning-and-continue path exists.
- **Why this must fail closed:** a full-receptor map already contains the potential contributed by the side-chain atoms that are now modelled as explicitly moving atoms. Running that map with `flexres` double-counts those atoms, producing an energy that is neither the rigid nor the flexible model. The failure mode is silent and numerically plausible, which is exactly why it cannot be left to a warning.
- The independent stock-AutoGrid4 ceiling of `20` receptor atom types documented in `DOCKING_POLICY.md` continues to be checked against `receptor_rigid.pdbqt` before map generation.

### 4. Invariant `E8` — `PoseComplexIdentity` (coupled complex materialization)

Under `sidechain_flex`, a pose is a **coupled complex**, and its identity says so:

- Every pose carries its own `pose_flex_sidechains_sha256` alongside the ligand pose identity. A pose is never identified by its ligand coordinates alone, because two poses with identical ligand coordinates and different side-chain rotamers are different scientific results.
- Ankora **deterministically materializes** the coupled full-atom complex `(receptor_rigid + pose_flex_sidechains + ligand_pose)` — same inputs, same bytes, same hash — and every downstream consumer reads that materialized complex rather than reconstructing its own:

| Consumer | Milestone | Requirement under `E8` |
| --- | --- | --- |
| `Mol*` viewer | existing | Renders the coupled complex, with the moved side chains **overlaid against the original crystal rotamers** so the scientist sees exactly what moved and how far. |
| `PoseBusters` | `M3` | Physical validity is assessed on the coupled complex, so side-chain/ligand clashes created by the flexible search are detected rather than invisible. |
| `ProLIF 2.2.1` | `M4` | Interaction fingerprints are computed against the moved side chains, not the original rotamers; the existing create-only hash-verified-triple contract of `POSE_INTERACTION_POLICY.md` extends to include `pose_flex_sidechains_sha256`. |
| `PC-Q` | `M5` | Clustering is **joint over `(ligand, flex)` coordinates** at the `<= 2.0 Å` complete-linkage threshold of `ADR-030` `E3`, and cross-family `--score_only` rescoring is performed on the coupled complex. Clustering on ligand coordinates alone would collapse genuinely distinct complexes into one representative. |
| `Export` | `v5` | The bundle format increments from `4` to `5`, adding the flexibility specs, the effective `TORSDOF`, the `receptor_rigid`/`receptor_flex` split identities, and `pose_flex_sidechains_sha256` per pose. Pre-`v5` bundles remain valid and are never rewritten. |

- Rigid-receptor poses are unaffected: `pose_flex_sidechains_sha256` is absent, and every consumer takes its existing frozen-baseline path.

### 5. Explicit Non-Goals and deferred backlog

- **Receptor Ensemble Docking** — discrete multi-structure docking across `2`–`5` `apo`/`holo` receptor conformers is **explicitly deferred to `v0.3+`** by scientist decision dated `2026-11-18`. It is a recorded backlog item, not a rejected idea, and no v0.2 contract may partially implement it.
- **Continuous full-backbone receptor flexibility during search** remains **excluded**. Post-docking pocket relaxation stays behind the conditional `M7` `OpenMM` spike, which is itself gated on the offline size budget of [`ADR-031`](ADR-031-external-benchmark-boundary.md).
- **Covalent / tethered docking** remains out of v0.2 scope entirely.
- Automatic selection of which residues to free, or automated detection of "flexible" pockets, is out of scope: the selection is the scientist's explicit, recorded decision.
- Ensemble-averaged or minimum-over-conformer scoring is out of scope; it would reintroduce exactly the pooling that `DOCKING_POLICY.md` and `ADR-030` forbid.

## M0 contract surface

These invariants bind to the M0 Pydantic contract module `backend/src/ankora_backend/schemas/v02_contracts.py`, whose implementation is a separate M0 deliverable and is **not present at the frozen baseline** `36f1c0e9b11adb579920437d23298472ac948bcf`. This ADR fixes the contract surface that module must expose:

| Contract | Role under this ADR |
| --- | --- |
| `MacrocyclePolicy` | Closed two-valued enumeration (`flexible_pseudoatoms`, `rigid_input_conformation`) with no implicit default substitution. |
| `ReceptorFlexMode` | Explicit rigid-vs-`sidechain_flex` selector; rigid is the default and reproduces frozen-baseline behavior. |
| `LigandFlexibilitySpec` | Macrocycle policy, rigidification SMARTS and bond indices, `--flexible_amides` toggle with its planarity warning, and the recorded effective `TORSDOF`. |
| `ReceptorFlexSpec` | The validated `FlexRes` locators (`>= 1` required, `1`–`4` recommended), the rejection rules for `GLY`/`ALA`/`PRO`/`CYX` and duplicates, the added-`chi`-torsion count, the `DOCKING_FLEXRES_DOF_HIGH` budget state, and the immutable `receptor_rigid`/`receptor_flex` split identities. |
| `PoseComplexIdentity` | `pose_flex_sidechains_sha256` plus the deterministic coupled-complex identity consumed by `Mol*`, `PoseBusters`, `ProLIF`, `PC-Q`, and `Export v5`. |
| `ProtocolSpec` | Carries both flexibility specs as part of the pre-declared, hash-recorded protocol identity, so a flexible run is never mistaken for a rigid one in provenance or comparison. |

## Primary-source references

Bibliographic fields are recorded below only where independently verifiable in this repository or unambiguous from the DOI; remaining identifiers must be expanded under the DOI-verified citation rule of [`METHODS_REPORT_POLICY.md`](../../scientific/METHODS_REPORT_POLICY.md) before they appear in any generated `Methods` output.

- McNutt *et al.*, *J. Cheminform.* 2021 — `10.1186/s13321-021-00522-2` (GNINA; already established in this repository by `ADR-027` / `ADR-028`).
- `10.1039/D3SC04185A` — *Chem. Sci.* 2024, `PoseBusters` (the `M3` physical-validity consumer of the `E8` coupled complex).
