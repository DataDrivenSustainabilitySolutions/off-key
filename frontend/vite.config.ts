import path from "path";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";
import { configDefaults } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  build: {
    // The limit applies to every file. Two on-demand libraries exceed the
    // default of 500 kB: the ELK graph layout (1,463 kB) and the chart time
    // axis (587 kB). The entry file is about 400 kB.
    chunkSizeWarningLimit: 1500,
  },
  server: {
    host: '0.0.0.0', // Allow connections from Docker network
    port: 5173,
    strictPort: true, // Prevents Vite from using a fallback port
    proxy: {
      '/api': {
        // VITE_API_URL is the pre-rename name of the same dev-only setting.
        target: process.env.API_PROXY_TARGET || process.env.VITE_API_URL || 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
    hmr: {
      clientPort: 5173,
    },
    watch: {
      usePolling: true, // Needed for Docker environments
      interval: 1000,
    }
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/Tests/setup.ts'],
    // Every test starts from restored spies, globals and environment variables.
    restoreMocks: true,
    unstubGlobals: true,
    unstubEnvs: true,
    exclude: [...configDefaults.exclude, 'e2e/**/*'],
    coverage: {
      provider: 'v8',
      include: ['src/**'],
      exclude: ['src/Tests/**'],
      reporter: ['text-summary', 'html'],
    },
  }
})
