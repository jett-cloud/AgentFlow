import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
  plugins: [vue()],
  base: '/agentFlow/',
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/console/api': {
        target: env.VITE_DIFY_API_ORIGIN || 'http://localhost:5001',
        changeOrigin: true,
        // Keep draft-run SSE streaming; default buffering hides node paint + results.
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq, req) => {
            const url = String(req.url || '')
            if (url.includes('/workflows/draft/run')
              || url.includes('/advanced-chat/workflows/draft/run')
              || (url.includes('/workflow/') && url.includes('/events'))) {
              proxyReq.setHeader('Accept', 'text/event-stream')
            }
          })
          proxy.on('proxyRes', (proxyRes, _req, res) => {
            const contentType = String(proxyRes.headers['content-type'] || '')
            const url = String(_req.url || '')
            const looksLikeDraftRun = url.includes('/workflows/draft/run')
              || url.includes('/advanced-chat/workflows/draft/run')
              || (url.includes('/workflow/') && url.includes('/events'))
            if (!contentType.includes('text/event-stream') && !looksLikeDraftRun)
              return
            // Prevent intermediary buffering that stalls node paint until the stream ends.
            res.setHeader('Cache-Control', 'no-cache, no-transform')
            res.setHeader('X-Accel-Buffering', 'no')
            res.setHeader('Content-Type', 'text/event-stream; charset=utf-8')
            delete proxyRes.headers['content-length']
            delete proxyRes.headers['content-encoding']
          })
        },
      },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/ws-endpoint': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true
      }
    }
  },
  optimizeDeps: {
    include: ['@stomp/stompjs', 'sockjs-client']
  }
  }
})
