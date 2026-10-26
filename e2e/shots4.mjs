// 官网截图（第四批）：分享管理（脱敏 token）/ 数据源面板
import { chromium } from 'playwright'

const BASE = 'http://localhost:5199'
const PV = 'c26b6eca-6ec1-4dfc-875a-a6448ea366b7'
const OUT = 'F:/mycode/webScada/website/assets/img/shots'

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1.5, locale: 'zh-CN' })
const page = await ctx.newPage()

await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
await page.getByPlaceholder('用户名').fill('admin')
await page.getByPlaceholder('密码').fill('admin12345')
await page.getByRole('button', { name: '进入控制台' }).click()
await page.waitForURL(`${BASE}/projects`, { timeout: 15000 })

await page.goto(`${BASE}/editor/${PV}`, { waitUntil: 'networkidle' })
await page.waitForTimeout(2500)

// 分享管理：token 脱敏后截图
const shareBtn = page.locator('button', { hasText: /^分享$/ }).first()
if (await shareBtn.count()) {
  await shareBtn.click()
  await page.waitForTimeout(1500)
  await page.evaluate(() => {
    document.querySelectorAll('.token').forEach((el) => {
      el.textContent = '演示链接'
    })
  })
  await page.waitForTimeout(300)
  await page.screenshot({ path: `${OUT}/share-dialog.jpg`, type: 'jpeg', quality: 84 })
  console.log('saved share-dialog')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(600)
}

// 数据源面板（数据来源一览）
const dataBtn = page.locator('button', { hasText: /^数据$/ }).first()
if (await dataBtn.count()) {
  await dataBtn.click()
  await page.waitForTimeout(1500)
  await page.screenshot({ path: `${OUT}/datasources.jpg`, type: 'jpeg', quality: 84 })
  console.log('saved datasources')
}

await browser.close()
