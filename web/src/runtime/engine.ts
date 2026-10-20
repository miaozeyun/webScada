/**
 * 运行态引擎（M3/M5 核心，M7 扩展）：数据源启动 → 变量池 → 绑定求值（覆盖层）→ 报警判定；
 * 新增：虚拟变量级联求值、反控写中心、条件弹框、动效绑定通道、历史采样。
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
import { VIRTUAL_DATASOURCE_ID } from '@/types/doc'
import { useRuntimeStore, type AlarmEvent } from './store'
import { startSource, type SourceHandle } from './sources'
import { evalExpr, exprIdents } from '@/utils/expr'
import { sample as histSample, startPersist, stopPersist } from './history'

export interface EngineOptions {
  /** 报警事件回调（通知/声音由宿主 UI 决定呈现方式） */
  onAlarmEvent?: (ev: AlarmEvent, rule: AlarmRule) => void
  /** M7：写通道开关（编辑器预览 true / 分享页 false，反控权限收敛到唯一入口） */
  writable?: boolean
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

/** 展示值：数值按变量 precision 取整（缺省 2 位），避免报警消息出现长浮点 */
function fmtNum(n: number, precision?: number | null): string {
  const p = precision ?? 2
  return Number.isFinite(n) ? n.toFixed(p) : String(n)
}

function fmtValue(v: VariableDef, value: number | boolean | string): string {
  if (typeof value === 'number') return fmtNum(value, v.precision)
  return String(value)
}

function formatMessage(rule: AlarmRule, v: VariableDef, value: number | boolean | string): string {
  return rule.message
    .replace(/\{key\}/g, v.key)
    .replace(/\{label\}/g, v.label)
    .replace(/\{value\}/g, fmtValue(v, value))
    .replace(/\{threshold\}/g, fmtNum(rule.threshold, v.precision))
}

/** 条件弹框登记项：表达式求值 → 弹框组 override.visible */
interface PopupTrigger {
  nodeId: string
  expr: string
  /** 依赖的变量 id 列表（未命中变量的标识符被忽略） */
  depVarIds: string[]
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

  // ---- M7：虚拟变量依赖图（varId → 依赖它的虚拟变量 id 列表，传递闭包按层展开） ----
  private virtualById = new Map<string, VariableDef>()
  private dependents = new Map<string, string[]>()
  private exprWarned = new Set<string>()

  // ---- M7：条件弹框 / 写通道 ----
  private popupTriggers: PopupTrigger[] = []
  private handleByDs = new Map<string, SourceHandle>()
  private dsById = new Map<string, ProjectDoc['datasources'][number]>()

  start(doc: ProjectDoc, opts: EngineOptions = {}): void {
    this.stop()
    this.opts = opts
    this.runtime.reset()

    for (const v of doc.variables) {
      this.variables.set(v.id, v)
      this.runtime.varByKey.set(v.key, v.id)
      if (v.expr) this.virtualById.set(v.id, v)
    }
    this.buildDependents()
    this.rules = doc.alarmRules.filter((r) => r.enabled)
    for (const ds of doc.datasources) this.dsById.set(ds.id, ds)
    for (const page of doc.pages) {
      for (const node of page.components) {
        this.indexNode(node)
        this.indexPopup(node)
      }
    }

    // 初始默认值先行（绑定组件先有静态值，再被数据源刷新）
    for (const v of doc.variables) {
      if (v.defaultValue !== null && v.defaultValue !== undefined) {
        this.runtime.values.set(v.id, v.defaultValue)
        this.applyBindings(v.id, v.defaultValue)
      }
    }
    // 虚拟变量初值（依赖默认值先行求值）
    this.recomputeAllVirtuals()

    this.runtime.running = true
    for (const ds of doc.datasources) {
      const handle = startSource(ds, doc.variables, (variable, raw) => this.onRaw(variable, raw))
      this.handles.push(handle)
      this.handleByDs.set(ds.id, handle)
    }
    startPersist()
  }

