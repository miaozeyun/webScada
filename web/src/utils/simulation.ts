/**
 * 实时数据仿真（工程联调仿真台，2026-10-26）。
 *
 * 设计约束：
 * - 只在浏览器本地构造一份「仿真副本 doc」交给 RuntimeEngine（local 模式），**绝不写回工程 doc**；
 * - 仿真值按工程值口径直接入池（K9），不经过 scale/offset/bitIndex（副本中已置空），
 *   因此页面看到的值 = 变量工程值，与服务端运行态同口径；
 * - 波形公式与 runtime/sources.ts 的 startMock / 服务端 collector.MockSource 保持同源语义，
 *   额外的「手动固定」波形仅本页面使用（不写入 doc，故不影响契约）。
 */
import type { DataSource, MockSpec, ProjectDoc, VariableDef, VariableType } from '@/types/doc'
import { VIRTUAL_DATASOURCE_ID } from '@/types/doc'
import { newId } from '@/utils/nanoid'

/** 仿真波形：五类自动波形 + 手动固定值（manual 仅仿真台内部使用） */
export type SimWaveKind = 'sine' | 'ramp' | 'random' | 'square' | 'manual'

export interface SimSignal {
  variableId: string
  key: string
  label: string
  type: VariableType
  unit: string | null
  precision: number | null
  /** 表达式虚拟变量：只读展示，由引擎级联求值 */
  virtual: boolean
  enabled: boolean
  wave: SimWaveKind
  min: number
  max: number
  /** 波形周期（秒）；random 波形忽略 */
  periodSec: number
  /** 初始相位偏移（毫秒）：按变量 id 散列，避免同参数信号完全同步重叠 */
  phaseMs: number
  /** manual 波形取值（按变量类型三选一） */
  manualNumber: number
  manualBool: boolean
  manualText: string
}

export interface SimBuildOptions {
  /** 默认启用的基础变量数量上限（大工程避免一次性驱动上百变量） */
  enabledLimit?: number
}

export interface SimBuildResult {
  /** 仿真副本 doc：单一 mock 数据源 + 全部变量改写为 hold（值由仿真台注入） */
  doc: ProjectDoc
  signals: SimSignal[]
  simDsId: string
}

const DEFAULT_ENABLED_LIMIT = 12
const MIN_PERIOD_SEC = 1

/** 数值取整：优先变量 precision，其次 3 位（避免 17 位浮点在读数里乱跳） */
function tidy(n: number, precision?: number | null): number {
  if (!Number.isFinite(n)) return 0
  const p = Math.min(Math.max(precision ?? 3, 0), 8)
  return Number(n.toFixed(p))
}

/**
 * 无 range 时按变量语义推导一个「像真的」区间（温度 20~80℃、压力 0.3~0.8MPa …），
 * 避免所有变量都挤在 0~100 同步摆动。默认值优先（围绕默认值 ±10%）。
 */
function defaultRange(v: VariableDef): [number, number] {
  const r = v.range
  if (r && Number.isFinite(r.min) && Number.isFinite(r.max) && r.max > r.min) return [r.min, r.max]
  if (typeof v.defaultValue === 'number' && Number.isFinite(v.defaultValue)) {
    const span = Math.max(Math.abs(v.defaultValue) * 0.1, 1)
    return [tidy(v.defaultValue - span), tidy(v.defaultValue + span)]
  }
  const text = `${v.label}${v.key}`
  const unit = (v.unit ?? '').trim()
  if (/温度|炉温|水温|气温|油温|temp/i.test(text) || /℃|°C/.test(unit)) {
    return /冷|冻/.test(text) ? [-15, 10] : [20, 80]
  }
  if (/液位|水位|料位|油位|level/i.test(text)) return [20, 90]
  if (/压力|压强|气压|液压|press/i.test(text)) {
    if (unit === 'MPa') return [0.3, 0.8]
    if (unit === 'kPa') return [100, 600]
    return [0, 100]
  }
  if (/流量|流速|风量|flow/i.test(text)) return [50, 300]
  if (/频率|转速|freq|speed/i.test(text)) return [45, 55]
  if (/电压|voltage/i.test(text)) return [220, 240]
  if (/电流|current/i.test(text)) return [5, 45]
  if (/功率|power|有功|无功/i.test(text)) return [50, 500]
  return [0, 100]
}

/** 按变量语义推导合理周期（温度慢、流量快、液位最慢），让仿真画面「像真的」 */
function defaultPeriodSec(v: VariableDef): number {
  const text = `${v.label}${v.key}`
  const unit = v.unit ?? ''
  if (/温度|炉温|水温|气温|油温/.test(text) || /℃|°C/.test(unit)) return 60
  if (/液位|水位|料位|油位/.test(text) || unit === '%') return 90
  if (/压力|压强|气压|液压/.test(text) || /MPa|kPa|\bPa\b/.test(unit)) return 24
  if (/流量|流速|风量/.test(text) || /m3\/h|m³\/h|L\/min|Nm3/.test(unit)) return 15
  if (/频率|转速/.test(text) || /Hz|r\/min|rpm/.test(unit)) return 12
  if (/电流|电压|功率|有功|无功/.test(text) || /\bA\b|\bV\b|kW|kWh|kVar/.test(unit)) return 10
  return 30
}

function defaultWave(v: VariableDef): SimWaveKind {
  // 开关量/文本量默认「手动固定」：避免方波来回翻转造成报警刷屏（需要时可手动切换方波）
  if (v.type !== 'number') return 'manual'
  // 计数/累计类走斜坡（单调语义），其余数值走正弦
  if (/计数|累计|总量|count|total/i.test(`${v.label}${v.key}`)) return 'ramp'
  return 'sine'
}

