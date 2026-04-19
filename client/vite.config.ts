import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ command }) => ({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  optimizeDeps: {
    include: ["react-mentions"],
    force: command === "serve",
  },
}));
