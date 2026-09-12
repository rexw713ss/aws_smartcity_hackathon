import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

// The dev server proxies /api to the local FastAPI service, so the browser makes
// same-origin requests and the backend needs no CORS middleware. Production
// should serve this bundle behind the same origin as the API for the same reason.
const backend = process.env.YOUTH_COMPASS_API_ORIGIN ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: backend, changeOrigin: true },
    },
  },
  build: {
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks(id) {
          const normalized = id.replace(/\\/g, '/')
          if (normalized.includes('/node_modules/recharts/')) return 'charts'
          if (/\/node_modules\/(react|react-dom)\//.test(normalized)) return 'react'
          return undefined
        },
      },
    },
  },
})
