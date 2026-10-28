import { test, expect } from '@playwright/test'
import { login } from './helpers'

test('正确凭证登录后进入工程台账', async ({ page }) => {
  await page.goto('/', { waitUntil: 'networkidle' })
  if (page.url().includes('/login')) {
    await login(page)
  }
  await expect(page).toHaveURL(/\/projects$/)
  await expect(page.locator('.el-table')).toBeVisible()
})

test('首次进入台账默认卡片视图（未手动切过表格）', async ({ page }) => {
  await page.goto('/', { waitUntil: 'networkidle' })
  await login(page, { view: 'card' })
  await expect(page.locator('.card-grid .project-card').first()).toBeVisible()
  await expect(page.locator('.el-table')).toHaveCount(0)
})

test('错误密码提示错误信息', async ({ page }) => {
  await page.goto('/login', { waitUntil: 'networkidle' })
  await page.evaluate(() => {
    const set = (sel: string, v: string) => {
      const el = document.querySelector(sel) as HTMLInputElement
      el.value = v
      el.dispatchEvent(new Event('input', { bubbles: true }))
      el.dispatchEvent(new Event('change', { bubbles: true }))
    }
    set("input[type='text']", 'admin')
    set("input[type='password']", 'wrong-password')
  })
  await page.locator('button', { hasText: '进入控制台' }).first().click()
  await expect(page.locator('.el-message--error').first()).toBeVisible()
})
