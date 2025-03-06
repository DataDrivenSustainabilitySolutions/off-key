import path from "path"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import autoprefixer from "autoprefixer"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  css: {
    postcss: {
      plugins: [
          autoprefixer({})
      ],
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: '0.0.0.0', // Allow connections from Docker network
    port: 5173,
    strictPort: true, // Prevents Vite from using a fallback port
    proxy: {
      '/api': {
        target: 'http://localhost:8000',  // FastAPI container's name and port
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
