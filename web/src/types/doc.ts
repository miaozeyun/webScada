/**
 * 工程 JSON 契约（TS 镜像）——与服务端 app/schemas/doc.py 同构。
 * 契约权威版：docs/design/02-工程JSON数据结构.md；改动必须双侧同步。
 */

// ============ 全局配置 ============

export type AdaptiveMode = 'fixed' | 'fit-width' | 'fit-height' | 'fit-contain' | 'stretch'

export interface DesignSize {
  width: number
  height: number
}

export interface LevelColors {
  info: string
  warn: string
  critical: string
}

/** 报警声音/级别设置（G14：存 doc.settings.alarm，随工程 doc 保存） */
export interface AlarmSettings {
  levelColors: LevelColors
  soundEnabled: boolean
  /** 同一规则提示音节流秒数，默认 60 */
  soundThrottleSec: number
}

export interface ProjectSettings {
  designSize: DesignSize
  adaptive: AdaptiveMode
  theme: 'blue-dark' | 'blue-light'
  primaryColor: string
  alarm: AlarmSettings
}

export interface ProjectMeta {
  /** UUID，服务端生成；导入时由服务端重写（G9） */
  id: string
  name: string
  description?: string | null
  author?: string | null
  createdAt: string
  updatedAt: string
  /** 首页缩略图（JPEG dataURL，编辑器保存前截图写入；出口脱敏/导出时剔除，台账卡片视图专用） */
  thumbnail?: string | null
}

// ============ 数据源（四类） ============

export interface MqttConfig {
  brokerUrl: string
  username?: string | null
  /** 敏感：GET/导出/分享快照中恒为空串（G6）；库内 Fernet 加密 */
  password?: string | null
  topics: string[]
  qos?: 0 | 1
  /** 反控写入 QoS（写 topic 取变量 writeAddress，缺省回落 address） */
  writeQos?: 0 | 1
  cleanSession?: boolean
  reconnectMinMs?: number
  reconnectMaxMs?: number
  staleTimeoutMs?: number | null
  tsPath?: string | null
}

export interface WebsocketConfig {
  url: string
  headers?: Record<string, string> | null
  subscribeFrame?: string | null
  heartbeatSec?: number | null
  reconnectMinMs?: number
  reconnectMaxMs?: number
  staleTimeoutMs?: number | null
  tsPath?: string | null
  /** 反控写入帧模板，占位 {key} {value}；缺省 {"key":value} */
  writeFrameTemplate?: string | null
}

export interface RestConfig {
  url: string
  method?: 'GET' | 'POST'
  /** 轮询间隔下限 500ms */
  intervalMs: number
  headers?: Record<string, string> | null
  body?: string | null
  timeoutMs?: number
  failureBackoffMs?: number | null
  staleTimeoutMs?: number | null
  tsPath?: string | null
  /** 反控写入端点（与轮询 url 分离）；无则该数据源不可写 */
  writeUrl?: string | null
  writeMethod?: 'POST' | 'PUT' | null
  /** 写入请求体模板，占位 {key} {value}；缺省 {"key":value} */
  writeBodyTemplate?: string | null
}

export interface MockConfig {
  defaultIntervalMs?: number
}

/** Modbus TCP（M8 阶段 1 后半）；变量 address 用 Modbus 惯用区位：4xxxx 保持寄存器/3xxxx 输入寄存器/0xxxx 线圈/1xxxx 离散输入 */
export interface ModbusConfig {
  host: string
  port?: number
  unitId?: number
  intervalMs?: number
  timeoutMs?: number
  staleTimeoutMs?: number | null
}

interface DsBase {
  id: string
  name: string
  /** 启用开关（G13：mock 类型的启停即此字段） */
  enabled?: boolean
}

export interface MqttDataSource extends DsBase { type: 'mqtt'; config: MqttConfig }
export interface WebsocketDataSource extends DsBase { type: 'websocket'; config: WebsocketConfig }
export interface RestDataSource extends DsBase { type: 'rest'; config: RestConfig }
export interface MockDataSource extends DsBase { type: 'mock'; config?: MockConfig }
export interface ModbusDataSource extends DsBase { type: 'modbus'; config: ModbusConfig }

