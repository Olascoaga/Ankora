# ADR-033: Hit-to-Analog Structural Similarity Expansion and Pose-Focused Mini-Library Virtual Screening

- **Status:** Accepted (M6.5 Contract for Ankora v0.2)
- **Date:** 2026-11-21
- **Baseline:** `codex/v0.2-dev` commit `79aa1ab01b3d90dc1391b542874fb40cfefcc355` (M0–M6 complete; frozen `v0.1.0-beta.2` `36f1c0e9b11adb579920437d23298472ac948bcf` untouched)
- **Extends:** `ADR-002` (explicit guided decisions), `ADR-004` (immutable originals), `ADR-005` (traceable derivatives), `ADR-011` (stale DAG propagation), `ADR-016` (explicit screening microstates), `ADR-018` (search-space volume warning), `ADR-024` (offline-first desktop with opt-in external retrieval), `ADR-030` (rank-space consensus & `E1`/`E4`), `ADR-031` (`0`-byte new dependency budget), `ADR-032` (`ReceptorFlexSpec`, `E7`, `E8` `PoseComplexIdentity`)
- **Amends:** `ADR-030` invariant `E1` (explicit separation of frozen Reference Panel manifest vs. scored target manifest, plus mandatory `executable_sha256s` and `k_max` enforcement in panel-context verification)
- **Platforms:** Windows 11 x64 **and** Linux `x86_64`
- **Installer size delta over `M0`–`M6` baselines:** `0` bytes of new external dependencies (`0` new Python distributions and `0` new executables). Implemented strictly over already-locked `rdkit==2025.9.6`, `httpx`, `sqlite3`, `numpy`, `scipy`, `prolif==2.2.1`, and `posebusters==0.6.5`.

## Context

After running an initial virtual screening campaign — whether single-engine, full-protein blind (`FULL_PROTEIN_BLIND`), pocket-detected (`POCKET_DETECTED`), or multi-engine rank-space consensus (`M5` `PC-Q`) — a medicinal chemist routinely needs to explore the local chemical neighborhood of a computational hit ("hit-to-analog expansion" / SAR-by-catalog) and re-screen a curated mini-library of structural analogs specifically in the binding site occupied by the selected lead pose.

Without a first-class, provenance-preserving workflow, scientists fall back to ad-hoc external scripts and manual box re-entry that introduce six documented scientific failure modes:

1. **Over-claiming from 2D similarity:** structural similarity (e.g., Morgan Tanimoto) does not guarantee biological activity, selectivity, or binding-mode conservation (*activity cliffs*).
2. **Cross-box score conflation (`E4`):** narrowing a wide or blind search box around a hit pose changes sampling density and search volume; raw docking scores from a wide box and a pose-focused box are not directly comparable, and a better score after focusing does not demonstrate higher affinity.
3. **Reference-panel mutation (`E1`):** evaluating a small congeneric analog mini-library (`N = 10–200`) by rebuilding an empirical quantile panel strictly from those analogs causes quantile collapse and rank compression, while appending analogs to an existing panel silently alters the reference distribution. In addition, the existing `_verify_reused_panel_context` guard validates receptor, `FlexRes`, box, map set, and scoring functions, but does not yet compare `executable_sha256s` or `k_max`.
4. **Chemistry & microstate leakage (`ADR-016`):** reconstructing query SMILES from `.pdbqt` or silently auto-picking salts, tautomers, stereoisomers, or protonation states corrupts chemical identity.
5. **Coupled-receptor and map inconsistencies (`E7`/`E8`):** shifting a box or introducing new ligand atom types invalidates `AutoGrid4` maps; shrinking a box around a pose can accidentally clip `FlexRes` side-chain atoms; and `Meeko --rigidify_bonds_smarts` freezes *internal torsions*, not 3D Cartesian core placement.
6. **Confidentiality / IP exposure:** silently transmitting proprietary hit SMILES to external web APIs violates local-first trust (`ADR-024`) and pharmaceutical intellectual-property expectations.

## Decision

Ankora `v0.2` adds an explicit, immutable, offline-first **Hit-to-Analog Expansion & Pose-Focused Mini-Library Virtual Screening** workflow composed of eight normative contracts. No parallel docking pipeline is created: curated analog mini-libraries enter Ankora's existing `ADR-016`, `M1`, docking, `M3`, `M4`, `M5`, `MethodsReport`, and verifiable export pipeline.

### 1. Epistemological Framing & Anti-Leakage Rules

