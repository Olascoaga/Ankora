# Linux AutoDock-GPU targeted CUDA build — predeclared exploration

This independent follow-up is planned after the official CUDA 12 binary failed
kernel setup, and is therefore exploratory, not blinded scientific evidence.
It builds unmodified official v1.6 source from commit
`e63e6f6280ebfad18caa3e8f48afdc269e79e063` (downloaded archive locally hashed
`393aaec5bddbc431c03b70487372459ed6762813dcc8bb77b84bccc39fde94c7`) in an
isolated workspace. The user-visible application and Windows executable stay
unchanged. This is not a redistributable package or a native-workstation test.

Use the installed CUDA 13.3 compiler, GCC 13.3 and WSL NVIDIA driver libraries;
run a bounded two-job upstream build with `DEVICE=CUDA NUMWI=128 TARGETS=120
OVERLAP=ON TENSOR=OFF`, GPU headers from the local CUDA toolkit and the WSL
driver library directory. Record exact command, versions, complete build output,
binary identity and linked dependencies, or the first failure. No source code
or docking algorithm changes are authorized in this build. A successful build
alone is not GPU docking acceptance and may not be portable to another host.

If the build succeeds, a separate immutable test protocol will be recorded
before any docking execution. No installer, external CUDA library redistribution,
or enabling of Linux GPU discovery is implied by this experiment.
