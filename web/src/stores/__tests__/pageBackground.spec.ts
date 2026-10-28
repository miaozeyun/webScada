/**
 * 页面背景（底色 + 图片 + 显示方式 + 不透明度）：
 * 合并写入，避免「只改图片丢掉底色 / 只调 fit 丢掉图片」的整对象替换缺陷（同 10-25 表单教训）。
 * 运行：cd web && npm test
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

// 打断三条依赖链（同 pasteAnchor.spec）：api → http → router；registry → 全部 .vue；assets/symbols
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

import type { ProjectDoc } from '@/types/doc'
import { useEditorStore } from '@/stores/editor'

function makeDoc(): ProjectDoc {
  return {
    schemaVersion: 1,
    project: { id: 'p1', name: '背景测试' },
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
  store.editingGroupPath = []
  store.editingGroupId = ''
})

describe('updatePageBackground', () => {
  it('设置背景图时保留已有底色', () => {
    store.updatePageBackground({ image: '/bg/tech-grid.svg' })
    expect(store.currentPage!.background.color).toBe('#0b1220')
    expect(store.currentPage!.background.image).toBe('/bg/tech-grid.svg')
  })

  it('调整显示方式/透明度时保留图片，不清空底色', () => {
    store.updatePageBackground({ image: '/bg/tech-grid.svg' })
    store.updatePageBackground({ imageFit: 'contain', imageOpacity: 0.5 })
    const bg = store.currentPage!.background
    expect(bg).toMatchObject({ color: '#0b1220', image: '/bg/tech-grid.svg', imageFit: 'contain', imageOpacity: 0.5 })
  })

  it('显式 null 清除背景图', () => {
    store.updatePageBackground({ image: '/bg/tech-grid.svg' })
    store.updatePageBackground({ image: null })
    expect(store.currentPage!.background.image).toBeNull()
  })

  it('标记脏数据（3s 防抖保存链路感知）', () => {
    const before = store.dirtySeq
    store.updatePageBackground({ image: '/bg/a.svg' })
    expect(store.dirtySeq).toBeGreaterThan(before)
  })
})