/** 稳定散列（FNV-1a 截断）：用于相位散列，同一变量每次进入仿真台相位一致 */
function hashSeed(text: string): number {
  let h = 2166136261
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

/** 单个变量的默认仿真配置（供 buildSimDoc 与测试复用） */
export function defaultSignal(v: VariableDef, enabled: boolean, virtual = false): SimSignal {
  const [min, max] = defaultRange(v)
  const periodSec = defaultPeriodSec(v)
  // bitIndex 变量在副本中已置空（仿真值即工程值），语义上是布尔量，信号按布尔处理
  const type: VariableType = v.bitIndex != null ? 'boolean' : v.type
  return {
    variableId: v.id,
    key: v.key,
    label: v.label,
    type,
    unit: v.unit ?? null,
    precision: v.precision ?? null,
    virtual,
    enabled,
    wave: type === 'number' ? defaultWave(v) : 'manual',
    min,
    max,
    periodSec,
    phaseMs: hashSeed(v.id + v.key) % Math.max(1, Math.round(periodSec * 1000)),
    manualNumber: typeof v.defaultValue === 'number' ? v.defaultValue : tidy((min + max) / 2),
    manualBool: v.defaultValue === true,
    manualText: typeof v.defaultValue === 'string' ? v.defaultValue : '',
  }
}

/**
 * 构造仿真副本 doc：
 * - 深拷贝入参（不污染编辑器/工程 doc）；
 * - 数据源只保留一个新建 mock 源（防止 local 模式下真的去连 MQTT/REST/Modbus）；
 * - 基础变量改挂仿真源、writable=true、mock=hold（引擎启动只推一次默认值，此后由仿真台驱动）；
 * - scale/offset/bitIndex 置空：仿真值即工程值，避免二次换算把数值改形；
 * - 虚拟变量（expr）原样保留，由引擎按基础变量级联求值。
 */
export function buildSimDoc(source: ProjectDoc, opts: SimBuildOptions = {}): SimBuildResult {
  const doc = JSON.parse(JSON.stringify(source)) as ProjectDoc
  const simDsId = newId('ds')
  const simDs: DataSource = {
    id: simDsId,
    name: '仿真数据源',
    type: 'mock',
    enabled: true,
    config: { defaultIntervalMs: 250 },
  }
  doc.datasources = [simDs]
  if (doc.project) doc.project.thumbnail = null

  const limit = Math.max(0, opts.enabledLimit ?? DEFAULT_ENABLED_LIMIT)
  const signals: SimSignal[] = []
  let baseCount = 0

  for (const v of doc.variables) {
    // 表达式虚拟变量：不挂数据源、不可写，值由引擎按依赖级联求值
    if (v.expr) {
      v.datasourceId = VIRTUAL_DATASOURCE_ID
      v.writable = false
      v.mock = null
      v.scale = null
      v.offset = null
      v.bitIndex = null
      signals.push(defaultSignal(v, true, true))
      continue
    }
    v.datasourceId = simDsId
    v.writable = true
    v.mock = { kind: 'hold' } as MockSpec
    v.scale = null
    v.offset = null
    v.bitIndex = null
    signals.push(defaultSignal(v, baseCount < limit))
    baseCount++
  }

  return { doc, signals, simDsId }
}

function manualValueOf(s: SimSignal): number | boolean | string {
  if (s.type === 'boolean') return s.manualBool
  if (s.type === 'string') return s.manualText
  return tidy(s.manualNumber, s.precision)
}

/**
 * 取仿真值。
 * - tMs：仿真时钟（由页面按变速累加，暂停时不前进，恢复后波形连续）；
 * - rand：随机源可注入，便于测试确定化。
 * 波形公式与 startMock/MockSource 同口径（sine/ramp/random/square）。
 */
export function simulateValue(s: SimSignal, tMs: number, rand: () => number = Math.random): number | boolean | string {
  if (s.virtual || s.wave === 'manual') return manualValueOf(s)

  const period = Math.max(MIN_PERIOD_SEC, s.periodSec) * 1000
  const phase = ((tMs % period) + period) % period / period
  const span = s.max - s.min

  if (s.type === 'string') return s.manualText
  if (s.type === 'boolean') {
    if (s.wave === 'square') return phase < 0.5
    // 其它波形按中值二值化（保留波形节奏的开关量变体）
    const raw = s.wave === 'random' ? s.min + rand() * span : s.min + span * phase
    return raw >= s.min + span / 2
  }

  let raw: number
  switch (s.wave) {
    case 'sine':
      raw = s.min + span * (0.5 + 0.5 * Math.sin(2 * Math.PI * phase))
      break
    case 'ramp':
      raw = phase < 0.5 ? s.min + span * phase * 2 : s.max - span * (phase - 0.5) * 2
      break
    case 'random':
      raw = s.min + rand() * span
      break
    case 'square':
      raw = phase < 0.5 ? s.max : s.min
      break
    default:
      raw = s.manualNumber
  }
  return tidy(raw, s.precision)
}

/** 读数格式化（仿真台表格用；布尔按工业习惯显示开/关） */
export function formatSimValue(s: SimSignal, value: number | boolean | string | undefined): string {
  if (value === undefined || value === null) return '—'
  if (typeof value === 'number') return value.toFixed(Math.min(Math.max(s.precision ?? 2, 0), 8))
  if (typeof value === 'boolean') return value ? '开' : '关'
  return String(value)
}
