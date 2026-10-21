/**
 * 历史接口分享通道验证（M8 终审 R3 finding 5b 回归位）：
 * setHistoryShareToken 注入后 queryHistory 携带 Bearer shareToken（分享页历史图接服务端
 * /history 的唯一通道），置空恢复 JWT 通道；setHistoryProjectId 注入/清除供历史图组件
 * 「组件配置 → editor store → 宿主注入」解析链末级消费。
 * vi.mock('@/api/http') 打断 axios/element-plus/router 依赖链（纯逻辑测试）。
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/http', () => ({
  http: { get: vi.fn(() => Promise.resolve({ series: {} })) },
}))

import { http } from '@/api/http'
import {
  getHistoryProjectId,
  queryHistory,
  setHistoryProjectId,
  setHistoryShareToken,
} from '@/api/history'

const getSpy = vi.mocked(http.get)

afterEach(() => {
  setHistoryShareToken(null)
  setHistoryProjectId('')
  getSpy.mockClear()
})

describe('R3-5b 分享页历史通道', () => {
  it('shareToken 注入：queryHistory 以 Bearer 头携带分享 token', async () => {
    setHistoryShareToken('st_token')
    await queryHistory('p1', { keys: ['t1'], from: 0, to: 1 })
    const cfg = getSpy.mock.calls[0]?.[1]
    expect(cfg?.headers).toMatchObject({ Authorization: 'Bearer st_token' })
  })

  it('token 置空恢复 JWT 通道：不再携带注入 headers（走请求拦截器）', async () => {
    setHistoryShareToken('st_token')
    setHistoryShareToken(null)
    await queryHistory('p1', { keys: ['t1'], from: 0, to: 1 })
    const cfg = getSpy.mock.calls[0]?.[1]
    expect(cfg?.headers).toBeUndefined()
  })

  it('工程 id 注入/清除（历史图组件宿主注入链末级）', () => {
    setHistoryProjectId('p9')
    expect(getHistoryProjectId()).toBe('p9')
    setHistoryProjectId('')
    expect(getHistoryProjectId()).toBe('')
  })
})

describe('agg 聚合参数透传（阶段二 Task 1）', () => {
  it('显式 agg → 序列化为查询参数（服务端窗口聚合口径）', async () => {
    await queryHistory('p1', { keys: ['t1'], from: 0, to: 1, agg: 'max' })
    const cfg = getSpy.mock.calls[0]?.[1]
    expect(cfg?.params).toMatchObject({ agg: 'max' })
  })

  it('未设置 agg 不下发参数（旧调用零影响，服务端缺省 mean）', async () => {
    await queryHistory('p1', { keys: ['t1'], from: 0, to: 1 })
    expect(getSpy.mock.calls[0]?.[1]?.params).not.toHaveProperty('agg')
  })
})
