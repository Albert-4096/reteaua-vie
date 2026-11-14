import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Frontend v3: landing + film + app in one look. Same /api as the backend; API_TARGET can point elsewhere.
const apiTarget = process.env.API_TARGET ?? "http://127.0.0.1:3000";
const port = Number(process.env.PORT ?? 3005);

export default defineConfig({
  base: process.env.BASE ?? "/",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: { host: "127.0.0.1", port, strictPort: true, proxy: { "/api": { target: apiTarget, changeOrigin: false } } },
  preview: { host: "127.0.0.1", port, proxy: { "/api": apiTarget } },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 2000 },
});
