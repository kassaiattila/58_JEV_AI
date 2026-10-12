// A felület buildje a ui/dist-be kerül; a helyi szolgáltatás (jav/api.py) ugyanazon a címen kiszolgálja.
// Fejlesztéskor (npm run dev) a Vite az /api hívásokat a futó szolgáltatáshoz továbbítja.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    // 056: a felület a configs/ közös fájljait is olvassa; 067 (066 Á34): csak a felület mappája és a configs/, nem a teljes projekt
    fs: { allow: [".", "../configs"] },
    proxy: { "/api": { target: "http://127.0.0.1:8930", changeOrigin: true } },
  },
  build: { outDir: "dist", emptyOutDir: true },
  // 149: a test may wait up to 5 s per step (src/test-setup.ts), so the whole test gets more than vitest's default 5 s
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test-setup.ts"], testTimeout: 30000 },
});
