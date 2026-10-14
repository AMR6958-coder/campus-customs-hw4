import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // This project lives in a OneDrive folder, where file-change events are
    // unreliable and Vite kept serving stale modules. Polling is slower but
    // catches every save.
    watch: {
      usePolling: true,
      interval: 300,
    },
    // During development, forward API calls and product images to the FastAPI
    // back end. This lets the front end use relative URLs such as
    // /api/products and /media/products/<file>.jpg without hard-coding a host.
    proxy: {
      '/api': 'http://localhost:8000',
      '/media': 'http://localhost:8000',
    },
  },
})
