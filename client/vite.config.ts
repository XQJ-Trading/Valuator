import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ command }) => ({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": "http://localhost:8001",
    },
  },
  /**
   * Pre-bundle TipTap + tippy. In dev (`vite` / `npm run dev`), `force` re-runs optimization so
   * the browser never keeps stale `node_modules/.vite/deps/*hash` URLs (504 Outdated Optimize Dep).
   * Production `vite build` skips this.
   */
  optimizeDeps: {
    include: [
      "@tiptap/core",
      "@tiptap/react",
      "@tiptap/starter-kit",
      "@tiptap/extension-mention",
      "@tiptap/extension-placeholder",
      "@tiptap/suggestion",
      "tippy.js",
    ],
    force: command === "serve",
  },
}));
