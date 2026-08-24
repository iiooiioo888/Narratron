import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// GitHub Pages: https://iiooiioo888.github.io/Narratron/
const isPages = process.env.GITHUB_PAGES === 'true'

export default defineConfig({
  plugins: [react()],
  base: isPages ? '/Narratron/' : '/',
  server: {
    port: 5173,
    proxy: {
      '/health': 'http://localhost:8080',
      '/parse': 'http://localhost:8080',
      '/direct': 'http://localhost:8080',
      '/keep': 'http://localhost:8080',
      '/run': 'http://localhost:8080',
      '/mux': 'http://localhost:8080',
      '/api': 'http://localhost:8080',
    },
  },
})
