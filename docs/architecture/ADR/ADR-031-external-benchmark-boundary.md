# ADR-031: External Comparison Benchmark Boundary and Installer Size Budget Guard

- **Status:** Proposed (M0 Frozen Contract for v0.2)
- **Date:** 2026-11-18
- **Baseline:** frozen `v0.1.0-beta.2` commit `36f1c0e9b11adb579920437d23298472ac948bcf`
- **Extends:** `ADR-012` (validation by reference cases), `ADR-024` (self-contained offline scientific installer), `ADR-026` / `ADR-029` (Linux port and modular offline Linux distribution)
- **Installer size delta over frozen baselines:** `0` bytes (this ADR adds no product dependency; it adds a CI guard and a documentation obligation)
- **Scope:** The architectural boundary between Ankora's shipped offline desktop product and any external comparison benchmark harness, plus the statistical discipline and size-budget accounting that every v0.2 ADR must satisfy.

## Context

Ankora is positioned against other structure-based virtual screening platforms, and an external comparison against a pinned third-party consensus-docking harness (e.g. pinned `DockM8` versions; scientist-supplied reference `PMC13613745`) is a legitimate scientific objective for v0.2. It is also the single most likely route by which the product's two hardest-won properties get destroyed:

1. **Offline self-sufficiency.** `ADR-024` requires supported workflows to run with no network, no user-installed Python/Conda/Java, no `PATH` edits, and no environment configuration. External harnesses typically assume container runtimes, package managers, network-fetched model weights, and multi-gigabyte benchmark corpora. A single benchmark dependency leaking into the product dependency graph converts a double-click install into an engineering project.
2. **Installer size discipline.** The frozen baseline installers are the product of sustained reduction work (`ADR-029`'s two-tier modular Linux distribution exists precisely because a `4.66 GiB` uncompressed GNINA/CUDA closure could not be bundled). v0.2 adds capability across seven milestones. Without per-ADR byte accounting, size regression is discovered at release time, when it is most expensive to reverse.

A third risk is statistical rather than architectural. A platform comparison produces a verdict, and a verdict chosen by inspecting the data it is evaluated on is optimistically biased (Cawley & Talbot, *JMLR* 11, 2010). Comparison results must therefore be governed by a pre-declared out-of-sample protocol, not assembled after the numbers are seen.

## Decision

### 1. Hard architectural separation of the benchmark harness

External comparison benchmarking lives **strictly outside** the shipped product:

- **Outside the installers.** External benchmark runners, their orchestration code, container definitions, third-party harness checkouts, downloaded model weights, and comparison datasets are **never** members of the Windows `.exe` payload, the Linux `.deb`, the portable `.tar.zst`, the sources-companion archives, or the optional GNINA CUDA pack.
- **Outside the product dependency graph.** No benchmark-only dependency may enter `requirements/windows-py312.in`, `requirements/linux-py312.in`, or their locks. Container runtimes (Docker/Podman and equivalents) are **never** product runtime dependencies on either platform. Ankora's own services must never require, detect, or invoke a container runtime.
- **Outside the runtime.** The desktop application must remain fully functional, fully offline, with zero benchmark artifacts present. Removing every benchmark asset from a machine must not change any product code path.
- **One-directional data flow.** The harness consumes Ankora's **structured** outputs — `Export` bundle manifests and their recorded columns — and never reaches into Ankora's internals or parses human-readable logs, consistent with the repository rule that structured data is preferred wherever it exists. Ankora never imports, links, or calls external harness code.
- **Preserved raw outputs.** Raw outputs of every third-party tool executed by the harness are retained unmodified alongside the comparison record, under the same provenance discipline Ankora applies to its own scientific tools.
- **Pinned third-party identity.** Any external harness under comparison is pinned to an exact version with recorded version identifiers and artifact digests. "Latest" is never a comparison target, and detected tool versions are recorded whenever tools are used.

### 2. Mandatory two-axis evaluation

A comparison claim is admissible only when **both** axes are reported. Reporting one alone is a misleading result and is rejected:

- **(a) Controlled comparison.** Identical prepared receptor, identical prepared ligand set, identical search box, identical splits, identical compound denominator, supplied to both platforms. This axis isolates sampling, scoring, and ranking behavior from everything upstream of it.
- **(b) End-to-end workflow comparison.** Each platform runs its own complete documented workflow from the same starting structure and compound set, including its own preparation, protonation, and binding-site decisions. This axis measures what a scientist actually experiences, including the cost and consequence of the explicit choices Ankora requires.

The two axes answer different questions and routinely disagree. Both results are published, including when (a) favors one platform and (b) favors the other. Neither axis may be presented as the headline with the other omitted.

### 3. Out-of-sample discipline

- **Grouped split.** Calibration and Confirmation sets are split with grouping by **parent compound** *and* by **Bemis-Murcko scaffold**, so no scaffold and no parent appears on both sides. The split is constructed and frozen at `M2`, before any comparison numbers exist.
- **Locked Confirmation set.** The Confirmation split is locked and single-use for a given claim. Protocol choices, consensus variant selection (including `PC-L2` promotion under [`ADR-030`](ADR-030-rank-space-consensus-prioritization.md)), thresholds, and hyperparameters are fixed on Calibration only.
- **Paired parent bootstrap `Δ BEDROC_20`.** The primary comparison statistic is the paired difference in `BEDROC` at `alpha = 20`, with uncertainty estimated by bootstrap resampling **over parent compounds** (the independent unit), not over rows, poses, or microstates.
- **`1-SE` parsimony rule.** Among configurations whose performance lies within one standard error of the best observed, the **simplest** is selected — fewer engines, fewer fitted parameters, fewer dependencies. A fitted variant does not displace an unfitted baseline on a difference inside the noise.
- **Explicit null verdict.** When the paired interval does not exclude zero, the recorded verdict is the exact phrase *"Insufficient evidence to prefer over baseline"*. This is a first-class, publishable outcome, not a failed experiment to be re-run with different settings.
- **Mandatory publication of negative and null results.** Every executed comparison that reaches a verdict is recorded and published under `docs/validation/`, including results that favor the external platform or show no difference. Selective reporting of favorable comparisons is forbidden. A comparison may not be silently abandoned after its numbers are seen.
- **No post-hoc metric substitution.** The primary metric is `BEDROC_20`, declared in advance. Additional metrics may be reported as secondary and labelled as such; they may never be promoted to primary after the fact.

### 4. CI installer-size budget guard

**Every v0.2 ADR that introduces or enables a dependency must declare its measured byte delta** against the frozen `v0.1.0-beta.2` baselines, as a required ADR metadata field (this ADR and [`ADR-030`](ADR-030-rank-space-consensus-prioritization.md) / [`ADR-032`](ADR-032-explicit-flexibility-and-pose-complex-identity.md) each declare `0` bytes). A declared delta is **measured**, never estimated. The CI guard fails closed when a packaged artifact exceeds its declared budget, and an undeclared delta is itself a failure.

#### Frozen baseline artifact sizes (repository-recorded)

| Baseline artifact | Size (bytes) | Size (MiB) | Recorded evidence |
| --- | ---: | ---: | --- |
| `Ankora_0.1.0_x64-setup.exe` (Windows slim) | `426,941,199` | `407.16` | [`PRIVATE_BETA_SLIM_INSTALLER_2026-10-20.md`](../../validation/PRIVATE_BETA_SLIM_INSTALLER_2026-10-20.md) |
| `Ankora_0.1.0_amd64.deb` (Linux core) | `285,567,716` | `272.34` | [`LINUX_OFFLINE_PACKAGE_SMOKE.md`](../../validation/LINUX_OFFLINE_PACKAGE_SMOKE.md) |
| `Ankora_0.1.0_linux_x86_64.tar.zst` (portable) | `329,218,220` | `313.97` | [`LINUX_OFFLINE_PACKAGE_SMOKE.md`](../../validation/LINUX_OFFLINE_PACKAGE_SMOKE.md) |

> **Baseline reconciliation.** Two consistent sets of baseline bytes exist. The table above records the **tracked validation-record** figures (`426,941,199` / `285,567,716` / `329,218,220` B). The `v0.1.0-beta.2` GitHub Release `SHA256SUMS.txt` published on `36f1c0e9b11adb579920437d23298472ac948bcf` carries `427,237,557` / `285,567,616` / `329,218,187` B for the same three artifacts. Both sets are legitimate — they are different builds of the same baseline — and neither is discarded. When the CI guard is implemented in `M0`/`M6`, **both** sets are locked into a **tracked CI baseline JSON manifest**, each entry naming its artifact, its byte count, its SHA-256, and its source (tracked validation record vs. release `SHA256SUMS.txt`), so the historical tracked-doc baselines and the released `v0.1.0-beta.2` bytes are cleanly reconciled in one hash-recorded place rather than reconciled by prose. The guard measures against that manifest and nothing else; the release `SHA256SUMS.txt` is not tracked in the repository at the frozen commit, so the manifest is what makes those figures auditable in-tree.

#### Declared per-milestone budget

| Milestone | Dependency introduced | Declared delta | Condition |
| --- | --- | ---: | --- |
| `M0` | none (contracts and ADRs only) | `0` bytes | Hard requirement |
| `M1` | none (existing pinned executables and flags only) | `0` bytes | Hard requirement |
| `M2` | none (grouped split logic on pinned `numpy`/`scipy`/RDKit) | `0` bytes | Hard requirement |
| `M3` | `posebusters` (pure-Python, MIT, wheel) | `< 1 MiB` | Must remain a pure-Python wheel with no new compiled closure; a binary-carrying release is rejected |
| `M7` | `OpenMM` ligand parameterization | **Not budgeted** | Gated behind a recorded offline spike; if the measured delta exceeds budget, it ships only as a **separate optional pack** on the `ADR-029` two-tier model, never inside the core installers |

`M4`–`M6` introduce no dependency beyond the already-pinned closure (notably `prolif==2.2.1`, `scipy==1.18.0`, `numpy==2.5.2`, present in both platform locks at the frozen baseline) and therefore declare `0` bytes; any change to that must be declared in its own ADR before implementation.

## Invariants and Non-Goals

- Shipping a container runtime, a benchmark corpus, or an external harness inside any Ankora installer is forbidden, in every variant and on both platforms.
- No comparison result may be published without both evaluation axes and its pre-declared split identity.
- No comparison may claim superiority from a difference that the paired parent bootstrap does not separate from zero.
- Benchmark execution never alters, re-derives, or overwrites product artifacts; original imported artifacts stay immutable per `ADR-004`.
- Tuning Ankora's protocols to maximize performance on a comparison corpus is explicitly out of scope and would void the out-of-sample discipline this ADR exists to protect.
- Vendoring, re-distributing, or re-licensing third-party harness code or benchmark datasets is out of scope.
- Claiming equivalence or superiority to any external platform on the basis of engineering smoke checks, rather than recorded scientific evidence, is forbidden under `ADR-012`.

## M0 contract surface

These obligations bind to the M0 Pydantic contract module `backend/src/ankora_backend/schemas/v02_contracts.py`, whose implementation is a separate M0 deliverable and is **not present at the frozen baseline** `36f1c0e9b11adb579920437d23298472ac948bcf`. This ADR fixes the contract surface that module must expose:

| Contract | Role under this ADR |
| --- | --- |
| `ProtocolSpec` | The pre-declared, hash-recorded protocol identity (engines, scoring functions, sampling controls, split identity) that makes a comparison reproducible and pins what was fixed before the Confirmation split was opened. |
| `PoseAssessment` | Per-pose physical-validity assessment carrying the `M3` verdict, so comparison claims can be stratified by pose validity instead of ranking on scores alone. |
| `PoseDiagnosticCheck` | One named individual check and its outcome within a `PoseAssessment`, retained individually rather than collapsed into a single pass/fail. |
| `ConformationalStrainDiagnostic` | Explicit strain diagnostic attached to a pose, reported as a diagnostic and never as an energy added to, or subtracted from, any docking score. |
| `RankingArtifact` | The `ADR-030` ranking table that the comparison consumes, including its tier counts and invariant parent denominator, which fixes the comparison denominator. |

## Primary-source references

Bibliographic fields are recorded below only where independently verifiable in this repository or unambiguous from the DOI; remaining identifiers are carried as scientist-supplied and must be expanded under the DOI-verified citation rule of [`METHODS_REPORT_POLICY.md`](../../scientific/METHODS_REPORT_POLICY.md) before they appear in any generated `Methods` output.

- Cawley & Talbot, *JMLR* 11, 2010 — over-fitting in model selection and the resulting selection bias in performance evaluation (the basis of the locked-Confirmation and `1-SE` rules).
- `10.1039/D3SC04185A` — *Chem. Sci.* 2024, `PoseBusters` (the `M3` physical pose-validity reference).
- `PMC13613745` — scientist-supplied external comparison-harness reference for the pinned third-party consensus-docking platform (`DockM8`).
- `10.1186/s13321-025-00973-x` — **GNINA 1.3** (scientist-supplied), recorded in [`ADR-030`](ADR-030-rank-space-consensus-prioritization.md). It is **not** a DockM8 reference and must not be cited as the external comparison harness. Its bibliographic fields are unverified in this repository and must be resolved against Crossref before any generated `Methods` output renders them.
- McNutt *et al.*, *J. Cheminform.* 2021 — `10.1186/s13321-021-00522-2` (GNINA; already established in this repository by `ADR-028`).
