import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': '/src',  // This should resolve to /src directory
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000/',  // FastAPI container's name and port
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
