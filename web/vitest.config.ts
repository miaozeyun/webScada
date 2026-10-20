import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'

/**
 * vitest 配置（M8 工作包 F 独占）。
 * - 环境 node：被测对象（migrateDoc）为纯函数，无 DOM 依赖；
 * - esbuild target 对齐 vite.config.ts 的 es2020 基线（G22：Chrome/Edge ≥ 90）；
 * - '@' 别名与 vite.config.ts 保持一致。
 */
export default defineConfig({
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  esbuild: { target: 'es2020' },
  test: { environment: 'node' },
})
