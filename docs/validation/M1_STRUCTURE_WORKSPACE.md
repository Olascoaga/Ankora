# M1 Structure Workspace acceptance evidence

Date: 2026-08-19
Authoritative platform: Windows 11 x64

## Acceptance criteria

- [x] Open a local PDB file.
- [x] Open a local CIF/mmCIF file.
- [x] Fetch a four-character PDB ID from RCSB.
- [x] Preserve every successful imported/downloaded original without overwriting it.
- [x] Record SHA-256, source, source URL where applicable, timestamp, parser/version, warnings, and provenance.
- [x] Parse and display structure metadata.
- [x] Render the preserved structure with Mol* behind the viewer adapter.
- [x] Click/select consolidated author chains and non-water heterogens.
- [x] Emit structured warnings for reported missing coordinates, alternate locations, and nonstandard polymer residues.
- [x] Keep M1 read-only and perform no coordinate transformation.
- [x] Pass automated tests, lint, type checks, production build, and a Windows-native smoke.

## Synthetic contract fixtures

`backend/tests/fixtures/synthetic_m1.pdb` and `synthetic_m1.cif` are explicitly synthetic contract fixtures, not experimental data. They exercise polymers, a ligand, water, a metal, alternate atom locations, and missing-coordinate records.

Two live imports of the PDB fixture created different artifact UUIDs while preserving identical bytes and SHA-256:

`7d93cbdefb6b2689d6c68c3d0d0364a0b5f339e5a6f3d61810d59e939a417630`

This demonstrates create-only identity; it is not a scientific validation result.

## Recorded RCSB smoke

Ankora fetched `https://files.rcsb.org/download/7AQF.cif` through the backend and preserved the returned file before visualization.

- Stored size: 698,639 bytes
- SHA-256: `79fd3b96adca6bdbe17ded6e9c693534007ae2cb0538739044788754b7c6faac`
- Parser: Gemmi 0.7.5
- Parsed observation for this exact hash: 1 model, 6,266 atoms, 1,218 residues, 2 consolidated author chains, 482 heterogen records including RV2 A:401 and 481 waters
- Warnings: stable missing-residue and missing-atom codes derived from mmCIF structured categories

The observed counts are recorded evidence tied to the exact downloaded hash. They are not frozen docking expectations and do not claim preparation correctness.

## Visual/native evidence

- Tauri launched `ankora-desktop.exe` with Vite and the localhost FastAPI backend.
- Mol* rendered the synthetic PDB fixture and the recorded 7AQF mmCIF artifact.
- The inspector showed two consolidated author chains for 7AQF, summarized the 481 waters, and selected RV2 A:401.
- A clean visual run produced no browser console warnings or errors.
- The complete automated suite passed: 16 backend tests and 9 frontend tests, plus Ruff, strict mypy, strict TypeScript, and production Vite build.

## M1 boundary

No imported coordinates were modified. No receptor preparation, ligand preparation, scientific executable, docking engine, or generated command was run.
