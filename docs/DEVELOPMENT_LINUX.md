# Linux Development and Offline Packaging Guide

This guide covers source development, hash-locked scientific environments, external tool discovery, modular offline packaging (`ADR-029`), clean-room verification (`D4`), bare-metal workstation attestation (`D6`), and continuous integration (`verify-linux`) for the **Linux `x86_64`** edition of Ankora (Ubuntu 24.04 LTS reference baseline).

For current platform and engine distribution status, see [`docs/product/PLATFORM_STATUS.md`](product/PLATFORM_STATUS.md). For Windows development and NSIS packaging, see [`docs/DEVELOPMENT.md`](DEVELOPMENT.md).

---

## 1. Current Linux Scope and Release Boundary

- **Implemented in source (`ADR-026`–`ADR-029`):** Full `M1–M9` desktop workflow (`Tauri v2` + `WebKitGTK 4.1` + `Python 3.12.13` FastAPI backend) across **AutoDock Vina `1.2.7`**, **AutoGrid4 / AutoDock4 `4.2.6` (CPU)**, **AutoDock-GPU `1.6` (CUDA 12)**, and Linux-only **GNINA `1.3.3`** (single-ligand and sequential virtual screening on `CPU` or single-GPU `CUDA 12.8`, `rescore` and CUDA-only `refinement`, built-in `dense_1_3`, `default_1_3_ensemble`, and `default1.0` CNN models, `CNNscore` and `CNN_VS` hit prioritization, redocking Validation UI, `ProLIF` interactions, `Methods`, Export v4, and recoverable `Trash`).
- **Distribution status (`release_candidate`):** Core offline `.deb` (`272.34 MiB`), zero-`sudo` portable `.tar.zst` (`313.97 MiB`), corresponding-sources companion `.zip` (`390.77 MiB`), and the 1-click GUI-imported offline GNINA CUDA 12.8 pack (`2.55 GiB` / `2,610.34 MiB`) pass clean-room verification under WSL2/WSLg (`D4`, [`LINUX_OFFLINE_PACKAGE_SMOKE.md`](validation/LINUX_OFFLINE_PACKAGE_SMOKE.md)). Final public Linux release sign-off awaits bare-metal physical Linux workstation execution (`D6`, [`LINUX_NATIVE_WORKSTATION_PROTOCOL.md`](validation/LINUX_NATIVE_WORKSTATION_PROTOCOL.md)).

---

## 2. System Prerequisites (Ubuntu 24.04 LTS / WSL2 with WSLg)

Install the native GTK/WebKitGTK desktop headers, Rust build essentials, and archive utilities:

```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  build-essential \
  dpkg-dev \
  libayatana-appindicator3-dev \
  libgtk-3-dev \
  librsvg2-dev \
  libssl-dev \
  libwebkit2gtk-4.1-dev \
  libxdo-dev \
  patchelf \
  pkg-config \
  zstd
```

Also install:
- **Node.js 22 LTS** (`node`, `npm`)
- **Rust stable toolchain** (`rustup`, `cargo`, `clippy`, `rustfmt`)
- **Miniforge3** (`conda`, Linux `x86_64` — never reuse Windows executables mounted under `/mnt/c`)

---

## 3. Locked Scientific Environment Setup

Create the isolated Linux Conda environment from the SHA-256-locked specification and install the hash-locked Python wheels without re-resolving transitive dependencies:

```bash
conda create -n ankora-dev --file environment/linux-64.conda.lock --yes
conda activate ankora-dev
export PYTHONNOUSERSITE=1

python -m pip install --require-hashes --only-binary=:all: -r requirements/linux-py312.lock
python -m pip install --no-deps --no-build-isolation -e backend
python -m pip check
python scripts/verify_linux_environment_lock.py --runtime
npm ci
```

> **Packaging isolation rule:** Never install `requirements/linux-packaging.lock` (`pyinstaller`, build-only `setuptools`) into `ankora-dev`; `scripts/build_linux_backend.py` creates a dedicated packaging virtual environment so runtime metadata stays byte-faithful to `linux-py312.lock`.

---

## 4. Running Ankora in Source Development

From the repository root with `ankora-dev` active:

```bash
npm run tauri:dev:linux
```

How the Linux development session works:
- `apps/desktop/scripts/tauri-linux.mjs` locates `cargo` on `PATH` or `${CARGO_HOME:-$HOME/.cargo}/bin` without mutating shell dotfiles.
- `scripts/dev_linux.py` selects a native Linux Python interpreter in strict priority order: explicit `ANKORA_PYTHON_PATH` (failing closed if invalid or pointing to a Windows PE binary), active non-`base` Conda prefix, project `.venv`, or named `ankora-dev` Conda environment.
- It starts `ankora_backend` on `127.0.0.1:8765` with `--parent-pid` supervision and `npm run dev` on `127.0.0.1:1420`, refusing to reuse or kill foreign listeners on occupied ports and terminating all owned session subprocesses cleanly on exit (`SIGINT`/`SIGTERM`).

---

