# Linux AutoDock-GPU 1.6 CUDA smoke — predeclared protocol

## Scope

This bounded engineering test exercises the official Linux CUDA executable
directly on WSL2, outside Ankora's still-disabled Linux GPU discovery. It is
not a scientific benchmark, a release, a GUI/API test, native workstation
acceptance, or a claim of equivalence with Windows/OpenCL. Original example
inputs and all tool outputs remain in a new, isolated development directory.

## Fixed inputs

- Official [AutoDock-GPU v1.6 release](https://github.com/forlilab/AutoDock-GPU/releases/tag/v1.6)
  `adgpu-v1.6_linux_x64_cuda12_128wi`, locally observed SHA-256
  `04870ff6cf3451f97540748fa2d20f2b261c9b30bc312ecfc6adb09246dbb276`.
  The release metadata does not publish a SHA-256 digest; this identity is a
  locally calculated hash of the HTTPS download, not an upstream checksum.
- Official `input/1stp/derived` example from upstream commit
  `e63e6f6280ebfad18caa3e8f48afdc269e79e063`. Locally computed SHA-256:

| File | SHA-256 |
| --- | --- |
| 1stp_ligand.pdbqt | `f35894b3bc097b9acb25a96aec19d16d81f4ca0e9a6bb657fad49c94d074e231` |
| 1stp_protein.maps.fld | `812deb685eae3bab93aecc97bdcaf3f1d894e63c39ae872dd613329a234c6e4a` |
| 1stp_protein.maps.xyz | `e5b028c1551cec6bdc2c7089c447a3c1104e998281c6fbe18f83598ce7506e60` |
| 1stp_protein.A.map | `4bc02b07d3179c4146bfdcaefb8d43334a0ae3f5db5d7a6813982b4b85c0d374` |
| 1stp_protein.C.map | `e8aa7ed6f69b3c998cc3d24c115174240650b3e4840b47fb791d61b2021d929d` |
| 1stp_protein.OA.map | `ef1e40f3fcd820a5f7d6dc664c44d4edea55c3f8d82c97c1e12d7ecdb4a0b4db` |
| 1stp_protein.N.map | `35e322aa01e2e3837342951eb65220c14e853fce9057b9e67ed626ff08797a57` |
| 1stp_protein.SA.map | `55506502bacfefddf02468e6cc5d1e2d61a5a11ad111a5b71cf28a3c0ac80446` |
| 1stp_protein.HD.map | `fe6cdca43ba02bc895e2bb1d3ab95e75406fc23ea88a13ba4a23cc1db22ee58e` |
| 1stp_protein.e.map | `d24fe2a7d486a5dacd582e2b1fae06b7becee3ed22d523efc481316a30d4bb74` |
| 1stp_protein.d.map | `ae95050c06fca78e796c8a1e573d3b77f44e4b4097562523adb4ff2ef57bbbf2` |
| 1stp_protein.pdbqt | `f30d46043ae82e28041bc7b5fb2f707bbb1ebc52cb646d52aa7bfb6ebcf0e946` |

## Run and evidence

Make a create-only working copy; do not alter the upstream downloads. Run one
attempt with `--ffile 1stp_protein.maps.fld --lfile 1stp_ligand.pdbqt
--devnum 1 --nrun 1 --heuristics 0 --autostop 0 --nev 5000 --seed
20261029,20261030,20261031 --resnam ankora_gpu_smoke`, with a 120-second
process limit. Other tool settings remain upstream defaults and are captured in
the resulting log. This intentionally small search does not measure accuracy.

Keep exact command, exit code, stdout, stderr, generated DLG and any XML; hash
outputs, recheck unchanged inputs, and independently inspect the success/failure
message and parseability of the DLG. An exit code of zero is not sufficient.
Record any failure and do not tune the test after seeing an outcome. Do not
enable Linux GPU discovery until separate adapter and end-to-end checks establish
its behavior; preserve the Windows contract.

## Observed official-binary attempt

The Linux CUDA 12 binary identified itself as `AutoDock-GPU version: v1.6`;
unlike the Windows build, this line contained no build or architecture fields.
With nonexistent input paths the device probe named an NVIDIA GeForce RTX 5050
Laptop GPU. That probe returned exit code 0 despite reporting a failed job;
it did not perform docking.

The predeclared calculation on WSL2 selected the same GPU (compute capability
12.0, driver 610.88) but aborted with exit code 134 during CUDA kernel setup.
No DLG or docking result was produced. The saved output reported an assertion
in `SetKernelsGpuData` after attempting a CUDA symbol copy. This evidence does
not identify the CUDA error code, so it does not prove the cause of the abort.

Locally observed output hashes:

- stdout `9492105a5c8b83d3bf127227310df5c7c78fcfd9033fbf7aaa389ffe8da73a75`.
- stderr `874db9b02ebf6e8fdaa3037d0d6ec82b6d3d91abc6aa2627995e6a596f4ef091`.
- recorded exit code `e726b440cc164001999e718b51780d80314709efe06e7857282377be9111127b`.

The tagged source's CUDA makefile lists code targets 52, 60, 61, 70 and 80 by
default; this is relevant context, but the actual failing CUDA error was not
captured and no root cause is established. The downloaded inputs, executable
and logs remain isolated. Linux GPU discovery remains disabled.
