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

## Observed result

The locally compiled binary completed the predeclared 1STP example on the RTX
5050 under WSL2. It named the CUDA device, returned exit 0, emitted `All jobs
ran without errors.` and saved one DLG and one XML; all original example inputs
remained byte-identical. The existing Ankora DLG parser read one cluster, one
ranked run and one pose, and the existing device and success parsers matched.
The existing Windows-style version parser did **not** match the Linux version
line. This small post-failure exploratory run is not an accuracy benchmark, an
Ankora service/GUI result, a native-workstation test or release acceptance.

- DLG SHA-256: `b4686979014e2c77cabfa7b191bdfd7b9ac463353386a87adf1cb9515ef94917`.
- XML SHA-256: `330a8447597a06448181f7b3f20e241dc9ae846b5f1cee64db4dfe699f5e8085`.
- stdout SHA-256: `5df027b5c3d22daffcfd9210a2fb819b859b391ebff42fffa5ae01c0a0168f80`.
- stderr was empty (SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`).

The source, actual executable, inputs and raw outputs are retained in the
isolated WSL workspace. The executable depends on local CUDA libraries and is
not a validated or legally reviewed distribution artifact.

## Next integration gate

A separate Linux-specific parser now recognizes the observed version-only
header while marking the build as unreported; the Windows header contract is
unchanged. Linux GPU discovery remains deliberately disabled. Before enabling
the engine, validate runtime/device provenance, device selection and
reproducibility statements for CUDA, then exercise the actual Ankora service
with an independently reviewed protocol. User-supplied Linux builds, OpenCL
vendors, packaging/licensing and native workstation acceptance are separate
gates. In particular, never present a Windows OpenCL reproducibility spread as
a measured result for this Linux CUDA build.

The Linux adapter, docking and discovery regression subset passed 74 tests;
the native Windows adapter and docking subset passed 40 tests. Backend Ruff and
mypy over 142 source files passed. Synthetic tests explicitly verify that the
version-only header is accepted only on Linux, build metadata remains
`unreported`, architecture comes from executable discovery, and the original
Windows version-header contract remains unchanged. These tests do not enable
Linux GPU discovery or establish CUDA scientific equivalence.
