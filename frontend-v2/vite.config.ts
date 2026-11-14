import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// v2 of the frontend (D-030). Same /api as v1; API_TARGET can point at another backend.
const apiTarget = process.env.API_TARGET ?? "http://127.0.0.1:3000";
const port = Number(process.env.PORT ?? 3020);

export default defineConfig({
  base: process.env.BASE ?? "/",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: { host: "127.0.0.1", port, strictPort: true, proxy: { "/api": { target: apiTarget, changeOrigin: false } } },
  preview: { host: "127.0.0.1", port, proxy: { "/api": apiTarget } },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 2000 },
});
