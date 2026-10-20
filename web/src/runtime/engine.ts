/**
 * 运行态引擎（M3/M5 核心）：数据源启动 → 变量池 → 绑定求值（覆盖层）→ 报警判定。
 * 编辑器预览（PreviewOverlay）与分享页（ShareView）共用；编辑态不启动。
 */
import type {
  AlarmOp,
  AlarmRule,
  Binding,
  ComponentNode,
  ProjectDoc,
  ValueMapping,
  VariableDef,
} from '@/types/doc'
import { useRuntimeStore, type AlarmEvent } from './store'
import { startSource, type SourceHandle } from './sources'

export interface EngineOptions {
  /** 报警事件回调（通知/声音由宿主 UI 决定呈现方式） */
  onAlarmEvent?: (ev: AlarmEvent, rule: AlarmRule) => void
}

const HISTORY_LIMIT = 60

/** 变量级换算（G3 口径）：bitIndex 优先于 scale（协议互斥） */
function toEngineering(v: VariableDef, raw: unknown): number | boolean | string {
  let value: number | boolean | string = raw as number | boolean | string
  if (typeof raw === 'string' && raw !== '' && !Number.isNaN(Number(raw))) value = Number(raw)
  if (v.bitIndex != null && typeof value === 'number') {
    value = ((value >> v.bitIndex) & 1) === 1
  } else if (typeof value === 'number') {
    if (v.scale != null) value = value * v.scale
    if (v.offset != null) value = value + v.offset
    if (v.precision != null) value = Number(value.toFixed(v.precision))
  }
  return value
}

/** 值映射（G4）：查表键为工程值字符串化 */
function applyMapping(mapping: ValueMapping, value: number | boolean | string): string | boolean | undefined {
  const key = String(value)
  if (mapping.kind === 'enum') {
    const hit = mapping.map[key]
    if (hit === undefined) return undefined
    return hit
  }
  if (typeof value === 'number') {
    for (const band of mapping.bands) {
      const geMin = band.min === undefined || value >= band.min
      const ltMax = band.max === undefined || value < band.max
      if (geMin && ltMax) return band.value
    }
  }
  return undefined
}

function compare(op: AlarmOp, value: number, threshold: number): boolean {
  switch (op) {
    case '>': return value > threshold
    case '>=': return value >= threshold
    case '<': return value < threshold
    case '<=': return value <= threshold
    case '==': return value === threshold
    case '!=': return value !== threshold
  }
}

function formatMessage(rule: AlarmRule, v: VariableDef, value: number | boolean | string): string {
  return rule.message
    .replace(/\{key\}/g, v.key)
    .replace(/\{label\}/g, v.label)
    .replace(/\{value\}/g, String(value))
    .replace(/\{threshold\}/g, String(rule.threshold))
}

export class RuntimeEngine {
  private runtime = useRuntimeStore()
  private handles: SourceHandle[] = []
  private variables = new Map<string, VariableDef>()
  /** varId → 绑定列表（组件树扁平，含组内节点） */
  private bindingsByVar = new Map<string, { nodeId: string; binding: Binding }[]>()
  private rules: AlarmRule[] = []
  /** varId → 近 HISTORY_LIMIT 个数值点（图表 props.data 绑定注入） */
  private history = new Map<string, number[]>()
  /** ruleId → 当前激活态（迟滞判定） */
  private alarmActive = new Map<string, boolean>()
  private opts: EngineOptions = {}

  start(doc: ProjectDoc, opts: EngineOptions = {}): void {
    this.stop()
    this.opts = opts
    this.runtime.reset()

    for (const v of doc.variables) this.variables.set(v.id, v)
    this.rules = doc.alarmRules.filter((r) => r.enabled)
    for (const page of doc.pages) {
      for (const node of page.components) this.indexNode(node)
    }

    // 初始默认值先行（绑定组件先有静态值，再被数据源刷新）
    for (const v of doc.variables) {
      if (v.defaultValue !== null && v.defaultValue !== undefined) {
        this.runtime.values.set(v.id, v.defaultValue)
        this.applyBindings(v.id, v.defaultValue)
      }
    }

    this.runtime.running = true
    for (const ds of doc.datasources) {
      this.handles.push(startSource(ds, doc.variables, (variable, raw) => this.onRaw(variable, raw)))
    }
  }

