import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as { version: string }

export default defineConfig({
  plugins: [
    vue(),
    // Element Plus 按需引入：模板组件/指令自动注入 import 与样式（替代全量 index.css）
    AutoImport({ resolvers: [ElementPlusResolver()] }),
    Components({ resolvers: [ElementPlusResolver()], directives: true }),
  ],
  define: {
    // 版本号构建期注入（登录页脚等处展示，避免硬编码与 CHANGELOG 脱节）
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  // G22：Chrome/Edge ≥ 90 基线，对应 es2020
  build: { target: 'es2020' },
  server: {
    port: 5199,
    strictPort: true, // 端口被占直接报错（本机 5173 已被其他应用占用，静默换端口会误导 E2E）
    // 本地开发：/api 代理到 compose 的 nginx 入口（server 容器 8000 端口不暴露宿主机）
    // ws:true：M8 运行态走 /api/v1/ws WebSocket，简写字符串代理不转发升级请求会永挂"连接中"
    proxy: { '/api': { target: 'http://localhost:8088', ws: true } },
  },
})
