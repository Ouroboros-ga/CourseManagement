import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    host: '127.0.0.1',
    port: 3000,
    strictPort: true,
    proxy: {
      '/health': {
        target: process.env.BACKEND_URL || 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/api': {
        target: process.env.BACKEND_URL || 'http://127.0.0.1:8000',
        changeOrigin: true,
        cookieDomainRewrite: '',
        configure(proxy) {
          proxy.on('proxyReq', (proxyReq, req) => {
            if (req.headers.origin === 'http://localhost:3000' ||
                req.headers.origin === 'http://127.0.0.1:3000' ||
                req.headers.origin === 'http://127.0.0.1:5173') {
              proxyReq.setHeader('Origin', 'http://127.0.0.1:8000')
            }
          })
          proxy.on('proxyRes', (proxyRes) => {
            const cookies = proxyRes.headers['set-cookie']
            if (cookies) {
              proxyRes.headers['set-cookie'] = cookies.map(cookie =>
                cookie.replace(/;\s*secure\b/gi, '')
              )
            }
          })
        }
      }
    }
  }
})
