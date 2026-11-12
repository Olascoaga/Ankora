# ADR-029 — Modular offline Linux distribution and one-click GNINA runtime pack

Status: accepted by the scientist, 2026-11-11.

## Context

`ADR-024` requires Ankora distributions to run supported scientific workflows
offline without asking end users to install Python, Conda, Java, or docking
executables manually, edit `PATH`, or configure environment variables. `ADR-026`
extends Ankora to Ubuntu 24.04 Linux (`WebKitGTK` + `Tauri`) with gates for
complete offline distribution (Gate 3) and bare-metal native Linux workstation
acceptance (Gate 4). `ADR-027` and `ADR-028` establish GNINA 1.3.3 (`rescore`,
CUDA `refinement`, built-in CNN ensembles, and `CNN_VS` hit prioritization) as a
Linux-only engine.

Empirical inspection of the Linux runtime binary closure reveals two hard
physical and licensing constraints that differ from the `~407 MiB` Windows slim
installer:

1. **Binary mass and dynamic CUDA/cuDNN closure:** Official `gnina` 1.3.3
   (`gnina.cuda12.8.static`, SHA-256 `3340c1f49cd3c7c84d8699182a1c6af13c7fa2a22448d1204640446106f72172`)
   is `2,056,131,000` bytes (`1.96 GiB`) by itself and dynamically links 7 CUDA
   12.8 user-space shared libraries (`libcudart.so.12`, `libcusparse.so.12`,
   `libcufft.so.11`, `libcublas.so.12`, `libcublasLt.so.12`, `libcusolver.so.11`,
   `libnvJitLink.so.12`, totaling `1.78 GiB`) plus `libcudnn.so.9` (`0.12 MiB`
   shim) which loads 9 additional `libcudnn_*.so.9` runtime sub-libraries via
   `dlopen()` during CUDA CNN evaluation (`1.12 GiB`). Bundling this `4.66 GiB`
   uncompressed GNINA closure inside the base installer would push every Linux
   download above `3.2 GiB`, exceed GitHub Releases' `2.0 GiB` single-asset
   ceiling, break standard `ar`-backed `.deb` tooling on many hosts, and force
   multi-gigabyte integrity hashing on cold start even for CPU Vina/AutoDock4
   users.
2. **Beginner Linux installation friction on Ubuntu 24.04 LTS:** Standard
   `AppImage` bundles fail out of the box for non-technical users on Ubuntu
   24.04 LTS because `libfuse2` (`libfuse.so.2`) is omitted from default
   installations, browser downloads strip the executable bit (`chmod +x`), and
   Ubuntu 24.04's AppArmor `unprivileged_userns` profile restricts unpackaged
   WebKit/sandboxed binaries. Conversely, a native `.deb` package opens directly
   in Ubuntu Software / GDebi on double-click, declares `libwebkit2gtk-4.1-0`
   and `libgtk-3-0t64` cleanly, and registers a desktop launcher without
   terminal usage.

## Decision

Adopt a **two-tier modular offline Linux distribution** (`Option A`) targeting
`linux-x86_64` (Ubuntu 24.04 LTS reference baseline):

1. **Core Offline Linux Installer (`~450 MiB`):**
   - **Primary beginner package (`Ankora_<version>_amd64.deb`):** Double-click
     graphical `.deb` installing the Tauri desktop shell, `.desktop` menu entry,
     icons, relocatable PyInstaller slim Python 3.12.13 scientific backend, and
     the complete hash-verified core tool suite (`AutoDock Vina 1.2.7`,
     `AutoGrid4/AutoDock4 4.2.6`, multi-architecture `AutoDock-GPU 1.6` linked
     against static `libcudart_static.a`, `Eclipse Temurin JRE 21.0.12.1+1`, and
     `P2Rank 2.5.1` with `default` and `alphafold` models), plus complete legal
     notices.
   - **Zero-`sudo` portable archive (`Ankora_<version>_linux_x86_64.tar.zst`):**
     Byte-equivalent relocalizable user-space bundle for managed university or
     laboratory workstations where end users lack administrator privileges.
   - **Corresponding-source companion (`Ankora_<version>_linux-sources-companion.zip`):**
     Carries unmodified upstream source archives satisfying `GPL-2.0`,
     `LGPL-2.1`, and `GPL-2.0 WITH Classpath-exception-2.0` obligations across
     both the core installer and the optional GNINA pack.

2. **One-Click Offline GNINA + CUDA 12.8 / cuDNN 9 Pack (`Ankora_<version>_gnina-cuda12-pack.tar.zst`):**
   - Distributed as a separate offline archive (with deterministic `<2.0 GiB`
     split-volume support when hosted on `2.0 GiB`-capped release mirrors).
   - Contains `gnina` 1.3.3 (`VERIFIED_GNINA_1_3_3_SHA256`), all 7 required CUDA
     12.8 runtime `.so` libraries (redistributable under NVIDIA CUDA SDK License
     Agreement Section `2.6 Attachment A`), all 10 cuDNN 9.25.0 runtime `.so`
     libraries including `dlopen()` sub-libraries (redistributable under NVIDIA
     cuDNN Supplement Chapter 8, `2. Distribution`), verbatim NVIDIA CUDA/cuDNN
     license notices, and a signed `gnina-pack.json` SHA-256 manifest.
   - **Never bundles host kernel-driver libraries** (`libcuda.so*`,
     `libnvidia-ml.so*`), which must always come from the host OS GPU driver.

3. **Zero-Terminal GUI Activation and Subprocess Linker Isolation:**
   - Inside Ankora's Linux desktop UI, when GNINA is not yet installed in
     packaged mode, the user selects the downloaded local pack file via a native
     file dialog (`Install GNINA Offline Pack...`).
   - The backend verifies every member against the compiled-in SHA-256 lock
     before atomically publishing the pack under
     `<app_local_data_dir>/toolchains/gnina-1.3.3-cuda12/`. No `sudo`, terminal
     commands, `chmod`, or `PATH` edits are required, and user-installed GNINA
     packs survive `.deb` application upgrades intact.
   - At execution time, Ankora injects the pack's private `lib/` directory into
     `LD_LIBRARY_PATH` **exclusively** for spawned `gnina` child processes,
     satisfying NVIDIA CUDA SDK License Section `1.2(ii)` ("distributable
     portions of the SDK shall only be accessed by your application") and
     preventing library collisions with Python/OpenMM, AutoDock-GPU, or WebKitGTK.

## Invariants and Non-Goals

- Windows packaging, locks (`windows-py312.lock`, `windows-packaging.lock`,
  `windows-scientific-payload.lock.json`), and runtime behavior remain untouched.
- Packaged Linux builds must never fall back to unverified developer `PATH`
  executables when a bundled core tool is missing or corrupted.
- Developer mode (`ANKORA_APP_MODE != "packaged"`) continues to honour
  `ANKORA_GNINA_PATH` and explicit developer environment discovery unchanged.
- WSL2/WSLg package smoke (`D4`) proves offline self-sufficiency and GUI/GPU
  mechanics in an isolated environment without Conda or `/usr/local/cuda` on
  `PATH`/`LD_LIBRARY_PATH`, while final release acceptance (`D6`, `ADR-026`
  Gate 4) still requires execution on a bare-metal native Linux workstation.
