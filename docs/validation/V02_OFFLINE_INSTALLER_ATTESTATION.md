# Ankora v0.2 Offline Installer Packaging, `ADR-031` Byte Attestation & Clean-Room Smoke (`D4`) — Dual-OS Verification

- **Date:** 2026-11-21
- **Branch:** `codex/v0.2-dev` (packaged at `142e904`; isolated from `main` and frozen tag `v0.1.0-beta.2` at `36f1c0e`)
- **Governance:** [`ADR-024`](../architecture/ADR/ADR-024-complete-scientific-installer.md), [`ADR-029`](../architecture/ADR/ADR-029-linux-offline-distribution.md), [`ADR-031`](../architecture/ADR/ADR-031-external-benchmark-boundary.md) (`<= 1.00 MiB` cumulative `M0`–`M6.5` installer-size delta budget), [`ADR-033`](../architecture/ADR/ADR-033-hit-to-analog-expansion-and-pose-focused-screening.md)
- **Preceding Records:** [`V02_M65_HIT_TO_ANALOG_EXPANSION.md`](V02_M65_HIT_TO_ANALOG_EXPANSION.md), [`LINUX_OFFLINE_PACKAGE_SMOKE.md`](LINUX_OFFLINE_PACKAGE_SMOKE.md)
- **Scope Boundary:** Offline packaging, PyInstaller frozen-runtime verification (bundling `posebusters==0.6.5` YAML configs while omitting `2.37 MB` of demo `posebusters/datasets/` PDB/SDF files), unified three-artifact `ADR-031` byte-delta attestation (`python -S scripts/check_v02_installer_budget.py`), Windows sanitized-PATH packaged smoke (`10/10` tools + `v0.2` endpoints), and Linux clean-room offline package smoke (`D4` under WSL2/WSLg with zero Conda/pip, `10/10` Core tools + 1-click `GNINA 1.3.3 CUDA` pack import + live CUDA execution + `.tar.zst` persistence). This record does **not** alter frozen `v0.1` scientific claims in [`VALIDATION_STATUS.md`](VALIDATION_STATUS.md) and does **not** replace bare-metal physical Linux workstation sign-off (`ADR-029` Gate `D6`).

---

## 1. Unified Three-Artifact `ADR-031` Byte-Delta Attestation (`python -S`)

Executed simultaneously against all three freshly compiled `v0.2` (`M0`–`M6.5` @ `142e904`) offline installers using stdlib-only `python -S scripts/check_v02_installer_budget.py` (`passed: true`; `191` backend Python modules audited, `0` forbidden dependency hits):

| Packaged Artifact (`v0.2` `M0`–`M6.5`) | `v0.1.0-beta.2` Baseline | Measured `v0.2` | Measured Delta | `ADR-031` Cap (`1.00 MiB`) | Verdict | SHA-256 |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| **Windows x64 NSIS** (`Ankora_0.1.0_x64-setup.exe`) | `427,237,557 B` (`407.45 MiB`) | **`428,043,636 B` (`408.21 MiB`)** | **`+806,079 B` (`+787.19 KiB`)** | `<= 1,048,576 B` | **`within_budget: true`** | `f4a814d1229bcaf57ec70e291fa4f07632509a2d612d3ab63e1bdfebe67be54c` |
| **Linux x86\_64 `.deb`** (`Ankora_0.1.0_amd64.deb`) | `285,567,616 B` (`272.34 MiB`) | **`285,972,040 B` (`272.72 MiB`)** | **`+404,424 B` (`+394.95 KiB`)** | `<= 1,048,576 B` | **`within_budget: true`** | `00677a9d51a965297b2f6ab457220abfac5595dcf39e8351394072770132a0e4` |
| **Linux x86\_64 portable `.tar.zst`** (`Ankora_0.1.0_linux_x86_64.tar.zst`) | `329,218,187 B` (`313.97 MiB`) | **`329,873,529 B` (`314.59 MiB`)** | **`+655,342 B` (`+639.98 KiB`)** | `<= 1,048,576 B` | **`within_budget: true`** | `e61604a51b5cf8e66468cd82195626cf2f156eff3dc2e24914ae6ca6569f21e9` |

Corresponding source companions built cleanly alongside the installers:
- Windows companion (`Ankora_0.1.0_x64-sources-companion.zip`): `243,736,647 B` (`232.45 MiB`), SHA-256 `46367eb873f5ccdb81589b26222750302b2f92b4d0b6fc3b6e5000642efc7c04`.
- Linux companion (`Ankora_0.1.0_linux-sources-companion.zip`): `409,749,819 B` (`390.77 MiB`), SHA-256 `e5c74c9c6e21364e4f3a513a03c238b3c5b9af9bd28f481667378f3bd6e4c557`.
- Preserved `v0.1.0-beta.2` Windows baseline (`Ankora_0.1.0_x64-setup.exe`) verified byte-identical after build (SHA-256 `db7850472fa836e01e86ab044a19bd62989f99aeab8382a660903cfc943e85bc`).

### Upstream Windows WebView2 Evergreen Drift Finding (`2026-11-21`)

