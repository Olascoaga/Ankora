# Ankora — Clean-Slate Project Bootstrap for Codex

> **Purpose:** This document is the single source of truth for generating Ankora from zero.
>
> **Audience:** Codex as the primary implementation agent, with Claude Code as a secondary reviewer/auditor.
>
> **Status:** Initial project contract.
>
> **Living-contract note (2026-08-26):** This file preserves the clean-slate
> baseline and original milestone numbering. Explicitly accepted later ADRs and
> scientist decisions supersede individual early scope exclusions. Read
> the accepted ADRs and validation records for current capability and milestone
> status. When the private, Git-ignored local `memory/` workspace exists, also
> read `memory/START_HERE.md` and `memory/PROJECT_STATE.md`. Do not treat the
> bootstrap's historical exclusions as evidence that an already accepted
> feature is absent.
>
> **Platform:** Windows 11 x64 only.
>
> **Development philosophy:** graphical, step-by-step, explicit, local, reproducible, scientist-controlled.
>
> **Important:** Do not copy or preserve implementation decisions from any previous Ankora repository unless they are independently justified by this document. The new project must be generated from a clean directory.

---

# 0. Agent instructions

Before writing code, read this entire document.

The first implementation session must:

1. Create the repository and its complete documentation/governance skeleton.
2. Initialize the desktop frontend, Windows desktop shell, and Python scientific backend.
3. Establish typed contracts between frontend and backend.
4. Add the ADRs defined in this document.
5. Add tests for the initial contracts.
6. Add a minimal desktop application that proves:
   - Tauri opens on Windows;
   - React renders;
   - the Python backend launches locally;
   - the frontend can call a typed health endpoint;
   - the backend can discover configured external scientific tools without running them.
7. Create project memory/state files for future Codex and Claude Code sessions.
8. Stop after the clean vertical skeleton works.

Do **not** implement molecular preparation or docking during the repository bootstrap unless explicitly instructed in a later session.

The project must remain buildable and testable after every milestone.

---

# 1. Product identity

## 1.1 Name

**Ankora**

## 1.2 One-sentence definition

> **Ankora is a native Windows visual workbench for performing molecular docking step by step, with the scientist explicitly inspecting, deciding, executing, and reviewing every stage.**

## 1.3 Product idea

Ankora is not an automated virtual-screening black box.

It is not intended to decide scientific choices on behalf of the user.

Its purpose is to remove mechanical friction from molecular docking while preserving scientific control.

The user should be able to:

- open a structure;
- inspect it visually;
- understand structural problems;
- make preparation decisions;
- inspect the prepared receptor;
- prepare a ligand;
- define a docking box visually;
- configure a docking engine;
- run docking;
- inspect poses;
- compare predicted and experimental poses;
- calculate redocking RMSD;
- inspect protein-ligand interactions;
- preserve exact provenance and commands.

The core design rule is:

> **Automate the mechanical work required to make a scientific decision; do not automate the scientific decision itself.**

---

# 2. Primary user

For the initial project, the primary user is the developer/scientist building Ankora.

Therefore:

- optimize first for a scientifically literate docking user;
- do not optimize primarily for beginners;
- do not hide technical details;
- do not require terminal usage during normal operation;
- expose commands, parameters, warnings, intermediate files, and provenance;
- prefer clarity and control over "one-click" automation.

If the tool later becomes useful to the broader community, accessibility can be expanded without changing the core scientific model.

---

# 3. Platform policy

## 3.1 Supported operating system

**Windows 11 x64 only.**

No official Linux support.
No macOS support.
No WSL execution provider.
No Docker requirement.
No remote execution.
No SSH/Slurm.
No cloud backend.

The scientific core should still avoid gratuitous OS coupling, but the product is allowed to make Windows-specific engineering decisions when they materially simplify development or improve UX.

## 3.2 Development environment

Reference development environment:

- Windows 11 x64
- PowerShell
- Git for Windows
- Node.js 22+
- npm
- Rust stable
- Tauri v2 toolchain
- Microsoft C++ Build Tools
- WebView2
- Python 3.12+
- VS Code
- Codex
- Claude Code

WSL may be used for unrelated experiments, but **Ankora features are not considered complete until they work natively on Windows**.

