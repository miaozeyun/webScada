/**
 * 演示案例工程构造器（M7 案例集，对齐业界主流组态 演示站）：共享快捷工厂。
 * 全部案例用单一 mock 数据源（开箱即用）；可控量用 hold 波形（反控回环保持）。
 */
import type {
  AlarmLevel,
  AlarmOp,
  AlarmRule,
  Binding,
  ComponentAnimations,
  ComponentNode,
  EventActionDef,
  EventTrigger,
  MockSpec,
  Page,
  ProjectDoc,
  TooltipCfg,
  ValueMapping,
  VariableDef,
} from '@/types/doc'
import { VIRTUAL_DATASOURCE_ID } from '@/types/doc'
import { uuidV4 } from '@/utils/uuid'

export const DS = 'ds_demo'

let seq = 0
export const nid = (p: string): string => `${p}_${(++seq).toString(36)}`

// ---- 变量 ----

export interface MVarOpts {
  kind?: 'sine' | 'ramp' | 'random' | 'square' | 'hold'
  min?: number
  max?: number
  periodMs?: number
  intervalMs?: number
  duty?: number
  unit?: string
  def?: number | boolean | string
  writable?: boolean
  /** 服务端入池前统一舍入（G3），KPI 翻牌等直读工程值的组件不出现 17 位浮点 */
  precision?: number
}

export function mvar(id: string, key: string, label: string, o: MVarOpts = {}): VariableDef {
  const kind = o.kind ?? 'sine'
  let mock: MockSpec
  switch (kind) {
    case 'hold': mock = { kind: 'hold' }; break
    case 'random': mock = { kind: 'random', min: o.min ?? 0, max: o.max ?? 100, intervalMs: o.intervalMs ?? 1000 }; break
    case 'square': mock = { kind: 'square', onValue: o.max ?? 1, offValue: o.min ?? 0, periodMs: o.periodMs ?? 8000, duty: o.duty ?? 0.5 }; break
    case 'ramp': mock = { kind: 'ramp', min: o.min ?? 0, max: o.max ?? 100, periodMs: o.periodMs ?? 30000 }; break
    default: mock = { kind: 'sine', min: o.min ?? 0, max: o.max ?? 100, periodMs: o.periodMs ?? 30000 }
  }
  return {
    id, key, label, type: 'number', unit: o.unit ?? null,
    defaultValue: o.def ?? null, datasourceId: DS, writable: o.writable === true, mock,
    precision: o.precision ?? null,
  }
}

/** 虚拟变量（M7/M9）：表达式引用其它变量 key（可含 _tick），引擎级联求值刷新 */
export function vvar(id: string, key: string, label: string, expr: string, o: { unit?: string; precision?: number } = {}): VariableDef {
  return {
    id, key, label, type: 'number', unit: o.unit ?? null,
    defaultValue: null, datasourceId: VIRTUAL_DATASOURCE_ID, expr,
    precision: o.precision ?? null,
  }
}

// ---- 绑定 ----

export function bd(variableId: string, prop: string, mode: Binding['mode'] = 'value', mapping?: ValueMapping | null): Binding {
  return { id: nid('bnd'), prop, variableId, mode, mapping: mapping ?? null }
}

export const enumMap = (map: Record<string, string | boolean>): ValueMapping => ({ kind: 'enum', map })

export const rangeMap = (...bands: { min?: number; max?: number; value: string | boolean }[]): ValueMapping =>
  ({ kind: 'range', bands })

/** 0/1 开关量 → 任意两值（流速/颜色等常用形态） */
export const onOff = (on: string, off: string): ValueMapping =>
  rangeMap({ max: 0.5, value: off }, { min: 0.5, value: on })

// ---- 组件 ----

