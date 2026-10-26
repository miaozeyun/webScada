/**
 * 实时数据仿真台工具（utils/simulation.ts）测试。
 * 覆盖三块：仿真副本 doc 构造（不污染源 doc / 数据源隔离 / 变量改写）、
 * 波形求值（与服务端 MockSource 同口径）、按语义推导的默认波形参数。
 */
import { describe, expect, it } from 'vitest'

import type { ProjectDoc, VariableDef } from '@/types/doc'
import { VIRTUAL_DATASOURCE_ID } from '@/types/doc'
import {
  buildSimDoc,
  defaultSignal,
  formatSimValue,
  simulateValue,
  type SimSignal,
} from '@/utils/simulation'

function vdef(partial: Partial<VariableDef> & Pick<VariableDef, 'id' | 'key' | 'label'>): VariableDef {
  return {
    type: 'number',
    datasourceId: 'ds_mqtt',
    defaultValue: null,
    ...partial,
  }
}

function makeDoc(variables: VariableDef[]): ProjectDoc {
  return {
    schemaVersion: 1,
    project: { id: 'p1', name: '测试工程', createdAt: '', updatedAt: '', thumbnail: 'data:image/png;base64,x' },
    settings: {},
    datasources: [
      { id: 'ds_mqtt', name: '现场 MQTT', type: 'mqtt', enabled: true, config: { brokerUrl: 'mqtt://x', topics: [] } },
    ],
    variables,
    pages: [],
    alarmRules: [],
  } as unknown as ProjectDoc
}

function sig(overrides: Partial<SimSignal> = {}): SimSignal {
  return {
    variableId: 'var_1',
    key: 't1',
    label: '温度',
    type: 'number',
    unit: '℃',
    precision: 2,
    virtual: false,
    enabled: true,
    wave: 'sine',
    min: 0,
    max: 100,
    periodSec: 60,
    phaseMs: 0,
    manualNumber: 50,
    manualBool: false,
    manualText: '',
    ...overrides,
  }
}

describe('buildSimDoc 仿真副本构造', () => {
  const variables = [
    vdef({ id: 'var_1', key: 't1', label: '温度', range: { min: 10, max: 20 }, scale: 0.1, offset: 5, bitIndex: 2 }),
    vdef({ id: 'var_2', key: 'p1', label: '压力', defaultValue: 1.2 }),
    vdef({ id: 'var_3', key: 'run', label: '运行', type: 'boolean', defaultValue: true }),
    vdef({ id: 'var_4', key: 'name', label: '名称', type: 'string', defaultValue: 'A' }),
    vdef({ id: 'var_5', key: 'kpi', label: '效率', expr: 't1 / p1', datasourceId: VIRTUAL_DATASOURCE_ID }),
  ]

  it('不修改源 doc（深拷贝隔离）', () => {
    const source = makeDoc(variables)
    buildSimDoc(source)
    expect(source.datasources).toHaveLength(1)
    expect(source.datasources[0]?.type).toBe('mqtt')
    expect(source.variables[0]?.datasourceId).toBe('ds_mqtt')
    expect(source.variables[0]?.scale).toBe(0.1)
    expect(source.variables[0]?.mock).toBeUndefined()
    expect(source.project.thumbnail).toBe('data:image/png;base64,x')
  })

  it('副本只保留一个 mock 数据源，基础变量全部改挂并置空换算字段', () => {
    const { doc, simDsId } = buildSimDoc(makeDoc(variables))
    expect(doc.datasources).toHaveLength(1)
    expect(doc.datasources[0]?.id).toBe(simDsId)
    expect(doc.datasources[0]?.type).toBe('mock')
    const base = doc.variables.filter((x) => !x.expr)
    expect(base).toHaveLength(4)
    for (const x of base) {
      expect(x.datasourceId).toBe(simDsId)
      expect(x.writable).toBe(true)
      expect(x.mock).toEqual({ kind: 'hold' })
      expect(x.scale).toBeNull()
      expect(x.offset).toBeNull()
      expect(x.bitIndex).toBeNull()
    }
    expect(doc.project.thumbnail).toBeNull()
  })

  it('虚拟变量保持表达式驱动：保留 expr、挂 virtual 哨兵、信号只读', () => {
    const { doc, signals } = buildSimDoc(makeDoc(variables))
    const kpi = doc.variables.find((x) => x.key === 'kpi')
    expect(kpi?.expr).toBe('t1 / p1')
    expect(kpi?.datasourceId).toBe(VIRTUAL_DATASOURCE_ID)
    expect(kpi?.writable).toBe(false)
    const sigKpi = signals.find((s) => s.variableId === 'var_5')
    expect(sigKpi?.virtual).toBe(true)
  })

  it('默认只启用前 12 个基础变量，可配置上限', () => {
    const many = Array.from({ length: 20 }, (_, i) => vdef({ id: `var_${i}`, key: `k${i}`, label: `量${i}` }))
    const all = buildSimDoc(makeDoc(many))
    expect(all.signals.filter((s) => s.enabled)).toHaveLength(12)
    const two = buildSimDoc(makeDoc(many), { enabledLimit: 2 })
    expect(two.signals.filter((s) => s.enabled)).toHaveLength(2)
  })
})

