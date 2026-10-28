// 官网截图生成（一次性脚本）：登录演示环境，截取台账/编辑器/运行大屏/报警中心/仿真台。
// 用法：node shots.mjs（需 5199 vite dev + 8088 compose 在跑）
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const BASE = 'http://localhost:5199'
const PV = 'c26b6eca-6ec1-4dfc-875a-a6448ea366b7'
const SHARE = '6R5M7AUTt1i6TBluzrDWlgyCpgGuanVn'
const OUT = 'F:/mycode/webScada/website/assets/img/shots'
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch()
const ctx = await browser.newContext({
  viewport: { width: 1600, height: 900 },
  deviceScaleFactor: 1.5,
  locale: 'zh-CN',
})
const page = await ctx.newPage()

async function shot(name, wait = 1200) {
  await page.waitForTimeout(wait)
  await page.screenshot({ path: `${OUT}/${name}.jpg`, type: 'jpeg', quality: 84 })
  console.log('saved', name)
}

// 登录
await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
await page.getByPlaceholder('用户名').fill('admin')
await page.getByPlaceholder('密码').fill('123456')
await page.getByRole('button', { name: '进入控制台' }).click()
await page.waitForURL(`${BASE}/projects`, { timeout: 15000 })

// 台账（卡片视图）
await page.waitForTimeout(1500)
const cardToggle = page.locator('button', { hasText: '卡片' }).first()
if (await cardToggle.count()) {
  await cardToggle.click().catch(() => {})
}
await shot('projects', 1500)

// 编辑器（光伏演示工程）
await page.goto(`${BASE}/editor/${PV}`, { waitUntil: 'networkidle' })
await page.waitForSelector('.canvas, .editor-canvas, .el-main', { timeout: 15000 }).catch(() => {})
await shot('editor', 3000)

// 运行大屏（分享页，纯运行态）
await page.goto(`${BASE}/s/${SHARE}`, { waitUntil: 'networkidle' })
await shot('runtime', 3500)

// 报警中心
await page.goto(`${BASE}/projects/${PV}/alarms`, { waitUntil: 'networkidle' })
await shot('alarms', 2500)

// 实时仿真台
await page.goto(`${BASE}/simulator?project=${PV}`, { waitUntil: 'networkidle' })
await shot('simulator', 3500)

await browser.close()
console.log('done')