export type DataSource = MqttDataSource | WebsocketDataSource | RestDataSource | MockDataSource | ModbusDataSource

// ============ 变量字典 ============

export type VariableType = 'number' | 'boolean' | 'string'

export interface VarRange { min: number; max: number }

export type MockSpec =
  | { kind: 'sine'; min: number; max: number; periodMs: number }
  | { kind: 'ramp'; min: number; max: number; periodMs: number }
  | { kind: 'random'; min: number; max: number; intervalMs: number }
  | { kind: 'square'; onValue: number; offValue: number; periodMs: number; duty?: number }
  /** 保持型：不周期推送，仅初始 defaultValue；写入回环后保持（反控演示/受控开关量） */
  | { kind: 'hold' }

/** 虚拟变量哨兵：expr 非空时 datasourceId 固定为此值，不入 datasources 数组 */
export const VIRTUAL_DATASOURCE_ID = 'virtual'

export interface VariableDef {
  id: string
  /** 工程内唯一、创建后不可改 */
  key: string
  label: string
  type: VariableType
  unit?: string | null
  range?: VarRange | null
  defaultValue?: number | boolean | string | null
  datasourceId: string
  /** 取数地址：mqtt=topic；websocket/rest=定位键；mock 忽略 */
  address?: string
  jsonPath?: string | null
  // ---- 反控（M7）：写通道经浏览器直连数据源，writable 变量才可写 ----
  writable?: boolean
  /** mqtt 写 topic（缺省回落 address）；ws/rest 写配置在数据源级 */
  writeAddress?: string | null
  // ---- 虚拟变量（M7）：表达式引用其它变量 key，引擎求值级联刷新 ----
  expr?: string | null
  // ---- 变量级换算（G3：服务端入池前一次执行；与 bitIndex 互斥） ----
  scale?: number | null
  offset?: number | null
  precision?: number | null
  /** 位提取：raw=(ToInt(raw)>>bitIndex)&1 */
  bitIndex?: number | null
  mock?: MockSpec | null
  description?: string | null
}

// ============ 页面与组件 ============

export type WidgetType =
  | 'text' | 'image' | 'rect' | 'circle' | 'line' | 'table' | 'button' | 'carousel'
  | 'flip-counter' | 'line-chart' | 'bar-chart' | 'pie-chart' | 'gauge' | 'progress' | 'trend-chart'
  | 'status-light' | 'motor' | 'pump' | 'valve' | 'pipe'
  // ---- M7 新增（对齐业界主流组态）----
  | 'var-display' | 'state-text' | 'switch' | 'multi-switch' | 'input-cmd'
  | 'tank' | 'flow-bar' | 'image-switch' | 'web-frame' | 'video' | 'weather' | 'clock' | 'history-chart'
  | 'breaker' | 'isolator' | 'ground' | 'ct' | 'pt' | 'transformer'
  // ---- M9 批次1 新增（对标业界主流组态「图元图库」）----
  | 'symbol'
  // ---- M9 批次3 新增（画面装饰）----
  | 'title-bar'
  | 'group'

export interface PageBackground { color: string; image?: string | null }

export interface ScreenCfg {
  designWidth: number
  designHeight: number
  mode: AdaptiveMode
  /** 运行态锁定画面：禁止滚动/拖拽（业界主流组态「不让实时画面移动」） */
  lockPan?: boolean
  /** M9 批次5：画面方向强制（auto=跟随时口；landscape/portrait 在视口方向不符时运行态自动旋转 90°） */
  orientation?: 'auto' | 'landscape' | 'portrait'
}

export interface ComponentStyle {
  fill?: string
  stroke?: string
  strokeWidth?: number
  borderRadius?: number
  color?: string
  fontSize?: number
  fontWeight?: number
  textAlign?: 'left' | 'center' | 'right'
}

