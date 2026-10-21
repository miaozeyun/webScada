import { test, expect } from '@playwright/test'
import { login } from './helpers'

test.beforeEach(async ({ page }) => {
  await login(page)
})

test('台账列表加载出工程行', async ({ page }) => {
  await expect(page.locator('.el-table__row').first()).toBeVisible()
})

test('新建工程后台账出现新工程行', async ({ page }) => {
  await page.locator('button', { hasText: '新建工程' }).first().click()
  const dialog = page.locator('.el-dialog')
  await dialog.waitFor()
  const name = `e2e-冒烟-${Date.now()}`
  await dialog.locator('input').first().evaluate((el: HTMLInputElement, v: string) => {
    el.value = v
    el.dispatchEvent(new Event('input', { bubbles: true }))
    el.dispatchEvent(new Event('change', { bubbles: true }))
  }, name)
  await dialog.locator('button', { hasText: '创建' }).click()
  // 台账分页满页时行数不变，断言新名称出现而非行数+1
  await expect(page.locator('.el-table__row', { hasText: name }).first()).toBeVisible({ timeout: 10_000 })
})

test('点首行“编辑”进入画布编辑器', async ({ page }) => {
  await page.locator('.el-table__row button', { hasText: '编辑' }).first().click()
  await page.waitForSelector('.canvas-page', { timeout: 15_000 })
  await expect(page).toHaveURL(/\/editor\//)
})
