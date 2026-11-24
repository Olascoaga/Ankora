# Ankora `v0.2` Post-Benchmark Offline Installer Rebuild, `ADR-031` Byte Attestation & Clean-Room `D4` Smoke (`86d89ed`)

- **Date:** 2026-11-24
- **Branch:** `codex/v0.2-dev` (packaged at `86d89ed` incorporating live multi-engine and physics fixes `4a07c19`, `2474334`, and `9ec95a1`; strictly isolated from `main` and frozen tag `v0.1.0-beta.2` at `36f1c0e`)
- **Governance:** [`ADR-024`](../architecture/ADR/ADR-024-complete-scientific-installer.md), [`ADR-029`](../architecture/ADR/ADR-029-linux-offline-distribution.md), [`ADR-031`](../architecture/ADR/ADR-031-external-benchmark-boundary.md) (`<= 1.00 MiB` cumulative `M0`–`M6.5` installer-size delta budget), [`ADR-033`](../architecture/ADR/ADR-033-hit-to-analog-expansion-and-pose-focused-screening.md)
- **Preceding Records:** [`V02_OFFLINE_INSTALLER_ATTESTATION.md`](V02_OFFLINE_INSTALLER_ATTESTATION.md) (initial `142e904` packaging attestation), [`V02_EXTERNAL_BENCHMARK_MULTITARGET_VS_DOCKM8.md`](V02_EXTERNAL_BENCHMARK_MULTITARGET_VS_DOCKM8.md), [`V02_EXTERNAL_BENCHMARK_INDUCED_FIT_FLEXRES_VS_DOCKM8.md`](V02_EXTERNAL_BENCHMARK_INDUCED_FIT_FLEXRES_VS_DOCKM8.md)
- **Scope Boundary:** Refreshed offline rebuild of all three `v0.2` installers (`.exe`, `.deb`, `.tar.zst`) embedding all live fixes uncovered during the `ADR-031` external comparison campaign (`4a07c19` Meeko topology clustering, `2474334` AutoDock `.dlg` staging strip, `9ec95a1` `AutoDock4 4.2.6 epdb` `unbound_model = bound` + AutoGrid map symlinks + parallel medoid rescoring), unified 3-artifact `python -S scripts/check_v02_installer_budget.py` attestation, Windows sanitized-PATH packaged smoke (`10/10` tools + `v0.2` REST routes), and Linux clean-room `D4` offline smoke under WSL2/WSLg. This record does **not** alter frozen `v0.1` scientific claims in [`VALIDATION_STATUS.md`](VALIDATION_STATUS.md) and does **not** substitute for bare-metal physical Linux workstation acceptance (`ADR-029` Gate `D6`).

---

## 1. Unified Three-Artifact `ADR-031` Byte-Delta Attestation (`python -S`, Packaged at `86d89ed`)

Executed simultaneously against all three newly compiled `86d89ed` offline installers via stdlib-only `/usr/bin/python3 -S scripts/check_v02_installer_budget.py` (`passed: true`, `191` backend Python modules audited, `5` dependency files checked, `0` forbidden dependency hits):

| Packaged Artifact (`v0.2` @ `86d89ed`) | `v0.1.0-beta.2` Baseline | Measured `v0.2` (`86d89ed`) | Measured Delta | `ADR-031` Cap (`1.00 MiB`) | Verdict | SHA-256 |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| **Windows x64 NSIS** (`Ankora_0.1.0_x64-setup.exe`) | `427,237,557 B` (`407.45 MiB`) | **`428,071,743 B` (`408.24 MiB`)** | **`+834,186 B` (`+814.63 KiB`)** | `<= 1,048,576 B` | **`within_budget: true`** | `1333b8e4106a642642e1dcd93fd25cfd4ee38f5d8c2a687ba1b35591b3cf37a4` |
| **Linux x86\_64 `.deb`** (`Ankora_0.1.0_amd64.deb`) | `285,567,616 B` (`272.34 MiB`) | **`285,974,140 B` (`272.73 MiB`)** | **`+406,524 B` (`+397.00 KiB`)** | `<= 1,048,576 B` | **`within_budget: true`** | `682392d532415c6ea43d7263bee81c349701edc0840eb7f144d3d5f16e22859e` |
| **Linux x86\_64 portable `.tar.zst`** (`Ankora_0.1.0_linux_x86_64.tar.zst`) | `329,218,187 B` (`313.97 MiB`) | **`329,905,206 B` (`314.62 MiB`)** | **`+687,019 B` (`+670.92 KiB`)** | `<= 1,048,576 B` | **`within_budget: true`** | `7ee32b2847719880b5e0ea3bf3b608d0f5aacd9e068306b68b2f89f052f24809` |