---

# 4. Core product principles

1. **Visual first**
   - The 3D molecular viewer is a central workspace, not a secondary result pane.

2. **Step by step**
   - The workflow is intentionally staged.
   - The user reviews each stage before continuing.

3. **Explicit decisions**
   - Receptor/ligand transformations require an explicit decision where scientifically relevant.

4. **Inspection before transformation**
   - Ankora analyzes the input first.
   - It reports problems and options.
   - Transformation happens only after review.

5. **Traceability by default**
   - Every transformation stores:
     - input;
     - output;
     - tool;
     - version;
     - parameters;
     - warnings;
     - hashes;
     - timestamp.

6. **Original files are immutable**
   - Imported/downloaded inputs are never overwritten.

7. **No fake certainty**
   - A docking score is not experimental affinity.
   - A docking pose is not evidence of biological activity.
   - Redocking success validates only the evaluated protocol/reference system.

8. **Failures must be informative**
   - Never show only:
     - `Preparation failed`
     - `Unknown error`
   - Show:
     - failing stage;
     - affected residue/molecule if known;
     - raw tool message;
     - structured diagnosis;
     - possible user actions.

9. **Commands remain visible**
   - Every docking run must expose the reproducible command generated by Ankora.

10. **Personal usefulness before public polish**
    - Build the tool that solves real docking work first.
    - Packaging, onboarding, documentation, and community features come later.

---

# 5. Initial workflow

The application should present a persistent left-side workflow.

```text
Project
  1. Structure
  2. Receptor
  3. Ligand
  4. Binding site
  5. Docking
  6. Results
  7. Validation
  8. Export
```

Each scientific step follows:

```text
Inspect
  -> Decide
  -> Apply
  -> Review
  -> Continue
```

The user must be able to move backward to inspect previous stages without destroying later artifacts automatically.

Changing an upstream scientific decision must mark dependent downstream artifacts as stale.

---

# 6. Main UI concept

Use a three-column desktop layout.

```text
+------------------------------------------------------------------+
| Ankora                                                           |
+----------------+--------------------------------+----------------+
| Workflow       |                                | Inspector      |
|                |                                |                |
| 1 Structure    |                                | Selected       |
| 2 Receptor     |          3D VIEWER             | object details |
| 3 Ligand       |            Mol*                |                |
| 4 Site         |                                | warnings       |
| 5 Docking      |                                | actions        |
| 6 Results      |                                | parameters     |
| 7 Validation   |                                |                |
| 8 Export       |                                |                |
+----------------+--------------------------------+----------------+
| status | warnings | provenance | generated command | logs         |
+------------------------------------------------------------------+
```

## 6.1 Viewer behavior

The central viewer should eventually support:

- cartoon/surface/stick representations;
- chain visibility;
- ligand visibility;
- waters;
- metals;
- cofactors;
- residue selection;
- distance measurement;
- highlighted structural warnings;
- prepared/original overlay;
- docking box visualization;
- docking poses;
- experimental/reference ligand overlay;
- interaction highlights.

Use **Mol\*** as the initial viewer unless a technical spike proves it unsuitable inside the Tauri/WebView2 environment.

---

# 7. Scope of Ankora v0.1

The first useful personal version should support:

## 7.1 Structure input

- PDB ID download from RCSB.
- Local PDB.
- Local mmCIF.

Do not include AlphaFold DB in v0.1.

## 7.2 Structure inspection

Display:

- chains;
- residue counts;
- heterogens;
- ligands;
- waters;
- metals;
- alternate locations;
- missing residues;
- missing atoms;
- nonstandard residues;
- obvious connectivity/preparation warnings.

The user can click a warning and jump to the corresponding structure location in 3D.

## 7.3 Receptor preparation

User-controlled actions:

- choose chains;
- remove/keep waters;
- remove/keep ligands;
- remove/keep cofactors;
- remove/keep metals;
- inspect alternate conformations;
- inspect missing residues;
- inspect missing side-chain atoms;
- choose whether specific incomplete residues should be:
  - left unchanged;
  - repaired;
  - removed;
  - manually reviewed;
