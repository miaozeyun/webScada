import { test, expect } from '@playwright/test'
import { login, freshEditor } from './helpers'

test.beforeEach(async ({ page }) => {
  await login(page)
  await freshEditor(page)
})

test('点击组件库首项放置组件，图层计数加一', async ({ page }) => {
  const before = await page.locator('.real-time-component-list .list').count()
  await page.locator('.component-list .list').first().click()
  await expect(page.locator('.real-time-component-list .list')).toHaveCount(before + 1)
})

test('点画布中心选中组件，属性面板显示组件属性', async ({ page }) => {
  await page.locator('.component-list .list').first().click()
  await page.waitForTimeout(600)
  const box = (await page.locator('.canvas-page').first().boundingBox())!
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2)
  await page.waitForTimeout(500)
  await expect(page.locator('.attr-container .attr-title', { hasText: '属性' }).first()).toBeVisible()
})

test('选中组件后右键弹出自定义菜单且不少于 10 项', async ({ page }) => {
  // 菜单项随选中态条件渲染：空白右键仅 1 项，须先放置并选中
  await page.locator('.component-list .list').first().click()
  await page.waitForTimeout(600)
  const box = (await page.locator('.canvas-page').first().boundingBox())!
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2)
  await page.waitForTimeout(400)
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2, { button: 'right' })
  await page.waitForTimeout(500)
  const items = await page.locator('.ws-contextmenu li').count()
  expect(items).toBeGreaterThanOrEqual(10)
})

test('Ctrl+Z 撤销放置，图层计数回落', async ({ page }) => {
  const before = await page.locator('.real-time-component-list .list').count()
  await page.locator('.component-list .list').first().click()
  await expect(page.locator('.real-time-component-list .list')).toHaveCount(before + 1)
  await page.keyboard.press('Control+z')
  await expect(page.locator('.real-time-component-list .list')).toHaveCount(before)
})

test('Delete 删除选中组件，Ctrl+Z 恢复', async ({ page }) => {
  const before = await page.locator('.real-time-component-list .list').count()
  await page.locator('.component-list .list').first().click()
  await expect(page.locator('.real-time-component-list .list')).toHaveCount(before + 1)
  // 放置在可视区中心，点击即选中
  const box = (await page.locator('.canvas-page').first().boundingBox())!
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2)
  await page.waitForTimeout(400)
  await page.keyboard.press('Delete')
  await expect(page.locator('.real-time-component-list .list')).toHaveCount(before)
  await page.keyboard.press('Control+z')
  await expect(page.locator('.real-time-component-list .list')).toHaveCount(before + 1)
})

test('数据抽屉含数据源/变量/报警三区', async ({ page }) => {
  await page.locator('button', { hasText: '数据' }).first().click()
  const drawer = page.locator('.el-drawer')
  await drawer.waitFor()
  for (const label of ['数据源', '变量', '报警']) {
    await expect(drawer.locator('text=' + label).first()).toBeVisible()
  }
})

test('页面页签新建页，tab 数加一', async ({ page }) => {
  const before = await page.locator('.page-tabs .page-tab').count()
  await page.locator('.page-tabs .add-btn').click()
  await expect(page.locator('.page-tabs .page-tab')).toHaveCount(before + 1)
})
