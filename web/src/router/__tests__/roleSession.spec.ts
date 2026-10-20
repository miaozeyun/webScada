/**
 * /admin 守卫角色会话修复验证（M8 终审 R3 finding 2 回归位）。
 * - 成功路径复位 meInflight：换账号后必发新 /auth/me，不复用上一账号的已决 promise
 *   （修复前 viewer 复用 admin 的结果可误过 /admin 守卫）；
 * - /login 作废在途请求：迟到结果按引用比较丢弃，不污染新会话缓存。
 * vi.mock('@/api/auth') 打断 http→router 循环依赖链；window/localStorage 桩供
 * router 模块顶层 createWebHistory 与守卫 token 读取。
 */
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

// router 模块顶层 createWebHistory 依赖浏览器 window（vitest node 环境无）→ 换内存 history
vi.mock('vue-router', async (importOriginal) => {
  const mod = await importOriginal<typeof import('vue-router')>()
  return { ...mod, createWebHistory: () => mod.createMemoryHistory() }
})

type Deferred = { resolve: (me: { role?: string } | undefined) => void }
let meQueue: Deferred[] = []

vi.mock('@/api/auth', () => ({
  meApi: () =>
    new Promise<{ role?: string } | undefined>((resolve) => {
      meQueue.push({ resolve })
    }),
}))

// 动态导入：等待 vi.mock('vue-router') 替换生效后再加载 router 模块
let fetchMyRole: () => Promise<string | undefined>
let invalidateRoleSession: () => void
beforeAll(async () => {
  ;({ fetchMyRole, invalidateRoleSession } = await import('@/router'))
})

beforeEach(() => {
  meQueue = []
  invalidateRoleSession()
})

/** 冲刷微任务/宏任务：meApi 经动态 import 的 then 链才被调用 */
const tick = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0))

describe('R3-2 meInflight 生命周期', () => {
  it('成功路径复位 inflight：并发合并共享，作废后再次拉取必发新请求', async () => {
    const p1 = fetchMyRole()
    const p2 = fetchMyRole()
    await tick()
    expect(meQueue.length).toBe(1) // 并发去重
    meQueue[0].resolve({ role: 'admin' })
    await expect(p1).resolves.toBe('admin')
    await expect(p2).resolves.toBe('admin')

    // 模拟 /login 守卫换账号（旧实现：成功路径不复位，此处复用已决 promise 返回 admin）
    invalidateRoleSession()
    const p3 = fetchMyRole()
    await tick()
    expect(meQueue.length).toBe(2) // 必须发出新请求
    meQueue[1].resolve({ role: 'viewer' })
    await expect(p3).resolves.toBe('viewer')
  })

  it('在途作废：迟到旧结果丢弃，不污染新会话缓存', async () => {
    const stale = fetchMyRole() // 旧 token 请求在途
    await tick()
    invalidateRoleSession() // 进入 /login 换账号
    const fresh = fetchMyRole()
    await tick()
    expect(meQueue.length).toBe(2)

    meQueue[0].resolve({ role: 'admin' }) // 旧 token 迟到结果（不应落缓存）
    meQueue[1].resolve({ role: 'viewer' })
    await Promise.allSettled([stale, fresh])

    expect(await fetchMyRole()).toBe('viewer') // 缓存为新会话角色
    await tick()
    expect(meQueue.length).toBe(2) // 未因旧结果污染而多发请求
  })

  it('失败路径允许重试：inflight 复位后再次拉取发新请求', async () => {
    const p1 = fetchMyRole()
    await tick()
    meQueue[0].resolve(undefined) // 失败（401 已由 http 拦截器接管）
    await expect(p1).resolves.toBeUndefined()

    const p2 = fetchMyRole()
    await tick()
    expect(meQueue.length).toBe(2)
    meQueue[1].resolve({ role: 'operator' })
    await expect(p2).resolves.toBe('operator')
  })
})