- Every analog expansion run and focused campaign is framed strictly as **"analogs compatible with a computational binding hypothesis"** — never as confirmed binders, validated SAR, or predicted experimental affinity.
- The seed pose remains a computational prediction unless independently validated; focusing around a false positive can reinforce that false positive.
- **`M2` Confirmation anti-leakage (`ADR-027`):** locked `Confirmation` split compounds may **never** supply seeds, poses, similarity thresholds, pharmacophore rules, or `POSE_FOCUSED` boxes used to tune a procedure subsequently evaluated on `Confirmation`.

### 2. Prerequisite `ADR-030` `E1` Hardening & Focused Mini-Library Consensus Policy

#### 2.1 Fail-closed panel-context verification
`PoseConsensusService._verify_reused_panel_context` enforces every field sealed into `ReferencePanelArtifact.reference_panel_sha256`:
- `receptor_id`, `receptor_flex_spec` (`mode`, `receptor_rigid_sha256`, `canonical_flex_locators()`),
- `binding_box_sha256`, `autogrid_map_set_sha256`,
- `enabled_functions`,
- `executable_sha256s`, and
- `k_max`.

#### 2.2 Frozen Reference Panel Manifest vs. Scored Target Manifest (`E1` Amendment)
`ReferencePanelArtifact` defines a frozen empirical distribution over its declared panel members. Scoring a new analog mini-library against a compatible locked `ReferencePanelArtifact` evaluates each analog medoid's quantile strictly against that unchanged frozen panel — newly scored targets are never inserted into the panel distribution and never mutate `reference_panel_sha256`.

#### 2.3 Two Explicit Modes for Small Congeneric Mini-Libraries (`N = 10–200`)
- **Mode 1 — Focused Screening Without External `PC-Q` Panel (default when deriving a new `POSE_FOCUSED` box):** run single-engine or multi-engine docking + `--score_only` rescoring with mandatory re-docking of the parent seed (`seed_control`), inspect separate columns for `2D Tanimoto`, native scores, `M3` (`PoseBusters` + `MMFF94s` strain), `M4` (`ProLIF` rules + IFP Tanimoto), and receptor-frame MCS core RMSD (§7). `PC-ECR` (`tau = 0.05`) may be computed and is explicitly labeled as **within-mini-library relative rank (not cross-campaign calibrated)**.
- **Mode 2 — Strict `PC-Q` Consensus:** available only when either (a) the focused campaign keeps the exact parent binding site / context and reuses the parent campaign's locked `ReferencePanelArtifact` under §2.1–§2.2, or (b) the scientist explicitly runs and locks a dedicated focused reference panel for the new `POSE_FOCUSED` box. Whenever `total_panel_parents < 50` or all panel entries collapse to a single Bemis–Murcko scaffold, Ankora emits `CONSENSUS_SMALL_OR_CONGENERIC_PANEL` recording quantile step resolution (`100 / N`) and upper-tail saturation rate.

### 3. Immutable `BindingSiteSource.POSE_FOCUSED`

- `BindingSiteSource` adds `POSE_FOCUSED = "pose_focused"`.
- `BindingSiteRequest` accepts `pose_focused: PoseFocusedOrigin | None = None` and permits `parent_binding_site_id` for both `MANUAL` and `POSE_FOCUSED`.
- `PoseFocusedOrigin` anchors immutably to a hash-verified saved pose resolved via `PoseInteractionService.resolve_verified_pose_inputs(...)`:
  - `source_catalog_id`, `engine_key`, `record_id`, `ligand_id`, `ligand_preparation_id`, `pose_artifact_id`, `pose_sha256`, optional `pose_flex_sidechains_sha256`, optional `source_consensus_id` + `source_cluster_id`,
  - `padding_angstrom: float = Field(default=5.0, ge=0.0, le=50.0)`,
  - optional `box_override: BindingBox | None = None` (preserving both computed base box and final accepted box in provenance).
- **Deterministic initial box geometry:** computed over real heavy atoms of the selected ligand pose (excluding hydrogens and `CG0`/`G0` glue pseudoatoms) in the immutable receptor coordinate frame:
  - `center_j = (min(x_j) + max(x_j)) / 2`
  - `size_j = (max(x_j) - min(x_j)) + 2 * padding_angstrom`
