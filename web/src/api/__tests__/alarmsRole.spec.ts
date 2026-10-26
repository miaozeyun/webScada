/**
 * 报警面板角色缓存（2026-10-26）：
 * - 并发挂载只发一次 /auth/me（单飞）；
 * - 缓存绑定 token：换账号/登出后不得复用上一账号角色；
 * - 迟到结果按 token 比对丢弃，不污染新会话；
 * - 失败允许重试。
 */
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

type Deferred = { resolve: (v: { role?: string }) => void; reject: (e: unknown) => void }
let queue: Deferred[] = []

vi.mock('@/api/http', () => ({
  http: {
    get: () =>
      new Promise<{ role?: string }>((resolve, reject) => {
        queue.push({ resolve, reject })
      }),
  },
}))

const storage = new Map<string, string>()
vi.stubGlobal('localStorage', {
  getItem: (k: string) => storage.get(k) ?? null,
  setItem: (k: string, v: string) => storage.set(k, v),
  removeItem: (k: string) => storage.delete(k),
})

let fetchMyRole: () => Promise<'admin' | 'operator' | 'viewer' | null>
let resetRoleCache: () => void
beforeAll(async () => {
  ;({ fetchMyRole, resetRoleCache } = await import('../alarms'))
})

beforeEach(() => {
  queue = []
  storage.clear()
  resetRoleCache()
})

const tick = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0))

describe('fetchMyRole 缓存与单飞', () => {
  it('并发调用合并为一次请求，结果按 token 缓存', async () => {
    storage.set('webscada_token', 't1')
    const p1 = fetchMyRole()
    const p2 = fetchMyRole()
    await tick()
    expect(queue.length).toBe(1)
    queue[0].resolve({ role: 'operator' })
    await expect(p1).resolves.toBe('operator')
    await expect(p2).resolves.toBe('operator')

    await expect(fetchMyRole()).resolves.toBe('operator')
    expect(queue.length).toBe(1) // 命中缓存
  })

  it('换 token 后重取；旧请求迟到结果不落缓存', async () => {
    storage.set('webscada_token', 'old')
    const stale = fetchMyRole()
    await tick()

    storage.set('webscada_token', 'new') // 换账号（登出再登录，不刷新页面）
    const fresh = fetchMyRole()
    await tick()
    expect(queue.length).toBe(2)

    queue[0].resolve({ role: 'admin' }) // 旧账号迟到
    queue[1].resolve({ role: 'viewer' })
    await Promise.allSettled([stale, fresh])

    await expect(fetchMyRole()).resolves.toBe('viewer')
    expect(queue.length).toBe(2)
  })

  it('无 token 直接返回 null 且不发请求（分享页）', async () => {
    await expect(fetchMyRole()).resolves.toBeNull()
    expect(queue.length).toBe(0)
  })

  it('失败可重试，缓存不失真', async () => {
    storage.set('webscada_token', 't1')
    const p1 = fetchMyRole()
    await tick()
    queue[0].reject(new Error('network'))
    await expect(p1).resolves.toBeNull()

    const p2 = fetchMyRole()
    await tick()
    expect(queue.length).toBe(2)
    queue[1].resolve({ role: 'admin' })
    await expect(p2).resolves.toBe('admin')
  })
})
