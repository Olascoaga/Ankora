# Linux desktop development bootstrap — 2026-10-28

## Scope

This bounded unit implements the initial Linux desktop development configuration
and minimal Rust compatibility under `apps/desktop` per [ADR-026](../architecture/ADR/ADR-026-linux-port-and-native-acceptance.md)
and [docs/DEVELOPMENT_LINUX.md](../DEVELOPMENT_LINUX.md):

- **`apps/desktop/package.json`**: adds explicit Linux development scripts
  (`dev:linux`, `dev:tauri-prereq:linux`, `tauri:dev:linux`, and `tauri:build:linux`)
  that consume `python3 ../../scripts/dev_linux.py` and the separate Linux Tauri
  configuration, while preserving all existing Windows scripts (`dev:tauri-prereq`,
  `tauri:dev`, `tauri:build`, `tauri:installer`) unchanged.
- **`apps/desktop/src-tauri/tauri.linux.conf.json`**: defines the separate Linux
  Tauri development configuration. It routes `beforeDevCommand` to
  `npm run dev:tauri-prereq:linux` (`python3 ../../scripts/dev_linux.py`), keeps
  `devUrl` on `http://127.0.0.1:1420`, retains the exact strict Content Security
  Policy (`connect-src 'self' http://127.0.0.1:8765`, no `unsafe-eval`), omits
  Windows-only WebView2 browser arguments without applying unverified WSL/WebGL
  workarounds, and disables installer/resource bundling (`bundle.active: false`,
  `bundle.targets: []`, `bundle.licenseFile: null`, `bundle.resources: null`).
- **`apps/desktop/src-tauri/src/backend_runtime.rs`**: adds minimal
  `#[cfg(target_os = "windows")]` and `#[cfg(any(target_os = "windows", test))]`
  gates around the Windows packaged-backend process launcher and its imports so
  Linux Rust builds and `cargo clippy --all-targets -- -D warnings` succeed
  without `#[allow(dead_code)]` or weakened lints. Windows packaged-backend
  startup and teardown behavior is unchanged.
- **Focused configuration and Rust tests**:
  - `apps/desktop/src/tests/linuxDesktopConfig.test.ts` verifies the preserved
    Windows scripts, explicit Linux launcher commands, strict CSP parity, and
    disabled Linux installer bundling.
  - `apps/desktop/src-tauri/src/backend_runtime.rs` (`mod tests`) verifies the
    Windows packaged resource path, safe no-op teardown when no packaged child
    is running, and the Linux Tauri configuration invariants.

## Boundaries and non-claims

- This unit does **not** claim a Linux installer, offline Linux bundle, or
  packaged Linux backend runtime (ADR-026 Gate 3).
- `scripts/dev_linux.py` is owned by the backend bootstrap unit (`codex/linux-backend`)
  and is integrated by Codex.
- No scientific adapter, chemistry workflow, theme, or CSP rule was relaxed.
- No WSL2/WSLg graphics workaround was pre-applied before observing real
  WebKitGTK runtime behavior.

## Verification status

Gemini prepared the source changes using file tools. Codex reviewed the diff and
executed these checks in the isolated Linux desktop worktree:

- `npm test`: 336 passed across 42 files, including two Linux configuration tests.
- `npm run typecheck` and `npm run build`: passed.
- `cargo fmt --all -- --check`: passed.
- `cargo test --locked -j 4`: three unit tests passed; binary/doc tests passed.
- `cargo clippy --locked --all-targets -j 4 -- -D warnings`: passed.
- `git diff --check`: passed.

Environment: Ubuntu 24.04 WSL2, Rust 1.99.1, GTK 3.24.41, WebKitGTK 2.52.6,
Node 24.19.0, npm 11.17.0; Cargo lock unchanged. The existing frontend act/NaN
test notices and Mol* chunk-size warning remain visible. Compilation used a
separate Linux target directory and at most four jobs.

The real WSLg Tauri window and structure rendering are integration checks still
pending at this source checkpoint. No Windows installer or native Linux
workstation test is claimed.