## 5. External Tool Discovery in Source Development

End users of packaged `.deb` / `.tar.zst` builds receive bundled Core tools automatically. When running from source (`ANKORA_APP_MODE != "packaged"`), Ankora discovers native Linux `x86_64` ELF binaries without executing them during discovery:

| Tool | Explicit env override (authoritative) | Conventional fallback locations | Notes |
| --- | --- | --- | --- |
| **AutoDock Vina `1.2.7`** | `ANKORA_VINA_PATH` | `PATH`, `~/tools/autodock-vina-*` | Verified with `--version` at job launch. |
| **AutoGrid4 / AutoDock4 `4.2.6`** | `ANKORA_AUTOGRID4_PATH`, `ANKORA_AUTODOCK4_PATH` | `PATH`, `~/tools/autodock-*` | Enforces `14` ligand / `20` receptor atom-type limits. |
| **P2Rank `2.5.1`** | `ANKORA_P2RANK_PATH` (+ `JAVA_HOME` Java 17–23) | `~/tools/p2rank_*` | Reads version metadata without executing Java during scan. |
| **AutoDock-GPU `1.6`** | `ANKORA_AUTODOCK_GPU_PATH` | `PATH`, `~/tools/autodock-gpu-1.6/bin` (`autodock_gpu_128wi`, `autodock_gpu_64wi`, `autodock_gpu`) | Requires compatible host GPU driver; preflight coordinates FIFO device probes via `ResourceArbiter` (`AUTODOCK_GPU_PROBE_RESOURCES_BUSY` / HTTP 409 when busy). |
| **GNINA `1.3.3`** | `ANKORA_GNINA_PATH` | `PATH`, `~/tools/gnina-*`, or GUI-imported `<app_local_data_dir>/toolchains/gnina-1.3.3-cuda12/` | Pinned to official `1.3.3` SHA-256 `3340c1f49cd3c7c84d8699182a1c6af13c7fa2a22448d1204640446106f72172` for built-in ensemble provenance (`ADR-028`). |

Restart a running development session after changing tool paths or environment variables, or click **Rescan tools** in **Tools -> Scientific tools**.

---

## 6. Building Offline Linux Packages & the 1-Click GNINA Pack (`ADR-029`)

The modular Linux release pipeline ([`ADR-029`](architecture/ADR/ADR-029-linux-offline-distribution.md)) produces self-contained offline Core installers alongside an optional 1-click GNINA CUDA 12.8 pack:

1. **Freeze slim Python 3.12.13 backend:** `python scripts/build_linux_backend.py` (compiles `ankora-backend` via PyInstaller in an isolated packaging venv and verifies frozen module bytecode parity).
2. **Compile multi-arch CUDA 12 AutoDock-GPU:** `python scripts/build_linux_autodock_gpu.py` (`sm_75`..`sm_120`, linked against static `libcudart_static.a` with zero bundled host driver libraries).
3. **Stage Core scientific payload & 700-component legal companion:** `python scripts/stage_linux_scientific_payload.py` and `python scripts/complete_linux_legal.py` (stages Vina `1.2.7`, AutoGrid4/AutoDock4 `4.2.6`, AutoDock-GPU `1.6`, Temurin OpenJDK `21.0.12.1+1`, P2Rank `2.5.1` with `default` and `alphafold` models, third-party notices, and `Ankora_0.1.0_linux-sources-companion.zip`).
4. **Build Core `.deb` and zero-`sudo` portable `.tar.zst`:** `python scripts/build_linux_installer.py` (emits `Ankora_0.1.0_amd64.deb` for double-click installation on Ubuntu/Debian/Mint/Pop!\_OS and `Ankora_0.1.0_linux_x86_64.tar.zst` for unprivileged user-space extraction).
5. **Build 1-click offline GNINA CUDA 12.8 pack:** `python scripts/build_linux_gnina_pack.py` (bundles `gnina 1.3.3` + `17` redistributable CUDA `12.8` and cuDNN `9.25` user-space `.so` libraries + NVIDIA/GPL notices + `gnina-pack.json` into `Ankora_0.1.0_gnina-cuda12-pack.tar.zst` plus `< 2 GiB` `.part01`/`.part02` chunks for GitHub Releases, strictly excluding `libcuda.so*`, `libnvidia-ml.so*`, and `libnvidia-ptxjitcompiler.so*`).

End users import `Ankora_0.1.0_gnina-cuda12-pack.tar.zst` directly inside **Tools -> Scientific tools** (or **Docking -> GNINA**) with zero `sudo` and zero terminal commands; Ankora verifies every SHA-256 entry, installs into `<app_local_data_dir>/toolchains/gnina-1.3.3-cuda12/`, and scopes the pack's `lib/` directory via `LD_LIBRARY_PATH` exclusively to `gnina` child processes (`LD_LIBRARY_PATH_ORIG` restores the host environment cleanly outside PyInstaller's `_internal/`).

---

## 7. Clean-Room Smoke (`D4`), Bare-Metal Gate (`D6`) & Ubuntu 24.04 CI (`D5`)

