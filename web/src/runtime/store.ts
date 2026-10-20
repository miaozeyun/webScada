/**
 * 运行态 store（M3/M5）：变量值池 + 绑定覆盖层 + 报警状态。
 * 关键约束：运行值绝不写回 editor.doc（不触发 dirty/保存），全部走 overrides
 * 由 WidgetHost（K12 唯一装配点）与 PreviewNode 在渲染时合并。
 */
import { defineStore } from 'pinia'
import type { AlarmRule } from '@/types/doc'

export interface NodeOverride {
  props?: Record<string, unknown>
  style?: Record<string, unknown>
  visible?: boolean
}

export interface AlarmEvent {
  id: string
  type: 'active' | 'recovered'
  level: AlarmRule['level']
  message: string
  value: number | boolean | string
  at: number
}

export const useRuntimeStore = defineStore('runtime', {
  state: () => ({
    running: false,
    /** 变量运行值 variableId → 工程值（已过变量级换算） */
    values: new Map<string, number | boolean | string>(),
    /** 绑定求值结果按 nodeId 聚合（渲染覆盖层） */
    overrides: new Map<string, NodeOverride>(),
    /** 激活中的报警 ruleId → 事件信息 */
    activeAlarms: new Map<string, AlarmEvent>(),
    /** 最近报警事件流（上限 100，供横幅/通知消费） */
    alarmEvents: [] as AlarmEvent[],
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
      this.overrides.clear()
      this.activeAlarms.clear()
      this.alarmEvents = []
    },

    pushAlarmEvent(ev: AlarmEvent): void {
      this.alarmEvents.push(ev)
      if (this.alarmEvents.length > 100) this.alarmEvents.splice(0, this.alarmEvents.length - 100)
      if (ev.type === 'active') this.activeAlarms.set(ev.id, ev)
      else this.activeAlarms.delete(ev.id)
    },
  },
})