export interface ComponentAnimations {
  blink?: { enabled: boolean; intervalMs: number }
  flow?: { enabled: boolean; speed: number }
  rotate?: { enabled: boolean; clockwise?: boolean; periodMs: number }
  /** 轨迹运动（M7）：沿 SVG path 做位移动画（CSS offset-path） */
  move?: { enabled: boolean; path: string; periodMs: number; mode: 'loop' | 'pingpong' }
}

/** 映射（G4）：查表键为变量工程值的字符串化形式 */
export type ValueMapping =
  | { kind: 'enum'; map: Record<string, string | boolean> }
  | { kind: 'range'; bands: { min?: number; max?: number; value: string | boolean }[] }

export interface Binding {
  id: string
  /** 目标路径五类：props.* / style.* / visible / opacity / anim.*（rotateOn/rotatePeriod/flowOn/blinkOn/moveOn） */
  prop: string
  variableId: string
  mode: 'value' | 'color' | 'visibility'
  /** color 必填（422）；value/visibility 可选 */
  mapping?: ValueMapping | null
}

// ---- 事件与行为（M7，对齐业界主流组态「事件与行为」） ----

export type EventTrigger = 'click' | 'dblclick' | 'contextmenu'

export type EventActionType = 'writeVar' | 'showPopup' | 'hidePopup' | 'switchPage' | 'openUrl' | 'toggleVisible'

export interface EventActionDef {
  type: EventActionType
  /** writeVar：目标变量（须 writable） */
  variableId?: string | null
  /** writeVar：写入值（支持表达式，如 '1' / 'tank.level + 1'） */
  value?: string | null
  /** showPopup/hidePopup/toggleVisible：目标组件 id */
  targetId?: string | null
  /** switchPage：目标页面 id */
  pageId?: string | null
  /** openUrl：新窗口地址 */
  url?: string | null
}

export interface NodeEventDef {
  id: string
  trigger: EventTrigger
  actions: EventActionDef[]
}

/** 鼠标悬停信息（M7）：模板占位 {变量key} 实时替换 */
export interface TooltipCfg {
  enabled: boolean
  template: string
}

/** 弹框容器（M7）：仅 group；运行态默认隐藏，事件/条件控制显隐 */
export interface PopupCfg {
  style: 'dialog' | 'menu'
  title?: string | null
  /** 条件弹框：表达式满足（真值）时自动显示；与事件动作独立生效 */
  triggerExpr?: string | null
}

export interface ComponentNode {
  id: string
  name: string
  type: WidgetType
  x: number
  y: number
  w: number
  h: number
  rotate?: number
  /** 图层序，大者在上 */
  z: number
  visible?: boolean
  locked?: boolean
  opacity?: number
  props: Record<string, unknown>
  style?: ComponentStyle | null
  animations?: ComponentAnimations | null
  bindings: Binding[]
  /** 事件与行为（M7）：运行态触发；编辑态不响应 */
  events?: NodeEventDef[] | null
  /** 悬停信息（M7） */
  tooltip?: TooltipCfg | null
  /** 弹框容器（M7）：仅 group */
  popup?: PopupCfg | null
  /** 仅 type='group'；组内坐标为相对组原点 */
  children?: ComponentNode[] | null
}

export interface Page {
  id: string
  name: string
  order: number
  background: PageBackground
  screen: ScreenCfg
  components: ComponentNode[]
}

// ============ 报警规则 ============

export type AlarmOp = '>' | '>=' | '<' | '<=' | '==' | '!='
export type AlarmLevel = 'info' | 'warn' | 'critical'

export interface AlarmRule {
  id: string
  name: string
  variableId: string
  op: AlarmOp
  /** 口径=工程值（与界面显示一致，G3） */
  threshold: number
  level: AlarmLevel
  /** 占位符 {key} {label} {value} {threshold} */
  message: string
  enabled: boolean
  hysteresis?: number | null
  durationMs?: number | null
  sound?: boolean | null
}

// ============ 顶层 ============

// ---- 我的图元（M9 批次2）：选中组件/组存为可复用资产，坐标归一化到包围盒原点 ----