describe('simulateValue 波形求值', () => {
  it('正弦：t=0 为中值，t=周期/4 为最大值（与服务端 MockSource 同口径）', () => {
    const s = sig({ min: 10, max: 30, periodSec: 4 })
    expect(simulateValue(s, 0)).toBe(20)
    expect(simulateValue(s, 1000)).toBe(30)
    expect(simulateValue(s, 2000)).toBe(20)
    expect(simulateValue(s, 3000)).toBe(10)
  })

  it('三角斜坡：前半程升、后半程降', () => {
    const s = sig({ min: 0, max: 100, periodSec: 4, wave: 'ramp' })
    expect(simulateValue(s, 0)).toBe(0)
    expect(simulateValue(s, 1000)).toBe(50)
    expect(simulateValue(s, 2000)).toBe(100)
    expect(simulateValue(s, 3000)).toBe(50)
  })

  it('随机：注入随机源后结果确定，且落在区间内', () => {
    const s = sig({ min: 10, max: 20, wave: 'random' })
    expect(simulateValue(s, 0, () => 0)).toBe(10)
    expect(simulateValue(s, 0, () => 0.5)).toBe(15)
    expect(simulateValue(s, 0, () => 0.999)).toBe(19.99)
  })

  it('数字方波：前半程取最大值、后半程取最小值', () => {
    const s = sig({ min: 1, max: 9, wave: 'square', periodSec: 10 })
    expect(simulateValue(s, 0)).toBe(9)
    expect(simulateValue(s, 6000)).toBe(1)
  })

  it('手动固定：原样返回（数值/布尔/文本）', () => {
    expect(simulateValue(sig({ wave: 'manual', manualNumber: 42.5 }), 9999)).toBe(42.5)
    expect(simulateValue(sig({ type: 'boolean', wave: 'manual', manualBool: true }), 0)).toBe(true)
    expect(simulateValue(sig({ type: 'string', wave: 'manual', manualText: '自动' }), 0)).toBe('自动')
  })

  it('布尔方波：按周期前后半程翻转', () => {
    const s = sig({ type: 'boolean', wave: 'square', periodSec: 4 })
    expect(simulateValue(s, 0)).toBe(true)
    expect(simulateValue(s, 3000)).toBe(false)
  })

  it('虚拟变量信号不参与求值（返回手动值，实际值由引擎表达式给出）', () => {
    const s = sig({ virtual: true, wave: 'sine', manualNumber: 7 })
    expect(simulateValue(s, 1234)).toBe(7)
  })
})

