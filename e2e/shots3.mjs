// 官网截图（第三批）：图元库面板
import { chromium } from 'playwright'

const BASE = 'http://localhost:5199'
const PV = 'c26b6eca-6ec1-4dfc-875a-a6448ea366b7'
const OUT = 'F:/mycode/webScada/website/assets/img/shots'

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1.5, locale: 'zh-CN' })
const page = await ctx.newPage()

await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
await page.getByPlaceholder('用户名').fill('admin')
await page.getByPlaceholder('密码').fill('123456')
await page.getByRole('button', { name: '进入控制台' }).click()
await page.waitForURL(`${BASE}/projects`, { timeout: 15000 })

await page.goto(`${BASE}/editor/${PV}`, { waitUntil: 'networkidle' })
await page.waitForTimeout(2500)

const tab = page.locator('button.tab', { hasText: '图元' }).first()
if (await tab.count()) {
  await tab.click()
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${OUT}/symbol-library.jpg`, type: 'jpeg', quality: 84 })
  console.log('saved symbol-library')
} else {
  console.log('图元 tab not found')
}

await browser.close()
