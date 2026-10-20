/**
 * 运行态服务端通道修复验证（M8 终审 R3 findings 回归位）。
 * 经 FakeWebSocket 驱动 startServerChannel（sources.ts）→ RuntimeEngine 全链路：
 * - finding 1：snapshot.activeAlarms 回填（刷新/重连后横幅/徽标不丢、alarmClear 不被丢弃）、
 *   按 snapshot id 集合差集清理已消失报警、截断（truncated）跳过清理、重复回填去重；
 * - finding 3：报警帧字段透传（variableKey/alarmId/ruleId/status），横幅快捷 ack 与
 *   分享页 S2 报警渲染的依赖位；
 * - finding 4：质量位 q 消费——stale/bad 登记灰显态（stale 值保留、bad 保留旧值），
 *   恢复 good 更新值并解除灰显。
 * 运行：cd web && npm test（vitest run）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { ProjectDoc, WsActiveAlarm } from '@/types/doc'
import { RuntimeEngine } from '../engine'
import { useRuntimeStore } from '../store'

/** 最小 WebSocket 桩：readyState 恒 OPEN，记录实例与发送帧供测试驱动/断言 */
class FakeWebSocket {
  static OPEN = 1
  static instances: FakeWebSocket[] = []
  readyState = FakeWebSocket.OPEN
  sent: string[] = []
  onopen: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onclose: ((ev: { code: number }) => void) | null = null
  onerror: (() => void) | null = null
  constructor(public url: string) {
    FakeWebSocket.instances.push(this)
  }
  send(data: string): void {
    this.sent.push(data)
  }
  close(): void {
    /* 桩：不触发 onclose，重连逻辑不在本组测试面 */
  }
}

function makeDoc(): ProjectDoc {
  return {
    schemaVersion: 1,
    project: { id: '11111111-1111-4111-8111-111111111111', name: '演示', createdAt: '', updatedAt: '' },
    settings: {
      designSize: { width: 1920, height: 1080 },
      adaptive: 'fit-contain',
      theme: 'blue-dark',
      primaryColor: '#0b7285',
      alarm: {
        levelColors: { info: '#3b82f6', warn: '#f59e0b', critical: '#ef4444' },
        soundEnabled: false,
        soundThrottleSec: 60,
      },
    },
    datasources: [],
    variables: [{ id: 'v1', key: 't1', label: '温度', type: 'number', datasourceId: 'ds1' }],
    pages: [
      {
        id: 'pg1',
        name: '页1',
        order: 0,
        background: { color: '#0b1220' },
        screen: { designWidth: 100, designHeight: 100, mode: 'fit-contain' },
        components: [],
      },
    ],
    alarmRules: [],
  }
}

/** snapshot 报警条目工厂（契约 §3.4 WsActiveAlarm 全字段） */
function alarm(partial: Partial<WsActiveAlarm> = {}): WsActiveAlarm {
  return {
    id: 11,
    ruleId: 'r1',
    variableKey: 't1',
    level: 'warn',
    message: '温度超限',
    value: '5',
    status: 'triggered',
    triggeredAt: 1000,
    ackedAt: null,
    ackedBy: null,
    ackedNote: null,
    clearedAt: null,
    ...partial,
  }
}

function lastSocket(): FakeWebSocket {
  return FakeWebSocket.instances[FakeWebSocket.instances.length - 1]
}

function send(ws: FakeWebSocket, frame: unknown): void {
  ws.onmessage?.({ data: JSON.stringify(frame) })
}

function snapshotFrame(activeAlarms: WsActiveAlarm[], truncated = false): Record<string, unknown> {
  return {
    type: 'snapshot',
    ts: 1,
    data: { t1: { v: 5, q: 'good', t: 1 } },
    activeAlarms,
    totalActive: activeAlarms.length,
    truncated,
  }
}

let engine: RuntimeEngine | null = null
const onAlarmEvent = vi.fn()

beforeEach(() => {
  setActivePinia(createPinia())
  FakeWebSocket.instances = []
  onAlarmEvent.mockReset()
  vi.stubGlobal('WebSocket', FakeWebSocket)
  // wsUrl() 读取 location（vitest node 环境无此全局）
  vi.stubGlobal('location', { protocol: 'http:', host: 'test.local' })
  engine = new RuntimeEngine()
  engine.start(makeDoc(), { server: { projectId: 'p1', token: 'tk' }, onAlarmEvent })
})

afterEach(() => {
  engine?.stop()
  engine = null
  vi.unstubAllGlobals()
})

