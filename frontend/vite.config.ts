import { fileURLToPath, URL } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

/**
 * The dev server proxies /api to the backend, so the browser sees a single origin.
 * That keeps CORS, cookies and SSE behaving in development exactly as they do in the
 * production single-process build where FastAPI serves the compiled bundle.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    host: '127.0.0.1',
    // Overridable so the deterministic E2E run can take its own ports and never attach to
    // a developer's `make dev` session. strictPort makes a clash fail loudly.
    port: Number(process.env.VITE_DEV_PORT ?? 5173),
    strictPort: true,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8756',
        changeOrigin: true,
        // Buffering would make progress arrive in one lump at the end of a run.
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            proxyRes.headers['cache-control'] = 'no-cache, no-transform';
          });
        },
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      // What the browser actually runs. The generated API types carry no logic, the entry
      // point is exercised by the browser tests rather than by jsdom, and measuring the
      // tests themselves flatters the number.
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.test.{ts,tsx}', 'src/main.tsx', 'src/test/**', 'src/api/generated/**'],
      // Set at what the suite covers today, not at an aspiration. A floor that fails on
      // the day it is added teaches people to lower it; this one only moves upward, and
      // only when tests have been written to earn it.
      thresholds: {
        statements: 67,
        branches: 62,
        functions: 57,
        lines: 69,
      },
    },
  },
});