- add hydrogens;
- protonation workflow;
- generate docking-ready receptor.

Initial backend candidates:

- PDBFixer;
- PDB2PQR;
- PROPKA;
- Meeko.

Do not silently reconstruct every missing atom.

### Pocket-aware policy

Once a binding-site reference exists, structural defects should report distance to the site.

Example:

```text
ARG271
Missing side-chain atoms
Distance to selected site: 51.3 Å
Severity: remote warning

Actions:
[Leave incomplete]
[Repair]
[Exclude residue]
[Inspect in 3D]
```

Near-pocket defects should be treated more conservatively than remote defects.

## 7.4 Ligand preparation

Initial inputs:

- SDF;
- MOL;
- SMILES;
- crystallographic ligand extracted from the receptor structure.

Initial preparation:

- preserve original;
- validate chemistry;
- preserve stereochemistry;
- optional salt handling;
- 3D generation;
- conformer generation;
- MMFF94/MMFF94s optimization where applicable;
- PDBQT generation through Meeko.

Internal object hierarchy:

```text
Compound
  -> Chemical state
      -> Conformer
          -> Docking pose
```

Do not collapse these concepts into a single "ligand" file.

## 7.5 Binding site

Support:

1. box around a selected crystallographic ligand;
2. box around selected residues;
3. fully manual box;
4. visual translation/resizing.

Always show:

- center X/Y/Z;
- size X/Y/Z;
- volume;
- nearby residues.

The box must be rendered interactively in 3D.

## 7.6 Docking engines

Initial engines:

- **AutoDock Vina**
- **GNINA**

Do not implement consensus scoring in v0.1.

Do not merge their scoring scales.

Each engine has its own adapter and result model.

The user chooses an engine explicitly.

Common settings where meaningful:

- seed;
- exhaustiveness;
- number of poses/modes;
- box;
- CPU/GPU selection where supported.

GNINA-specific settings must remain GNINA-specific.

## 7.7 Results

Central table should support at least:

| Pose | Engine | Docking score | CNN score | CNN affinity | RMSD | Status |
|---|---|---:|---:|---:|---:|---|

Fields not produced by the selected engine remain absent/NA.

Selecting a row must update the 3D viewer.

Support:

- pose overlay;
- original ligand;
- experimental ligand;
- distance measurements;
- nearby residues;
- interaction analysis.

## 7.8 Validation

If a suitable crystallographic ligand exists:

```text
Validate protocol by redocking
```

Workflow:

1. preserve experimental pose as immutable reference;
2. generate an independent docking conformer;
3. dock;
4. calculate symmetry-aware heavy-atom RMSD;
5. report:
   - Top-1 RMSD;
   - best Top-5 RMSD;
   - best overall RMSD;
   - first pose below threshold;
   - sampling success;
   - ranking success.

Default reference threshold:

```text
RMSD <= 2.0 Å
```

The threshold and RMSD algorithm must be documented and configurable.

Validation language must be careful:

```text
PASS:
The evaluated docking configuration recovered the experimental binding mode
within the configured RMSD criterion.
```

Never:

```text
The docking method is universally validated.
```

## 7.9 Interactions

Use an adapter around ProLIF or PLIP after a dedicated technical spike.

Potential interactions:

- hydrogen bonds;
- hydrophobic interactions;
- pi stacking;
- cation-pi;
- salt bridges;
- halogen bonds;
- metal contacts.

The 2D interaction diagram should be generated from structured interaction data rather than scraping an image from another program whenever practical.

## 7.10 Save project

An Ankora project must preserve:

- original structures;
- derivatives;
- ligand states;
- box;
- engine parameters;
- generated commands;
- results;
- validation metrics;
- warnings;
- logs;
- software versions;
- hashes.

SQLite plus project files is acceptable.

---

# 8. Explicitly excluded from v0.1

Do not implement unless this document is formally amended:

- AutoDock-GPU;
- Uni-Dock;
- DiffDock;
- consensus scoring;
- automatic ligand ranking across incompatible engines;
- AlphaFold retrieval;
- PAE/pLDDT analysis;
- molecular dynamics;
- receptor ensemble docking;
- induced-fit docking;
- covalent docking;
- free-energy calculations;
- QSAR;
- ADMET;
- molecule generation;
- AI biological interpretation;
- automatic cavity prediction;
- millions-of-compounds screening;
- HPC;
- Slurm;
- SSH;
- cloud execution;
- collaboration/multi-user features;
- web/mobile version;
- macOS;
- Linux;
- WSL execution;
- automated scientific decisions.

