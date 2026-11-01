// The interface is built into ui/dist; the local service (jav/service/api.py) serves it on the same address.
// In development (npm run dev) Vite forwards the /api calls to the running service.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    // the interface reads the shared files of configs/ too: only its own folder and configs/, not the whole project
    fs: { allow: [".", "../configs"] },
    proxy: { "/api": { target: "http://127.0.0.1:8930", changeOrigin: true } },
  },
  build: { outDir: "dist", emptyOutDir: true },
  // 149: a test may wait up to 5 s per step (src/test-setup.ts), so the whole test gets more than vitest's default 5 s.
  // D0 (2026-10-26): Node 26 turns its own Web Storage on, whose `localStorage` (undefined without a storage file) hides
  // jsdom's in the test workers; the workers start with it off, so the tests read the browser-like storage as before.
  test: {
    // 265 (code review TOOL-05): two test processes, beside the Python suite's (all cores but one before)
    environment: "jsdom", globals: true, setupFiles: ["src/test-setup.ts"], testTimeout: 30000, maxWorkers: 2,
    execArgv: ["--no-experimental-webstorage"],
  },
});