- **Explicit choice preserved:** the scientist chooses between reusing the original binding site or creating a new `POSE_FOCUSED` `BindingSiteRecord`. Creating a new branch never overwrites or invalidates the parent campaign; stale source poses or receptors are rejected fail-closed (`409 PROJECT_INPUT_STALE`).
- **`ADR-018` compliance:** boxes exceeding `27,000 Å³` emit `DOCKING_SEARCH_SPACE_LARGE` without altering `exhaustiveness`.
- **`FlexRes` full-atom containment (`ADR-032`):** under `sidechain_flex`, Ankora verifies that all anchor and mobile side-chain atoms of every declared flexible residue lie inside the proposed box with an explicit margin (`>= 1.5 Å`, never `Cα`-only). Failing containment blocks creation (`422 BINDING_SITE_FLEXRES_OUTSIDE_BOX`) until the scientist enlarges the box or explicitly changes `ReceptorFlexSpec` — Ankora never silently drops flexible residues.
- **`AutoGrid4` map invalidation (`E7`):** any box change or newly introduced ligand atom type among selected analogs invalidates prior map sets and requires explicit regeneration; the stock `14`-ligand / `20`-receptor atom-type caps remain fail-closed.

### 4. Offline-First Local Analog Search (`RDKit 2025.9.6`)

The complete hit-expansion workflow runs **100% offline** with zero network calls:
- **Immutable catalog snapshots:** accepts local `.sdf`, `.smi`/`.smiles`, bounded **`.csv`** (requiring explicit `smiles_column`, `id_column`, `delimiter`, and `encoding`), or an immutable snapshot copied from an existing Ankora project `LigandLibraryRecord` (never a mutable cross-workspace pointer). Enforces the existing local bounds (`<= 10,000` records, `<= 100 MiB`) for `v0.2`; multi-million-record indexing is deferred to `v0.3+`.
- **Query provenance:** the query canonical isomeric SMILES is taken exclusively from the seed pose's resolved chemical state (`ADR-016`), never reconstructed from `.pdbqt`.
- **Deterministic fingerprint profile:** primary search uses `rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048, includeChirality=True)` and Tanimoto similarity, recording all generator parameters and exact `rdkit.__version__`. Optional substructure constraint uses graph-verified `SMARTS` (`HasSubstructMatch`). Results are deterministically sorted by `(-tanimoto, canonical_isomeric_smiles, catalog_record_index)`.
- **Fingerprint cache:** workspace-local SQLite cache (outside immutable raw evidence) keyed strictly by `(catalog_sha256, normalization_profile_sha256, fp_params_sha256, rdkit_version)`.
- **Non-mutating search normalization & deduplication:** salt stripping / canonicalization occurs strictly on ephemeral search representations — raw catalog bytes remain immutable and `ADR-016` microstate curation is never bypassed. Deduplication preserves stereochemical identity; the parent seed is retained and explicitly tagged `role = "seed_control"` rather than presented as a "new analog".

### 5. Explicit Opt-In Online Analog Search (`PubChem PUG-REST` & `ChEMBL REST`)

Online search is strictly opt-in, disabled by default, never triggered as a silent fallback, and never fetches external 2D images or runs background refreshes:
- **Supported providers (over already-locked `httpx`):**
  - `pubchem_pug_rest`: PubChem PUG-REST 2D similarity (`POST` query structure, `Threshold`, `MaxRecords`, `MaxSeconds`).
  - `chembl_rest`: ChEMBL REST `/similarity` endpoint.
- **Mandatory cryptographic IP/confidentiality consent gate:** before any outbound HTTP request is constructed, the backend requires an explicit consent payload bound to the exact provider and canonical query SMILES:
  - `acknowledge_external_transmission: bool = True`
  - `consent_payload_sha256 == sha256(f"{provider}:{canonical_query_smiles}")`
  - Missing or mismatched consent fails closed (`422 ANALOG_EXTERNAL_CONSENT_REQUIRED`). The UI visibly displays the exact canonical SMILES and target provider URL with the explicit warning that transmitting the structure leaves the local machine and may disclose confidential IP.
- **Hard rate, size, and retry bounds:** max `1` concurrent outbound request, `<= 1.0 req/s` client throttle, `max_candidates <= 500`, cumulative response cap `<= 10 MiB`, at most `2` bounded retries honoring HTTP `Retry-After` / throttling headers, explicit connect/read timeouts.
- **Immutable raw-response archiving:** request parameters, provider URL, HTTP status codes, timestamps, provider version headers (if returned), and verbatim raw response bytes (with SHA-256) are persisted inside the project's immutable `AnalogSearchRecord` evidence tree.
- **Mandatory local RDKit recalculation:** every downloaded candidate is re-parsed and scored locally with Ankora's frozen Morgan ECFP4 Tanimoto (`local_rdkit_tanimoto`), keeping any remote score separately in `provider_similarity`. A capped remote result is explicitly flagged as `truncated_or_capped` and never represented as exhaustive over the entire remote database.
- **Explicitly rejected external sources:** web/vendor scraping, LLM queries, generative *de novo* APIs, cloud docking, and uploading full local libraries to external servers.

