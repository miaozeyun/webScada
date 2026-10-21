import { defineConfig } from '@playwright/test'

/**
 * webScada E2E 冒烟：跑前服务须已起（docker compose，入口 http://localhost:8088），
 * 不自动拉起服务。凭证 admin/admin12345（.env）。
 * 三陷阱规约：① 就绪信号用语义 selector 不用 URL；② 受控 el-input 用 JS 设值+change 事件；
 * ③ 运行态断言一律限定 .runtime-stage 作用域。
 */
export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  use: {
    baseURL: 'http://localhost:8088',
    headless: true,
    screenshot: 'only-on-failure',
    viewport: { width: 1728, height: 960 },
  },
})