describe('R3-1 snapshot 存量活动报警回填', () => {
  it('snapshot.activeAlarms 逐条回填：进横幅/徽标数据源（activeAlarms），且不重复通知', () => {
    const runtime = useRuntimeStore()
    send(lastSocket(), snapshotFrame([alarm()]))
    expect(runtime.activeAlarms.get('r1')?.message).toBe('温度超限')
    expect(runtime.activeAlarmCount).toBe(1)
    // 存量回填不打扰：不触发通知/声音（RuntimeStage onAlarmEvent 不被调用）
    expect(onAlarmEvent).not.toHaveBeenCalled()
  })

  it('回填后 alarmClear 正常关联恢复事件（修复前被丢弃）', () => {
    const runtime = useRuntimeStore()
    send(lastSocket(), snapshotFrame([alarm()]))
    send(lastSocket(), { type: 'alarmClear', alarmId: 11, recoveredAt: 2000 })
    expect(runtime.activeAlarms.size).toBe(0)
    const last = runtime.alarmEvents[runtime.alarmEvents.length - 1]
    expect(last?.type).toBe('recovered')
    expect(last?.message).toContain('已恢复')
  })

  it('差集清理：snapshot 中消失的已知报警按恢复处理', () => {
    const runtime = useRuntimeStore()
    send(lastSocket(), snapshotFrame([alarm(), alarm({ id: 12, ruleId: 'r2', message: '液位超限' })]))
    expect(runtime.activeAlarms.size).toBe(2)
    // 下一次 snapshot 只剩 #11 → #12 差集清理
    send(lastSocket(), snapshotFrame([alarm()]))
    expect(runtime.activeAlarms.has('r1')).toBe(true)
    expect(runtime.activeAlarms.has('r2')).toBe(false)
    const last = runtime.alarmEvents[runtime.alarmEvents.length - 1]
    expect(last?.message).toContain('液位超限（已恢复）')
  })

  it('truncated=true 跳过差集清理（服务端超 200 条截断，防误清）', () => {
    const runtime = useRuntimeStore()
    send(lastSocket(), snapshotFrame([alarm(), alarm({ id: 12, ruleId: 'r2' })]))
    send(lastSocket(), snapshotFrame([alarm()], true))
    expect(runtime.activeAlarms.has('r1')).toBe(true)
    expect(runtime.activeAlarms.has('r2')).toBe(true) // 未被误清
  })

  it('重连重复回填去重：已知报警仅刷新快照，不重复进事件流', () => {
    const runtime = useRuntimeStore()
    send(lastSocket(), snapshotFrame([alarm()]))
    const count = runtime.alarmEvents.length
    send(lastSocket(), snapshotFrame([alarm({ status: 'acked' })])) // 重连后同一报警已确认
    expect(runtime.alarmEvents.length).toBe(count)
    expect(runtime.activeAlarms.get('r1')?.status).toBe('acked')
    expect(runtime.serverAckedAlarmIds.has(11)).toBe(true)
  })

  it('已恢复（cleared）条目不入活动集（兜底防御）', () => {
    const runtime = useRuntimeStore()
    send(lastSocket(), snapshotFrame([alarm({ status: 'cleared', clearedAt: 1500 })]))
    expect(runtime.activeAlarms.size).toBe(0)
  })
})

describe('R3-3 报警帧字段透传', () => {
  it('snapshot 回填事件携带 variableKey/alarmId/ruleId/status', () => {
    const runtime = useRuntimeStore()
    send(lastSocket(), snapshotFrame([alarm()]))
    const ev = runtime.activeAlarms.get('r1')
    expect(ev?.variableKey).toBe('t1') // WidgetHost S2 按此反查绑定变量（分享页）
    expect(ev?.alarmId).toBe(11) // AlarmBanner 快捷 ack 依赖 DB id
    expect(ev?.ruleId).toBe('r1')
    expect(ev?.status).toBe('triggered')
  })

  it('实时 alarm 帧同样透传，且保留通知回调（onAlarmEvent）', () => {
    const runtime = useRuntimeStore()
    send(lastSocket(), { type: 'alarm', alarm: alarm({ id: 13, ruleId: 'r9' }) })
    const ev = runtime.activeAlarms.get('r9')
    expect(ev?.alarmId).toBe(13)
    expect(ev?.variableKey).toBe('t1')
    expect(onAlarmEvent).toHaveBeenCalledTimes(1)
  })

  it('alarmAck 帧登记确认集合（AlarmPanel 联动刷新依赖）', () => {
    const runtime = useRuntimeStore()
    send(lastSocket(), { type: 'alarmAck', alarmId: 11, ackedAt: 3000, ackedBy: 'op' })
    expect(runtime.serverAckedAlarmIds.has(11)).toBe(true)
  })
})

describe('R3-4 质量位 q 消费', () => {
  it('stale：登记灰显态且保留显示值，恢复 good 后更新值并解除', () => {
    const runtime = useRuntimeStore()
    send(lastSocket(), { type: 'values', data: { t1: { v: 5, q: 'good', t: 1 } } })
    expect(runtime.values.get('v1')).toBe(5)
    expect(runtime.degradedVars.size).toBe(0)

    send(lastSocket(), { type: 'values', data: { t1: { v: null, q: 'stale', t: 2 } } })
    expect(runtime.degradedVars.get('v1')).toBe('stale')
    expect(runtime.values.get('v1')).toBe(5) // stale 值保留（契约 03 §2.10）

    send(lastSocket(), { type: 'values', data: { t1: { v: 6, q: 'good', t: 3 } } })
    expect(runtime.values.get('v1')).toBe(6)
    expect(runtime.degradedVars.size).toBe(0)
  })

  it('bad：登记灰显态并保留旧值（灰显表达不可信，不闪空）', () => {
    const runtime = useRuntimeStore()
    send(lastSocket(), { type: 'values', data: { t1: { v: 5, q: 'good', t: 1 } } })
    send(lastSocket(), { type: 'values', data: { t1: { v: null, q: 'bad', t: 2 } } })
    expect(runtime.degradedVars.get('v1')).toBe('bad')
    expect(runtime.values.get('v1')).toBe(5)
  })

  it('good 首帧前无灰显态（未知 key 忽略不受影响）', () => {
    const runtime = useRuntimeStore()
    send(lastSocket(), { type: 'values', data: { unknown_key: { v: null, q: 'stale', t: 1 } } })
    expect(runtime.degradedVars.size).toBe(0)
  })
})
