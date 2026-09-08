# Native scientific-tool smoke matrix — 2026-09-08

## Risk closed

Ankora previously had separate real-tool validation notes, but no single
repeatable command exercised every supported process-launching boundary after
recreating the Windows environment. A green dependency lock could therefore
coexist with a broken launcher, Java dependency, portable executable, compiled
limit parser, OpenCL selection, or raw-output retention path.

## Contract

`scripts/run_native_tool_smoke.py` creates a new evidence directory for every
run and refuses to reuse an existing one. It covers ten explicit rows:

| Row | Adapter boundary | Bounded operation |
| --- | --- | --- |
| Python runtime | locked scientific imports | Imports PDBFixer/OpenMM, PDB2PQR/PROPKA, Meeko, RDKit, Dimorphite-DL, ProLIF, and MDAnalysis and reports distribution versions. |
| PDBFixer | `run_pdbfixer` | Repairs the reported missing CB in the explicitly synthetic M1 ALA fixture. |
| PDB2PQR/PROPKA | `run_pdb2pqr_propka` | Protonates the installed PDBFixer 1BHL test fixture at pH 7.4 with AMBER. |
| Meeko receptor | `run_meeko_receptor` | Converts that generated PQR with `charge_model=read`. |
| Meeko ligand | `execute_meeko_ligand` | Generates a deterministic ETKDGv3/MMFF94s conformer from synthetic ethanol and prepares it with explicit Gasteiger charges. |
| P2Rank | `execute_p2rank` | Runs prediction against the same fixed 1BHL fixture and requires a structured predictions CSV. |
| Vina | `probe_vina` | Verifies exact version 1.2.7 without docking. |
| AutoGrid4 | `probe_autogrid4` | Verifies exact version 4.2.6 and compiled limits without generating maps. |
| AutoDock4 CPU | `probe_autodock4` | Verifies exact version 4.2.6 and compiled limits without docking. |
| AutoDock-GPU | `probe_autodock_gpu` | Verifies exact version/build and selected OpenCL device using deliberately absent inputs, so no docking can occur. |

GNINA is named as deferred in both the executable contract and every manifest;
there is no supported GNINA execution adapter to smoke in this release.
`--check` validates the row set and tracked fixture presence without requiring
any external scientific tool, and is enforced by local verification and CI.
The aggregate local gate also creates a unique pytest base directory under the
Windows temporary root on every invocation; it no longer reuses the historical
repository-local directory whose stale ACL could cause unrelated setup errors.

Every adapter result records status, scope, version, executable hash when
applicable, fixture and output byte counts/SHA-256 values, exact argument-array
commands, exit codes, and separately hashed raw stdout/stderr files. The raw
manifest may contain machine-local paths and therefore remains below ignored
`.ankora-data`; this tracked record contains no private path.

## Recorded Windows execution

The authoritative run completed all **10/10** rows. Its local manifest SHA-256
is:

```text
16471ad86f064baea530ab2298a92ce8afdb4137e6f8719ae964c2b419acbb9a
```

Observed versions were PDBFixer 1.12.0, OpenMM 8.5.2, PDB2PQR 3.7.1,
PROPKA 3.5.1, Meeko 0.7.1, RDKit 2025.9.6, Dimorphite-DL 2.0.2, ProLIF
2.2.1, MDAnalysis 2.10.0, P2Rank 2.5.1 on OpenJDK 21.0.12, Vina 1.2.7,
AutoGrid4/AutoDock4 4.2.6, and AutoDock-GPU 1.6. The GPU probe selected the
recorded NVIDIA OpenCL device; it did not receive valid maps or ligand input.

Key fixture/output evidence:

| Evidence | Bytes | SHA-256 |
| --- | ---: | --- |
| Synthetic M1 receptor fixture | 936 | `7d93cbdefb6b2689d6c68c3d0d0364a0b5f339e5a6f3d61810d59e939a417630` |
| PDBFixer repaired PDB | 809 | `c84b47214841d31b527779c727e25e7d9052d02774a9b9eadc192c9a6320c5e8` |
| Upstream 1BHL fixture | 123,363 | `7ff77930c706778d5009d49fe314d36829fb24b42392c9ca76a49b91301f228f` |
| PDB2PQR protonated PQR | 158,551 | `e8e8327fbf4968eb492827e0dbb36e462ee00c32b1de431f86562190171e44ee` |
| Meeko receptor PDBQT | 115,182 | `cc3d4748789b2fd188c05a71f35e12bcfe9143fe3cd9ef16040dce394ed71d2b` |
| Synthetic ethanol source | 22 | `e8aad0bdae1b0bb65afcb6a728823dd0d028c9988d3a34299ce9f3d09c95f92d` |
| Generated minimized ethanol SDF | 829 | `c512116a5f2de9a9181642b5eabf64f704c3003b760896cdc7de5ccd3749677c` |
| Meeko ligand PDBQT | 456 | `cc1a0556c11daf6e7025c30c0207550d28bf2b1eba08e4e2c118b8f4b179e748` |
| P2Rank predictions CSV | 322 | `42574b705d8a1d6e0fd3a122b05b879e3cc5855bc30b6aa32c777d9eec458e7b` |

Executable SHA-256 values remained
`e0c4b2715e0c1a74f6e92d0f3be0328ac97542eafbc111e6b1efad897a73cce5`
for Vina,
`797efce687d1ae82df59726461e0e1966b3d8edb0f8b187f982fa1ab0c12da9e`
for AutoGrid4,
`36c0b16c04d7df8e6225737bae65bb04058d1f4c90accfaf2d230dbc913954bf`
for AutoDock4 CPU, and
`be21dd5dea36a391e3d77286cd8a5bf18b080306d32c7178c56f0a9e4f373bbf`
for AutoDock-GPU.

The run is compatibility evidence only. It does not establish preparation
quality, docking convergence, ranking validity, affinity, or biological
meaning; those claims remain governed by the frozen scientific validations.

## Verification gate

- Native matrix: 10/10 real adapter rows passed.
- Backend: 505 tests passed; Ruff and strict mypy passed across 118 source files.
- Frontend: 245 tests across 34 files, strict TypeScript, and the production
  Vite build passed.
- Native shell: Rust formatting, strict Clippy, unit/doc tests, and the
  optimized Windows Tauri build passed.
- Repository: environment-lock, matrix-contract, and public-path checks passed.
