import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// API_TARGET lets a second dev server point at a private backend (write tests on a copied DATA_DIR).
const apiTarget = process.env.API_TARGET ?? "http://127.0.0.1:3000";
const port = Number(process.env.PORT ?? 3012);

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port,
    strictPort: true,
    proxy: { "/api": { target: apiTarget, changeOrigin: false } },
  },
  preview: { host: "127.0.0.1", port, proxy: { "/api": apiTarget } },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 1500 },
});