export interface NDOpts {
  name?: string
  props?: Record<string, unknown>
  style?: ComponentNode['style']
  anim?: ComponentAnimations
  bindings?: Binding[]
  events?: { trigger: EventTrigger; actions: EventActionDef[] }[]
  tooltip?: string
  popup?: ComponentNode['popup']
  children?: ComponentNode[]
  /** 运行态/编辑态初始显隐（非弹框面板类用 false = 初始隐藏） */
  visible?: boolean
}

export function nd(id: string, type: string, x: number, y: number, w: number, h: number, o: NDOpts = {}): ComponentNode {
  const node: ComponentNode = {
    id, name: o.name ?? id, type: type as ComponentNode['type'],
    x, y, w, h, rotate: 0, z: ++seq, visible: o.visible !== false,
    props: o.props ?? {}, style: o.style ?? null, animations: o.anim ?? null,
    bindings: o.bindings ?? [], events: null, tooltip: null, popup: null,
  }
  if (o.events) node.events = o.events.map((e) => ({ id: nid('evt'), trigger: e.trigger, actions: e.actions }))
  if (o.tooltip !== undefined) node.tooltip = { enabled: true, template: o.tooltip } satisfies TooltipCfg
  if (o.popup) node.popup = o.popup
  if (o.children) node.children = o.children
  return node
}

/** 文本快捷（深色底白字） */
export function txt(
  id: string,
  x: number,
  y: number,
  w: number,
  h: number,
  text: string,
  fontSize = 14,
  color?: string,
  /** 演示说明文字：仅编辑器/演示可见，分享快照会剔除（不污染交付画面） */
  demoNote = false,
): ComponentNode {
  return nd(id, 'text', x, y, w, h, {
    name: text.slice(0, 12),
    props: demoNote ? { text, demoNote: true } : { text },
    style: { fontSize, color, fontWeight: fontSize >= 20 ? 700 : 400 },
  })
}

// ---- 页面 / 工程 ----

export function pg(id: string, name: string, w: number, h: number, components: ComponentNode[], o: { order?: number; lockPan?: boolean; bg?: string } = {}): Page {
  return {
    id, name, order: o.order ?? 0,
    background: { color: o.bg ?? '#0b1220' },
    screen: { designWidth: w, designHeight: h, mode: 'fit-contain', lockPan: o.lockPan === true },
    components,
  }
}

export function alm(id: string, name: string, variableId: string, op: AlarmOp, threshold: number, level: AlarmLevel, message: string): AlarmRule {
  return { id, name, variableId, op, threshold, level, message, enabled: true, hysteresis: null, durationMs: null, sound: true }
}

export function demoDoc(name: string, description: string, variables: VariableDef[], pages: Page[], alarms: AlarmRule[] = []): ProjectDoc {
  // 统一层序：按数组书写顺序重赋 z（循环构造的节点块先于字面量求值，nd() 的自增 z
  // 会与数组序脱节，后写的面板 rect 反而 zIndex 更高压住前面的卡片；组内 children 同理递归）
  const renumber = (nodes: ComponentNode[]): void => nodes.forEach((c, i) => {
    c.z = i + 1
    if (c.children) renumber(c.children)
  })
  pages.forEach((pg) => renumber(pg.components))
  return {
    schemaVersion: 1,
    project: {
      id: uuidV4(),
      name: `${name}（演示案例）`,
      description,
      author: null,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    },
    settings: {
      designSize: { width: pages[0]?.screen.designWidth ?? 1920, height: pages[0]?.screen.designHeight ?? 1080 },
      adaptive: 'fit-contain', theme: 'blue-dark', primaryColor: '#2563eb',
      alarm: { levelColors: { info: '#3b82f6', warn: '#f59e0b', critical: '#ef4444' }, soundEnabled: true, soundThrottleSec: 60 },
    },
    datasources: [{ id: DS, name: '演示 mock 数据源', type: 'mock', enabled: true, config: { defaultIntervalMs: 1000 } }],
    variables,
    pages,
    alarmRules: alarms,
  }
}
