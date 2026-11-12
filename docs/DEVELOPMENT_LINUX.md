# Linux port work plan

For WSL or native Linux development, activate the project environment and run
`npm run tauri:dev:linux`. The Linux Tauri launcher respects Cargo on `PATH` and,
if it is absent there, checks the Rust installation in `${CARGO_HOME:-$HOME/.cargo}/bin`.
It does not install Rust or change the user's shell configuration. In an existing
checkout without this launcher, run `source "$HOME/.cargo/env"` before starting.
In WSL Ubuntu, the fallback was checked with a PATH lacking Cargo: the real
`cargo metadata --no-deps --format-version 1` succeeded through the launcher.
Synthetic launcher tests cover an existing PATH entry, a custom Cargo home,
missing Cargo, and argument forwarding. This check does not test WSLg display.

The scientist authorized the Linux port on 2026-10-28. See ADR-026.

## Source baseline

The independent Linux checkout starts from public-lineage commit `e233788`.
The accepted working Obsidian UI is carried into Linux as a separate source
snapshot, preserving the Windows checkout and its uncommitted work. The snapshot
contains only the eight existing UI/design files; Windows installer experiments,
private memory, build products and scientific projects are excluded.

## Initial unit — development bootstrap

- **Claude / backend:** implement a Linux development launcher and focused tests.
  Own `scripts/dev_linux.py`, `backend/tests/test_linux_dev.py` and
  `docs/validation/LINUX_BACKEND_BOOTSTRAP.md`. Select an explicit or project
  Python interpreter, verify API identity/readiness, fail clearly on occupied
  ports, retain startup errors, and clean up only owned subprocesses on exit.
  Launch commands as arrays, bind localhost, keep existing chemistry unchanged.
- **Gemini / desktop:** own `apps/desktop/package.json`, Linux Tauri configuration,
  platform-specific Rust compatibility, focused configuration/Rust tests and
  `docs/validation/LINUX_DESKTOP_BOOTSTRAP.md`. Add explicit Linux development
  commands consuming Claude's launcher. Preserve Windows commands/configuration,
  installed backend behavior, CSP and current appearance. No Linux installer
  claim in this unit.
- **Codex / review:** owns this plan, ADR, policy, environment setup and integration
  evidence. Review each diff and relevant tests before integration. Resolve
  shared-file changes sequentially. No automatic pushes or co-author trailers.

The launcher interface is `python3 ../../scripts/dev_linux.py` from the desktop
package directory. It owns a backend plus `npm run dev` from the repository root,
using the existing API port 8765 and frontend port 1420. Python selection:
`ANKORA_PYTHON_PATH`, active non-base Conda, project `.venv`, or a named
`ankora-dev` environment; an invalid explicit selection must fail clearly.
Do not silently reuse another running backend or kill unrelated listeners.

## Acceptance

1. Linux frontend tests, type check and production build pass on the carried UI.
2. Launcher tests prove startup/readiness, collision handling and owned cleanup.
3. Linux Rust formatting/tests/check or build passes with real GTK/WebKit deps.
4. A real Tauri window opens through WSLg; an imported tracked structure fixture
   is visible in Mol*. Record actual rendering/runtime, screenshots and errors.
5. Confirm the Windows checkout has exactly its original dirty-file set and
   preserved source bytes. Record any checks not executed rather than claiming
   Windows packaging or native workstation acceptance.

## Later units

Scientific Linux parity and lock, CPU engines and cancellation, independent GPU
acceptance, then complete offline packaging and native workstation validation.
Each bounded completed unit gets relevant tests, tracked evidence and a small
commit. Private coordination logs and memory stay ignored.

## Scientific foundation update — 2026-10-28

The second bounded unit now has native discovery, a Linux scientific environment
lock/verifier and owned-session process cancellation, integrated from isolated
Claude/Gemini branches after coordinator review. Public PR lineage begins at
`e705ff6`; the unrelated unpublished manual commit from the original local source
snapshot is excluded. Windows development files remain preserved.

