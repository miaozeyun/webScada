/**
 * 演示案例集结构自检（2026-10-29）：防止新增/调整案例时踩服务端 422 的硬约束。
 *
 * 断言口径与 server/app/schemas/doc.py + doc_service.validate_references 对齐：
 * id/key 唯一、绑定变量存在、同组件同 prop 单绑定、style/anim 目标键合法、
 * 单页组件数 ≤200、表达式标识符可解析、行业图元 ID 存在。
 */
import { describe, expect, it } from 'vitest'
import { symbolAssets } from '@/assets/symbols'
import type { ComponentNode, ProjectDoc } from '@/types/doc'
import { exprIdents } from '@/utils/expr'
import { DEMO_CASES } from '../demos'

const STYLE_KEYS = new Set(['fill', 'stroke', 'strokeWidth', 'borderRadius', 'color', 'fontSize', 'fontWeight', 'textAlign'])
const SYMBOL_IDS = new Set(symbolAssets.map((s) => s.id))

function walk(nodes: ComponentNode[], visit: (n: ComponentNode) => void): void {
  for (const n of nodes) {
    visit(n)
    if (n.children?.length) walk(n.children, visit)
  }
}

describe('演示案例结构自检', () => {
  it.each(DEMO_CASES.map((c) => [c.key, c] as const))('%s', (_key, c) => {
    const doc: ProjectDoc = c.build()
    expect(doc.schemaVersion).toBe(1)
    expect(doc.pages.length).toBeGreaterThan(0)

    // 变量 id/key 唯一；表达式引用可解析
    const keys = new Set(doc.variables.map((v) => v.key))
    expect(new Set(doc.variables.map((v) => v.id)).size).toBe(doc.variables.length)
    expect(keys.size).toBe(doc.variables.length)
    for (const v of doc.variables) {
      if (!v.expr) continue
      for (const ident of exprIdents(v.expr)) {
        expect(keys.has(ident) || ident === '_tick', `${v.key} 的表达式引用了未知标识符 ${ident}`).toBe(true)
      }
    }

    // 数据源 / 报警规则引用存在
    const dsIds = new Set(doc.datasources.map((d) => d.id))
    const varIds = new Set(doc.variables.map((v) => v.id))
    // 虚拟变量 datasourceId='virtual'（哨兵，不在 datasources 内）
    for (const v of doc.variables) {
      if (v.expr) continue
      expect(dsIds.has(v.datasourceId), `${v.key} 的数据源不存在`).toBe(true)
    }
    expect(new Set(doc.alarmRules.map((r) => r.id)).size).toBe(doc.alarmRules.length)
    for (const r of doc.alarmRules) expect(varIds.has(r.variableId), `${r.name} 的变量不存在`).toBe(true)

    // 页面 / 组件约束
    const allIds = new Set<string>()
    for (const p of doc.pages) {
      expect(p.components.length, `${p.name} 组件数超过单页 200 上限`).toBeLessThanOrEqual(200)
      walk(p.components, (n) => {
        expect(allIds.has(n.id), `组件 id 重复：${n.id}`).toBe(false)
        allIds.add(n.id)
        const props = new Set<string>()
        for (const b of n.bindings) {
          expect(varIds.has(b.variableId), `${n.id} 绑定变量不存在：${b.variableId}`).toBe(true)
          expect(props.has(b.prop), `${n.id} 同一目标重复绑定：${b.prop}`).toBe(false)
          props.add(b.prop)
          const okPath =
            b.prop === 'visible' ||
            b.prop === 'opacity' ||
            /^props\.[A-Za-z0-9_]+$/.test(b.prop) ||
            (b.prop.startsWith('style.') && STYLE_KEYS.has(b.prop.slice(6))) ||
            ['anim.rotateOn', 'anim.rotatePeriod', 'anim.flowOn', 'anim.blinkOn', 'anim.moveOn'].includes(b.prop)
          expect(okPath, `${n.id} 绑定目标非法：${b.prop}`).toBe(true)
        }
        if (n.type === 'symbol') {
          expect(SYMBOL_IDS.has(String(n.props.symbolId)), `${n.id} 图元不存在：${String(n.props.symbolId)}`).toBe(true)
        }
      })
    }
  })
})
