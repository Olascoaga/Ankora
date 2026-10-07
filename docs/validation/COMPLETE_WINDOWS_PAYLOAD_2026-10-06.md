# Complete Windows payload — implementation evidence

Date: 2026-10-06. Implements ADR-024 in bounded units. This record is not a
clean-machine acceptance or a public release declaration.

## 1. Upstream inputs

`resources/windows-scientific-payload.lock.json` freezes the exact supported
Vina 1.2.7, AutoDock Suite 4.2.6, AutoDock-GPU 1.6 reference/source, P2Rank
2.5.1 distribution/models/source, and private Temurin 21.0.12.1+1 artifacts.
The Java 21 security patch is a runtime choice, not a scientific engine upgrade.
The build-only 7-Zip 26.04 MSI is also hash-bound. None is downloaded at end-user
runtime and no developer tools directory is used as the distribution source.

All eleven upstream inputs were acquired and independently SHA-256-verified.
Vina and AutoDock Suite/GPU match the previously recorded executable hashes.
P2Rank and Temurin match the digest published by their official release APIs.
Archives without upstream digest metadata are pinned to the bytes acquired
over official HTTPS, not claimed to have an upstream signature.

The acquisition helper rejects corrupt caches instead of silently replacing
them. Partial downloads cannot become verified cache entries. Extraction is
create-only and validates every archive member before writing, rejecting
traversal, symlinks, Windows aliases/devices/streams and case collisions.
Eighteen synthetic acquisition/extraction tests pass; the real offline cache
verification passes all eleven entries. This is input verification, not a
completed redistribution review for every transitive dependency.

## 2. AutoDock-GPU dependency finding

PE inspection of the official 1.6 Windows executable found imports of
`KERNEL32.dll`, `OpenCL.dll`, and `libomp140.x86_64.dll`. Microsoft's
[/openmp documentation](https://learn.microsoft.com/en-us/cpp/build/reference/openmp-enable-openmp-2-0-support?view=msvc-170)
identifies the LLVM-flavored MSVC runtime as non-redistributable. The official
executable is therefore explicitly `reference-only` in the lock, not an
approved installer payload. Do not copy that DLL from a development machine.

The scientist explicitly authorized rebuilding the same 1.6 source with a
redistributable dependency and validating a new binary identity. Historical
results keep their original executable hashes and are not relabeled.
The supported MSVC OpenMP runtime is documented separately in Microsoft's
[OpenMP library reference](https://learn.microsoft.com/en-us/cpp/parallel/openmp/reference/openmp-library-reference?view=msvc-170).

## 3. Private installed discovery

Frozen backends resolve all six external runtime entries only from a relative,
SHA-256-verified inventory beside the executable. Developer PATH, Conda, Java
and explicit tool overrides cannot mask a missing packaged component. Python
tools dispatch to frozen workers. P2Rank launches private Java directly with an
argument array (no command shell), and ignores Java injection environment
variables. Sources, models and user scientific artifacts are not modified.

The frozen native smoke now propagates its actual exit status and includes its
synthetic fixtures. A local isolated-PATH run under a directory containing
spaces and an accented character passed nine of ten adapters, including private
Java/P2Rank and all engine probes. Ligand preparation failed because RDKit's
filename reader cannot open an accented Windows path. This is an acceptance
finding to fix, not permission to drop Unicode from testing. This local test
does not constitute a clean Windows installation or a complete installer.

## 4. Redistributable GPU candidate and bounded calculation

The authorized 1.6 rebuild uses MSVC 14.44.35207 and the redistributable
14.44.35112 `vcomp140.dll`, with static C/C++ runtime linkage. Its only direct
imports are `KERNEL32.dll`, `OpenCL.dll` (the device driver interface), and
`VCOMP140.DLL`. The LLVM runtime is absent. Scientific search/scoring code is
unchanged: three atomic timing-counter updates use equivalent OpenMP 2.0
syntax, the project selects ordinary MSVC OpenMP, and debug-path information is
disabled. The builder retains the patched corresponding source and raw build
logs, and refuses unexpected source patterns or overwritten evidence.

- New executable SHA-256:
  `e1f7704efca05c8b1c05fb47fbb13ecdc472a79b3cbe7f8d8d08f69d42269a69`.
- OpenMP DLL SHA-256:
  `55aba23cdcd6484fbb06f4155b8ca75adfce7a881f10afd0c49457165e677164`.
- Patched corresponding-source archive SHA-256:
  `76f64f65988546d2c418e7769a27a6f452eaf55eedd2256031261ad0c3480a5e`.

`scripts/smoke_rebuilt_autodock_gpu.py` ran the upstream 1STP example with two
runs, 200,000 evaluations, explicit three-part seed, ADADELTA, heuristics off
and autostop off. On the NVIDIA GeForce RTX 5050 Laptop GPU, both requested
poses passed Ankora's existing DLG parser. Actual recorded scores were -7.95 and
-6.87 kcal/mol; these are runtime smoke observations, not benchmark acceptance
or expected numbers for another run/build/device. No old result is relabeled.
DLG SHA-256: `1973e134952f6b4a3cf8468e9de8bd110ca78dd3e84fa6c8f2e309ea2c4a0e14`.
The raw input copies, stdout, stderr, commands, DLG and acceptance manifest are
retained privately under the ignored build tree.

Create-only staging now assembles six private tool entries and 485 hash-bound
files, including private Java and the complete P2Rank runtime/model directories
without upstream example datasets. The build-only extractor is independently
hash-checked. Nineteen acquisition/extraction tests and four builder guard
tests use explicitly synthetic archives/metadata, not invented chemistry.

## Remaining acceptance

All transitive notices/corresponding sources, complete
offline NSIS integration, and installed end-to-end
CPU/GPU smokes must pass before calling this a complete installer. A local
isolated-PATH check is not evidence of a clean Windows VM. Signing, a release
tag and community publication remain separate gates.