During Windows packaging, `scripts/prepare_windows_webview2.py` detected live upstream rotation at Microsoft's Evergreen redirect (`212,358,352 B` locked 2026-10-07 snapshot `1.3.275.13` -> `294,099,168 B` live 2026-11-21 snapshot, `+81.74 MB`). To preserve exact apples-to-apples `ADR-031` measurement and prevent unreviewed upstream drift, `scripts/build_slim_windows_installer.py` (`d856178`) added explicit `--locked-webview2` pinning verified by `verify_nsis_selection` against both `resources/windows-webview2.lock.json` (`SHA-256 ac22ecdc19c5b88b87f3fa752c00da9541653a8f5c0c5fc4a3b2b6ebe6591f69`) and Microsoft's Authenticode signature.

---

## 2. Packaged Runtime Smoke Evidence

### 2.1 Windows 11 x64 Packaged Frozen Backend (`ankora-backend.exe`)
- PyInstaller `6.22.2` (`ankora_backend.spec`) bundled `posebusters/config/dock.yml` while omitting `posebusters/datasets/` (`2,368,028 B` saved) and froze all `ankora_backend` submodules (`complete-legal`: `665` components, `124` files).
- Launched directly with sanitized `PATH` (zero Python or Conda on `PATH`), `ANKORA_APP_MODE=packaged`:
  - `10/10` scientific tools reported `available = true` (`pdbfixer`, `pdb2pqr`, `propka`, `meeko`, `meeko_ligand`, `vina`, `autogrid4`, `autodock4`, `autodock_gpu`, `p2rank`).
  - Live `v0.2` REST routes (`/api/v1/calibrations`, `/api/v1/consensus/runs`, `/api/v1/analog-expansion/catalogs`) responded `200 OK`.

### 2.2 Linux x86\_64 Clean-Room Offline Package Smoke (`ADR-029` Gate `D4`, WSL2/WSLg)
- Executed via `/usr/bin/python3 scripts/smoke_linux_package.py` (stdlib-only, zero Conda/pip, sanitized `PATH`/`HOME`/`XDG_DATA_HOME`) against the newly built `v0.2` `.deb` + `.tar.zst` + pinned 2-part offline `GNINA 1.3.3 CUDA 12.8` pack.
- **Outcome:** **`status: "passed"`** (`2026-11-21T21:32:05Z` -> `2026-11-21T21:35:36Z`, `package-smoke-evidence.json` SHA-256 `9bf9402c54613fc90bee2163298361793622ef0845935e107070136d7c38b711`):
  - Cold-start `.deb` verification: `app_mode = packaged`, `Bundled Python 3.12.13`, strict loopback `/proc/net/tcp:0100007F`, **`10/10` Core tools ready**, `gnina_available_before_import = false`.
  - Native scientific adapter matrix (`Vina`, `AutoGrid4/AD4`, `AutoDock-GPU`, `Meeko`, `PDBFixer`, `PDB2PQR`, `PROPKA`, `P2Rank`, `ProLIF`): passed.
  - 1-click offline GNINA pack import (`13.843 s`, `17` isolated user-space CUDA `12.8`/cuDNN `9.25` shared libs, `gnina 1.3.3` SHA-256 `3340c1f4...`): passed (`11/11` tools).
  - Live GNINA docking inside packaged clean-room runtime:
    - CPU `rescore` (`dense_1_3`): `2` poses in `13.431 s` (`top_cnn_vs = 1.881`).
    - CUDA `rescore` (`dense_1_3`, RTX 5050 `GPU-4fec5c6f-e22d-45ac-5898-743b25fe83b6`): `3` poses in `6.513 s` (`gpu_process_observed = true`).
    - CUDA `refinement` (`default_1_3_ensemble`, `3` KD models, RTX 5050): `3` poses in `69.755 s` (`gpu_process_observed = true`).
  - Portable `.tar.zst` persistence parity after package removal: `gnina_persisted_available = true`, `3` persisted GNINA campaigns verified.

---

## 3. Bare-Metal Linux Workstation Gate (`ADR-029` Gate `D6`) — Execution Runbook

WSL2/WSLg passes `D4` cleanly but does **not** substitute for physical bare-metal Linux acceptance (`ADR-026` Gate 4 / `ADR-029` Gate `D6`). To close `Gate D6` on a physical non-WSL `x86_64` Ubuntu 24.04 LTS / Linux Mint / Pop!\_OS workstation with native NVIDIA driver (`>= 570.x`) and native X11/Wayland display:

1. Copy `Ankora_0.1.0_amd64.deb` (`00677a9d...`), `Ankora_0.1.0_linux_x86_64.tar.zst` (`e61604a5...`), `Ankora_0.1.0_gnina-cuda12-pack.tar.zst.part{01,02}`, and `SHA256SUMS.txt` to the workstation and verify `sha256sum -c SHA256SUMS.txt`.
2. Install the `.deb` (`sudo apt install ./Ankora_0.1.0_amd64.deb`).
3. Execute the single-command stdlib attestation script:
   ```bash
   /usr/bin/python3 scripts/smoke_linux_package.py \
     --native-workstation-attestation \
     --gnina-pack ./Ankora_0.1.0_gnina-cuda12-pack.tar.zst.part01
   ```
4. Archive the emitted `native-workstation-attestation.json` and SHA-256 alongside [`LINUX_NATIVE_WORKSTATION_PROTOCOL.md`](LINUX_NATIVE_WORKSTATION_PROTOCOL.md).
