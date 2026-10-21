/**
 * 画面模板契约：每套模板产出的页面必须是可直接落库的合法 Page——
 * id 唯一（服务端 validate_references 会拦截重复 id）、z 连续（数组序 = 层级序）、
 * 组件不出画布（拖入后一眼可见）、页尺寸与 size 声明一致。
 */
import { describe, expect, it } from 'vitest'
import { PAGE_TEMPLATES } from '../pageTemplates'
import type { ComponentNode } from '@/types/doc'

function walk(nodes: ComponentNode[], out: ComponentNode[] = []): ComponentNode[] {
  for (const n of nodes) {
    out.push(n)
    if (n.children) walk(n.children, out)
  }
  return out
}

describe('pageTemplates', () => {
  it('模板 id/名称唯一', () => {
    const ids = PAGE_TEMPLATES.map((t) => t.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  for (const tpl of PAGE_TEMPLATES) {
    describe(tpl.name, () => {
      const page = tpl.build()
      const nodes = walk(page.components)

      it('页尺寸与声明一致', () => {
        expect(page.screen.designWidth).toBe(tpl.size.w)
        expect(page.screen.designHeight).toBe(tpl.size.h)
      })

      it('组件 id 唯一且非空', () => {
        const ids = nodes.map((n) => n.id)
        expect(ids.every(Boolean)).toBe(true)
        expect(new Set(ids).size).toBe(ids.length)
      })

      it('z 按数组序连续（顶层）', () => {
        page.components.forEach((c, i) => expect(c.z).toBe(i + 1))
      })

      it('顶层组件都在画布范围内', () => {
        for (const c of page.components) {
          expect(c.x).toBeGreaterThanOrEqual(0)
          expect(c.y).toBeGreaterThanOrEqual(0)
          expect(c.x + c.w).toBeLessThanOrEqual(tpl.size.w)
          expect(c.y + c.h).toBeLessThanOrEqual(tpl.size.h)
        }
      })

      it('文字类组件显式给了颜色（深底不继承黑字）', () => {
        for (const c of nodes) {
          if (c.type === 'text' || c.type === 'var-display') {
            expect(c.style?.color, `${c.name} 缺 style.color`).toBeTruthy()
          }
        }
      })
    })
  }
})