See [the coordinator's scientific review](validation/LINUX_SCIENTIFIC_FOUNDATION_REVIEW.md)
for exact accepted checks, raw-evidence manifest identity and known failures.
Environment identity and preparation smoke are accepted for this bounded unit;
the complete Linux parity/release gate remains open. Native P2Rank execution,
the recorded portability failures, real CPU docking/redocking, independent GPU
acceptance and complete Linux packaging still require their own evidence.

## AutoDock-GPU development — WSL2

Linux development now discovers executable x86-64 ELF AutoDock-GPU binaries
named `autodock_gpu_128wi`, `autodock_gpu_64wi` or `autodock_gpu` on PATH,
in a versioned `~/tools/autodock-gpu-1.6/bin` directory, or at an explicit
`ANKORA_AUTODOCK_GPU_PATH`. An explicit path is authoritative; an invalid
one is not silently replaced by a different installation. Discovery only
reads the executable's identity; a docking request separately probes the
engine version and device. A compatible GPU driver and the binary's native
runtime libraries must already be available to the backend.

The locally compiled AutoDock-GPU 1.6 CUDA binary was tested on WSL2 with an
RTX 5050 through the actual API, including a two-molecule campaign and
cancellation after the process was observed in GPU compute. See
[the recorded engineering checks](validation/LINUX_AUTODOCK_GPU_CAMPAIGN_AND_CANCEL.md).
Restart a running development session after changing its executable or
environment. If the scheduler is busy, device preflight returns an explicit
busy message; retry when active or queued work has finished.

These checks do not establish compatibility for other GPU architectures,
CUDA/OpenCL builds or drivers, cancellation of an uninterruptible process,
the packaged runtime, or a native Linux workstation. Linux distribution and
native workstation acceptance remain open; no existing Windows binary is used
as a Linux engine.

## GNINA development — Linux only

The scientist authorized GNINA as a Linux-only engine; see
[ADR-027](architecture/ADR/ADR-027-linux-gnina.md). The official 1.3.3 CUDA
12.8 binary was checksum-verified and exercised on the WSL RTX 5050. A backend
engine boundary now probes Linux executable version and hash, builds explicit
`rescore` commands using `dense_1_3` and prepared PDBQT inputs, and parses
ranked SDF/PDBQT poses and separate CNN/empirical scores. PDBQT poses can be
checked against the prepared conformer using Meeko. See the
[initial run](validation/LINUX_GNINA_INITIAL_SMOKE.md) and
[topology and adapter checks](validation/LINUX_GNINA_TOPOLOGY_SMOKE.md).

This is **not yet an application-level GNINA feature**: no GNINA job API,
durable service, result catalog or docking UI is wired. The backend adapter
alone does not verify that a requested CUDA run used the GPU. Next integrate
resource arbitration, observed device evidence, cancellation, work recovery,
project-scoped persistence and a single-ligand API before enabling the UI;
library screening and cross-platform result review follow separately.
GNINA is not enabled on native Windows. The 2 GB executable used for
development is local and ignored by Git, not part of a distributable bundle.
Native workstation, driver/library identity and licensing checks remain open.

## Offline Linux Packaging, One-Click GNINA Pack & Ubuntu 24.04 CI (ADR-029)

The historical bootstrap/development notes above are preserved for lineage. Under
[ADR-028](architecture/ADR/ADR-028-gnina-cnn-vs-refinement-ensemble.md) and
[ADR-029](architecture/ADR/ADR-029-linux-offline-distribution.md), Linux GNINA
single-ligand and screening workflows (`CNN_VS`, `CNNscore`, `rescore`, CUDA
`refinement`, built-in CNN ensembles, M9 ProLIF interactions, redocking,
Methods, and campaign Export v4) and modular offline Linux distribution are
implemented:

1. **Core Offline Linux Installer (`D0`–`D3`):**
   - `scripts/build_linux_backend.py` freezes the slim Python 3.12.13 scientific
     backend via PyInstaller inside an isolated packaging virtual environment
     without mutating the locked Conda prefix.
   - `scripts/build_linux_autodock_gpu.py` compiles a multi-architecture CUDA 12
     (`sm_75`..`sm_120`, static `cudart`) AutoDock-GPU 1.6 binary free of host
     driver libraries.
   - `scripts/stage_linux_scientific_payload.py` and
     `scripts/complete_linux_legal.py` stage Vina 1.2.7, AutoGrid4/AutoDock4
     4.2.6, AutoDock-GPU 1.6, Temurin OpenJDK 21, P2Rank 2.5.1 (`default` +
     `alphafold` models), the 700-component legal inventory/notices, and the
     corresponding-sources companion ZIP (`Ankora_0.1.0_linux-sources-companion.zip`).
   - `scripts/build_linux_installer.py` builds `Ankora_0.1.0_amd64.deb` (primary
     double-click Debian/Ubuntu/Mint/Pop!_OS package) and
     `Ankora_0.1.0_linux_x86_64.tar.zst` (portable zero-`sudo` archive).

2. **One-Click Offline GNINA CUDA 12 Pack (`D2b`–`D3`):**
   - `scripts/build_linux_gnina_pack.py` packages `gnina 1.3.3` alongside its 17
     required CUDA 12.8 and cuDNN 9.25 user-space `.so` runtime libraries,
     `gnina-pack.json`, and NVIDIA/GPL legal notices into
     `Ankora_0.1.0_gnina-cuda12-pack.tar.zst`, explicitly excluding host driver
     libraries (`libcuda.so*`, `libnvidia-ml.so*`, `libnvidia-ptxjitcompiler.so*`).
   - End users import the `.tar.zst` pack directly from the **Tools** tab inside
     Ankora (`POST /api/v1/tools/gnina-pack/import`) into
     `<app_local_data_dir>/toolchains/gnina-1.3.3-cuda12/` with zero `sudo`,
     zero terminal commands, and scoped `LD_LIBRARY_PATH` isolation on GNINA
     subprocesses only.

3. **Clean-Room Package Smoke (`D4`) & Bare-Metal Workstation Gate (`D6`):**
   - `scripts/smoke_linux_package.py` verifies both `.deb` and `.tar.zst`
     artifacts end-to-end under a sanitized user environment (`HOME`, `PATH`
     stripped of developer toolchains); see
     [LINUX_OFFLINE_PACKAGE_SMOKE.md](validation/LINUX_OFFLINE_PACKAGE_SMOKE.md).
   - WSL2/WSLg acceptance does **not** substitute for bare-metal Linux release
     acceptance ([ADR-026](architecture/ADR/ADR-026-linux-port-and-native-acceptance.md)
     Gate 3). On a physical non-WSL Linux x86_64 workstation with an NVIDIA GPU,
     run the single-command attestation protocol documented in
     [LINUX_NATIVE_WORKSTATION_PROTOCOL.md](validation/LINUX_NATIVE_WORKSTATION_PROTOCOL.md):
     ```bash
     python3 scripts/smoke_linux_package.py \
       --native-workstation-attestation \
       --gnina-pack /path/to/Ankora_0.1.0_gnina-cuda12-pack.tar.zst
     ```

4. **Ubuntu 24.04 GitHub Actions CI (`D5`):**
   - `.github/workflows/ci.yml` defines `verify-linux` (`ubuntu-24.04`) alongside
     `verify` (`windows-latest`), enforcing `environment/linux-64.conda.lock`,
     `requirements/linux-py312.lock`, `requirements/linux-packaging.lock`,
     `scripts/verify_linux_environment_lock.py --runtime`, the SHA-256-anchored
     cross-OS primary metrics diagnostic
     ([LINUX_PRIMARY_METRICS_NUMERIC_DIAGNOSTIC.md](validation/LINUX_PRIMARY_METRICS_NUMERIC_DIAGNOSTIC.md)),
     backend `pytest`/`ruff`/`mypy`, frontend `vitest`/`tsc`/`vite build`, Rust
     `fmt`/`clippy`/`test`, and `npm run tauri:build:linux`.