---

# 9. Technology stack

## 9.1 Desktop

- Tauri v2
- Rust stable
- React
- TypeScript strict mode
- Vite

## 9.2 3D visualization

Primary candidate:

- Mol*

Create a viewer adapter so the rest of the frontend does not depend directly on Mol* implementation details.

## 9.3 Scientific backend

- Python 3.12+
- Pydantic
- FastAPI or a similarly small typed localhost API
- RDKit
- PDBFixer
- PDB2PQR
- PROPKA
- Meeko
- ProLIF and/or PLIP after evaluation
- SQLite

## 9.4 Docking engines

External executable adapters:

- Vina
- GNINA

They must not be called directly from React.

## 9.5 Packaging strategy

During development:

- system/developer Python environment is acceptable;
- external scientific executables may be configured by path.

Future distribution:

- package Python scientific backend as a Tauri sidecar or bundled runtime;
- bundle supported engine binaries when licensing permits;
- a public release should not require end users to install Python, Conda, WSL, Docker, or command-line dependencies.

Do not solve full distribution during v0.1 development.

---

# 10. Architecture

```text
Tauri Desktop
|
+-- React UI
|   |
|   +-- Workflow state
|   +-- 3D viewer adapter
|   +-- Inspector panels
|   +-- Results tables
|   +-- Logs/provenance UI
|
+-- Typed local API client
    |
    +-- Python scientific backend
        |
        +-- Domain
        |   +-- structures
        |   +-- receptors
        |   +-- ligands
        |   +-- binding_sites
        |   +-- docking
        |   +-- validation
        |   +-- interactions
        |   +-- projects
        |
        +-- Application services
        |   +-- inspect_structure
        |   +-- prepare_receptor
        |   +-- prepare_ligand
        |   +-- define_binding_site
        |   +-- run_docking
        |   +-- evaluate_redocking
        |   +-- analyze_interactions
        |
        +-- Tool adapters
        |   +-- pdbfixer
        |   +-- pdb2pqr
        |   +-- propka
        |   +-- meeko
        |   +-- rdkit
        |   +-- prolif_or_plip
        |
        +-- Engine adapters
        |   +-- vina
        |   +-- gnina
        |
        +-- Persistence
        |   +-- sqlite
        |   +-- artifact_store
        |   +-- provenance_ledger
        |
        +-- Windows execution
            +-- executable discovery
            +-- subprocess runner
            +-- cancellation
            +-- stdout/stderr capture
```

---

# 11. Domain rules

## 11.1 Original artifacts are immutable

Never modify imported/downloaded files in place.

Use:

```text
original/
derived/
results/
logs/
```

## 11.2 Dependency graph

Derived artifacts must know their parents.

Example:

```text
7AQF.pdb
  -> receptor_chain_A.pdb
      -> receptor_prepared.pdb
          -> receptor.pdbqt
```

If `receptor_chain_A.pdb` changes, downstream artifacts become stale.

## 11.3 Scientific actions are first-class records

Example:

```json
{
  "type": "remove_residue",
  "target": "A:271",
  "reason": "user_selected",
  "input_artifact": "...",
  "output_artifact": "...",
  "tool": "ankora",
  "timestamp": "..."
}
```

## 11.4 Structured warnings

Warnings must use stable codes.

Example:

```text
REC_MISSING_SIDECHAIN
REC_REMOTE_INCOMPLETE_RESIDUE
REC_NEAR_POCKET_GAP
REC_PROTONATION_AMBIGUOUS
MEEKO_CONNECTIVITY_FAILURE
LIG_STEREOCHEMISTRY_UNDEFINED
DOCKING_ENGINE_FAILED
VALIDATION_RMSD_FAIL
```

Human-readable text is presentation only.

---

# 12. ADRs to create during bootstrap

Create these files under:

```text
docs/architecture/ADR/
```