Corresponding source companions & preserved baseline integrity:
- Windows source companion (`Ankora_0.1.0_x64-sources-companion.zip`): `243,736,647 B` (`232.45 MiB`), SHA-256 `46367eb873f5ccdb81589b26222750302b2f92b4d0b6fc3b6e5000642efc7c04` (pinned with `--locked-webview2` SHA-256 & Authenticode lock `1.3.275.13`).
- Linux source companion (`Ankora_0.1.0_linux-sources-companion.zip`): `409,749,819 B` (`390.77 MiB`), SHA-256 `70c6c3b538290f6a2818d9a3ee26dc8e28c2bf62e264e143ca36bfb3ffccc1f7` (`701` legal components, `7` files).
- Frozen `v0.1.0-beta.2` Windows baseline (`Ankora_0.1.0_x64-setup.exe`) verified byte-identical after build (SHA-256 `db7850472fa836e01e86ab044a19bd62989f99aeab8382a660903cfc943e85bc`).

---

## 2. Packaged Runtime Smoke Evidence (`86d89ed`)

### 2.1 Windows 11 x64 Packaged Frozen Backend (`ankora-backend.exe`)
- Built cleanly with PyInstaller `6.22.2` (`ankora_backend.spec`) and launched directly with sanitized `PATH=C:\Windows\System32;C:\Windows` (zero Python or Conda on `PATH`), `ANKORA_APP_MODE=packaged`:
  - `app_mode = "packaged"`, `python_version = "3.12.13"`.
  - **`10/10` scientific tools reported `available = true`** (`autodock4`, `autodock_gpu`, `autogrid4`, `meeko`, `meeko_ligand`, `p2rank`, `pdb2pqr`, `pdbfixer`, `propka`, `vina`).
  - Live `v0.2` REST routes (`/api/v1/calibrations`, `/api/v1/consensus/runs`, `/api/v1/analog-expansion/catalogs`) responded **`200 OK`**.

### 2.2 Linux x86\_64 Clean-Room Offline Package Smoke (`ADR-029` Gate `D4`, WSL2/WSLg)
- Frozen Linux backend rebuilt with `scripts/build_linux_backend.py` (`executable_sha256`: `989a78eb2082d0e92d1a4276edaffe3b478378ddfa744ad8c15bf57b13ebb2ad`, `191` frozen Ankora modules, `origin_guard_verified: true`, `parent_pid_watchdog_verified: true`).
- Clean-room smoke executed via `/usr/bin/python3 scripts/smoke_linux_package.py` (`2026-11-24T17:03:15Z` -> `2026-11-24T17:08:51Z`, `status: "passed"`, `package-smoke-evidence.json` SHA-256 **`256e7237cfd6c21449c8eacb20eb9013a53296b6e385389086ecfba4b95b0ec5`**):
  - Cold-start `.deb`: `app_mode = "packaged"`, `Bundled Python 3.12.13`, strict loopback `/proc/net/tcp:0100007F`, **`10/10` Core tools ready**, `gnina_available_before_import = false`.
  - 1-click offline GNINA pack import (`58.125 s`, `17` isolated user-space CUDA `12.8`/cuDNN `9.25` shared libs, `gnina 1.3.3` SHA-256 `3340c1f4...`): passed (`11/11` tools).
  - Live docking inside packaged clean-room runtime:
    - `Vina 1.2.7` CPU: `3` poses (`-2.377 kcal/mol`).
    - `GNINA 1.3.3` CPU `rescore` (`dense_1_3`): `2` poses in `37.599 s` (`top_cnn_vs = 1.8811`).
    - `GNINA 1.3.3` CUDA `rescore` (`dense_1_3`, RTX 5050 `GPU-4fec5c6f-e22d-45ac-5898-743b25fe83b6`): `3` poses in `7.255 s` (`gpu_process_observed = true`).
    - `GNINA 1.3.3` CUDA `refinement` (`default_1_3_ensemble`, `3` KD models, RTX 5050): `3` poses in `72.586 s` (`top_cnn_vs = 2.8239`, `gpu_process_observed = true`).
  - Portable `.tar.zst` persistence parity after `.deb` removal: `gnina_persisted_available = true`, `persisted_gnina_campaign_entries = 3`.

---

## 3. Remaining Open Hardware Gate (`ADR-029` Gate `D6`)

Physical non-WSL bare-metal Linux workstation attestation (`Gate D6` per [`LINUX_NATIVE_WORKSTATION_PROTOCOL.md`](LINUX_NATIVE_WORKSTATION_PROTOCOL.md)) cannot be executed inside WSL2 and remains the sole hardware gate before cutting public `v0.2.0` Linux GA.
