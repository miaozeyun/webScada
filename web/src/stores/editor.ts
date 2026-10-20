/**
 * 编辑器核心 store：全量 doc + 选中态 + 历史 + 保存链路（3s 防抖 + baseRevision 乐观锁，G2）。
 * 变更协议：所有变更先 beginChange()（交互开始时快照/合并），再改 doc，改动后 _markDirty()。
 * 历史为页面级快照，切换页面即清空（快照不含页面切换语义）。
 */
import { defineStore } from 'pinia'
import type { ComponentNode, Page, ProjectDoc, WidgetType } from '@/types/doc'
import { getProject, updateProject } from '@/api/projects'
import { HistoryStack } from '@/editor/history'
import { buildGroup, flattenGroup, normalizeZ } from '@/editor/canvas/group'
import { nodesBBox } from '@/utils/coord'
import { newComponentId, newPageId } from '@/utils/nanoid'
import { registry } from '@/widgets/registry'

// 历史栈保持非响应式（模块级实例），版本计数驱动按钮状态
const history = new HistoryStack(50)

export const useEditorStore = defineStore('editor', {
  state: () => ({
    projectId: '' as string,
    projectName: '' as string,
    revision: 0,
    doc: null as ProjectDoc | null,
    currentPageId: '' as string,
    selection: [] as string[],
    dirty: false,
    /** 变更计数：自增触发自动保存防抖 */
    dirtySeq: 0,
    saving: false,
    saveError: '' as '' | 'network' | 'conflict',
    historyVersion: 0,
    spaceHeld: false, // 空格平移模式（CanvasStage 消费）
    zoom: 1,
    pan: { x: 0, y: 0 },
    /** 剪贴板（进程内）：粘贴时重新生成全部 id 并整体偏移 10px */
    clipboard: [] as ComponentNode[],
    /** 行内编辑中的节点 id（双击文本进入，blur/Enter 提交） */
    editingNodeId: '' as string,
    /** 画布右键菜单（坐标相对画布视口） */
    contextMenu: { show: false, x: 0, y: 0 } as { show: boolean; x: number; y: number },
  }),

  getters: {
    currentPage(state): Page | null {
      return state.doc?.pages.find((p) => p.id === state.currentPageId) ?? null
    },
    /** 顶层节点（M1 约定：选择只作用于顶层，组作为整体） */
    topLevelNodes(state): ComponentNode[] {
      return this.currentPage?.components ?? []
    },
    selectedNodes(state): ComponentNode[] {
      return this.topLevelNodes.filter((n) => state.selection.includes(n.id))
    },
    /** 主选中（最后一个点选的），属性面板/缩放柄作用对象 */
    primarySelected(): ComponentNode | null {
      const sel = this.selectedNodes
      return sel.length ? sel[sel.length - 1] : null
    },
  },

  actions: {
    // ---------------- 装载与保存 ----------------

    async load(id: string): Promise<void> {
      const detail = await getProject(id)
      if (!detail.doc) throw new Error('工程 doc 为空（数据异常）')
      this.projectId = detail.id
      this.projectName = detail.name
      this.revision = detail.revision
      this.doc = detail.doc
      this.currentPageId = detail.doc.pages[0]?.id ?? ''
      this.selection = []
      this.dirty = false
      this.saveError = ''
      history.clear()
      this.historyVersion++
      this.zoom = 1
      this.pan = { x: 0, y: 0 }
    },

    _markDirty(): void {
      this.dirty = true
      this.dirtySeq++
    },

    /** 保存：PUT 全量 doc + baseRevision；失败保内存态（M1 验收：断网不丢编辑态） */
    async save(): Promise<boolean> {
      if (!this.dirty || this.saving || !this.doc) return true
      this.saving = true
      try {
        const resp = await updateProject(this.projectId, this.doc, this.revision)
        this.revision = resp.revision
        this.dirty = false
        this.saveError = ''
        return true
      } catch (err) {
        const status = (err as { response?: { status?: number } })?.response?.status
        this.saveError = status === 409 ? 'conflict' : 'network'
        return false
      } finally {
        this.saving = false
      }
    },

    /** 冲突后重新载入最新（丢弃本地，经用户确认后调用） */
    async reloadFromServer(): Promise<void> {
      await this.load(this.projectId)
    },

    // ---------------- 历史 ----------------

    beginChange(mergeKey?: string): void {
      if (!this.currentPage) return
      history.push(JSON.stringify(this.currentPage), mergeKey)
      this.historyVersion++
    },

    /** 交互未产生实际变化时回退快照（纯点击不入历史） */
    cancelChange(): void {
      history.cancelLast()
      this.historyVersion++
    },

    _applySnapshot(snap: string | null): void {
      if (!snap || !this.doc) return
      const idx = this.doc.pages.findIndex((p) => p.id === this.currentPageId)
      if (idx < 0) return
      // 整对象替换，保证深层响应性触发
      this.doc.pages[idx] = JSON.parse(snap)
      // 清掉已不存在的选中项
      const alive = new Set(this.currentPage?.components.map((c) => c.id) ?? [])
      this.selection = this.selection.filter((id) => alive.has(id))
      this.historyVersion++
      this._markDirty()
    },

    undo(): void {
      if (!this.currentPage) return
      this._applySnapshot(history.undo(JSON.stringify(this.currentPage)))
    },

    redo(): void {
      if (!this.currentPage) return
      this._applySnapshot(history.redo(JSON.stringify(this.currentPage)))
    },

    canUndo(): boolean {
      return history.canUndo
    },

    canRedo(): boolean {
      return history.canRedo
    },

    // ---------------- 选中 ----------------

    select(ids: string[]): void {
      this.selection = ids
    },

    toggleSelect(id: string): void {
      if (this.selection.includes(id)) {
        this.selection = this.selection.filter((s) => s !== id)
      } else {
        this.selection = [...this.selection, id]
      }
    },

    clearSelection(): void {
      this.selection = []
    },

    // ---------------- 组件变更（离散动作内部自带 beginChange） ----------------

    addComponent(type: WidgetType, x: number, y: number): string {
      const page = this.currentPage
      const meta = registry.get(type)
      if (!page || !meta) return ''
      this.beginChange()
      const node: ComponentNode = {
        id: newComponentId(),
        name: meta.name,
        type,
        x: Math.round(x),
        y: Math.round(y),
        w: meta.defaultSize.w,
        h: meta.defaultSize.h,
        rotate: 0,
        z: (page.components.length ? Math.max(...page.components.map((c) => c.z)) + 1 : 0),
        visible: true,
        locked: false,
        opacity: 1,
        props: meta.defaultProps(),
        bindings: [],
      }
      page.components.push(node)
      this.selection = [node.id]
      this._markDirty()
      return node.id
    },

    deleteSelection(): void {
      const page = this.currentPage
      if (!page || this.selection.length === 0) return
      this.beginChange()
      page.components = page.components.filter((c) => !this.selection.includes(c.id))
      normalizeZ(page)
      this.selection = []
      this._markDirty()
    },

    /** 清空当前页全部组件（工具栏"清空画布"，UI 层已确认） */
    clearPage(): void {
      const page = this.currentPage
      if (!page || page.components.length === 0) return
      this.beginChange()
      page.components = []
      this.selection = []
      this._markDirty()
    },

    /** 导入 JSON 覆盖当前工程 doc（宽松前端校验，服务端保存时 schema 兜底；跨 doc 替换历史清空） */
    replaceDoc(doc: ProjectDoc): boolean {
      if (!doc || !Array.isArray(doc.pages) || doc.pages.length === 0) return false
      this.doc = doc
      this.currentPageId = doc.pages[0].id
      this.selection = []
      history.clear()
      this.historyVersion++
      this._markDirty()
      return true
    },

    /** 方向键微调（1px，Shift 10px）；长按合并为一条记录 */
    nudgeSelection(dx: number, dy: number): void {
      if (this.selection.length === 0) return
      this.beginChange(`nudge:${this.selection.join(',')}`)
      for (const node of this.selectedNodes) {
        node.x += dx
        node.y += dy
      }
      this._markDirty()
    },

    /** 拖拽/缩放过程中直接写坐标（历史快照由交互开始时的 beginChange 负责） */
    setNodeRect(id: string, patch: Partial<Pick<ComponentNode, 'x' | 'y' | 'w' | 'h' | 'rotate'>>): void {
      const node = this.topLevelNodes.find((n) => n.id === id)
      if (!node) return
      Object.assign(node, patch)
      this._markDirty()
    },

    /** 属性面板通用更新（mergeKey 合并连续输入） */
    updateNode(id: string, patch: Partial<ComponentNode>, mergeKey?: string): void {
      const node = this.topLevelNodes.find((n) => n.id === id)
      if (!node) return
      this.beginChange(mergeKey)
      Object.assign(node, patch)
      this._markDirty()
    },

    updateNodeProps(id: string, key: string, value: unknown): void {
      const node = this.topLevelNodes.find((n) => n.id === id)
      if (!node) return
      this.beginChange(`props:${id}:${key}`)
      node.props = { ...node.props, [key]: value }
      this._markDirty()
    },

    updateNodeStyle(id: string, key: string, value: unknown): void {
      const node = this.topLevelNodes.find((n) => n.id === id)
      if (!node) return
      this.beginChange(`style:${id}:${key}`)
      const style: Record<string, unknown> = { ...(node.style ?? {}) }
      if (value === undefined || value === null) {
        delete style[key] // 空值=清除该键，回落默认外观
      } else {
        style[key] = value as never
      }
      node.style = style
      this._markDirty()
    },

    // ---------------- 成组 / 解组 / 图层 ----------------

    groupSelection(): void {
      const page = this.currentPage
      const members = this.selectedNodes
      if (!page || members.length < 2) return
      this.beginChange()
      const group = buildGroup(members)
      if (!group) return
      page.components = page.components.filter((c) => !this.selection.includes(c.id))
      page.components.push(group)
      normalizeZ(page)
      this.selection = [group.id]
      this._markDirty()
    },

    ungroupSelection(): void {
      const page = this.currentPage
      const targets = this.selectedNodes.filter((n) => n.type === 'group')
      if (!page || targets.length === 0) return
      this.beginChange()
      let newIds: string[] = []
      for (const g of targets) {
        const children = flattenGroup(g)
        const idx = page.components.findIndex((c) => c.id === g.id)
        page.components.splice(idx, 1, ...children)
        newIds = newIds.concat(children.map((c) => c.id))
      }
      normalizeZ(page)
      this.selection = newIds
      this._markDirty()
    },

    // ---------------- 复制 / 粘贴 / 剪切（含 children 递归重生成 id） ----------------

    _cloneWithNewIds(node: ComponentNode): ComponentNode {
      const clone: ComponentNode = JSON.parse(JSON.stringify(node))
      const rename = (n: ComponentNode): void => {
        n.id = newComponentId()
        n.bindings = n.bindings.map((b) => ({ ...b, id: newComponentId() }))
        ;(n.children ?? []).forEach(rename)
      }
      rename(clone)
      return clone
    },

    copySelection(): void {
      if (this.selection.length === 0) return
      this.clipboard = this.selectedNodes.map((n) => JSON.parse(JSON.stringify(n)) as ComponentNode)
    },

    cutSelection(): void {
      this.copySelection()
      this.deleteSelection()
    },

    /** 粘贴：重新生成全部 id（含组内与绑定 id），整体偏移 +10px，粘贴后选中新节点 */
    pasteClipboard(): void {
      const page = this.currentPage
      if (!page || this.clipboard.length === 0) return
      this.beginChange()
      const newIds: string[] = []
      let maxZ = page.components.length ? Math.max(...page.components.map((c) => c.z)) : -1
      for (const raw of this.clipboard) {
        const node = this._cloneWithNewIds(raw)
        node.x += 10
        node.y += 10
        node.z = ++maxZ
        page.components.push(node)
        newIds.push(node.id)
      }
      this.selection = newIds
      this._markDirty()
    },

    /** Ctrl+D 快速复制（等价 copy+paste，不占用剪贴板） */
    duplicateSelection(): void {
      if (this.selection.length === 0) return
      this.copySelection()
      this.pasteClipboard()
    },

    /** 行内编辑提交（快照在进入编辑时已入栈，此处直接变更） */
    setEditing(id: string): void {
      this.editingNodeId = id
    },

    commitTextEdit(id: string, text: string): void {
      const node = this.topLevelNodes.find((n) => n.id === id)
      this.editingNodeId = ''
      if (!node || node.props.text === text) return
      node.props = { ...node.props, text }
      this._markDirty()
    },

    openContextMenu(x: number, y: number): void {
      this.contextMenu = { show: true, x, y }
    },

    closeContextMenu(): void {
      this.contextMenu = { show: false, x: 0, y: 0 }
    },

    // ---------------- 对齐 / 分布（多选，参照 visual-drag-demo 的对齐集） ----------------

    alignSelection(mode: 'left' | 'right' | 'top' | 'bottom' | 'centerX' | 'centerY' | 'distributeX' | 'distributeY'): void {
      const nodes = this.selectedNodes
      const need = mode.startsWith('distribute') ? 3 : 2
      if (nodes.length < need) return
      this.beginChange(`align:${mode}`)
      const box = nodesBBox(nodes)
      switch (mode) {
        case 'left': nodes.forEach((n) => (n.x = box.x)); break
        case 'right': nodes.forEach((n) => (n.x = box.x + box.w - n.w)); break
        case 'top': nodes.forEach((n) => (n.y = box.y)); break
        case 'bottom': nodes.forEach((n) => (n.y = box.y + box.h - n.h)); break
        case 'centerX': nodes.forEach((n) => (n.x = box.x + (box.w - n.w) / 2)); break
        case 'centerY': nodes.forEach((n) => (n.y = box.y + (box.h - n.h) / 2)); break
        case 'distributeX': {
          const sorted = [...nodes].sort((a, b) => a.x - b.x)
          const first = sorted[0]
          const last = sorted[sorted.length - 1]
          const gap = (last.x - first.x) / (sorted.length - 1)
          sorted.forEach((n, i) => (n.x = Math.round(first.x + gap * i)))
          break
        }
        case 'distributeY': {
          const sorted = [...nodes].sort((a, b) => a.y - b.y)
          const first = sorted[0]
          const last = sorted[sorted.length - 1]
          const gap = (last.y - first.y) / (sorted.length - 1)
          sorted.forEach((n, i) => (n.y = Math.round(first.y + gap * i)))
          break
        }
      }
      this._markDirty()
    },

    /** z 序调整：front 置顶 / back 置底 / forward 上移一层 / backward 下移一层 */
    orderSelection(op: 'front' | 'back' | 'forward' | 'backward'): void {
      const page = this.currentPage
      if (!page || this.selection.length === 0) return
      this.beginChange()
      const zs = page.components.map((c) => c.z)
      const maxZ = Math.max(...zs)
      const minZ = Math.min(...zs)
      // 用临时分数 z 表达插入位置，再归一化为连续整数
      for (const node of this.selectedNodes) {
        if (op === 'front') node.z = maxZ + 1
        else if (op === 'back') node.z = minZ - 1
        else if (op === 'forward') node.z += 1.5
        else node.z -= 1.5
      }
      normalizeZ(page)
      this._markDirty()
    },

    // ---------------- 页面管理 ----------------

    setCurrentPage(id: string): void {
      if (id === this.currentPageId) return
      this.currentPageId = id
      this.selection = []
      history.clear()
      this.historyVersion++
    },

    addPage(): void {
      if (!this.doc) return
      this.beginChange()
      const current = this.currentPage
      const page: Page = {
        id: newPageId(),
        name: `页面 ${this.doc.pages.length + 1}`,
        order: this.doc.pages.length,
        background: { color: current?.background.color ?? '#0b1220' },
        screen: {
          designWidth: current?.screen.designWidth ?? this.doc.settings.designSize.width,
          designHeight: current?.screen.designHeight ?? this.doc.settings.designSize.height,
          mode: current?.screen.mode ?? this.doc.settings.adaptive,
        },
        components: [],
      }
      this.doc.pages.push(page)
      this.currentPageId = page.id
      this.selection = []
      history.clear()
      this.historyVersion++
      this._markDirty()
    },

    deletePage(id: string): void {
      if (!this.doc || this.doc.pages.length <= 1) return
      const idx = this.doc.pages.findIndex((p) => p.id === id)
      if (idx < 0) return
      this.beginChange()
      this.doc.pages.splice(idx, 1)
      // order 重排为连续值
      this.doc.pages.sort((a, b) => a.order - b.order).forEach((p, i) => (p.order = i))
      if (this.currentPageId === id) {
        this.currentPageId = this.doc.pages[0].id
        history.clear()
        this.selection = []
      }
      this.historyVersion++
      this._markDirty()
    },

    renamePage(id: string, name: string): void {
      const page = this.doc?.pages.find((p) => p.id === id)
      if (!page || !name.trim()) return
      this.beginChange(`page-name:${id}`)
      page.name = name.trim()
      this._markDirty()
    },

    movePage(id: string, dir: -1 | 1): void {
      if (!this.doc) return
      const pages = [...this.doc.pages].sort((a, b) => a.order - b.order)
      const idx = pages.findIndex((p) => p.id === id)
      const target = idx + dir
      if (idx < 0 || target < 0 || target >= pages.length) return
      this.beginChange()
      ;[pages[idx].order, pages[target].order] = [pages[target].order, pages[idx].order]
      this.doc.pages.sort((a, b) => a.order - b.order)
      this._markDirty()
    },

    /** 页面属性（设计尺寸/自适应/背景） */
    updatePage(screen: Partial<Page['screen']>, background?: string): void {
      const page = this.currentPage
      if (!page) return
      this.beginChange('page-screen')
      Object.assign(page.screen, screen)
      if (background !== undefined) page.background.color = background
      this._markDirty()
    },

    // ---------------- 视口 ----------------

    setZoom(z: number): void {
      this.zoom = z
    },

    setPan(x: number, y: number): void {
      this.pan = { x, y }
    },

    /** 适配视口：整页等比缩放居中（留 24px 边距，上限 1 倍）；调用方传入视口尺寸 */
    fitToView(vw: number, vh: number): void {
      const p = this.currentPage
      if (!p || vw <= 0 || vh <= 0) return
      const z = Math.min((vw - 24) / p.screen.designWidth, (vh - 24) / p.screen.designHeight, 1)
      this.zoom = Math.max(z, 0.25)
      this.pan = {
        x: (vw - p.screen.designWidth * this.zoom) / 2,
        y: (vh - p.screen.designHeight * this.zoom) / 2,
      }
    },
  },
})
