# ADR-026 — Linux port and native acceptance

Status: accepted, 2026-10-28.

> **Current status note (2026-11-12):** Gates 1–3 below—together with Linux `GNINA 1.3.3` single-ligand and screening integration ([ADR-027](ADR-027-linux-gnina.md), [ADR-028](ADR-028-gnina-cnn-vs-refinement-ensemble.md)), modular `.deb`/`.tar.zst` + 1-click offline GNINA CUDA 12.8 packaging ([ADR-029](ADR-029-linux-offline-distribution.md)), clean-room WSL2/WSLg package smoke (`D4`), and the Ubuntu 24.04 CI lane (`verify-linux`)—are implemented and verified in source. Gate 4 (bare-metal physical Linux workstation attestation, `ADR-029` Gate `D6`) remains the pending final release gate; see [`PLATFORM_STATUS.md`](../../product/PLATFORM_STATUS.md).

## Decision

Extend the existing application to Linux. Develop on Ubuntu 24.04 in WSL2,
exercise the real Tauri/WebKitGTK window through WSLg, and perform final release
acceptance on a native Linux workstation. This supersedes the Windows-only
scope of ADR-001 and the historical bootstrap; the accepted Windows behavior
remains a regression requirement. This is a port, not a rewrite.

Claude Code and Gemini implement bounded assignments in separate Git worktrees.
Codex coordinates, reviews, and integrates accepted commits. Codex may implement
remaining work after their available budgets are exhausted. Never edit one
branch concurrently. Model choices and reasoning settings belong to local
coordination state, not scientific provenance.

## Invariants

- Reuse the existing domain models, scientific adapters, typed API and UI.
- Preserve immutable inputs, exact tool versions/hashes, raw outputs, stale
  guards, resource budgets, and create-only scientific derivatives.
- Keep services on localhost and scientific execution behind the backend.
- Never reuse Windows executable paths or dependency locks as Linux evidence.
- Do not infer Linux GPU support from a successful CUDA or WSLg probe. Each
  engine/runtime combination requires its own native calculation and identity.
- Do not copy private scientific projects into a development clone by default.
- Retain the strict CSP and test Mol* in WebKitGTK, not only Chromium.

## Delivery gates

1. Independent Linux source checkout, reproducible development prerequisites,
   backend readiness and cleanup, native Tauri launch, real 3D structure display.
2. Linux tool discovery, process-tree cancellation and scientific environment
   lock; bounded real preparation, docking, redocking and interaction checks.
3. Complete offline Linux distribution with notices, checksums, installation,
   upgrade/uninstall/data-preservation and clean-machine tests.
4. Native workstation acceptance, including supported GPU configurations.

Gate 1 does not imply gates 2–4. WSLg tests are development evidence, not native
Linux release acceptance. GNINA, Vina-GPU, new scoring and scientific protocol
changes are outside the initial port unit.