## ADR-001 — Windows-only personal workbench

Decision:
Windows 11 x64 is the only supported platform during the personal-tool phase.

Consequence:
The implementation may use Windows-native assumptions when justified, while keeping scientific domain code reasonably portable.

## ADR-002 — Guided manual workflow over automation

Decision:
Scientific choices remain explicit user decisions.

Consequence:
Ankora may recommend, explain, or warn, but does not silently make consequential preparation choices.

## ADR-003 — Inspection precedes transformation

Decision:
Structure/ligand analysis is represented separately from transformation.

Consequence:
A user can inspect problems before changing the molecular system.

## ADR-004 — Immutable original inputs

Decision:
Original structures and ligands are never modified.

## ADR-005 — Traceable scientific transformations

Decision:
Every scientific transformation emits structured provenance.

## ADR-006 — External scientific tools behind adapters

Decision:
RDKit, Meeko, PDBFixer, PDB2PQR, PROPKA, Vina, GNINA, and interaction tools live behind versioned adapters.

## ADR-007 — Mol* behind a viewer abstraction

Decision:
Mol* is the initial 3D viewer but UI domain logic does not depend directly on its API.

## ADR-008 — Vina and GNINA as initial docking engines

Decision:
Both engines are supported independently.

Consequence:
No automatic consensus score.

## ADR-009 — Local API boundary

Decision:
React communicates with the Python scientific backend through an explicit typed localhost API.

## ADR-010 — SQLite plus artifact store

Decision:
Structured project state goes to SQLite; molecular files/raw outputs remain normal project artifacts.

## ADR-011 — Stale downstream artifact propagation

Decision:
Changes in upstream scientific decisions invalidate dependent downstream artifacts explicitly.

## ADR-012 — Validation by reference cases

Decision:
Core scientific capabilities require frozen reference cases and expected evidence before being called complete.

---

# 13. Reference validation cases

Do not implement them in the first bootstrap session, but create documentation placeholders.

## 13.1 SERPINE1

```text
PDB: 7AQF
Protein chain: A
Reference ligand: RV2 A:401

Historical directed box:
center = 35.561, -4.298, -0.660 Å
size   = 12.585, 10.101, 11.617 Å
```

Known modern benchmark evidence:

```text
Vina 1.1.2
Top-1 RMSD = 1.162 Å
PASS

GNINA 1.3.3
Top-1 RMSD = 1.054 Å
PASS
```

Important edge case:

- ARG271 has experimentally missing side-chain atoms.
- Blind automatic reconstruction can create problematic connectivity.
- The UI should eventually make this kind of issue visible and user-resolvable.

## 13.2 PIK3CD

```text
PDB: 6OCO
Protein chain: A
Reference ligand: M5V A:1101

Historical directed box:
center = 39.024, 13.576, 35.174 Å
size   = 14.423, 9.405, 12.053 Å
```

Expected historical redocking criterion:

```text
RMSD < 2 Å
```

This case should become the second independent reference case.

## 13.3 Adversarial case

```text
PDB: 3UT3
Ligand: EMJ
```

This is not the primary historical validation case.

Use later as an adversarial/preparation/scoring test.

Do not fail the entire scientific validation suite merely because an adversarial case does not reproduce the crystallographic pose.

---

# 14. Repository structure

Generate approximately:

