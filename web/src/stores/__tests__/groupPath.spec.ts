/**
 * 嵌套组编辑路径栈（B-5）：逐层进入 / 退一级 / 面包屑跳层 / 锁定与跨层防护。
 * 此前 editingGroup 只查顶层，双击组内子组静默失败。运行：cd web && npm test。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/projects', () => ({ getProject: vi.fn(), updateProject: vi.fn() }))
vi.mock('@/widgets/registry', () => ({ registry: new Map() }))
vi.mock('@/assets/symbols', () => ({ getSymbol: vi.fn(() => undefined) }))

import type { ProjectDoc } from '@/types/doc'
import { useEditorStore } from '@/stores/editor'

function makeDoc(): ProjectDoc {
  return {
    schemaVersion: 1,
    project: { id: 'p1', name: '嵌套组测试' },
    settings: { theme: 'blue-dark' },
    datasources: [],
    variables: [],
    alarmRules: [],
    pages: [
      {
        id: 'page_1', name: 'P1', order: 0, background: { color: '#0b1220' },
        screen: { designWidth: 1920, designHeight: 1080, mode: 'fit-contain', orientation: 'auto' },
        components: [
          {
            id: 'cmp_g1', name: '外层组', type: 'group', x: 0, y: 0, w: 400, h: 300, z: 0,
            props: {}, bindings: [],
            children: [
              {
                id: 'cmp_g2', name: '内层组', type: 'group', x: 10, y: 10, w: 200, h: 150, z: 0,
                props: {}, bindings: [],
                children: [
                  { id: 'cmp_leaf', name: '叶子', type: 'rect', x: 5, y: 5, w: 40, h: 20, z: 0, props: {}, bindings: [] },
                ],
              },
            ],
          },
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

describe('嵌套组路径栈', () => {
  it('逐层进入：外层 → 内层（此前双击子组静默失败）', () => {
    store.enterGroup('cmp_g1')
    expect(store.editingGroupId).toBe('cmp_g1')
    expect(store.editingGroup?.id).toBe('cmp_g1')
    store.enterGroup('cmp_g2')
    expect(store.editingGroupPath).toEqual(['cmp_g1', 'cmp_g2'])
    expect(store.editingGroup?.children ?? []).toHaveLength(1)
    // 内层上下文的选中池 = 内层直接子节点
    store.selection = ['cmp_leaf']
    expect(store.selectedNodes.map((n) => n.id)).toEqual(['cmp_leaf'])
  })

  it('面包屑链与跳层：点页级 = 全退，点外层组 = 退回外层', () => {
    store.enterGroup('cmp_g1')
    store.enterGroup('cmp_g2')
    expect(store.editingGroupChain.map((g) => g.name)).toEqual(['外层组', '内层组'])
    store.exitToGroupLevel(1)
    expect(store.editingGroupPath).toEqual(['cmp_g1'])
    store.exitToGroupLevel(0)
    expect(store.editingGroupPath).toEqual([])
    expect(store.editingGroup).toBeNull()
  })

  it('Esc 语义 = 退一级：退出后可立即选中刚退出的组', () => {
    store.enterGroup('cmp_g1')
    store.enterGroup('cmp_g2')
    const gid = store.editingGroupId
    store.exitGroup()
    store.select([gid])
    // cmp_g2 是外层组的直接子级，选池正确命中
    expect(store.editingGroupId).toBe('cmp_g1')
    expect(store.selectedNodes.map((n) => n.id)).toEqual(['cmp_g2'])
  })

  it('跨层跳入被拒：处于内层时直接 enter 顶层 id 无效', () => {
    store.enterGroup('cmp_g1')
    store.enterGroup('cmp_g2')
    store.enterGroup('cmp_g1') // 不在当前上下文直接子级
    expect(store.editingGroupPath).toEqual(['cmp_g1', 'cmp_g2'])
  })

  it('锁定组不可进入', () => {
    const g1 = store.topLevelNodes[0]
    g1.locked = true
    store.enterGroup('cmp_g1')
    expect(store.editingGroupId).toBe('')
  })
})
