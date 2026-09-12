import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks(id) {
          const normalizedId = id.replace(/\\/g, '/')

          if (normalizedId.includes('/node_modules/recharts/')) return 'charts'
          if (normalizedId.includes('/node_modules/papaparse/')) return 'data'
          if (/\/node_modules\/(react|react-dom)\//.test(normalizedId)) return 'react'

          return undefined
        },
      },
    },
  },
})
