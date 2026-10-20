/**
 * migrateDoc 机制测试（M8 契约 §9-F 验收位）。
 * 本期 CURRENT_SCHEMA_VERSION=1，注册表为空——用「注入假想迁移」的方式验证机制：
 * - v=2 假想文件 → too_new（round-trip 拒绝路径位，服务端 test_schema_window.py 同构覆盖）；
 * - 注入 MIGRATIONS[0] 模拟 N-1 → 逐步升级接受路径（round-trip 接受路径位）。
 * 运行：cd web && npm test（vitest run，见 vitest.config.ts）。
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { CURRENT_SCHEMA_VERSION, MIGRATIONS } from '@/types/migrations'
import { migrateDoc } from '@/utils/migrateDoc'

/** 最小合法形态的 v=1 工程 doc（migrateDoc 不做结构校验，仅版本推进） */
function makeDoc(version: number = CURRENT_SCHEMA_VERSION): Record<string, unknown> {
  return {
    schemaVersion: version,
    project: { id: '3f2b8c1e-0000-4000-8000-000000000001', name: '演示工程' },
    settings: { theme: 'blue-dark' },
    datasources: [],
    variables: [],
    pages: [],
    alarmRules: [],
  }
}

afterEach(() => {
  // 测试内注入的假想迁移一律清理，注册表对后续测试/生产代码保持空表现状
  for (const k of Object.keys(MIGRATIONS)) delete MIGRATIONS[Number(k)]
})

describe('migrateDoc 基础语义', () => {
  it('v=CURRENT 直通：ok 且版本不变', () => {
    const r = migrateDoc(makeDoc())
    expect(r.ok).toBe(true)
    if (!r.ok) return
    expect(r.doc.schemaVersion).toBe(CURRENT_SCHEMA_VERSION)
    expect(r.doc.project.name).toBe('演示工程')
  })

  it('v=CURRENT 直通返回深拷贝：修改结果不影响入参对象', () => {
    const raw = makeDoc()
    const r = migrateDoc(raw)
    expect(r.ok).toBe(true)
    if (!r.ok) return
    expect(r.doc).not.toBe(raw)
    r.doc.project.name = '改名'
    expect((raw.project as { name: string }).name).toBe('演示工程')
  })

  it('v>CURRENT → too_new（假想 v=2 拒绝路径，禁止静默降级）', () => {
    const r = migrateDoc(makeDoc(CURRENT_SCHEMA_VERSION + 1))
    expect(r.ok).toBe(false)
    if (r.ok) return
    expect(r.reason).toBe('too_new')
    expect(r.message).toContain('升级前端')
  })

  it('远期版本（v=CURRENT+5）同样 too_new', () => {
    const r = migrateDoc(makeDoc(CURRENT_SCHEMA_VERSION + 5))
    expect(r.ok).toBe(false)
    if (r.ok) return
    expect(r.reason).toBe('too_new')
  })
})

describe('migrateDoc 非法输入 → invalid', () => {
  const cases: [string, unknown][] = [
    ['null', null],
    ['数组', [makeDoc()]],
    ['字符串', '"不是对象"'],
    ['数字', 123],
    ['缺 schemaVersion', { project: {} }],
    ['版本为字符串', { ...makeDoc(), schemaVersion: '1' }],
    ['版本为浮点', { ...makeDoc(), schemaVersion: 1.5 }],
    ['版本为 null', { ...makeDoc(), schemaVersion: null }],
  ]
  for (const [name, input] of cases) {
    it(name, () => {
      const r = migrateDoc(input)
      expect(r.ok).toBe(false)
      if (r.ok) return
      expect(r.reason).toBe('invalid')
    })
  }
})

describe('migrateDoc 逐版升级（注入假想迁移模拟 N-1 接受路径）', () => {
  it('注册 MIGRATIONS[0]：v=0 文件逐步升级到 CURRENT，框架统一推进版本号', () => {
    const step = vi.fn((doc: Record<string, unknown>) => {
      // 假想 v0 → v1 结构变换：旧字段 alpha 归档进 settings.legacy
      const settings = (doc.settings as Record<string, unknown>) ?? {}
      return { ...doc, settings: { ...settings, legacy: doc.alpha } }
    })
    MIGRATIONS[0] = step

    const raw = { ...makeDoc(0), alpha: '旧值' }
    const r = migrateDoc(raw)
    expect(step).toHaveBeenCalledTimes(1)
    expect(r.ok).toBe(true)
    if (!r.ok) return
    expect(r.doc.schemaVersion).toBe(CURRENT_SCHEMA_VERSION)
    expect((r.doc.settings as { legacy?: unknown }).legacy).toBe('旧值')
  })

  it('多级链按起始版本逐版推进；键 ≥ CURRENT 的注册项不会被消费', () => {
    const calls: number[] = []
    // CURRENT=1 时 v=0 经 MIGRATIONS[0] 一步达 CURRENT；注册 MIGRATIONS[1] 验证 while 不会越界消费
    MIGRATIONS[0] = (d) => (calls.push(0), { ...d, m0: true })
    MIGRATIONS[1] = (d) => (calls.push(1), { ...d, m1: true })

    const r = migrateDoc(makeDoc(0))
    expect(calls).toEqual([0])
    expect(r.ok).toBe(true)
    if (!r.ok) return
    expect(r.doc.schemaVersion).toBe(CURRENT_SCHEMA_VERSION)
    expect(r.doc).not.toHaveProperty('m1')
  })

  it('注册表缺级（v=0 且无 MIGRATIONS[0]）→ invalid，提示缺少迁移实现', () => {
    const r = migrateDoc(makeDoc(0))
    expect(r.ok).toBe(false)
    if (r.ok) return
    expect(r.reason).toBe('invalid')
    expect(r.message).toContain('缺少')
  })

  it('迁移函数执行抛错 → invalid，消息携带原因', () => {
    MIGRATIONS[0] = () => {
      throw new Error('字段损坏无法迁移')
    }
    const r = migrateDoc(makeDoc(0))
    expect(r.ok).toBe(false)
    if (r.ok) return
    expect(r.reason).toBe('invalid')
    expect(r.message).toContain('字段损坏无法迁移')
  })

  it('迁移函数返回非对象（undefined）→ invalid（版本号改写兜底）', () => {
    MIGRATIONS[0] = () => undefined as unknown as Record<string, unknown>
    const r = migrateDoc(makeDoc(0))
    expect(r.ok).toBe(false)
    if (r.ok) return
    expect(r.reason).toBe('invalid')
  })
})