  stop(): void {
    this.handles.forEach((h) => h.stop())
    this.handles = []
    this.variables.clear()
    this.bindingsByVar.clear()
    this.rules = []
    this.history.clear()
    this.alarmActive.clear()
    this.runtime.reset()
  }

  private indexNode(node: ComponentNode): void {
    for (const b of node.bindings ?? []) {
      const list = this.bindingsByVar.get(b.variableId) ?? []
      list.push({ nodeId: node.id, binding: b })
      this.bindingsByVar.set(b.variableId, list)
    }
    for (const child of node.children ?? []) this.indexNode(child)
  }

  private onRaw(variable: VariableDef, raw: unknown): void {
    const value = toEngineering(variable, raw)
    this.runtime.values.set(variable.id, value)

    if (typeof value === 'number') {
      const h = this.history.get(variable.id) ?? []
      h.push(value)
      if (h.length > HISTORY_LIMIT) h.splice(0, h.length - HISTORY_LIMIT)
      this.history.set(variable.id, h)
    }

    this.applyBindings(variable.id, value)
    this.evalAlarms(variable, value)
  }

  /** 绑定求值 → 覆盖层（value/color/visibility） */
  private applyBindings(varId: string, value: number | boolean | string): void {
    const list = this.bindingsByVar.get(varId)
    if (!list) return
    for (const { nodeId, binding } of list) {
      const ov = this.runtime.overrides.get(nodeId) ?? {}
      let display: number | boolean | string | number[] = value

      if (binding.mode === 'value' && binding.prop === 'props.data') {
        // 图表类：注入历史序列（等价于该变量近 60 点）
        display = this.history.get(varId) ?? (typeof value === 'number' ? [value] : [])
      } else if (binding.mapping) {
        const mapped = applyMapping(binding.mapping, value)
        if (mapped === undefined) continue
        display = mapped
      }

      if (binding.prop === 'visible') {
        ov.visible = display === true || display === 'true' || display === 1
      } else if (binding.prop === 'opacity') {
        ov.props = ov.props
        // opacity 目标在节点层，借 overrides.style 通道（PreviewNode 消费）
        ov.style = { ...(ov.style ?? {}), opacity: Number(display) }
      } else {
        const [kind, ...rest] = binding.prop.split('.')
        const key = rest.join('.')
        if (kind === 'props') ov.props = { ...(ov.props ?? {}), [key]: display }
        else if (kind === 'style') ov.style = { ...(ov.style ?? {}), [key]: display }
      }
      this.runtime.overrides.set(nodeId, ov)
    }
  }

  /** 报警判定：迟滞（hysteresis 内不反复翻转）+ 触发/恢复事件 */
  private evalAlarms(variable: VariableDef, value: number | boolean | string): void {
    for (const rule of this.rules) {
      if (rule.variableId !== variable.id) continue
      if (typeof value !== 'number') continue

      const active = this.alarmActive.get(rule.id) ?? false
      const hys = rule.hysteresis ?? 0
      let nowActive: boolean
      if (active) {
        // 已激活：越过 threshold±hys 反向区间才恢复
        const recoverThreshold = ['>', '>='].includes(rule.op) ? rule.threshold - hys : rule.threshold + hys
        nowActive = compare(rule.op, value, recoverThreshold)
      } else {
        nowActive = compare(rule.op, value, rule.threshold)
      }
      if (nowActive === active) continue
      this.alarmActive.set(rule.id, nowActive)

      const ev: AlarmEvent = {
        id: rule.id,
        type: nowActive ? 'active' : 'recovered',
        level: rule.level,
        message: nowActive
          ? formatMessage(rule, variable, value)
          : `${rule.name} 已恢复（${variable.label}=${value}）`,
        value,
        at: Date.now(),
      }
      this.runtime.pushAlarmEvent(ev)
      this.opts.onAlarmEvent?.(ev, rule)
    }
  }
}