describe('defaultSignal 语义默认值', () => {
  it('周期按变量语义推导：温度 60s / 液位 90s / MPa 压力 24s', () => {
    expect(defaultSignal(vdef({ id: 'a', key: 't', label: '炉膛温度' }), false).periodSec).toBe(60)
    expect(defaultSignal(vdef({ id: 'b', key: 'l', label: '水箱液位' }), false).periodSec).toBe(90)
    expect(defaultSignal(vdef({ id: 'c', key: 'p', label: '母管压力', unit: 'MPa' }), false).periodSec).toBe(24)
  })

  it('有 range 用 range；无 range 按默认值 ±10% 推导', () => {
    const withRange = defaultSignal(vdef({ id: 'a', key: 't', label: '温度', range: { min: 5, max: 15 } }), false)
    expect([withRange.min, withRange.max]).toEqual([5, 15])
    const withDefault = defaultSignal(vdef({ id: 'b', key: 'p', label: '压力', defaultValue: 100 }), false)
    expect([withDefault.min, withDefault.max]).toEqual([90, 110])
    expect(withDefault.manualNumber).toBe(100)
  })

  it('开关量/文本量默认手动固定，数值量默认正弦，计数类走斜坡', () => {
    expect(defaultSignal(vdef({ id: 'a', key: 'b', label: '运行', type: 'boolean' }), true).wave).toBe('manual')
    expect(defaultSignal(vdef({ id: 'b', key: 's', label: '模式', type: 'string' }), true).wave).toBe('manual')
    expect(defaultSignal(vdef({ id: 'c', key: 'n', label: '压力' }), true).wave).toBe('sine')
    expect(defaultSignal(vdef({ id: 'd', key: 'm_counter', label: '秒计数' }), true).wave).toBe('ramp')
  })

  it('无 range/默认值时按语义推导区间：温度/液位/压力各得其所', () => {
    expect(defaultSignal(vdef({ id: 'a', key: 't', label: '1线温度', unit: '℃' }), false).min).toBe(20)
    expect(defaultSignal(vdef({ id: 'a', key: 't', label: '1线温度', unit: '℃' }), false).max).toBe(80)
    expect(defaultSignal(vdef({ id: 'b', key: 'l', label: '水箱液位' }), false).min).toBe(20)
    expect(defaultSignal(vdef({ id: 'b', key: 'l', label: '水箱液位' }), false).max).toBe(90)
    const press = defaultSignal(vdef({ id: 'c', key: 'p', label: '母管压力', unit: 'MPa' }), false)
    expect([press.min, press.max]).toEqual([0.3, 0.8])
    const freq = defaultSignal(vdef({ id: 'd', key: 'f', label: '并网点频率', unit: 'Hz' }), false)
    expect([freq.min, freq.max]).toEqual([45, 55])
  })

  it('显式 defaultValue 优先于语义区间（围绕默认值 ±10%）', () => {
    const s = defaultSignal(vdef({ id: 'a', key: 't', label: '温度', unit: '℃', defaultValue: 50 }), false)
    expect([s.min, s.max]).toEqual([45, 55])
  })

  it('bitIndex 变量（副本已置空换算）按布尔信号处理', () => {
    const s = defaultSignal(vdef({ id: 'a', key: 'run', label: '运行位', type: 'number', bitIndex: 3 }), true)
    expect(s.type).toBe('boolean')
    expect(s.wave).toBe('manual')
  })

  it('同参数变量相位散列不同（避免曲线完全重叠）', () => {
    const a = defaultSignal(vdef({ id: 'var_a', key: 't1', label: '1线温度', unit: '℃' }), true)
    const b = defaultSignal(vdef({ id: 'var_b', key: 't2', label: '2线温度', unit: '℃' }), true)
    expect(a.phaseMs).not.toBe(b.phaseMs)
    expect(a.phaseMs).toBeGreaterThanOrEqual(0)
    expect(a.phaseMs).toBeLessThan(60_000)
  })
})

describe('formatSimValue', () => {
  it('数值按 precision 格式化，布尔显示开/关，空值显示破折号', () => {
    expect(formatSimValue(sig({ precision: 1 }), 1.234)).toBe('1.2')
    expect(formatSimValue(sig({ type: 'boolean' }), true)).toBe('开')
    expect(formatSimValue(sig({ type: 'boolean' }), false)).toBe('关')
    expect(formatSimValue(sig(), undefined)).toBe('—')
  })
})