### Clean-room package smoke (`D4`)

Run `python scripts/smoke_linux_package.py` to test `.deb` and `.tar.zst` cold start, loopback binding, the `10/10` Core scientific adapter matrix, 1-click GNINA pack import (`11/11` tools), CPU/CUDA `rescore` and CUDA `refinement` (`default_1_3_ensemble`) runs, and persistence across package removal under a sanitized `PATH`/`HOME`/`XDG_DATA_HOME`. Recorded WSL2/WSLg evidence: [`LINUX_OFFLINE_PACKAGE_SMOKE.md`](validation/LINUX_OFFLINE_PACKAGE_SMOKE.md).

### Bare-metal native Linux workstation attestation (`D6`)

WSL2/WSLg execution uses Microsoft's `/usr/lib/wsl/lib` driver bridge and does **not** substitute for physical workstation acceptance ([`ADR-026`](architecture/ADR/ADR-026-linux-port-and-native-acceptance.md) Gate 4). On a physical non-WSL `x86_64` Linux workstation with an NVIDIA GPU (`driver >= 570.x` recommended), execute [`LINUX_NATIVE_WORKSTATION_PROTOCOL.md`](validation/LINUX_NATIVE_WORKSTATION_PROTOCOL.md):

```bash
/usr/bin/python3 scripts/smoke_linux_package.py \
  --native-workstation-attestation \
  --gnina-pack ./Ankora_0.1.0_gnina-cuda12-pack.tar.zst
```

### Local test suite & Ubuntu 24.04 CI (`verify-linux`)

`.github/workflows/ci.yml` runs `verify-linux` (`ubuntu-24.04`) alongside `verify` (`windows-latest`). Locally, run the exact CI checks:

```bash
python scripts/check_public_paths.py
python scripts/check_public_validation_status.py
python scripts/check_platform_docs.py
python scripts/verify_linux_environment_lock.py --runtime
python -m pytest backend/tests/test_screening_benchmark_primary_metrics_diagnostic.py
python -m pytest backend \
  --deselect tests/test_screening_benchmark_protocol.py::test_primary_vina_metrics_reproduce_from_the_closed_campaign \
  --deselect tests/test_screening_benchmark_sensitivity_plan.py::test_sensitivity_plan_is_deterministic_and_loss_preserving \
  --deselect tests/test_screening_benchmark_sensitivity_plan.py::test_sensitivity_plan_rejects_post_freeze_factor_tampering \
  --deselect tests/test_screening_benchmark_sensitivity_plan.py::test_recorded_sensitivity_plan_reproduces_exactly \
  --deselect "tests/test_screening_benchmark_sensitivity_plan.py::test_historical_verification_rejects_changed_source_bytes[microstate_schema_path]" \
  --deselect "tests/test_screening_benchmark_sensitivity_plan.py::test_historical_verification_rejects_changed_source_bytes[microstate_service_path]"
python -m ruff check backend
python -m mypy --config-file backend/pyproject.toml backend/src
npm run test:frontend
npm run typecheck
npm run build
cargo fmt --manifest-path apps/desktop/src-tauri/Cargo.toml --all -- --check
cargo clippy --manifest-path apps/desktop/src-tauri/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml
```

> **Note on the 6 deselected Windows BEDROC checks:** Frozen Windows LIT-PCBA BEDROC floating-point outputs differ at `<= 4 ULP` (`<= 8.33e-17`) under Linux `glibc` `libm` (`expm1`). Ankora preserves the frozen Windows manifests untouched and runs the SHA-256-anchored diagnostic in [`LINUX_PRIMARY_METRICS_NUMERIC_DIAGNOSTIC.md`](validation/LINUX_PRIMARY_METRICS_NUMERIC_DIAGNOSTIC.md) instead of loosening strict Windows reproduction.

---

## 8. Historical Bootstrap Lineage

The Linux port was authorized on `2026-10-28` (`ADR-026`) starting from public-lineage commit `e705ff6` while keeping the Windows development checkout isolated. Sequential milestones—development launcher (`LINUX_BACKEND_BOOTSTRAP.md`), WebKitGTK desktop shell (`LINUX_DESKTOP_BOOTSTRAP.md`), scientific runtime lock & process lifetime (`LINUX_SCIENTIFIC_FOUNDATION_REVIEW.md`), native P2Rank & Vina execution, CUDA AutoDock-GPU campaign & cancellation (`LINUX_AUTODOCK_GPU_CAMPAIGN_AND_CANCEL.md`), GNINA single-ligand and screening integration (`LINUX_GNINA_INITIAL_SMOKE.md`, `LINUX_GNINA_TOPOLOGY_SMOKE.md`, `LINUX_GNINA_CNN_MODES.md`, `LINUX_GNINA_REFINEMENT_CUDA.md`, `LINUX_GNINA_SCREENING_CNN_VS.md`), and offline packaging (`LINUX_OFFLINE_PACKAGE_SMOKE.md`)—are indexed in full under [`docs/validation/INDEX.md`](validation/INDEX.md).
