# Linux locally built AutoDock-GPU smoke — predeclared exploratory follow-up

This is a separate test planned after the official binary aborted; it is an
engineering follow-up, not blinded benchmarking, scientific validation, GUI
testing, native Linux workstation acceptance or portable distribution.

Use the local CUDA 13.3 build recorded in `LINUX_AUTODOCK_GPU_BUILD2_PLAN.md`
with SHA-256 `3e1bba7691983c97e1d64fef6cc45dd8306d54d10e5f81f50185694f06e8be78`.
Use the exact unchanged upstream 1STP example files and SHA-256 identities in
`LINUX_AUTODOCK_GPU_NATIVE_SMOKE.md`, but copy them to a distinct create-only
working directory. Use the same parameters and process limit as that plan:
one run, device 1, 5000 maximum evaluations, heuristics and autostop disabled,
seed `20261029,20261030,20261031`, output name `ankora_gpu_smoke`. Set the
local CUDA toolkit and WSL driver library paths; this is host-specific.

Preserve the precise command, stdout, stderr, exit status, raw DLG and XML,
input and output hashes and device identity. Verify actual tool success and
DLG parseability; exit code alone is insufficient. Stop at the first failure,
do not change these parameters after seeing the result, and do not treat a
docking score or pose as a scientific acceptance threshold. Linux GPU product
discovery remains disabled pending separate adapter/service and reproducibility
checks, and the failed official-binary attempt remains unchanged.
