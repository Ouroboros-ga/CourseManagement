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
      '/api': {
        target: 'https://course.zsitai.xyz',
        changeOrigin: true,
        secure: true,
        cookieDomainRewrite: '',
        configure(proxy) {
          proxy.on('proxyReq', (proxyReq, req) => {
            // 同源开发请求经可信代理转发到云端；保留其他 Origin 和 Sec-Fetch-Site，
            // 让云端继续拒绝非法来源，而无需扩大生产 CSRF 白名单。
            if (req.headers.origin === 'http://localhost:3000' ||
                req.headers.origin === 'http://127.0.0.1:3000') {
              proxyReq.setHeader('Origin', 'https://course.zsitai.xyz')
            }
          })
          proxy.on('proxyRes', (proxyRes) => {
            // 仅本地 HTTP 代理去掉 Secure；保留 HttpOnly、SameSite 与作用路径。
            // 正式 HTTPS 服务仍返回 Secure Cookie，此配置不进入静态构建产物。
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