export interface MySymbolDef {
  id: string
  label: string
  /** 展平后的节点集（group 已拆平为绝对坐标；插入时整体 id 重映射） */
  nodes: ComponentNode[]
  createdAt: string
}

export interface DocAssets {
  mySymbols: MySymbolDef[]
}

export interface ProjectDoc {
  schemaVersion: number
  project: ProjectMeta
  settings: ProjectSettings
  datasources: DataSource[]
  variables: VariableDef[]
  pages: Page[]
  alarmRules: AlarmRule[]
  /** M9 批次2：用户资产库（可选字段，旧 doc 缺省视为空；schemaVersion 不变） */
  assets?: DocAssets | null
}

// ============ M8 服务端运行态：WS 帧类型（增量追加，契约 docs/design/03 §3.4 + 实施契约 §5） ============

/** 值质量位：good=有效；stale=超 staleTimeoutMs 未见新帧（值保留）；bad=缺帧/解析失败（v=null） */
export type ValueQuality = 'good' | 'stale' | 'bad'

/** 值条目：v 为服务端换算后的工程值（bad 时 null）；t 为 epoch 毫秒 */
export interface WsValueEntry {
  v: number | boolean | string | null
  q: ValueQuality
  t: number
}

/** S→C snapshot 内嵌的活动报警（结构同 REST 报警列表条目，时间戳为 epoch 毫秒） */
export interface WsActiveAlarm {
  id: number
  ruleId: string
  variableKey: string
  level: AlarmLevel
  message: string
  value: string | null
  status: 'triggered' | 'acked' | 'cleared'
  triggeredAt: number
  ackedAt?: number | null
  ackedBy?: string | null
  ackedNote?: string | null
  clearedAt?: number | null
}

export interface WsSnapshotFrame {
  type: 'snapshot'
  ts: number
  /** 键为变量 key；值均为工程值（服务端换算后） */
  data: Record<string, WsValueEntry>
  activeAlarms: WsActiveAlarm[]
  totalActive: number
  /** 超过 200 条按 critical>warn>info 截断时为 true */
  truncated: boolean
}

export interface WsValuesFrame {
  type: 'values'
  data: Record<string, WsValueEntry>
}

export interface WsAlarmFrame {
  type: 'alarm'
  alarm: WsActiveAlarm
}

export interface WsAlarmClearFrame {
  type: 'alarmClear'
  alarmId: number
  recoveredAt: number
}

export interface WsAlarmAckFrame {
  type: 'alarmAck'
  alarmId: number
  ackedAt: number
  ackedBy: string
}

export interface WsPingFrame { type: 'ping' }
export interface WsPongFrame { type: 'pong' }
export interface WsReloadFrame { type: 'reload' }

export type WsWriteErrorCode =
  | 'NOT_WRITABLE'
  | 'READ_ONLY'
  | 'FORBIDDEN'
  | 'VARIABLE_NOT_FOUND'
  | 'WRITE_FAILED'

export interface WsWriteFrame {
  type: 'write'
  reqId: string
  variableKey: string
  value: number | boolean | string
}

export interface WsWriteAckFrame {
  type: 'writeAck'
  reqId: string
  ok: boolean
  code?: WsWriteErrorCode
  message?: string
}

export type WsErrorCode =
  | 'TOKEN_EXPIRED'
  | 'PROJECT_REMOVED'
  | 'SHARE_REVOKED'
  | 'SHARE_EXPIRED'
  | 'RATE_LIMITED'
  | 'PROJECT_MISMATCH'
  | 'INTERNAL_ERROR'

export interface WsErrorFrame {
  type: 'error'
  code: WsErrorCode
  message?: string
}

/** S→C 全部帧的判别联合（客户端忽略未知 type） */
export type WsServerFrame =
  | WsSnapshotFrame
  | WsValuesFrame
  | WsAlarmFrame
  | WsAlarmClearFrame
  | WsAlarmAckFrame
  | WsPingFrame
  | WsReloadFrame
  | WsErrorFrame
  | WsWriteAckFrame
