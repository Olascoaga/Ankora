# Complete Windows installer candidate — 2026-10-08

## Scope and identity

ADR-024 supersedes the Python-only packaging subset for this new candidate.
GNINA remains deferred. No scientific model, historical result, engine default,
system driver or Windows security policy is changed by packaging.

The reviewed private tools manifest is
`e83f404b38e20345806c19e3e811d764d0e1c476324ddfdd544f7e36a52c6c7c`.
It contains Vina 1.2.7, AutoGrid4/AutoDock4 4.2.6, the separately validated
AutoDock-GPU 1.6 MSVC/OpenMP variant, P2Rank 2.5.1's validated vecmath-1.5.2-only
variant, unchanged P2Rank models and private Temurin Java 21.

## Source and notice closure

The source companion contains 112 JAR records, 116 source records and zero
mechanical source/notice gaps. Its manifest SHA-256 is
`be756aaa95624b078dff9cd0e99c0f520c92c952736caa2e9b52d9488eb9f5b8`.
Maven coordinates are accepted only after comparing the exact shipped binary;
non-Maven forks and legacy dependencies have separately pinned upstream source
archives. Source bytes are retained unchanged, not reconstructed from decompilation.

The complete legal payload contains 664 component records, source archives,
full notices, Java per-module terms and Microsoft's component-scoped terms.
The patched AutoDock-GPU corresponding source SHA-256 is
`76f64f65988546d2c418e7769a27a6f452eaf55eedd2256031261ad0c3480a5e`.
The installer license screen does not relicense GPL/LGPL components under MIT
or Microsoft terms. The historical Python-only inventory is retained unchanged
as historical evidence, but is not the complete installer's legal resource.

The original source-companion report deliberately says
`source-evidence-not-legal-approval`: collecting source is not by itself legal
approval. The complete assembler additionally pins the reviewed runtime,
source companion, patched GPU source, WebView2 and vendor terms. No external
legal opinion or certification is claimed.

## Observed validation before NSIS packaging

- The freshly frozen backend passed all **10/10** native-tool smoke checks with
  only Windows directories on PATH and a data path containing spaces/accents.
  Evidence manifest:
  `15918b5d5d65050c0231a287377c6f5e98cdd367696cc9c4eee0f170a0abe697`.
- This matrix includes real preparation, minimization and pocket detection;
  engine version/device checks are not described as full docking calculations.
  The GPU rebuild has its separately recorded bounded real docking smoke.
- Nine synthetic complete-payload tests check byte-preserving source copying,
  tampering, safe notice reading, missing/extra legal files, exact runtime
  identity and offline installer configuration. Combined with the nine Maven
  evidence tests and six WebView2 tests: **24 passed**.
- Release-index, historical notice and complete-payload tests: **17 passed**.
  These tests do not fabricate scientific outcomes.
- Full backend gate: **709 passed**; one upstream Starlette/httpx deprecation
  warning. Strict mypy: **137 files**, Ruff clean. Frontend: **247 passed in
  34 files**, with existing test-console warnings; TypeScript and production
  build pass. An initial invocation from `backend/` could not import root-level
  packaging scripts; the authoritative gate uses the repository-root invocation
  used by CI, `python -m pytest backend`.

## Build and acceptance boundary

The complete NSIS candidate was generated successfully (Rust release and native
unit test pass). File: `Ankora_0.1.0_x64-setup.exe`, **1,139,221,308 bytes**,
SHA-256 `e5b794fda5d92bca80692bb50fd3e20b726ca5bed0ba2c70573462487aa921ce`.
Authenticode status: **NotSigned**, not a signed public release. Generated NSIS
selection independently matches the locked Microsoft-signed offline WebView2
installer. Installed-machine acceptance is recorded separately below.

### Installed candidate acceptance (developer Windows machine)

The exact candidate above installed silently into a new test directory. The
installed scientific payload and all legal/source files passed exact-set and
SHA-256 verification. The desktop started its own bundled backend; all ten
supported tools were available with only Windows directories on PATH.

The **installed** backend then passed **10/10 native scientific smoke checks**,
using a separate create-only output directory containing spaces and an accent.
Installed-run evidence manifest:
`bd1b9557c5df8f27a9149d50506f6e6c9a9cb90c34594e57abcbcea179dbbb46`.
Desktop shutdown released its backend port. Silent uninstall succeeded and
removed the desktop executable without deleting the application data directory.
No existing registered Ankora installation was replaced. This verifies this
machine, not an offline clean VM, upgrade matrix or all GPU models.

Release-index assembly exposed a Windows environment-key casing bug: copying
`os.environ` produces an ordinary dict, whose `ProgramFiles` lookup missed
`PROGRAMFILES`. The helper now normalizes keys, including the PowerShell module
path; a synthetic regression test covers that condition. This metadata-only
fix does not change the already-tested installer bytes.

The builder requires staged `-ScientificTools`, `-SourceCompanion` and
`-GpuSource` inputs (or their documented default paths) in addition to the
locked build Python. It refuses an
unreviewed identity, assembles/verifies the full legal payload, stages private
tools, verifies the Microsoft-signed offline WebView2 input, then verifies the
WebView2 bytes selected by the generated NSIS script.

The complete payload is intentionally generated under ignored build/resource
directories, not committed to Git. `memory/` stays private. End users do not
need these build inputs, Python, Conda, Java or manual path configuration.

General-public release still requires the ADR-024 clean-Windows acceptance
matrix and a user-controlled Authenticode signing identity. Testing with an
isolated PATH on a developer machine is not a clean-machine test. Compatible
GPU hardware and a vendor driver remain hardware/OS prerequisites; CPU tools
are bundled independently. No release/tag or outreach is performed here.
