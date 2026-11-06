# Linux AutoDock-GPU CUDA build follow-up — predeclared

This is a separate, exploratory build after the failed link documented in
`LINUX_AUTODOCK_GPU_LOCAL_BUILD_PLAN.md`. Use a new create-only extraction of
the same pinned v1.6 source archive, without modifying source files. The
compiler, target `sm_120`, two-worker limit and other build options remain as
in that plan. Keep the failed build and all logs intact.

Provide the CUDA toolkit library directory and the WSL driver library
directory to the linker through `LIBRARY_PATH`; keep the explicit GPU header
and driver paths. Pass `GIT_VERSION=v1.6` to make so the containing Ankora
checkout cannot masquerade as the upstream version. The independently recorded
source commit and archive hash, not that label, establish the input identity.
Set runtime library paths for this WSL-only experiment; this is not a portable
redistribution or Linux packaging decision.

Record the exact build command, exit status, raw output and resulting binary
and library identities. Stop and report any failure. Successful compilation does
not establish docking functionality. Before any docking, define a separate
bounded test plan; do not enable the Linux GPU adapter on this basis alone.

## Observed build

The second isolated build completed with exit code 0. The actual compile used
`-gencode arch=compute_120,code=sm_120`, and the linker reported version
`v1.6`, supplied explicitly. The resulting Linux x86-64 ELF had SHA-256
`3e1bba7691983c97e1d64fef6cc45dd8306d54d10e5f81f50185694f06e8be78`.
`--help` returned `AutoDock-GPU version: v1.6`.

The linked runtime includes `libcudart.so.13` supplied by the local CUDA 13.3
toolkit and normal C++/OpenMP/system libraries. Driver resolution and these
paths are specific to this WSL host; no redistribution decision is made.
Build stdout SHA-256 `cafe78dbc7273f74481633a84a5a1646a8577a56141b409f45c977ad39b5a3f3`;
stderr SHA-256 `a5c416dcfbbc2b69d86011b580f9d8ed4b0be482907210d31d9b01b8f05582fe`.
The raw outputs and locally built binary remain in the isolated workspace.
This confirms a build, not a completed GPU docking.
