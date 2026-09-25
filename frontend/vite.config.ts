/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// `--mode pages` builds the static GitHub Pages demo under /docmind-rag/.
// Override with VITE_BASE for other hosts (e.g. VITE_BASE=/ for Docker/nginx).
const apiProxy = process.env.DOCMIND_API_PROXY ?? 'http://localhost:8000'

export default defineConfig(({ mode }) => ({
  base: process.env.VITE_BASE ?? (mode === 'pages' ? '/docmind-rag/' : '/'),
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/v1': apiProxy,
      '/healthz': apiProxy,
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
}))