```text
Ankora/
|
+-- README.md
+-- LICENSE
+-- AGENTS.md
+-- CODEX_BOOTSTRAP.md
+-- CHANGELOG.md
+-- .gitignore
+-- .editorconfig
+-- package.json
+-- package-lock.json
|
+-- .github/
|   +-- workflows/
|       +-- ci.yml
|
+-- apps/
|   +-- desktop/
|       +-- src/
|       |   +-- app/
|       |   +-- components/
|       |   +-- features/
|       |   +-- viewer/
|       |   +-- api/
|       |   +-- types/
|       |   +-- tests/
|       +-- src-tauri/
|       +-- package.json
|
+-- backend/
|   +-- pyproject.toml
|   +-- src/
|   |   +-- ankora_backend/
|   |       +-- api/
|   |       +-- domain/
|   |       +-- services/
|   |       +-- adapters/
|   |       |   +-- tools/
|   |       |   +-- engines/
|   |       +-- execution/
|   |       +-- persistence/
|   |       +-- provenance/
|   |       +-- schemas/
|   +-- tests/
|
+-- docs/
|   +-- product/
|   |   +-- PRODUCT_DEFINITION.md
|   |   +-- SCOPE.md
|   |   +-- USER_WORKFLOW.md
|   |   +-- UI_PRINCIPLES.md
|   +-- architecture/
|   |   +-- ARCHITECTURE.md
|   |   +-- ADR/
|   +-- scientific/
|   |   +-- RECEPTOR_PREPARATION_POLICY.md
|   |   +-- LIGAND_PREPARATION_POLICY.md
|   |   +-- DOCKING_POLICY.md
|   |   +-- REDOCKING_VALIDATION.md
|   +-- validation/
|       +-- VALIDATION_STRATEGY.md
|       +-- reference_cases/
|           +-- SERPINE1_7AQF_RV2.md
|           +-- PIK3CD_6OCO_M5V.md
|           +-- ADVERSARIAL_3UT3_EMJ.md
|
+-- schemas/
|   +-- project.schema.json
|   +-- provenance_event.schema.json
|   +-- warning.schema.json
|
+-- resources/
|   +-- icons/
|   +-- templates/
|
+-- scripts/
|   +-- bootstrap.ps1
|   +-- dev.ps1
|   +-- test.ps1
|
+-- tests/
|   +-- fixtures/
|
+-- memory/
    +-- START_HERE.md
    +-- PROJECT_STATE.md
    +-- NEXT_SESSION.md
    +-- DECISIONS.md
    +-- FUTURE_IDEAS.md
    +-- SESSION_LOG.md
```

`memory/` is private local continuity state and is intentionally Git-ignored.
Tracked ADRs, validation records, and Git history remain the public handoff.

---

# 15. AGENTS.md policy

Generate an `AGENTS.md` that applies to Codex and Claude Code.

Minimum rules:

1. Read:
   - `CODEX_BOOTSTRAP.md`
   - `memory/START_HERE.md`
   - `memory/PROJECT_STATE.md`
   - `memory/NEXT_SESSION.md`
   before modifying code.

2. Do not expand scope without explicit authorization.

3. Never silently replace scientific behavior with a shortcut.

4. No capability is considered complete without:
   - implementation;
   - tests;
   - acceptance criteria;
   - recorded validation evidence.

5. Preserve raw outputs from external scientific tools.

6. Do not parse human-readable log strings when a structured API/output exists.

7. Never invent scientific results in tests.
   - synthetic fixtures must be labeled synthetic;
   - reference-case expected values must come from recorded evidence.

8. Frontend must not call Vina/GNINA/Meeko/etc. directly.

9. External tool versions must be detectable and recorded.

10. Windows-native behavior is authoritative.

11. Before ending a coding session:
    - run tests;
    - update `PROJECT_STATE.md`;
    - update `NEXT_SESSION.md`;
    - record important decisions.

12. Codex implements.
    Claude Code may audit/review.
    Do not let two agents edit the same branch concurrently.

---

# 16. Initial API contract

Bootstrap only.

Create:

```text
GET /api/v1/health
GET /api/v1/system
GET /api/v1/tools
```

Example health response:

```json
{
  "status": "ok",
  "backend_version": "0.1.0"
}
```

Example system response:

```json
{
  "platform": "windows",
  "architecture": "x86_64",
  "python_version": "...",
  "app_mode": "development"
}
```

Example tools response:

```json
{
  "vina": {
    "available": false,
    "path": null,
    "version": null
  },
  "gnina": {
    "available": false,
    "path": null,
    "version": null
  }
}
```

No docking execution during bootstrap.

---

# 17. Frontend bootstrap acceptance criteria

The initial desktop UI must have:

- left workflow rail;
- central placeholder for molecular viewer;
- right inspector pane;
- bottom status/provenance area;
- dark/light theme support if trivial;
- backend connectivity status;
- tool availability panel;
- no fake scientific functionality.

Workflow steps may be disabled except `Structure`.

The UI should look intentionally designed rather than like a developer demo, but do not spend excessive time on polish before functionality.

