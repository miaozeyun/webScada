import type { Page } from '@playwright/test'

/** 登录（受控 el-input：JS 设值 + input/change 事件）→ 等 .el-table 就绪 */
export async function login(page: Page): Promise<void> {
  await page.goto('/', { waitUntil: 'networkidle' })
  if (!page.url().includes('/login')) return
  await jsSetInput(page, "input[type='text']", 'admin')
  await jsSetInput(page, "input[type='password']", 'admin12345')
  await page.locator('button', { hasText: '进入控制台' }).first().click()
  await page.waitForSelector('.el-table', { timeout: 15_000 })
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
