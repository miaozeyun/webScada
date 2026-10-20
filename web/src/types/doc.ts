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
}

// ============ 数据源（四类） ============

export interface MqttConfig {
  brokerUrl: string
  username?: string | null
  /** 敏感：GET/导出/分享快照中恒为空串（G6）；库内 Fernet 加密 */
  password?: string | null
  topics: string[]
  qos?: 0 | 1
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
}

export interface MockConfig {
  defaultIntervalMs?: number
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

export type DataSource = MqttDataSource | WebsocketDataSource | RestDataSource | MockDataSource

// ============ 变量字典 ============

export type VariableType = 'number' | 'boolean' | 'string'

export interface VarRange { min: number; max: number }

export type MockSpec =
  | { kind: 'sine'; min: number; max: number; periodMs: number }
  | { kind: 'ramp'; min: number; max: number; periodMs: number }
  | { kind: 'random'; min: number; max: number; intervalMs: number }
  | { kind: 'square'; onValue: number; offValue: number; periodMs: number; duty?: number }

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
  | 'text' | 'image' | 'table' | 'button' | 'carousel'
  | 'flip-counter' | 'line-chart' | 'bar-chart' | 'pie-chart' | 'gauge' | 'progress' | 'trend-chart'
  | 'status-light' | 'motor' | 'pump' | 'valve' | 'pipe'
  | 'group'

export interface PageBackground { color: string; image?: string | null }

export interface ScreenCfg {
  designWidth: number
  designHeight: number
  mode: AdaptiveMode
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
}

/** 映射（G4）：查表键为变量工程值的字符串化形式 */
export type ValueMapping =
  | { kind: 'enum'; map: Record<string, string | boolean> }
  | { kind: 'range'; bands: { min?: number; max?: number; value: string | boolean }[] }

export interface Binding {
  id: string
  /** 目标路径四类：props.* / style.* / visible / opacity */
  prop: string
  variableId: string
  mode: 'value' | 'color' | 'visibility'
  /** color 必填（422）；value/visibility 可选 */
  mapping?: ValueMapping | null
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

export interface ProjectDoc {
  schemaVersion: number
  project: ProjectMeta
  settings: ProjectSettings
  datasources: DataSource[]
  variables: VariableDef[]
  pages: Page[]
  alarmRules: AlarmRule[]
}