---

# 18. Testing policy

## 18.1 Backend

Use `pytest`.

Must test:

- health endpoint;
- system endpoint;
- external tool discovery;
- stable warning schema;
- provenance-event schema;
- Windows path handling.

## 18.2 Frontend

Use a modern TypeScript test runner compatible with Vite.

Must test:

- API client;
- initial application state;
- workflow navigation rules;
- rendering of backend disconnected/connected state.

## 18.3 Integration

At least one smoke test or documented manual test must prove:

```text
Tauri
  -> React
      -> Python backend
          -> JSON response
              -> visible UI state
```

## 18.4 CI

GitHub Actions should run:

- Python tests;
- Python lint/type check;
- TypeScript tests;
- TypeScript type check;
- frontend build.

Windows CI is preferred because Windows is authoritative.

---

# 19. Coding standards

## Python

- typed Python;
- small domain models;
- Pydantic at API boundaries;
- `pathlib.Path`;
- no global mutable state;
- no bare `except`;
- exceptions translated into structured domain/API errors;
- logging through standard logging;
- no scientific decision hidden inside UI-oriented code.

## TypeScript

- strict mode;
- no `any` without written justification;
- domain/API types separated from view components;
- viewer adapter isolated;
- no direct subprocess calls.

## Rust/Tauri

Keep Rust thin.

Responsibilities:

- application shell;
- lifecycle;
- sidecar/process integration when needed;
- native filesystem/window capabilities.

Do not duplicate scientific domain logic in Rust.

---

# 20. Error model

All backend errors should contain:

```json
{
  "code": "STABLE_ERROR_CODE",
  "stage": "receptor_preparation",
  "message": "Human-readable explanation",
  "details": {},
  "recoverable": true
}
```

When wrapping an external tool failure, preserve:

- executable;
- version;
- arguments;
- exit code;
- stdout;
- stderr.

User-facing UI should show concise explanation with expandable technical details.

---

# 21. Provenance model

Minimum provenance event:

```json
{
  "event_id": "...",
  "event_type": "...",
  "timestamp": "...",
  "input_artifacts": [],
  "output_artifacts": [],
  "tool": {
    "name": "...",
    "version": "..."
  },
  "parameters": {},
  "warnings": [],
  "command": null
}
```

Docking events must store the exact command.

---

# 22. Security and privacy

Initial project is local-only.

Rules:

- backend binds only to localhost;
- no telemetry;
- no cloud upload;
- no analytics;
- no credential storage unless explicitly introduced later;
- downloaded structures must record their source;
- sanitize file paths passed to subprocesses;
- never construct shell commands through raw string concatenation.

Use argument arrays for subprocess execution.

---

# 23. Development milestones

## M0 — Clean bootstrap

Deliver:

- repository skeleton;
- docs;
- ADRs;
- Tauri + React desktop shell;
- Python backend;
- health/system/tools endpoints;
- tests;
- CI;
- memory files.

## M1 — Structure workspace

Deliver:

- open local PDB/mmCIF;
- fetch PDB ID;
- parse structure;
- display structure metadata;
- Mol* viewer;
- click/select chains and heterogens;
- structured warnings.

No transformation yet.

## M2 — Receptor preparation

Deliver:

- inspection report;
- user decisions;
- immutable derivatives;
- PDBFixer adapter;
- PDB2PQR/PROPKA adapter;
- Meeko receptor adapter;
- prepared/original overlay;
- structured failure diagnosis.

Reference case:
7AQF.

## M3 — Ligand preparation

Deliver:

- crystallographic ligand extraction;
- SDF/MOL/SMILES import;
- RDKit conformer generation;
- MMFF optimization;
- Meeko ligand preparation;
- state/conformer model.

Reference ligand:
RV2.

## M4 — Binding-site editor

Deliver:

- box around ligand;
- residue selection;
- manual numeric editing;
- visual drag/resize if technically feasible;
- box persistence.

## M5 — Vina

Deliver:

- Vina adapter;
- configuration UI;
- job execution;
- cancellation;
- pose parsing;
- results table;
- 3D pose inspection.

## M6 — Redocking validation

Deliver:

