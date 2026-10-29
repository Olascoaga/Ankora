# Linux port work plan

The scientist authorized the Linux port on 2026-10-28. See ADR-026.

## Source baseline

The independent Linux checkout starts from public-lineage commit `e233788`.
The accepted working Obsidian UI is carried into Linux as a separate source
snapshot, preserving the Windows checkout and its uncommitted work. The snapshot
contains only the eight existing UI/design files; Windows installer experiments,
private memory, build products and scientific projects are excluded.

## Initial unit — development bootstrap

- **Claude / backend:** implement a Linux development launcher and focused tests.
  Own `scripts/dev_linux.py`, `backend/tests/test_linux_dev.py` and
  `docs/validation/LINUX_BACKEND_BOOTSTRAP.md`. Select an explicit or project
  Python interpreter, verify API identity/readiness, fail clearly on occupied
  ports, retain startup errors, and clean up only owned subprocesses on exit.
  Launch commands as arrays, bind localhost, keep existing chemistry unchanged.
- **Gemini / desktop:** own `apps/desktop/package.json`, Linux Tauri configuration,
  platform-specific Rust compatibility, focused configuration/Rust tests and
  `docs/validation/LINUX_DESKTOP_BOOTSTRAP.md`. Add explicit Linux development
  commands consuming Claude's launcher. Preserve Windows commands/configuration,
  installed backend behavior, CSP and current appearance. No Linux installer
  claim in this unit.
- **Codex / review:** owns this plan, ADR, policy, environment setup and integration
  evidence. Review each diff and relevant tests before integration. Resolve
  shared-file changes sequentially. No automatic pushes or co-author trailers.

The launcher interface is `python3 ../../scripts/dev_linux.py` from the desktop
package directory. It owns a backend plus `npm run dev` from the repository root,
using the existing API port 8765 and frontend port 1420. Python selection:
`ANKORA_PYTHON_PATH`, active non-base Conda, project `.venv`, or a named
`ankora-dev` environment; an invalid explicit selection must fail clearly.
Do not silently reuse another running backend or kill unrelated listeners.

## Acceptance

1. Linux frontend tests, type check and production build pass on the carried UI.
2. Launcher tests prove startup/readiness, collision handling and owned cleanup.
3. Linux Rust formatting/tests/check or build passes with real GTK/WebKit deps.
4. A real Tauri window opens through WSLg; an imported tracked structure fixture
   is visible in Mol*. Record actual rendering/runtime, screenshots and errors.
5. Confirm the Windows checkout has exactly its original dirty-file set and
   preserved source bytes. Record any checks not executed rather than claiming
   Windows packaging or native workstation acceptance.

## Later units

Scientific Linux parity and lock, CPU engines and cancellation, independent GPU
acceptance, then complete offline packaging and native workstation validation.
Each bounded completed unit gets relevant tests, tracked evidence and a small
commit. Private coordination logs and memory stay ignored.

## Scientific foundation update — 2026-10-28

The second bounded unit now has native discovery, a Linux scientific environment
lock/verifier and owned-session process cancellation, integrated from isolated
Claude/Gemini branches after coordinator review. Public PR lineage begins at
`e705ff6`; the unrelated unpublished manual commit from the original local source
snapshot is excluded. Windows development files remain preserved.

See [the coordinator's scientific review](validation/LINUX_SCIENTIFIC_FOUNDATION_REVIEW.md)
for exact accepted checks, raw-evidence manifest identity and known failures.
Environment identity and preparation smoke are accepted for this bounded unit;
the complete Linux parity/release gate remains open. Native P2Rank execution,
the recorded portability failures, real CPU docking/redocking, independent GPU
acceptance and complete Linux packaging still require their own evidence.

## AutoDock-GPU development — WSL2

Linux development now discovers executable x86-64 ELF AutoDock-GPU binaries
named `autodock_gpu_128wi`, `autodock_gpu_64wi` or `autodock_gpu` on PATH,
in a versioned `~/tools/autodock-gpu-1.6/bin` directory, or at an explicit
`ANKORA_AUTODOCK_GPU_PATH`. An explicit path is authoritative; an invalid
one is not silently replaced by a different installation. Discovery only
reads the executable's identity; a docking request separately probes the
engine version and device. A compatible GPU driver and the binary's native
runtime libraries must already be available to the backend.

The locally compiled AutoDock-GPU 1.6 CUDA binary was tested on WSL2 with an
RTX 5050 through the actual API, including a two-molecule campaign and
cancellation after the process was observed in GPU compute. See
[the recorded engineering checks](validation/LINUX_AUTODOCK_GPU_CAMPAIGN_AND_CANCEL.md).
Restart a running development session after changing its executable or
environment. If the scheduler is busy, device preflight returns an explicit
busy message; retry when active or queued work has finished.

These checks do not establish compatibility for other GPU architectures,
CUDA/OpenCL builds or drivers, cancellation of an uninterruptible process,
the packaged runtime, or a native Linux workstation. Linux distribution and
native workstation acceptance remain open; no existing Windows binary is used
as a Linux engine.

## GNINA development — Linux only

The scientist authorized GNINA as a Linux-only engine; see
[ADR-027](architecture/ADR/ADR-027-linux-gnina.md). The official 1.3.3 CUDA
12.8 binary was checksum-verified and exercised on the WSL RTX 5050. A backend
engine boundary now probes Linux executable version and hash, builds explicit
`rescore` commands using `dense_1_3` and prepared PDBQT inputs, and parses
ranked SDF/PDBQT poses and separate CNN/empirical scores. PDBQT poses can be
checked against the prepared conformer using Meeko. See the
[initial run](validation/LINUX_GNINA_INITIAL_SMOKE.md) and
[topology and adapter checks](validation/LINUX_GNINA_TOPOLOGY_SMOKE.md).

This is **not yet an application-level GNINA feature**: no GNINA job API,
durable service, result catalog or docking UI is wired. The backend adapter
alone does not verify that a requested CUDA run used the GPU. Next integrate
resource arbitration, observed device evidence, cancellation, work recovery,
project-scoped persistence and a single-ligand API before enabling the UI;
library screening and cross-platform result review follow separately.
GNINA is not enabled on native Windows. The 2 GB executable used for
development is local and ignored by Git, not part of a distributable bundle.
Native workstation, driver/library identity and licensing checks remain open.
