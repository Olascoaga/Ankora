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

## Remaining acceptance

Private tool staging, all transitive notices/corresponding sources, complete
offline NSIS integration, the rebuilt GPU calculation, and installed end-to-end
CPU/GPU smokes must pass before calling this a complete installer. A local
isolated-PATH check is not evidence of a clean Windows VM. Signing, a release
tag and community publication remain separate gates.