- crystal reference preservation;
- independent conformer;
- symmetry-aware RMSD;
- Top-1/Top-5/sampling metrics;
- SERPINE1 7AQF/RV2 regression test.

Expected benchmark:
Top-1 RMSD <= 2.0 Å.

## M7 — GNINA

Deliver:

- GNINA adapter;
- GPU detection;
- GNINA-specific scoring fields;
- same visual result workflow;
- 7AQF/RV2 reference validation.

Known evidence:
Top-1 RMSD about 1.054 Å under the recorded modern benchmark configuration.

## M8 — Second validation target

PIK3CD 6OCO/M5V.

The project should not be called scientifically mature until at least two independent receptor/ligand validation systems pass their documented criteria.

## M9 — Interactions and export

Deliver:

- interaction analysis;
- 2D interaction diagram;
- reproducible methodology export;
- selected figures/data export.

---

# 24. First implementation session — exact task

Codex should perform the following now:

1. Create a brand-new repository in an empty directory named `Ankora`.
2. Initialize Git.
3. Copy this document into the root as `CODEX_BOOTSTRAP.md`.
4. Create all project/documentation directories from Section 14.
5. Create concise versions of:
   - `README.md`
   - `AGENTS.md`
   - product docs;
   - architecture doc;
   - all ADRs;
   - validation placeholders.
6. Initialize:
   - npm workspace;
   - React + TypeScript + Vite desktop frontend;
   - Tauri v2 shell;
   - Python backend package.
7. Implement:
   - `/api/v1/health`
   - `/api/v1/system`
   - `/api/v1/tools`
8. Add a minimal but intentional desktop layout:
   - workflow rail;
   - viewer placeholder;
   - inspector;
   - status bar.
9. Connect frontend to backend.
10. Add automated tests.
11. Add Windows GitHub Actions CI.
12. Run all available tests.
13. Update:
    - `memory/PROJECT_STATE.md`
    - `memory/NEXT_SESSION.md`
14. End the session.

The single next action written in `NEXT_SESSION.md` should be:

> **Implement M1 Structure Workspace beginning with local PDB/mmCIF import and immutable artifact storage.**

Do not implement M1 during the bootstrap session.

---

# 25. Definition of done for bootstrap

Bootstrap is complete only when:

```text
[ ] fresh Windows clone installs development dependencies
[ ] backend tests pass
[ ] frontend tests pass
[ ] TypeScript typecheck passes
[ ] Python typecheck/lint passes
[ ] frontend build passes
[ ] Tauri application opens
[ ] Python backend starts
[ ] frontend reports backend health
[ ] frontend displays detected/missing Vina and GNINA tools
[ ] no scientific feature is falsely represented as implemented
[ ] ADRs exist
[ ] project state is updated
[ ] exactly one next action is recorded
```

---

# 26. Product language

Prefer:

- docking score
- predicted pose
- crystallographic reference pose
- redocking
- structural warning
- preparation decision
- chemical state
- conformer
- configuration recovered the reference pose

Avoid:

- binding affinity, unless experimental/validated external evidence exists
- validated ligand
- confirmed binder
- inhibitor, unless independently established
- correct pose
- universally validated docking

---

# 27. Long-term product direction

Potential future versions may include:

- AutoDock-GPU;
- improved interaction diagrams;
- publication-ready structure figures;
- larger virtual-screening campaigns;
- AlphaFold models;
- Linux;
- WSL GPU execution;
- remote/HPC execution;
- additional engines.

These are not commitments.

The personal workflow remains the product compass:

> **Can Ankora make a real docking experiment easier to inspect, execute, understand, and reproduce without taking scientific control away from the user?**

If yes, implement it.

If it only adds automation, complexity, or marketing value, defer it.

---

# 28. Final instruction to Codex

Build conservatively.

Prefer a small working vertical architecture over a large speculative framework.

Do not implement future abstractions without a demonstrated need.

Do not optimize for community adoption yet.

Do not copy the previous Ankora implementation.

Do not reuse old code merely because it exists.

Treat this document as the initial clean-slate contract.

The first goal is not to dock a molecule.

The first goal is to create a trustworthy foundation on which the docking workbench can be built.
