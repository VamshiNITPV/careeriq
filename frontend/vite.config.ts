import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
// From 'vitest/config', not 'vite': it accepts the `test` block below with
// types. The plain vite export would reject it.
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react(), tailwindcss()],

  resolve: {
    // `@/services/apiClient` instead of `../../../services/apiClient`. Relative
    // chains break silently when a file moves; the alias does not.
    alias: { '@': path.resolve(__dirname, './src') },
  },

  server: {
    // 0.0.0.0 so the dev server is reachable from outside the container.
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    watch: {
      // Bind mounts on Docker Desktop for Windows do not deliver inotify
      // events, so HMR silently stops working without polling.
      usePolling: true,
      interval: 300,
    },
    proxy: {
      // The browser calls /api/... on the dev server's own origin, which
      // forwards to the backend. This means development runs same-origin, so
      // CORS is never exercised locally and cannot mask a misconfiguration —
      // the app talks to the API exactly as it will in production behind a
      // single hostname.
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET ?? 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },

  build: {
    outDir: 'dist',
    sourcemap: true,
    rollupOptions: {
      output: {
        // Split vendor code so an application change does not invalidate the
        // cached React/router bundles for returning users.
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          query: ['@tanstack/react-query'],
          // Country, currency and city lists. Same reasoning as above from the
          // other direction: reference data changes roughly never while app
          // code changes constantly, so splitting keeps it cached across every
          // deploy.
          data: [
            './src/data/countries.ts',
            './src/data/currencies.ts',
            './src/data/locations.ts',
          ],
        },
      },
    },
  },

  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: true,
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.test.{ts,tsx}', 'src/test/**', 'src/main.tsx'],
    },
  },
})
