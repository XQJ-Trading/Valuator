import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      // Optional: proxy backend if you prefer same-origin during dev
      // '/api': 'http://127.0.0.1:8000'
    }
  }
})

