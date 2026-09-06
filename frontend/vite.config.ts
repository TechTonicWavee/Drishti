import path from 'node:path'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// The dev server proxies /api to the FastAPI backend. Keeping the browser on
// a single origin means no CORS round-trip and no backend hostname baked into
// the bundle — the same build works on a laptop and inside docker-compose,
// where BACKEND_ORIGIN becomes http://backend:8000.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendOrigin = env.BACKEND_ORIGIN ?? 'http://127.0.0.1:8000'

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: { '@': path.resolve(import.meta.dirname, './src') },
    },
    server: {
      host: true, // bind 0.0.0.0 so the container port is reachable
      port: 5173,
      proxy: {
        '/api': {
          target: backendOrigin,
          changeOrigin: true,
          rewrite: (p) => p.replace(/^\/api/, ''),
        },
      },
    },
  }
})
