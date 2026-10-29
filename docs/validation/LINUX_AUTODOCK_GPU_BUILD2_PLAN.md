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
