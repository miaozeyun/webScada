/**
 * 运行态 store（M3/M5，M8 扩展服务端通道状态）：变量值池 + 绑定覆盖层 + 报警状态。
 * 关键约束：运行值绝不写回 editor.doc（不触发 dirty/保存），全部走 overrides
 * 由 WidgetHost（K12 唯一装配点）与 PreviewNode 在渲染时合并。
 */
import { defineStore } from 'pinia'
import type { AlarmRule, ValueQuality } from '@/types/doc'

/** 非 good 的质量态（stale=超时值保留 / bad=数据不可信），UI 据此灰显 */
export type DegradedQuality = Exclude<ValueQuality, 'good'>

export interface NodeOverride {
  props?: Record<string, unknown>
  style?: Record<string, unknown>
  visible?: boolean
  /** M7：动效绑定通道（anim.rotateOn 等），PreviewNode 与静态 animations 合并 */
  anim?: {
    rotateOn?: boolean
    rotatePeriod?: number
    flowOn?: boolean
    blinkOn?: boolean
    moveOn?: boolean
  }
}

export interface AlarmEvent {
  id: string
  type: 'active' | 'recovered'
  level: AlarmRule['level']
  message: string
  value: number | boolean | string
  at: number
  /** M8 服务端帧透传字段（本地引擎事件无）：alarmId 供横幅快捷 ack（DB id），
   *  variableKey 供 WidgetHost S2 报警态反查绑定变量（分享页 rules 不在本地 doc）；
   *  缺失这两个字段会使分享页报警渲染与快捷确认双双失效 */
  variableKey?: string
  ruleId?: string
  alarmId?: number
  status?: 'triggered' | 'acked' | 'cleared'
}

/** M8：服务端值流通道状态（off=浏览器直连/未启用） */
export type ServerStatus = 'off' | 'connecting' | 'online' | 'offline' | 'error'

export const useRuntimeStore = defineStore('runtime', {
  state: () => ({
    running: false,
    /** 变量运行值 variableId → 工程值（已过变量级换算） */
    values: new Map<string, number | boolean | string>(),
    /** 变量 key → id 索引（M7：tooltip 模板 / 表达式 scope / 控制组件取值） */
    varByKey: new Map<string, string>(),
    /** 绑定求值结果按 nodeId 聚合（渲染覆盖层） */
    overrides: new Map<string, NodeOverride>(),
    /** 激活中的报警 ruleId → 事件信息 */
    activeAlarms: new Map<string, AlarmEvent>(),
    /** 最近报警事件流（上限 100，供横幅/通知消费） */
    alarmEvents: [] as AlarmEvent[],
    // ---- M8 服务端通道 ----
    serverStatus: 'off' as ServerStatus,
    /** 服务端报警 DB id ← 规则 id（alarmAck 帧按 DB id 关联，D 包报警面板消费） */
    serverAlarmIdByRule: new Map<string, number>(),
    /** 已确认报警的服务端 DB id（alarmAck 帧到达后登记） */
    serverAckedAlarmIds: new Set<number>(),
    /** 变量质量位（M8 契约 q∈good|stale|bad）：仅登记非 good（stale/bad）态，
     *  恢复 good 时移除；WidgetHost 据此对绑定节点叠灰（03 §2.10 质量位消费） */
    degradedVars: new Map<string, DegradedQuality>(),
  }),

  getters: {
    overrideOf(state): (nodeId: string) => NodeOverride | undefined {
      return (nodeId: string) => state.overrides.get(nodeId)
    },
    activeAlarmCount(state): number {
      return state.activeAlarms.size
    },
  },

  actions: {
    reset(): void {
      this.running = false
      this.values.clear()
      this.varByKey.clear()
      this.overrides.clear()
      this.activeAlarms.clear()
      this.alarmEvents = []
      this.serverStatus = 'off'
      this.serverAlarmIdByRule.clear()
      this.serverAckedAlarmIds.clear()
      this.degradedVars.clear()
    },

    pushAlarmEvent(ev: AlarmEvent): void {
      this.alarmEvents.push(ev)
      if (this.alarmEvents.length > 100) this.alarmEvents.splice(0, this.alarmEvents.length - 100)
      if (ev.type === 'active') this.activeAlarms.set(ev.id, ev)
      else this.activeAlarms.delete(ev.id)
    },

    /** M8：alarmAck 帧到达（REST ack 广播）→ D 包据此更新列表确认态 */
    markAlarmAcked(alarmId: number): void {
      this.serverAckedAlarmIds.add(alarmId)
    },

    /** M8：变量质量态登记（q!=='good'），WidgetHost 灰显依据 */
    markDegraded(variableId: string, q: DegradedQuality): void {
      this.degradedVars.set(variableId, q)
    },

    /** M8：质量恢复 good → 解除灰显标记 */
    clearDegraded(variableId: string): void {
      this.degradedVars.delete(variableId)
    },
  },
})
