import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The Station serves `dist/` as static files and nothing else — there is no
// server half to this app (spec J.5: Studio is a plain REST client). During
// development, proxy the API so `npm run dev` talks to a running Station.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/v1': { target: process.env.STATION_URL || 'http://127.0.0.1:8800', changeOrigin: true },
    },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
