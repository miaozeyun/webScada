/**
 * 演示只读工程：保存链路整体旁路（2026-10-29）。
 * 前端禁用保存只是体验，服务端 PUT 亦 403 PROJECT_READONLY；这里锁住 store 侧「不发请求」。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

// 打断依赖链（同 pageBackground.spec）：api → http → router；registry → 全部 .vue；assets/symbols
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

import { updateProject } from '@/api/projects'
import { useEditorStore } from '@/stores/editor'

let store: ReturnType<typeof useEditorStore>

beforeEach(() => {
  vi.clearAllMocks()
  setActivePinia(createPinia())
  store = useEditorStore()
  store.readonly = true
  store.dirty = true
})

describe('演示只读保存旁路', () => {
  it('save() 直接返回成功，不 PUT、不伪造已保存', async () => {
    const ok = await store.save()
    expect(ok).toBe(true)
    expect(updateProject).not.toHaveBeenCalled()
    // dirty 保持 true：状态栏显示「演示工程·修改不保存」，而不是误导性的「已保存」
    expect(store.dirty).toBe(true)
    expect(store.lastSavedAt).toBeNull()
    expect(store.saveError).toBe('')
  })
})
