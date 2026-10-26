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
  WsActiveAlarm,
  WsValueEntry,
} from '@/types/doc'
import { VIRTUAL_DATASOURCE_ID } from '@/types/doc'
import { useRuntimeStore, type AlarmEvent } from './store'
import { startServerChannel, startSource, type ServerChannelHandle, type SourceHandle } from './sources'
import { evalExpr, exprIdents } from '@/utils/expr'
import { sample as histSample, startPersist, stopPersist } from './history'

export interface ServerRuntimeOptions {
  projectId: string
  token: string
  page?: string
}

export interface EngineOptions {
  /** 报警事件回调（通知/声音由宿主 UI 决定呈现方式）；server 模式下规则可能不在本地 rules 集 */
  onAlarmEvent?: (ev: AlarmEvent, rule?: AlarmRule) => void
  /** M7：写通道开关（编辑器预览 true / 分享页 false，反控权限收敛到唯一入口） */
  writable?: boolean
  /** M8：server 模式——值流/报警/写通道由服务端 WS 驱动；不启动浏览器直连数据源 */
  server?: ServerRuntimeOptions
  /** M8：分享快照被刷新（reload 帧）→ 宿主重新拉取 doc */
  onServerReload?: () => void
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

/** M9 批次4：内置秒节拍变量（与服务端 hub.TICK_KEY 同名同构）。
 *  虚拟变量 expr / 条件弹框表达式引用 _tick 即获得每秒重算（定时脚本等价物，无脚本引擎风险）；
 *  server 模式值由服务端 tick_all 推送；本地（编辑器直连）模式由引擎定时器推进。 */
const TICK_VAR: VariableDef = {
  id: '_tick',
  key: '_tick',
  label: '秒节拍（内置）',
  type: 'number',
  unit: null,
  defaultValue: null,
  datasourceId: 'virtual',
  writable: false,
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

  // ---- M8：server 模式（值流/报警/写通道权威在服务端） ----
  private serverMode = false
  private serverChannel: ServerChannelHandle | null = null
  /** 服务端报警 id（DB 自增） → 本地事件（alarmClear 按 id 关联回显消息） */
  private serverAlarms = new Map<number, AlarmEvent>()

  // ---- M7：虚拟变量依赖图（varId → 依赖它的虚拟变量 id 列表，传递闭包按层展开） ----
  private virtualById = new Map<string, VariableDef>()
  private dependents = new Map<string, string[]>()
  private exprWarned = new Set<string>()

  // ---- M7：条件弹框 / 写通道 ----
  private popupTriggers: PopupTrigger[] = []
  private handleByDs = new Map<string, SourceHandle>()
  private dsById = new Map<string, ProjectDoc['datasources'][number]>()

  // ---- M9 批次4：内置 _tick 本地推进定时器（server 模式不用，值走 WS 帧） ----
  private tickTimer: number | null = null

  start(doc: ProjectDoc, opts: EngineOptions = {}, seedValues?: Map<string, string | number | boolean>): void {
    this.stop()
    this.opts = opts
    this.runtime.reset()

    for (const v of doc.variables) {
      this.variables.set(v.id, v)
      this.runtime.varByKey.set(v.key, v.id)
      if (v.expr) this.virtualById.set(v.id, v)
      // 03 §3.8 reload：已收到的变量值缓存保留（宿主替换 doc 重启引擎时透传，画面不闪空白）
      const seed = seedValues?.get(v.id)
      if (seed !== undefined) {
        this.runtime.values.set(v.id, seed)
      }
    }
    // 内置 _tick（须先于 buildDependents 注册：expr 引用 _tick 的依赖图才能建立）
    this.variables.set(TICK_VAR.id, TICK_VAR)
    this.runtime.varByKey.set(TICK_VAR.key, TICK_VAR.id)
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
    if (opts.server) {
      // M8 server 模式：浏览器直连数据源停用，值池由 WS 帧驱动
      this.serverMode = true
      this.serverChannel = startServerChannel({
        projectId: opts.server.projectId,
        token: opts.server.token,
        page: opts.server.page,
        onEntry: (key, entry) => this.applyServerEntry(key, entry),
        onAlarm: (alarm) => this.onServerAlarm(alarm),
        onAlarmClear: (alarmId, recoveredAt) => this.onServerAlarmClear(alarmId, recoveredAt),
        onAlarmAck: (alarmId) => this.runtime.markAlarmAcked(alarmId),
        onSnapshotAlarms: (alarms, truncated) => this.onServerAlarmSync(alarms, truncated),
        onError: (code, message) => {
          console.warn(`[webScada] 运行态服务端连接错误：${code} ${message}`)
          this.runtime.serverStatus = 'error'
        },
        onReload: () => this.opts.onServerReload?.(),
        onStatus: (status) => { this.runtime.serverStatus = status },
      })
      startPersist()
      return
    }
    // 本地模式：_tick 引擎内推进（每秒 setValue → 虚拟变量级联/条件弹框重评）
    const tick = (): void => this.setValue(TICK_VAR, Math.floor(Date.now() / 1000))
    tick()
    this.tickTimer = window.setInterval(tick, 1000)
    for (const ds of doc.datasources) {
      const handle = startSource(ds, doc.variables, (variable, raw) => this.onRaw(variable, raw))
      this.handles.push(handle)
      this.handleByDs.set(ds.id, handle)
    }
    startPersist()
  }

  /** 当前值池快照（reload 重启时作为 seed 透传，03 §3.8 已收值保留） */
  snapshotValues(): Map<string, string | number | boolean> {
    return new Map(this.runtime.values)
  }

  stop(): void {
    if (this.tickTimer !== null) {
      clearInterval(this.tickTimer)
      this.tickTimer = null
    }
    stopPersist()
    this.serverChannel?.stop()
    this.serverChannel = null
    this.serverMode = false
    this.serverAlarms.clear()
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

  /** M8 server 模式：WS 值条目入池（值已是服务端换算后工程值，键=变量 key）。
   *  未知 key 忽略（03 §3.4：保存后变量集变化，客户端等重连 snapshot 对齐）；
   *  质量位消费（03 §2.10 q∈good|stale|bad）：非 good 登记灰显态（UI 叠灰标记数据不可信），
   *  stale 值保留、bad 保留上一显示值（不闪空，灰显表达不可信）；恢复 good 才更新值并解除灰显。 */
  private applyServerEntry(key: string, entry: WsValueEntry): void {
    this.runtime.markValueArrived()
    const varId = this.runtime.varByKey.get(key)
    if (!varId) return
    if (entry.q !== 'good') {
      this.runtime.markDegraded(varId, entry.q)
      return
    }
    if (entry.v === null || entry.v === undefined) return
    const variable = this.variables.get(varId)
    if (!variable) return
    this.runtime.clearDegraded(varId)
    this.setValue(variable, entry.v as number | boolean | string)
  }

  /** 服务端报警帧 → 本地事件流（通知/声音/列表由宿主 UI 消费）。
   *  backfill=true（snapshot 存量回填）：仅回填横幅/徽标/面板状态，不触发通知与声音
   *  （刷新/重连场景存量报警不重复打扰）。 */
  private onServerAlarm(alarm: WsActiveAlarm, backfill = false): void {
    if (alarm.status === 'cleared') return // 兜底：已恢复条目不入活动集
    // 帧字段透传：alarmId（DB id，横幅快捷 ack）/variableKey（S2 反查绑定变量）/
    // status（消费方 isAlarmActive 服务端状态机口径），仅 ruleId 会双失效（契约 §4.1）
    const ev: AlarmEvent = {
      id: alarm.ruleId,
      type: 'active',
      level: alarm.level,
      message: alarm.message,
      value: alarm.value ?? '',
      at: alarm.triggeredAt,
      variableKey: alarm.variableKey,
      ruleId: alarm.ruleId,
      alarmId: alarm.id,
      status: alarm.status,
    }
    if (backfill && this.serverAlarms.has(alarm.id)) {
      // 重连 snapshot 回填：已知报警仅刷新快照（消息/级别/确认态可能变化），不重复进事件流
      const merged: AlarmEvent = { ...this.serverAlarms.get(alarm.id)!, ...ev }
      this.serverAlarms.set(alarm.id, merged)
      this.runtime.activeAlarms.set(merged.id, merged)
      if (alarm.status === 'acked') this.runtime.markAlarmAcked(alarm.id)
      return
    }
    this.serverAlarms.set(alarm.id, ev)
    this.runtime.pushAlarmEvent(ev)
    this.runtime.serverAlarmIdByRule.set(alarm.ruleId, alarm.id)
    if (alarm.status === 'acked') this.runtime.markAlarmAcked(alarm.id)
    const rule = this.rules.find((r) => r.id === alarm.ruleId)
    if (!backfill) this.opts.onAlarmEvent?.(ev, rule)
  }

  /** snapshot 存量活动报警回填（刷新/重连后横幅、徽标、面板不丢，其 alarmClear 不再被丢弃）：
   *  逐条走 onServerAlarm 回填状态，再按 snapshot 报警 id 集合对已知报警做差集清理；
   *  服务端截断（>200 条）时跳过差集，防误清仍在活动的报警 */
  private onServerAlarmSync(alarms: WsActiveAlarm[], truncated: boolean): void {
    for (const alarm of alarms) this.onServerAlarm(alarm, true)
    if (truncated) return
    for (const alarmId of [...this.serverAlarms.keys()]) {
      if (alarms.some((a) => a.id === alarmId)) continue
      this.onServerAlarmClear(alarmId, Date.now())
    }
  }

  private onServerAlarmClear(alarmId: number, recoveredAt: number): void {
    const ev = this.serverAlarms.get(alarmId)
    if (!ev) return
    this.serverAlarms.delete(alarmId)
    // status 一并置 cleared：透传字段不残留激活态标记（消费方 isAlarmActive 服务端口径判定安全）
    const cleared: AlarmEvent = {
      ...ev,
      type: 'recovered',
      status: 'cleared',
      at: recoveredAt,
      message: `${ev.message}（已恢复）`,
    }
    this.runtime.pushAlarmEvent(cleared)
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
    if (this.serverMode) {
      // 服务端权威：报警判定（rules_engine）与虚拟变量求值（hub 拓扑）均在服务端完成，随帧下发
      this.evalPopupTriggers(variable.id)
      return
    }
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
   * 反控写中心（M7 唯一入口）：校验 writable → 分发。
   * M8 server 模式：统一走服务端 write/writeAck 通道（mock 服务端回环、mqtt/rest/ws 服务端分发）；
   * 浏览器直连模式（编辑器连接测试遗留）：mock 本地回环，mqtt publish / rest POST / ws send。
   */
  async write(variableId: string, value: number | boolean | string): Promise<void> {
    if (!this.opts.writable) throw new Error('当前视图为只读（分享页不允许反控）')
    const v = this.variables.get(variableId)
    if (!v) throw new Error('变量不存在')
    if (v.expr) throw new Error(`虚拟变量 ${v.key} 不可写（由表达式驱动）`)
    if (!v.writable) throw new Error(`变量 ${v.key} 未开启可写（writable）`)

    if (this.serverMode) {
      // 服务端二次校验（角色/可写/存在性），失败原因经 writeAck code 回传
      if (!this.serverChannel) throw new Error('服务端连接未就绪')
      await this.serverChannel.write(v.key, value)
      return
    }

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

  /**
   * 仿真注入（工程联调仿真台专用，2026-10-26）：绕过 writable/反控校验，按工程值直接入池。
   * setValue 统一收口 → 绑定求值、报警判定、历史采样、虚拟变量级联、条件弹框全部照常。
   * 仅 local 模式生效：server 模式下值流权威在服务端，本地注入会造成双源冲突。
   * @returns 是否成功注入（虚拟变量/未知变量/server 模式返回 false）
   */
  injectValue(variableId: string, value: number | boolean | string): boolean {
    if (this.serverMode) return false
    const v = this.variables.get(variableId)
    if (!v || v.expr) return false
    this.setValue(v, value)
    return true
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
        // 与 M8 服务端帧同构：WidgetHost S2 报警态按 variableKey 反查绑定变量。
        // 缺这个字段时，仿真台/分享页（editor.doc 不是当前工程）无法给组件叠报警色。
        variableKey: variable.key,
        ruleId: rule.id,
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
