/**
 * 粘贴锚点语义（pasteClipboard(at)）：at 统一为页面绝对设计坐标，
 * 组编辑上下文内先换算为目标池（eg.children）相对坐标——
 * 修复组内「粘贴到此处」 historically 偏移组原点的错位；无 at 回落 +10px 阶梯。
 * 关联：Ctrl+V 落点跟随鼠标（keyboard.ts 传 store.lastPointerDesign）。
 * 运行：cd web && npm test（vitest run）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

// 打断三条依赖链（纯逻辑测试，同 history.spec 先例）：
// ① api/projects → http → router；② widgets/registry → 43 个 .vue（node 环境无 vue 插件）；③ assets/symbols
vi.mock('@/api/projects', () => ({
  getProject: vi.fn(),
  updateProject: vi.fn(),
}))
vi.mock('@/widgets/registry', () => ({
  registry: new Map(),
}))
vi.mock('@/assets/symbols', () => ({
  getSymbol: vi.fn(() => undefined),
}))

import type { ComponentNode, ProjectDoc } from '@/types/doc'
import { useEditorStore } from '@/stores/editor'

function node(partial: Partial<ComponentNode> & Pick<ComponentNode, 'id' | 'type' | 'x' | 'y'>): ComponentNode {
  return {
    name: partial.id,
    w: 80,
    h: 40,
    z: 0,
    props: {},
    bindings: [],
    ...partial,
  } as ComponentNode
}

function makeDoc(): ProjectDoc {
  return {
    schemaVersion: 1,
    project: { id: 'p1', name: '粘贴锚点测试' },
    settings: { theme: 'blue-dark' },
    datasources: [],
    variables: [],
    alarmRules: [],
    pages: [
      {
        id: 'page_1',
        name: 'P1',
        order: 0,
        background: { color: '#0b1220' },
        screen: { designWidth: 1920, designHeight: 1080, mode: 'fit-contain', orientation: 'auto' },
        components: [
          node({ id: 'cmp_a', type: 'rect', x: 100, y: 50 }),
          node({
            id: 'cmp_g',
            type: 'group',
            x: 200,
            y: 100,
            w: 300,
            h: 200,
            z: 1,
            children: [node({ id: 'cmp_c', type: 'rect', x: 10, y: 20 })],
          }),
        ],
      },
    ],
  } as unknown as ProjectDoc
}

let store: ReturnType<typeof useEditorStore>

beforeEach(() => {
  setActivePinia(createPinia())
  store = useEditorStore()
  store.doc = makeDoc()
  store.currentPageId = 'page_1'
  store.selection = []
  store.editingGroupPath = []
  store.editingGroupId = ''
})

describe('pasteClipboard(at) 粘贴锚点', () => {
  it('顶层：剪贴板包围盒原点对齐 at（页面绝对坐标）', () => {
    store.selection = ['cmp_a']
    store.copySelection()
    store.selection = []
    store.pasteClipboard({ x: 500, y: 400 })
    const pasted = store.currentPage!.components.filter((n) => n.id !== 'cmp_a' && n.id !== 'cmp_g')
    expect(pasted).toHaveLength(1)
    expect(pasted[0].x).toBe(500)
    expect(pasted[0].y).toBe(400)
  })

  it('组内复制→组内粘贴：at 页面绝对坐标正确换算为目标池相对坐标（修复组原点偏移）', () => {
    store.enterGroup('cmp_g')
    store.selection = ['cmp_c']
    store.copySelection()
    store.selection = []
    store.pasteClipboard({ x: 500, y: 400 })
    const g = store.currentPage!.components.find((n) => n.id === 'cmp_g')!
    const pasted = (g.children ?? []).filter((n) => n.id !== 'cmp_c')
    expect(pasted).toHaveLength(1)
    // cmp_c 是唯一源节点（minX=10/minY=20）：相对坐标 = at - 组原点 + (node - min)
    expect(pasted[0].x).toBe(500 - 200 + (10 - 10))
    expect(pasted[0].y).toBe(400 - 100 + (20 - 20))
  })

  it('跨上下文：顶层复制→组内粘贴，落点仍为页面绝对 at', () => {
    store.selection = ['cmp_a']
    store.copySelection()
    store.enterGroup('cmp_g')
    store.selection = []
    store.pasteClipboard({ x: 500, y: 400 })
    const g = store.currentPage!.components.find((n) => n.id === 'cmp_g')!
    const pasted = (g.children ?? []).filter((n) => n.id !== 'cmp_c')
    expect(pasted).toHaveLength(1)
    // 页面绝对 = 500 ⇒ 相对组 = 500 - 200 = 300
    expect(pasted[0].x).toBe(300)
    expect(pasted[0].y).toBe(300)
  })

  it('无 at：回落 +10px 阶梯偏移（纯键盘路径不变）', () => {
    store.selection = ['cmp_a']
    store.copySelection()
    store.selection = []
    store.pasteClipboard()
    const pasted = store.currentPage!.components.filter((n) => n.id !== 'cmp_a' && n.id !== 'cmp_g')
    expect(pasted[0].x).toBe(110)
    expect(pasted[0].y).toBe(60)
  })
})
