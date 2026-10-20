/**
 * 压测工程生成器（M7，对齐 BY组态「1100 个组件加载测试」）：
 * 单页 1100 组件混合（变量显示/状态/流动条/开关/状态灯/进度条/矩形闪烁/静态文本），
 * 20 个 mock 变量（sine/square/random 混合，1s 级刷新），验证编辑器打开与运行态渲染性能。
 */
import type { Binding, ComponentNode, ProjectDoc, VariableDef } from '@/types/doc'

export function buildStressDoc(): ProjectDoc {
  const dsId = 'ds-stress'
  const varIds: string[] = []
  const variables: VariableDef[] = []

  for (let i = 0; i < 20; i++) {
    const id = `var-stress-${i}`
    varIds.push(id)
    variables.push({
      id,
      key: `stress.v${i}`,
      label: `压测变量${i}`,
      type: 'number',
      unit: i % 3 === 0 ? '℃' : '',
      defaultValue: 50,
      datasourceId: dsId,
      writable: true,
      mock:
        i % 3 === 0
          ? { kind: 'sine', min: 10, max: 90, periodMs: 20000 + i * 500 }
          : i % 3 === 1
            ? { kind: 'square', onValue: 1, offValue: 0, periodMs: 4000 + i * 200, duty: 0.5 }
            : { kind: 'random', min: 0, max: 100, intervalMs: 1000 },
    })
  }

  const components: ComponentNode[] = []
  const CELL = 92
  const COLS = 25
  let z = 0

  const bind = (variableId: string, prop: string, mode: Binding['mode'] = 'value'): Binding[] => [
    { id: `bnd-stress-${z}`, prop, variableId, mode, mapping: null },
  ]

  const push = (node: Omit<ComponentNode, 'z'>): void => {
    components.push({ ...node, z: z++ })
  }

  const at = (i: number): { x: number; y: number } => ({ x: 40 + (i % COLS) * CELL, y: 40 + Math.floor(i / COLS) * CELL })

  // 1) 变量显示 300（绑 props.value）
  for (let i = 0; i < 300; i++) {
    const p = at(i)
    push({
      id: `n-vd-${i}`, name: `变量${i}`, type: 'var-display',
      x: p.x, y: p.y, w: 80, h: 40,
      props: { prefix: '', unit: i % 3 === 0 ? '℃' : '', precision: 1 },
      bindings: bind(varIds[i % 20], 'props.value'),
    })
  }
  // 2) 矩形 200（每 10 个一个闪烁动画）
  for (let i = 0; i < 200; i++) {
    const p = at(300 + i)
    push({
      id: `n-rect-${i}`, name: `矩形${i}`, type: 'rect',
      x: p.x, y: p.y, w: 60, h: 36,
      props: {},
      style: { fill: '#1e3a5f', stroke: '#3b82f6' },
      animations: i % 10 === 0 ? { blink: { enabled: true, intervalMs: 800 } } : null,
      bindings: [],
    })
  }
  // 3) 流动条 100（绑 props.speed，方波变量启停）
  for (let i = 0; i < 100; i++) {
    const p = at(500 + i)
    push({
      id: `n-flow-${i}`, name: `流动条${i}`, type: 'flow-bar',
      x: p.x, y: p.y, w: 84, h: 26,
      props: { speed: 80, showArrow: true, vertical: false },
      bindings: bind(varIds[(i % 20) + 1] ?? varIds[1], 'props.speed'),
    })
  }
  // 4) 开关 100（读写一体，mock 回环）
  for (let i = 0; i < 100; i++) {
    const p = at(600 + i)
    push({
      id: `n-sw-${i}`, name: `开关${i}`, type: 'switch',
      x: p.x, y: p.y, w: 76, h: 34,
      props: { variableId: varIds[(i % 20) + 1] ?? varIds[1], onValue: 1, offValue: 0, confirm: false, label: `K${i}` },
      bindings: [],
    })
  }
  // 5) 状态文本 100（绑 props.value）
  for (let i = 0; i < 100; i++) {
    const p = at(700 + i)
    push({
      id: `n-st-${i}`, name: `状态${i}`, type: 'state-text',
      x: p.x, y: p.y, w: 80, h: 34,
      props: {
        defaultText: '--',
        states: '[{"value":0,"text":"停止","color":"#909399"},{"value":1,"text":"运行","color":"#67c23a"}]',
      },
      bindings: bind(varIds[(i % 20) + 1] ?? varIds[1], 'props.value'),
    })
  }
  // 6) 状态灯 100（绑 style.color）
  for (let i = 0; i < 100; i++) {
    const p = at(800 + i)
    push({
      id: `n-sl-${i}`, name: `灯${i}`, type: 'status-light',
      x: p.x, y: p.y, w: 30, h: 30,
      props: {},
      bindings: [
        {
          id: `bnd-sl-${i}`, prop: 'style.color', variableId: varIds[(i % 20) + 1] ?? varIds[1], mode: 'color',
          mapping: { kind: 'enum', map: { '1': '#22c55e', '0': '#64748b' } },
        },
      ],
    })
  }
  // 7) 静态文本 100
  for (let i = 0; i < 100; i++) {
    const p = at(900 + i)
    push({
      id: `n-txt-${i}`, name: `文本${i}`, type: 'text',
      x: p.x, y: p.y, w: 84, h: 30,
      props: { text: `静态 ${i}`, ellipsis: true },
      bindings: [],
    })
  }
  // 8) 进度条 100（绑 props.percent）
  for (let i = 0; i < 100; i++) {
    const p = at(1000 + i)
    push({
      id: `n-pg-${i}`, name: `进度${i}`, type: 'progress',
      x: p.x, y: p.y, w: 84, h: 18,
      props: { percent: 50 },
      bindings: bind(varIds[i % 3 === 2 ? i % 20 : 2], 'props.percent'),
    })
  }

  return {
    schemaVersion: 1,
    project: {
      id: crypto.randomUUID(),
      name: `压测工程 1100 组件 ${new Date().toLocaleString('zh-CN', { hour12: false })}`,
      description: '性能测试：300 变量显示 + 200 矩形（20 闪烁）+ 100 流动条 + 100 开关 + 100 状态 + 100 状态灯 + 100 文本 + 100 进度条',
      author: null,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    },
    settings: {
      designSize: { width: 2400, height: 1600 },
      adaptive: 'fit-contain',
      theme: 'blue-dark',
      primaryColor: '#2563eb',
      alarm: { levelColors: { info: '#3b82f6', warn: '#f59e0b', critical: '#ef4444' }, soundEnabled: false, soundThrottleSec: 60 },
    },
    datasources: [{ id: dsId, name: '压测 mock', type: 'mock', enabled: true, config: { defaultIntervalMs: 1000 } }],
    variables,
    pages: [
      {
        id: 'page-stress',
        name: '压测页',
        order: 0,
        background: { color: '#0b1220', image: null },
        screen: { designWidth: 2400, designHeight: 1600, mode: 'fit-contain' },
        components,
      },
    ],
    alarmRules: [],
  }
}
