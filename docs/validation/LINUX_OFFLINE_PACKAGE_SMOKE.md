# Linux Offline Package & One-Click GNINA Pack Clean-Room Smoke (`ADR-029` Gate `D4`)

## Scope and boundary

This record documents the clean-room offline package verification (`D4` in
[ADR-029](../architecture/ADR/ADR-029-linux-offline-distribution.md)) executed by
`scripts/smoke_linux_package.py` against the built Ankora `0.1.0` Linux x86-64
release artifacts.

- **What this verifies:** Self-contained execution of `Ankora_0.1.0_amd64.deb`
  and `Ankora_0.1.0_linux_x86_64.tar.zst` with Conda and `/usr/local/cuda`
  stripped from `PATH` and `LD_LIBRARY_PATH` unset; Tauri `WebKitGTK` desktop
  shell ownership and monotonic `/proc/<pid>/stat` parent-watchdog lifecycle of
  the frozen `ankora-backend`; loopback-only API binding (`127.0.0.1:8765`);
  `10/10` Core scientific tool execution including multi-architecture
  `AutoDock-GPU 1.6` and `P2Rank 2.5.1` on bundled `Temurin OpenJDK 21`;
  zero-`sudo` API import and SHA-256 verification of
  `Ankora_0.1.0_gnina-cuda12-pack.tar.zst` (`gnina 1.3.3` + `17` CUDA `12.8` and
  cuDNN `9.25` shared libraries with `LD_LIBRARY_PATH_ORIG` isolation from
  PyInstaller `_internal/`); end-to-end `Vina`, `GNINA` CPU `rescore`, `GNINA`
  CUDA `rescore`, and `GNINA` CUDA `refinement` (`default_1_3_ensemble`) runs;
  and persistence of user-installed GNINA toolchains and project records across
  package removal and portable `.tar.zst` launch.
- **What this does not claim:** Execution took place under WSL2/WSLg
  (`Linux-6.18.33.2-microsoft-standard-WSL2-x86_64-with-glibc2.39`,
  `NVIDIA GeForce RTX 5050 Laptop GPU`, `/usr/lib/wsl/lib` host driver bridge).
  Per `ADR-026` Gate 4 and `ADR-029` Gate `D6`, bare-metal Linux workstation
  acceptance remains a separate final gate governed by
  [LINUX_NATIVE_WORKSTATION_PROTOCOL.md](LINUX_NATIVE_WORKSTATION_PROTOCOL.md).
  Docking checks use the fixed `1VII` villin headpiece and explicitly synthetic
  ethanol smoke inputs and make no biological or benchmark accuracy claim.

## Verified release artifacts (`<release_dir>/`)

| Artifact | Size (bytes) | Size (MiB) | SHA-256 |
| --- | ---: | ---: | --- |
| `Ankora_0.1.0_amd64.deb` | `285,567,716` | `272.34` | `1c005b5e7cf7cc7626c895a1cd6ca2e536da529c7b9864a6949834c5e306aca9` |
| `Ankora_0.1.0_linux_x86_64.tar.zst` | `329,218,220` | `313.97` | `3390fdfa5075dd24b9b034acbfd908b462c5968b11402bc432e04b4a9bf8bd6b` |
| `Ankora_0.1.0_linux-sources-companion.zip` | `409,749,819` | `390.77` | `881889e5151ce2adc16aa8594a2ef2d4c06ab1dbaa06f2282b1087c74745323b` |
| `Ankora_0.1.0_gnina-cuda12-pack.tar.zst` | `2,737,137,778` | `2,610.34` | `d9f1bb6496b621a5e8fc14b2eac1ca2566497630829a8e6682bc434f73ed70be` |
| `Ankora_0.1.0_gnina-cuda12-pack.tar.zst.part01` | `1,610,612,736` | `1,536.00` | `1fda57990872851fb0b20bf8b12f36e6a03028ead611cd94d00f1b67aa328ff8` |
| `Ankora_0.1.0_gnina-cuda12-pack.tar.zst.part02` | `1,126,525,042` | `1,074.34` | `4ee73d1008634c51a023a67932b4c564fe1dbc1bc53d824e971de952d6cf5686` |

Packaged ELF binary identities across both `.deb` and `.tar.zst` bundles:

