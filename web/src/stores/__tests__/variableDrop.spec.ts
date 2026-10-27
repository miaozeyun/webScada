/**
 * 拖变量到画布生成绑定组件（B-1）：appendBinding 语义 + 「创建+绑定 = 一步 undo」。
 * 运行：cd web && npm test。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

// 打断依赖链：api→router、registry→.vue（node 环境无 vue 插件）；registry 只给 var-display 元信息
vi.mock('@/api/projects', () => ({ getProject: vi.fn(), updateProject: vi.fn() }))
vi.mock('@/widgets/registry', () => ({
  registry: new Map([
    ['var-display', { name: '变量', defaultSize: { w: 220, h: 64 }, defaultProps: () => ({}) }],
  ]),
}))
vi.mock('@/assets/symbols', () => ({ getSymbol: vi.fn(() => undefined) }))

import type { ProjectDoc } from '@/types/doc'
import { useEditorStore } from '@/stores/editor'

function makeDoc(): ProjectDoc {
  return {
    schemaVersion: 1,
    project: { id: 'p1', name: '拖变量测试' },
    settings: { theme: 'blue-dark' },
    datasources: [],
    variables: [{ id: 'var1', key: 'temp', label: '温度', type: 'number', datasourceId: 'ds1' }],
    alarmRules: [],
    pages: [
      {
        id: 'page_1', name: 'P1', order: 0, background: { color: '#0b1220' },
        screen: { designWidth: 1920, designHeight: 1080, mode: 'fit-contain', orientation: 'auto' },
        components: [],
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
  store.editingGroupId = ''
})

describe('appendBinding（拖变量生成组件的收尾步骤）', () => {
  it('创建 + 绑定合并为一步 undo：undo 一次组件与绑定同时消失', () => {
    const id = store.addComponent('var-display' as never, 100, 100)
    expect(id).toBeTruthy()
    store.appendBinding(id, 'var1', 'props.value')
    const comps = store.currentPage!.components
    expect(comps).toHaveLength(1)
    expect(comps[0].bindings).toHaveLength(1)
    expect(comps[0].bindings![0]).toMatchObject({ variableId: 'var1', prop: 'props.value', mode: 'value' })

    store.undo()
    expect(store.currentPage!.components).toHaveLength(0)
  })

  it('同变量同 prop 去重：重复追加不产生第二条绑定', () => {
    const id = store.addComponent('var-display' as never, 0, 0)
    store.appendBinding(id, 'var1', 'props.value')
    store.appendBinding(id, 'var1', 'props.value')
    expect(store.currentPage!.components[0].bindings).toHaveLength(1)
  })
})
