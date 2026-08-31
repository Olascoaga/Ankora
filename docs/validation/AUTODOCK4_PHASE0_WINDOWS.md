# AutoDock4 Phase 0 native-Windows validation — 2026-08-24

## Outcome

Phase 0 passed on the authoritative Windows 11 x64 development machine. The
official AutoGrid4 and AutoDock4 4.2.6 CPU binaries are discoverable and their
real version probes succeed. AutoGrid produced complete map sets for both the
current 7AQF co-crystallized-ligand pocket and the previously confirmed 7AQF
full-protein blind box. This validates the native CPU distribution and grid
contract; it does not enable AutoDock4 docking, which still needs immutable map
persistence plus typed DPF/DLG execution.

## Native tools

The official `autodocksuite-4.2.6.i86Windows.exe` installer was downloaded from
the Scripps AutoDock site. It is unsigned PE32/x86, 577,275 bytes, SHA-256
`306dc72a06e80a2da6f3c410ac6aba7ebdaeef6b702eca42de44c7c6c9d48755`.
Because two isolated silent-install attempts created no output, its NSIS payload
was extracted without a system install and inspected directly.

- AutoGrid 4.2.6: x86, SHA-256
  `797efce687d1ae82df59726461e0e1966b3d8edb0f8b187f982fa1ab0c12da9e`.
  Its real `--version` probe reports double precision, 20 receptor types, 14
  ligand atom types, 16 maps, 1025 maximum grid intervals per axis, and GPLv2+.
- AutoDock 4.2.6: x86, SHA-256
  `36c0b16c04d7df8e6225737bae65bb04058d1f4c90accfaf2d230dbc913954bf`.
  Its real `-v` probe reports double precision, no OpenMP, 32 torsions, 2048
  atoms, 16 maps, 1025 maximum grid intervals per axis, and GPLv2+.
- AutoDock-GPU 1.6: x86_64, SHA-256
  `be21dd5dea36a391e3d77286cd8a5bf18b080306d32c7178c56f0a9e4f373bbf`.
  Its real `--help` probe succeeds. No GPU docking was launched in Phase 0.

## Real selection preflight

Input selection was preserved Vina batch
`06f9a26e-a722-453a-b99a-042674abf977`, containing 283 manifest rows. The
receptor PDBQT SHA-256 is
`bb85972139b2dbe53c404ac91c870e53d4850ed19f09c7c4ca36aec1e6a8f55a`
and its types are `A C HD N NA OA SA`.

- 282 rows have prepared PDBQT.
- 281 are compatible with stock AutoDock4 CPU 4.2.6.
- Compound 143 has no prepared PDBQT and remains an explicit preflight failure.
- Compound 195 contains Meeko macrocycle glue types `CG0` and `G0`. Stock
  AutoGrid/AutoDock4 cannot parameterize them, so it remains an explicit
  engine-incompatible row. They were not changed to carbon.
- The compatible library union is `A C Cl F HD N NA OA S SA`, ten affinity maps
  and therefore below AutoGrid 4.2.6's hard limit of fourteen.

The complete local preflight manifest is preserved at
`.ankora-data/projects/default/validation/autodock4-phase0-20260824/selection_preflight.json`,
SHA-256 `cfcab32c217cc5d1d606173e66d1dfbf79f989251869fff0e6437b0a006ac179`.

## Real AutoGrid evidence

Both jobs used an ASCII-only job namespace, the exact receptor above, 0.375 Å
spacing, 0.5 Å smoothing, calibrated distance-dependent dielectric `-0.1465`,
and the exact ten-type compatible library union. Grid intervals were calculated
with ceiling followed by the next even integer, so no confirmed box shrank.

| Binding site | Requested size (Å) | Intervals | Realized size (Å) | Wall time | Evidence size | Result |
| --- | --- | --- | --- | --- | --- | --- |
| `cfb3d5cd-8c8a-456e-9607-b7abe57fcfb5` co-crystallized ligand | 21.597 × 19.870 × 19.317 | 58 × 54 × 52 | 21.75 × 20.25 × 19.50 | 9.80 s | 16.07 MiB | Successful Completion |
| `02d298cd-82a3-42ad-b6fa-358badec0502` full protein | 58.521 × 85.371 × 68.626 | 158 × 228 × 184 | 59.25 × 85.50 × 69.00 | 5 min 22.88 s | 453.56 MiB | Successful Completion |

Each evidence directory retains the GPF, GLG, receptor copy, `.fld`, `.xyz`, ten
affinity maps, electrostatic map, desolvation map, command, stdout/stderr, sizes,
and SHA-256 values. The aggregate local `report.json` SHA-256 is
`6a634b8f83a54e3658d09530d524da4d336a1c6d9773722b66b4491531966cc1`.
The reproducible runner is `scripts/validate_autodock4_phase0.py`.

## Acceptance boundary

Accepted: binary identity/version/architecture, grid discretization, exact atom
type union, row-level incompatibility, GPF generation, small/full AutoGrid
execution, and preservation of raw evidence.

Not yet accepted: production map-store/API/UI, DPF generation, AutoDock4 CPU
docking, DLG parsing and clustering, library scheduling, redocking validation,
or AutoDock-GPU execution.
