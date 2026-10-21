import type { Page } from '@playwright/test'

/** 登录（受控 el-input：JS 设值 + input/change 事件）→ 等 .el-table 就绪 */
export async function login(page: Page): Promise<void> {
  await page.goto('/', { waitUntil: 'networkidle' })
  if (!page.url().includes('/login')) return
  await jsSetInput(page, "input[type='text']", 'admin')
  await jsSetInput(page, "input[type='password']", 'admin12345')
  // 偶发点击落在表单校验未就绪瞬间：点后未跳转则重试（最终仍必须见到台账）
  for (let i = 0; i < 3; i++) {
    await page.locator('button', { hasText: '进入控制台' }).first().click()
    try {
      await page.waitForURL(/\/projects/, { timeout: 6_000 })
      break
    } catch {
      await page.waitForTimeout(500)
    }
  }
  await page.waitForSelector('.el-table', { timeout: 15_000 })
}

/** 新建一个隔离工程并进入编辑器（避免用例间共享首行工程互相污染） */
export async function freshEditor(page: Page): Promise<void> {
  await page.locator('button', { hasText: '新建工程' }).first().click()
  const dialog = page.locator('.el-dialog')
  await dialog.waitFor()
  const name = `e2e-隔离-${Date.now()}-${Math.floor(Math.random() * 1000)}`
  await dialog.locator('input').first().evaluate((el: HTMLInputElement, v: string) => {
    el.value = v
    el.dispatchEvent(new Event('input', { bubbles: true }))
    el.dispatchEvent(new Event('change', { bubbles: true }))
  }, name)
  await dialog.locator('button', { hasText: '创建' }).click()
  const row = page.locator('.el-table__row', { hasText: name })
  await row.first().waitFor({ timeout: 10_000 })
  await row.locator('button', { hasText: '编辑' }).first().click()
  await page.waitForSelector('.canvas-page', { timeout: 15_000 })
}

/** Element Plus 受控输入注入：handleInput 的 nextTick 写回会吞掉 fill()，须直设 value 并派发事件 */
export async function jsSetInput(page: Page, selector: string, value: string): Promise<void> {
  await page
    .locator(selector)
    .first()
    .evaluate((el: HTMLInputElement, v: string) => {
      el.value = v
      el.dispatchEvent(new Event('input', { bubbles: true }))
      el.dispatchEvent(new Event('change', { bubbles: true }))
    }, value)
}