- `ankora-desktop`: `b2e04c19eb01ac9bc176d5d2ceb70d5724edb34139b8f24703fd16cd64e5d318`
- `ankora-backend`: `3c973607b1e73b30c0325c3127c2c0b4d008f8b68f587c35b2b22a74c60156a2`

## Clean-room smoke execution summary (`package-smoke-20261112T034040Z`)

- **Command:** `python scripts/smoke_linux_package.py`
- **Sanitized `PATH`:** `/usr/bin:/bin:/usr/lib/wsl/lib` (`LD_LIBRARY_PATH` unset, isolated temporary `HOME` and `XDG_DATA_HOME`)
- **Started / Completed (UTC):** `2026-11-12T03:40:40.189910+00:00` -> `2026-11-12T03:43:43.505799+00:00`
- **Outcome:** `passed` (`package-smoke-evidence.json` SHA-256: `c4f55d17e738d0f9fa1bf9de0da4c827f4e5c3cc3a45783de9d8d7dca3e71b46`)

### 1. Bundle audit & desktop cold start (`.deb`)

- Extracted `.deb` audit passed: `2,303` regular files, `211` relative intra-tree
  symlinks, `700`-component legal manifest verified, and zero bundled host
  kernel-driver libraries (`libcuda.so*`, `libnvidia-ml.so*`).
- `ankora-desktop` launched under WSLg and started `ankora-backend` on loopback
  `127.0.0.1:8765` (`/proc/net/tcp:0100007F`).
- `/api/v1/system` reported `app_mode = "packaged"`, `platform = "linux"`,
  `architecture = "x86_64"`, `python_environment = "Bundled Python 3.12"`,
  `python_version = "3.12.13"`.
- `/api/v1/tools` reported all `10/10` Core tools available (`autodock4 4.2.6`,
  `autodock_gpu 1.6`, `autogrid4 4.2.6`, `meeko 0.7.1`, `meeko_ligand 0.7.1`,
  `p2rank 2.5.1`, `pdb2pqr 3.7.1`, `pdbfixer 1.12.0`, `propka 3.5.1`,
  `vina 1.2.7`) and `gnina.available = false` prior to pack import.

### 2. Core `10/10` native scientific tool matrix

- Executed `<bundle>/usr/lib/ankora/backend/ankora-backend --worker native-smoke`
  under the sanitized environment in `12.582 s`.
- All `10/10` adapters passed (`manifest_sha256`:
  `0f08703e2326ec672daa3a517e34512f3d800fa9ecc29bc8016bca8cd55ddf6e`):
  - `python_scientific_runtime`: `MDAnalysis 2.10.0; dimorphite_dl 2.0.2; meeko 0.7.1; openmm 8.5.2; pdb2pqr 3.7.1; pdbfixer 1.12.0; prolif 2.2.1; propka 3.5.1; rdkit 2025.9.6`
  - `pdbfixer_repair`: `1.12.0`
  - `pdb2pqr_propka`: `pdb2pqr 3.7.1; propka 3.5.1`
  - `meeko_receptor` / `meeko_ligand`: `0.7.1`
  - `p2rank`: `2.5.1` on bundled `Temurin-21.0.12.1+1` (`java` SHA-256 `999c141a6e620c71aa4230ccb62341a89162f37818753ff006d766bf935dcbe1`)
  - `vina`: `1.2.7` (`f31f774f723bba7bbe6e9d1c47577020eea9a8da16424284c043d22593570644`)
  - `autogrid4`: `4.2.6` (`e38a7b299336af0e150eadf87d3e89b409a3b3ca43ec7975922e08534ddca19d`)
  - `autodock4_cpu`: `4.2.6` (`6dad50cb0ae291a824dc23d98b242f6243e6e101cc2a8350940897ec08890818`)
  - `autodock_gpu`: `1.6` (`0d1be9d563be94e439eea592578b9e689b6603712507212e663c0076806a009c`) on `NVIDIA GeForce RTX 5050 Laptop GPU`

### 3. One-click offline GNINA pack import & docking verification

