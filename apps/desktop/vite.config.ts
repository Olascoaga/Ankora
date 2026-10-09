import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { molstarCsp } from "./build/molstarCsp";

export default defineConfig({
  plugins: [molstarCsp(), react()],
  optimizeDeps: {
    // Keep Mol* source available to the reviewed CSP transform in both modes.
    exclude: ["molstar"],
    // Mol* imports this deep CommonJS entry, not mutative's ESM package root.
    // An excluded ESM dependency still needs its nested CJS dependency bundled.
    include: [
      "molstar > mutative/dist/index.js",
      // Mol* UI markdown also contains a CommonJS style-parser dependency.
      "molstar > react-markdown",
    ],
  },
  clearScreen: false,
  server: {
    host: "127.0.0.1",
    port: 1420,
    strictPort: true,
    watch: {
      ignored: ["**/src-tauri/target/**"],
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/tests/setup.ts",
    css: true,
  },
});
