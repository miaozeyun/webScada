import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  // G22：Chrome/Edge ≥ 90 基线，对应 es2020
  build: { target: 'es2020' },
  server: {
    port: 5199,
    strictPort: true, // 端口被占直接报错（本机 5173 已被其他应用占用，静默换端口会误导 E2E）
    // 本地开发：/api 代理到 compose 的 nginx 入口（server 容器 8000 端口不暴露宿主机）
    proxy: { '/api': 'http://localhost:8088' },
  },
})