### 6. Explicit Human Curation, Derived Mini-Library (`<= 200` Parents) & Mandatory Seed Control

- No candidate returned by offline or online similarity search is docked automatically.
- The scientist reviews hits and creates an immutable `AnalogSelectionRecord` capturing selected rows, excluded rows, explicit rationale, and `role` (`"seed_control"` vs. `"analog"`), capped operationally at `<= 200` selected parents per derived mini-library for `v0.2`.
- Materializing the selection creates a standard immutable `LigandLibraryRecord` with explicit provenance fields (`origin_analog_selection_id`, `origin_analog_search_id`, `source = LigandSource.ANALOG_EXPANSION`, frozen snapshot SHA-256) that enters Ankora's existing `LigandLibraryTable` / `ADR-016` microstate review, conformer generation, `M1` `Meeko` preparation (`--rigidify_bonds_smarts` disclosed as internal torsion rigidification, never Cartesian core tethering), and docking / `M3` / `M4` / `M5` execution.
- **Mandatory seed control:** the parent seed (`seed_control`) is automatically included (removable only via explicit recorded override emitting `ANALOG_SEED_CONTROL_EXCLUDED`) and re-docked under the exact same focused protocol and box. Ankora never fixes the seed's moved `FlexRes` side-chain rotamer as a static receptor for the analog series.

### 7. Receptor-Frame MCS Core RMSD Diagnostic (Separate Column, Zero Superscores)

- `adapters/chemistry/mcs_core_rmsd.py` computes Maximum Common Substructure (`rdFMCS.FindMCS`) with recorded parameters (`atomCompare`, `bondCompare`, `ringMatchesRingOnly`, `completeRingsOnly`, `timeout_seconds`), emitting `ANALOG_MCS_TIMEOUT` whenever the search hits the timeout rather than presenting a partial match as a certified maximum.
- Computes heavy-atom RMSD **in place in the receptor coordinate frame (no Kabsch / ligand superposition)** across symmetry-equivalent MCS mappings, taking the minimum over valid automorphism matches.
- Reported strictly in its own column alongside separate `2D Tanimoto`, `ProLIF IFP Tanimoto`, `InteractionRuleSet`, `PoseBusters`, `MMFF94s strain`, native engine scores, and `PC-Q`/`PC-ECR` — never merged into a composite superscore.

### 8. DAG Lineage (`ADR-011`), `MethodsReport`, `Export v6` & `ADR-031` Budget

- `ProjectDependencyService` registers `DependencyNodeKind.ANALOG_CATALOG`, `ANALOG_SEARCH`, `ANALOG_SELECTION` and reference keys (`analog_catalog_id`, `analog_search_id`, `analog_selection_id`, `source_pose_artifact_id`, `source_consensus_id`).
- `MethodsReport` gains a dedicated disclosure block for analog-expansion and pose-focused runs.
- **Verifiable Export (`Export v6` additive upgrade):** runs with no analog-expansion lineage remain byte-compatible at `Export v4` / `Export v5`. Runs carrying `POSE_FOCUSED` or `ANALOG_EXPANSION` provenance emit **`ankora_export_format: 6`** attaching `analog_search`, `analog_selection`, `pose_focused_site`, optional `online_raw_response` snapshot, and either the catalog snapshot or an explicit size-policy omission attestation + SHA-256. The zero-dependency verifier `scripts/verify_export_bundle.py` (`python -S`) validates `v2`–`v6` fail-closed.
- `environment/v02-installer-size-budget.json` and `scripts/check_v02_installer_budget.py` register `M6.5` with `max_delta_bytes: 0` and `new_dependencies: []`.

### 9. Explicit Non-Goals (Out of Scope for `v0.2`)

- Generative AI / *de novo* molecule design or LLM-proposed chemical structures.
- Predictive QSAR / ADMET / experimental potency claims.
- New tethered/constrained docking engine modifications (beyond existing `M1` `Meeko --rigidify_bonds_smarts` internal-torsion control).
- Multi-million-compound local catalog indexing (deferred to `v0.3+`).
- Discrete receptor ensembles (deferred to `v0.3+` per `ADR-032`).
- Any silent external network transmission, scraping, or automatic uncurated docking.
