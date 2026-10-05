import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the API runs separately (uvicorn on :8000); /api is proxied so the app
// uses the same relative URLs as in production, where FastAPI serves this build itself.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