- `POST /api/v1/tools/gnina-pack/import` verified and installed
  `gnina-1.3.3-cuda12.8-cudnn9.25-linux-x86_64` (`gnina` SHA-256
  `3340c1f49cd3c7c84d8699182a1c6af13c7fa2a22448d1204640446106f72172` + `17`
  CUDA 12.8 / cuDNN 9.25 `.so` libraries) into
  `<XDG_DATA_HOME>/science.ankora.workbench/toolchains/gnina-1.3.3-cuda12` in
  `17.672 s`, transitioning `/api/v1/tools` to `11/11` without restart.
- Prepared the `1VII` receptor + synthetic ethanol ligand through the live
  packaged HTTP API and executed four docking runs:

| Engine & Mode | Job ID | CNN Model Identity | Poses | Top Primary Metric | GPU Process Observed (`nvidia-smi`) | Wall (s) |
| --- | --- | --- | ---: | --- | --- | ---: |
| `Vina 1.2.7` CPU | `01a8f371-d452-48fb-bbce-e621408a6ea7` | N/A | `3` | `-2.377 kcal/mol` | N/A | `<1.0` |
| `GNINA 1.3.3` CPU `rescore` | `a7407819-ba24-482e-bea3-42e84da0d487` | `dense_1_3` (`1` model) | `2` | `CNNscore 0.930388` (`CNN_VS 1.881092`) | `false` | `25.014` |
| `GNINA 1.3.3` CUDA `rescore` | `017a8f27-f47d-426b-a20f-7c68a3058a95` | `dense_1_3` (`1` model) | `3` | `CNNscore 0.930393` (`CNN_VS 1.881805`) | `true` (`GPU-4fec5c6f-e22d-45ac-5898-743b25fe83b6`) | `6.992` |
| `GNINA 1.3.3` CUDA `refinement` | `995f6fb5-1525-4194-b363-d4a751b3c137` | `default_1_3_ensemble` (`3` KD models) | `3` | `CNNscore 0.916750` (`CNN_VS 2.739088`) | `true` (`GPU-4fec5c6f-e22d-45ac-5898-743b25fe83b6`) | `72.056` |

### 4. Package removal & portable `.tar.zst` persistence parity

- Stopped `ankora-desktop` (`SIGTERM` cleanly terminated both desktop and child
  backend and closed port `8765`), deleted the `.deb` extraction directory, and
  extracted `Ankora_0.1.0_linux_x86_64.tar.zst` (`2,305` regular files, `211`
  intra-tree symlinks, identical `ankora-desktop` and `ankora-backend` SHA-256
  digests).
- Launched the portable bundle against the same isolated `XDG_DATA_HOME`:
  `/api/v1/tools` immediately reported `gnina 1.3.3` available without
  re-importing the `2.55 GiB` pack, and `/api/v1/results` preserved all `3`
  recorded GNINA jobs (`persisted_gnina_campaign_entries = 3`).

### 5. GitHub Releases `< 2 GiB` split-part streaming import & rollback verification

- Split `Ankora_0.1.0_gnina-cuda12-pack.tar.zst` (`2,737,137,778` bytes) with
  `--split-mib 1536` into two `< 2.0 GiB` release assets (`.part01`:
  `1,610,612,736` bytes / `1,536.00 MiB`; `.part02`: `1,126,525,042` bytes /
  `1,074.34 MiB`) recorded in `gnina-pack-manifest.json` and `SHA256SUMS.txt`.
- **Missing-part guard:** Importing `.part01` with `.part02` absent failed
  immediately before decompression with `GNINA_PACK_PARTS_INCOMPLETE`.
- **Clean-room 2-part streaming import:** Importing `.part01` with `.part02`
  present streamed and verified the full `2.55 GiB` archive in `122.775 s`,
  installing `gnina 1.3.3` (`3340c1f49cd3c7c84d8699182a1c6af13c7fa2a22448d1204640446106f72172`)
  and all `17` CUDA `12.8` / cuDNN `9.25` shared libraries with zero temporary
  concatenated copy on disk.
- **Corrupted-part rollback & toolchain preservation:** Flipping `16` tail bytes
  in `.part02` and re-importing failed cleanly with `GNINA_PACK_CORRUPT_ARCHIVE`
  while preserving the existing installed toolchain (`verify_installed_pack(force_rehash=True)` passed).
