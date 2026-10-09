import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { molstarCsp } from "./build/molstarCsp";

export default defineConfig({
  plugins: [molstarCsp(), react()],
  // Keep the same reviewed transform in development and packaged builds.
  optimizeDeps: { exclude: ["molstar"] },
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
