import { test, expect } from '@playwright/test'
import { login, freshEditor } from './helpers'

test.beforeEach(async ({ page }) => {
  await login(page)
  await freshEditor(page)
})

test('预览进入运行态', async ({ page }) => {
  await page.locator('button', { hasText: '预览' }).first().click()
  await page.waitForSelector('.runtime-stage', { timeout: 10_000 })
  await expect(page.locator('.runtime-stage')).toBeVisible()
})

test('运行态存在非空读数（限定 runtime-stage 作用域）', async ({ page }) => {
  await page.locator('button', { hasText: '预览' }).first().click()
  await page.waitForSelector('.runtime-stage', { timeout: 10_000 })
  await page.waitForTimeout(2500) // 等实时数据注入
  const scope = page.locator('.runtime-stage')
  const text = ((await scope.textContent()) ?? '').trim()
  expect(text.length).toBeGreaterThan(10)
})

test('退出预览无页面错误', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(String(e)))
  await page.locator('button', { hasText: '预览' }).first().click()
  await page.waitForSelector('.runtime-stage', { timeout: 10_000 })
  await page.locator('button', { hasText: '退出' }).first().click()
  await page.waitForTimeout(1500)
  expect(errors).toEqual([])
})
