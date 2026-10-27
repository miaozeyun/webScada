/**
 * 跨页撤销栈（B-3）：切页不清历史，undo/redo 只作用于当前页；删页丢栈、整 doc 替换全清。
 * 运行：cd web && npm test。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/projects', () => ({ getProject: vi.fn(), updateProject: vi.fn() }))
vi.mock('@/widgets/registry', () => ({ registry: new Map() }))
vi.mock('@/assets/symbols', () => ({ getSymbol: vi.fn(() => undefined) }))

import type { ProjectDoc } from '@/types/doc'
import { history, useEditorStore } from '@/stores/editor'

function page(id: string, nodeId: string, x: number) {
  return {
    id, name: id, order: 0, background: { color: '#0b1220' },
    screen: { designWidth: 1920, designHeight: 1080, mode: 'fit-contain' as const, orientation: 'auto' as const },
    components: [{ id: nodeId, name: nodeId, type: 'rect', x, y: 0, w: 40, h: 20, z: 0, props: {}, bindings: [] }],
  }
}

function makeDoc(): ProjectDoc {
  return {
    schemaVersion: 1,
    project: { id: 'p1', name: '跨页撤销测试' },
    settings: { theme: 'blue-dark' },
    datasources: [],
    variables: [],
    alarmRules: [],
    pages: [page('page_1', 'n1', 0), page('page_2', 'n2', 500)],
  } as unknown as ProjectDoc
}

let store: ReturnType<typeof useEditorStore>

function nodeX(pageId: string, nodeId: string): number {
  return store.doc!.pages.find((p) => p.id === pageId)!.components.find((c) => c.id === nodeId)!.x
}

beforeEach(() => {
  setActivePinia(createPinia())
  store = useEditorStore()
  store.doc = makeDoc()
  store.currentPageId = 'page_1'
  store.selection = []
  store.editingGroupPath = []
  store.editingGroupId = ''
  history.clearAll() // 模块级单例：跨用例隔离
})

describe('PageHistory 跨页撤销', () => {
  it('切页不清栈：两页各自可 undo，互不串扰', () => {
    // page_1：n1 0 → 100
    store.beginChange()
    store.setNodeRect('n1', { x: 100 })
    // 切 page_2：n2 500 → 700
    store.setCurrentPage('page_2')
    store.beginChange()
    store.setNodeRect('n2', { x: 700 })

    expect(store.canUndo()).toBe(true)
    store.undo() // 撤销 page_2 的改动
    expect(nodeX('page_2', 'n2')).toBe(500)
    expect(nodeX('page_1', 'n1')).toBe(100) // page_1 改动不受影响

    // 切回 page_1 仍可撤销自己的改动
    store.setCurrentPage('page_1')
    expect(store.canUndo()).toBe(true)
    store.undo()
    expect(nodeX('page_1', 'n1')).toBe(0)
    expect(store.canUndo()).toBe(false)
  })

  it('redo 分页独立：page_1 的 redo 不动 page_2', () => {
    store.beginChange()
    store.setNodeRect('n1', { x: 100 })
    store.setCurrentPage('page_2')
    store.beginChange()
    store.setNodeRect('n2', { x: 700 })
    store.undo() // page_2 回 500，redo 栈有 1 条

    store.setCurrentPage('page_1')
    expect(store.canRedo()).toBe(false) // page_1 无 redo
    store.setCurrentPage('page_2')
    expect(store.canRedo()).toBe(true)
    store.redo()
    expect(nodeX('page_2', 'n2')).toBe(700)
  })

  it('删除页面丢弃该页撤销栈', () => {
    store.beginChange()
    store.setNodeRect('n1', { x: 100 })
    store.beginChange()
    store.setNodeRect('n1', { x: 200 })
    expect(store.canUndo()).toBe(true)
    store.deletePage('page_1')
    store.setCurrentPage('page_2')
    expect(store.canUndo()).toBe(false)
  })

  it('整 doc 替换（replaceDoc）全清各页历史', () => {
    store.beginChange()
    store.setNodeRect('n1', { x: 100 })
    store.setCurrentPage('page_2')
    store.beginChange()
    store.setNodeRect('n2', { x: 700 })
    expect(store.replaceDoc(makeDoc())).toBe(true)
    expect(store.canUndo()).toBe(false)
    store.setCurrentPage('page_1')
    expect(store.canUndo()).toBe(false)
  })
})
