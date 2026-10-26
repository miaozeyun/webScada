/** 变量引用扫描：删除阻断的口径（硬引用 vs 表达式软引用）。 */
import { describe, expect, it } from 'vitest'

import type { ProjectDoc, VariableDef } from '@/types/doc'
import { findVariableUsage, variablesOfDatasource } from '@/utils/usage'

function makeDoc(): ProjectDoc {
  const v = (id: string, key: string, extra: Partial<VariableDef> = {}): VariableDef => ({
    id, key, label: key, type: 'number', datasourceId: 'ds1', ...extra,
  })
  return {
    schemaVersion: 1,
    project: { id: 'p1', name: '测试', author: 'a', createdAt: '', updatedAt: '' },
    settings: {} as ProjectDoc['settings'],
    datasources: [],
    variables: [
      v('var1', 'temp'),
      v('var2', 'virtual', { datasourceId: 'virtual', expr: 'temp * 2' }),
      v('var3', 'other', { datasourceId: 'ds2' }),
    ],
    pages: [{
      id: 'page1', name: '页1', order: 0, background: { color: '#000' },
      screen: {} as never,
      components: [{
        id: 'c1', name: '温度显示', type: 'var-display', x: 0, y: 0, w: 10, h: 10, z: 1,
        bindings: [{ id: 'b1', prop: 'props.value', variableId: 'var1', mode: 'value' }],
        events: [{ id: 'e1', trigger: 'click', actions: [{ type: 'writeVar', variableId: 'var1', value: '1' }] }],
      }],
    }],
    alarmRules: [{
      id: 'a1', name: '温度高', variableId: 'var1', op: '>', threshold: 90, level: 'warn',
      message: '', enabled: true,
    }],
  } as unknown as ProjectDoc
}

describe('findVariableUsage', () => {
  it('识别绑定、事件写变量、报警规则三处硬引用', () => {
    const doc = makeDoc()
    const usages = findVariableUsage(doc, doc.variables[0])
    expect(usages.filter((u) => u.kind !== 'expr').map((u) => u.kind).sort()).toEqual(['alarm', 'binding', 'event'])
    expect(usages.some((u) => u.where.includes('温度显示'))).toBe(true)
  })

  it('组件 props 里的变量 id（开关/历史图/表格）也算硬引用', () => {
    const doc = makeDoc()
    doc.pages[0].components[0].props = { variableId: 'var1', rangeMs: 3600 } as never
    const usages = findVariableUsage(doc, doc.variables[0])
    expect(usages.some((u) => u.kind === 'prop' && u.where.includes('variableId'))).toBe(true)
  })

  it('表达式引用按 key 识别为软引用', () => {
    const doc = makeDoc()
    const usages = findVariableUsage(doc, doc.variables[0]).filter((u) => u.kind === 'expr')
    expect(usages).toHaveLength(1)
    expect(usages[0].where).toContain('虚拟变量')
  })

  it('未被引用的变量返回空；key 边界不误匹配（temp 不匹配 temp2）', () => {
    const doc = makeDoc()
    doc.variables.push({
      id: 'var4', key: 'temp2', label: 'temp2', type: 'number', datasourceId: 'ds1',
    })
    expect(findVariableUsage(doc, doc.variables[3])).toEqual([])
  })
})

describe('variablesOfDatasource', () => {
  it('按数据源筛变量（删除数据源前阻断）', () => {
    const doc = makeDoc()
    expect(variablesOfDatasource(doc, 'ds1').map((v) => v.key)).toEqual(['temp'])
    expect(variablesOfDatasource(doc, 'ds2').map((v) => v.key)).toEqual(['other'])
    expect(variablesOfDatasource(doc, 'nope')).toEqual([])
  })
})
