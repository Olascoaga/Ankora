# Linux AutoDock-GPU service smoke — predeclared exploratory protocol

## Scope

Exercise real Ankora API/services, AutoGrid and the previously tested CUDA
AutoDock-GPU executable in an isolated WSL2 development project. This one
bounded, post-investigation engineering test is not a scientific benchmark,
native Linux workstation acceptance, installer test or general support claim.
Linux production GPU discovery remains disabled.

## Inputs and explicit decisions

- Reuse a byte-verified copy of the isolated 1HSG/MK1 exploratory project's
  immutable receptor, crystallographic ligand, independent conformer, PDBQT
  and binding site. Its prior evidence SHA-256 is
  `d0a5ca8c9bfae80f70b607dec17c18b90bb3efb2348aeb3e913dbbeba732db4b`.
  Do not modify or replace the original project. It contains only public
  source data and artifacts from that documented test, not user projects.
- Generate an AutoGrid4 map set through the real Ankora API, using its default
  explicit map parameters for the selected ligand. The Ubuntu AutoGrid4 binary
  SHA-256 is `91621b89d13410efde31aed2a0934b15837172ef167d783bec0b3a94d384dc72`.
- Use the locally compiled CUDA 13.3 `sm_120` AutoDock-GPU v1.6 executable,
  SHA-256 `3e1bba7691983c97e1d64fef6cc45dd8306d54d10e5f81f50185694f06e8be78`,
  on device 1. Its local library paths are supplied at process launch.
  **Test seam:** the runner overrides only executable discovery for this exact
  path and hash. It does not mock the version/device probe, execution, map
  generation, service, stores, resource arbiter, parser or API. This override
  exists only in the test process; it is not Linux product discovery support.
- Request two runs, population 150, maximum 5000 evaluations per run,
  heuristics and autostop disabled, ADADELTA, clustering threshold 2 Å,
  seeds 20261029, 20261030 and 20261031, timeout two minutes. These are a
  deliberately small engineering workload, not a docking-quality protocol.

## Acceptance and evidence

Use a new create-only isolated directory. Confirm GPU is not already executing
another workload before starting. Retain API requests and responses, exact
subprocess evidence, map and pose files, warning records, tool/device identity,
and input/output SHA-256 hashes. Confirm the copied source project matches the
original before testing, the original remains unchanged, successful poses
match their recorded hashes, device report and probe are distinguished, and
resource reservations are released. Record failure without changing parameters
or silently retrying. No score or RMSD is a scientific acceptance criterion.

## First execution and parser correction

The predeclared `run-01` was performed once. AutoGrid succeeded, and the GPU
executable reported success on the RTX 5050, but Ankora rejected the DLG as
`AUTODOCK4_OUTPUT_INVALID`. The raw DLG contains two complete conformations;
the second binding energy is written as `+0.70` in the pose, ranking and
histogram. The parser accepted negative and unsigned numbers, but not this
valid explicit positive sign. The isolated run's `evidence.json` SHA-256 is
`013669bd5ce7835e4886ed2948b078f61433204e76f9a9f2d942683ee67c9efc`;
the source project was verified unchanged. This failed application result is
retained as-is, including the original DLG and tool output.

The parser was corrected to accept explicit `+` in those three energy fields;
it still rejects missing and non-finite energies. The regression excerpt is
derived from the actual preserved records and intentionally omits coordinates.
After this fix, a second isolated execution is predeclared using exactly the
inputs and parameters above, with a new output directory. This is an
engineering regression check after observing a failure, not an independent
scientific validation or a replacement for the first execution.

## Second execution

The predeclared `run-02` completed through the real API, AutoGrid and the
hash-pinned AutoDock-GPU executable. The run reported CUDA on the RTX 5050,
matching the separately probed device name. The returned pose artifact hashes
matched their files; the original input project was unchanged and the GPU
reservation was released after completion. The retained evidence SHA-256 is
`3cc06cb41a630364bda33e58d92a2ed99a0210731d107a8caeec17a2c731f128`.
The result tests one WSL environment and one device only. It does not establish
general Linux compatibility, reproducibility, cancellation under a driver
hang, or any scientific accuracy claim. Production Linux GPU discovery is
still disabled; workstation and packaged-runtime validation remain necessary.

An independent read-only review identified potential queue and GPU reservation
leaks on exceptional paths. Separate synthetic regression tests cover a
capacity check raising, single-job update/execution failures, and a campaign
lease acquisition failure. The preflight device probe still executes before
GPU admission; its scheduling and long-running cancellation need further work
before enabling discovery in the product.

The parser, AutoDock services and scheduler regression selection passed 81
tests in WSL and 78 tests on Windows, after the scheduler changes. Backend
type checking passed on 142 source files. These tests do not replace a real
GPU cancellation or native Linux workstation acceptance test.
