# Linux source baseline — 2026-10-28

An independent Linux checkout starts at `e233788`. The eight-file Obsidian
UI/design snapshot is imported from the accepted Windows working source, with
patch SHA-256 `c00f7329d8d748bca3bfcb54fb7f75775da504204876afb8fd4088b731b17f6a`.
The Windows checkout is not staged or modified by this transfer. Private memory,
scientific data, Windows installer experiments and generated products are excluded.

Before any Linux implementation, Ubuntu 24.04 / Node 24.19.0 / npm 11.17.0:

- `npm ci --no-fund --no-audit`: passed, 365 packages from the unchanged lock.
- `npm test`: passed, 334 tests in 41 files.
- `npm run typecheck`: passed.
- `npm run build`: passed, Vite 7.3.6.

The existing React act/NaN test notices and large Mol* build chunk warning remain
visible. These checks establish the carried frontend source baseline; they do
not prove a native Tauri/WebKitGTK render, Linux scientific parity, an installer,
or native Linux workstation acceptance. No scientific tools were executed.
