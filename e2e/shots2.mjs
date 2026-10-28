// 官网截图（第二批）：卡片台账 / 分享管理 / 通知渠道与投递记录
import { chromium } from 'playwright'

const BASE = 'http://localhost:5199'
const PV = 'c26b6eca-6ec1-4dfc-875a-a6448ea366b7'
const OUT = 'F:/mycode/webScada/website/assets/img/shots'

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

await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
await page.getByPlaceholder('用户名').fill('admin')
await page.getByPlaceholder('密码').fill('123456')
await page.getByRole('button', { name: '进入控制台' }).click()
await page.waitForURL(`${BASE}/projects`, { timeout: 15000 })

// 卡片视图 + 搜索演示
await page.waitForTimeout(1200)
await page.getByPlaceholder('按名称搜索').fill('演示')
await page.keyboard.press('Enter')
await page.waitForTimeout(1200)
await page.locator('button[title="卡片视图（画面缩略图）"]').click()
await shot('projects-card', 1800)

// 分享管理对话框
await page.goto(`${BASE}/editor/${PV}`, { waitUntil: 'networkidle' })
await page.waitForTimeout(2500)
const shareBtn = page.locator('button', { hasText: /^分享$/ }).first()
if (await shareBtn.count()) {
  await shareBtn.click()
  await shot('share-dialog', 1800)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(500)
}

// 数据抽屉 → 通知 tab
const dataBtn = page.locator('button', { hasText: /^数据$/ }).first()
if (await dataBtn.count()) {
  await dataBtn.click()
  await page.waitForTimeout(1200)
  const notifyTab = page.locator('.el-tabs__item', { hasText: '通知' }).first()
  if (await notifyTab.count()) {
    await notifyTab.click()
    await shot('notify-panel', 1800)
  }
}

await browser.close()
console.log('done')