  stop(): void {
    stopPersist()
    this.handles.forEach((h) => h.stop())
    this.handles = []
    this.handleByDs.clear()
    this.dsById.clear()
    this.variables.clear()
    this.bindingsByVar.clear()
    this.rules = []
    this.history.clear()
    this.alarmActive.clear()
    this.virtualById.clear()
    this.dependents.clear()
    this.exprWarned.clear()
    this.popupTriggers = []
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

  /** 弹框组触发表达式登记（含组内递归） */
  private indexPopup(node: ComponentNode): void {
    if (node.popup?.triggerExpr) {
      this.popupTriggers.push({
        nodeId: node.id,
        expr: node.popup.triggerExpr,
        depVarIds: this.resolveIdents(node.popup.triggerExpr, node.id),
      })
    }
    for (const child of node.children ?? []) this.indexPopup(child)
  }

  /** 表达式标识符 → 变量 id（未命中忽略）；warnedKey 用于一次性告警去重 */
  private resolveIdents(expr: string, warnedKey: string): string[] {
    const ids: string[] = []
    for (const ident of exprIdents(expr)) {
      const id = this.runtime.varByKey.get(ident)
      if (id) ids.push(id)
      else if (!this.exprWarned.has(warnedKey)) {
        this.exprWarned.add(warnedKey)
        console.warn(`[webScada] 表达式引用了未知变量：${ident}（${expr}）`)
      }
    }
    return ids
  }

  /** 虚拟变量依赖图：变量 id → 直接依赖它的虚拟变量 id 列表 */
  private buildDependents(): void {
    this.dependents.clear()
    for (const v of this.virtualById.values()) {
      for (const ident of exprIdents(v.expr ?? '')) {
        const depId = this.runtime.varByKey.get(ident)
        if (!depId) continue
        const list = this.dependents.get(depId) ?? []
        list.push(v.id)
        this.dependents.set(depId, list)
      }
    }
  }

  private onRaw(variable: VariableDef, raw: unknown): void {
    const value = toEngineering(variable, raw)
    this.setValue(variable, value)
  }

  /** 值入池：覆盖层 + 报警 + 历史 + 虚拟级联 + 弹框条件（统一收口） */
  private setValue(variable: VariableDef, value: number | boolean | string): void {
    this.runtime.values.set(variable.id, value)

    if (typeof value === 'number' || typeof value === 'boolean') {
      histSample(variable.id, value)
      const h = this.history.get(variable.id) ?? []
      h.push(typeof value === 'number' ? value : value ? 1 : 0)
      if (h.length > HISTORY_LIMIT) h.splice(0, h.length - HISTORY_LIMIT)
      this.history.set(variable.id, h)
    }

    this.applyBindings(variable.id, value)
    this.evalAlarms(variable, value)
    this.propagateVirtuals(variable.id)
    this.evalPopupTriggers(variable.id)
  }

  /** 前向传播：重算直接/传递依赖该变量的虚拟变量（虚拟变量自身继续传播） */
  private propagateVirtuals(changedId: string): void {
    const queue = [changedId]
    const visited = new Set<string>([changedId])
    while (queue.length) {
      const cur = queue.shift()!
      for (const depId of this.dependents.get(cur) ?? []) {
        if (visited.has(depId)) continue // 防环（循环引用配置）
        visited.add(depId)
        const v = this.virtualById.get(depId)
        if (!v) continue
        const value = this.evalVirtual(v)
        this.setValue(v, value)
        queue.push(depId)
      }
    }
  }

  private evalVirtual(v: VariableDef): number | boolean | string {
    try {
      const scope: Record<string, unknown> = {}
      for (const [key, id] of this.runtime.varByKey) {
        const val = this.runtime.values.get(id)
        if (val !== undefined) scope[key] = val
      }
      const result = evalExpr(v.expr ?? '0', scope)
      if (typeof result === 'number') return Number.isFinite(result) ? result : 0
      if (typeof result === 'boolean') return result
      if (typeof result === 'string') return result
      return 0
    } catch (err) {
      if (!this.exprWarned.has(v.id)) {
        this.exprWarned.add(v.id)
        console.warn(`[webScada] 虚拟变量 ${v.key} 求值失败：${(err as Error).message}`)
      }
      return (this.runtime.values.get(v.id) as number | boolean | string) ?? 0
    }
  }

  private recomputeAllVirtuals(): void {
    // 拓扑排序（Kahn）：依赖先行；环上节点按出现序求值（evalVirtual 出错回落旧值，不死循环）
    const inDeg = new Map<string, number>()
    for (const id of this.virtualById.keys()) inDeg.set(id, 0)
    for (const [, deps] of this.dependents) {
      for (const d of deps) inDeg.set(d, (inDeg.get(d) ?? 0) + 1)
    }
    const queue = [...inDeg.entries()].filter(([, d]) => d === 0).map(([id]) => id)
    const ordered: string[] = []
    while (queue.length) {
      const id = queue.shift()!
      ordered.push(id)
      for (const dep of this.dependents.get(id) ?? []) {
        const d = (inDeg.get(dep) ?? 1) - 1
        inDeg.set(dep, d)
        if (d === 0) queue.push(dep)
      }
    }
    for (const id of [...ordered, ...[...inDeg.keys()].filter((k) => !ordered.includes(k))]) {
      const v = this.virtualById.get(id)
      if (!v) continue
      this.setValue(v, this.evalVirtual(v))
    }
  }

  /** 条件弹框：任一依赖变量变化后重评（绑定按 depVarIds 索引，避免全量扫） */
  private evalPopupTriggers(changedId: string): void {
    for (const t of this.popupTriggers) {
      if (!t.depVarIds.includes(changedId)) continue
      const ov = this.runtime.overrides.get(t.nodeId) ?? {}
      this.runtime.overrides.set(t.nodeId, { ...ov, visible: this.evalTrigger(t) })
    }
  }

  private evalTrigger(t: PopupTrigger): boolean {
    try {
      const scope: Record<string, unknown> = {}
      for (const [key, id] of this.runtime.varByKey) {
        const val = this.runtime.values.get(id)
        if (val !== undefined) scope[key] = val
      }
      const r = evalExpr(t.expr, scope)
      return r === true || r === 1 || r === 'true'
    } catch (err) {
      if (!this.exprWarned.has(`popup:${t.nodeId}`)) {
        this.exprWarned.add(`popup:${t.nodeId}`)
        console.warn(`[webScada] 弹框条件求值失败：${(err as Error).message}`)
      }
      return false
    }
  }

  /**
   * 反控写中心（M7 唯一入口）：校验 writable → 按数据源类型分发；
   * mock 本地回环（setValue 全链路生效），mqtt publish / rest POST / ws send。
   */
  async write(variableId: string, value: number | boolean | string): Promise<void> {
    if (!this.opts.writable) throw new Error('当前视图为只读（分享页不允许反控）')
    const v = this.variables.get(variableId)
    if (!v) throw new Error('变量不存在')
    if (v.expr) throw new Error(`虚拟变量 ${v.key} 不可写（由表达式驱动）`)
    if (!v.writable) throw new Error(`变量 ${v.key} 未开启可写（writable）`)

    if (v.datasourceId === VIRTUAL_DATASOURCE_ID) throw new Error('虚拟变量不可写')
    const ds = this.dsById.get(v.datasourceId)
    if (!ds) throw new Error('变量所属数据源不存在')

    if (ds.type === 'mock') {
      // 本地回环：经 toEngineering 全链路（换算/绑定/报警/历史一致）
      this.onRaw(v, value)
      return
    }
    const handle = this.handleByDs.get(v.datasourceId)
    if (!handle?.write) throw new Error(`数据源类型 ${ds.type} 不支持写入，或未配置写端点`)
    await handle.write(v, value)
  }

  /** 绑定求值 → 覆盖层（value/color/visibility/anim.*） */
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
      } else if (binding.prop.startsWith('anim.')) {
        // M7 动效通道：启停按真值，周期按数值
        const key = binding.prop.slice(5) as 'rotateOn' | 'rotatePeriod' | 'flowOn' | 'blinkOn' | 'moveOn'
        ov.anim = { ...(ov.anim ?? {}) }
        if (key === 'rotatePeriod') ov.anim.rotatePeriod = Number(display) || 0
        else ov.anim[key] = display === true || display === 1 || display === 'true'
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
          : `${rule.name} 已恢复（${variable.label}=${fmtValue(variable, value)}）`,
        value,
        at: Date.now(),
      }
      this.runtime.pushAlarmEvent(ev)
      this.opts.onAlarmEvent?.(ev, rule)
    }
  }

  /** 运行态滚动序列（近 60 点，供 live 迷你趋势图/悬浮明细消费）。
   *  必须返回副本：内部数组是原地 push，直接返回引用会让调用方的 ref 赋值得不到响应式更新 */
  historyOf(variableId: string): number[] {
    return [...(this.history.get(variableId) ?? [])]
  }

  /** 事件动作用：表达式求值（writeVar 动作值支持表达式） */
  evalValueExpr(src: string): number | boolean | string {
    const scope: Record<string, unknown> = {}
    for (const [key, id] of this.runtime.varByKey) {
      const val = this.runtime.values.get(id)
      if (val !== undefined) scope[key] = val
    }
    const r = evalExpr(src, scope)
    if (typeof r === 'number' || typeof r === 'boolean' || typeof r === 'string') return r
    return 0
  }

  /** 事件动作用：弹框/显隐切换（与绑定覆盖层同通道，优先级高于绑定） */
  setNodeVisible(nodeId: string, visible: boolean): void {
    const ov = this.runtime.overrides.get(nodeId) ?? {}
    this.runtime.overrides.set(nodeId, { ...ov, visible })
  }
}
