/**
 * 编辑器核心 store：全量 doc + 选中态 + 历史 + 保存链路（3s 防抖 + baseRevision 乐观锁，G2）。
 * 变更协议：所有变更先 beginChange()（交互开始时快照/合并），再改 doc，改动后 _markDirty()。
 * 历史为页面级快照，切换页面即清空（快照不含页面切换语义）。
 */
import { defineStore } from 'pinia'
import type { Binding, ComponentNode, MySymbolDef, Page, ProjectDoc, WidgetType } from '@/types/doc'
import { getProject, updateProject } from '@/api/projects'
import { PageHistory } from '@/editor/history'
import { buildGroup, flattenGroup, normalizeZ, normalizeZOf } from '@/editor/canvas/group'
import { nodesBBox } from '@/utils/coord'
import { newComponentId, newId, newPageId } from '@/utils/nanoid'
import { getSymbol } from '@/assets/symbols'
import { registry } from '@/widgets/registry'
import { normalizeComponents, normalizeDoc } from '@/utils/docNormalize'

// 历史栈保持非响应式（模块级实例），版本计数驱动按钮状态
// 跨页撤销单例（保持非响应式，版本计数驱动按钮态）。导出仅为测试隔离用，业务代码走 store action
export const history = new PageHistory(50, 200)

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
    saveError: '' as '' | 'network' | 'conflict' | 'server',
    /** 最近一次保存成功的时刻（状态栏读数；空 = 本次会话未保存过） */
    lastSavedAt: null as string | null,
    historyVersion: 0,
    spaceHeld: false, // 空格平移模式（CanvasStage 消费）
    zoom: 1,
    pan: { x: 0, y: 0 },
    /** 剪贴板（进程内）：粘贴时重新生成全部 id 并整体偏移 10px。
     *  base = 复制时所在组的原点（组内复制的子节点坐标为相对值，顶层粘贴时需还原绝对坐标） */
    clipboard: [] as ComponentNode[],
    clipboardBase: null as { x: number; y: number } | null,
    /** 行内编辑中的节点 id（双击文本进入，blur/Enter 提交） */
    editingNodeId: '' as string,
    /** 组编辑路径（栈，顶层→当前）：嵌套组逐层进入；editingGroupId 为栈顶（空 = 顶层）。
     *  双击进入；Esc/空白单击退一级并选回该组（各退出点共用此语义），面包屑可跳任意层级。 */
    editingGroupPath: [] as string[],
    editingGroupId: '' as string,
    /** 组件库拖拽载荷尺寸提示（palette dragstart 写入，画布渲染放置 ghost；dragend/drop 清除） */
    dropHint: null as { w: number; h: number; label: string } | null,
    /** 画布右键菜单（坐标相对画布视口） */
    contextMenu: { show: false, x: 0, y: 0 } as { show: boolean; x: number; y: number },
    /** 最近一次画布内指针的设计坐标（CanvasStage 悬停轨迹写入；Ctrl+V 粘贴落点跟随鼠标，
     *  离开画布/窗口失焦即清空回落 +10px 阶梯偏移，保住纯键盘路径） */
    lastPointerDesign: null as { x: number; y: number } | null,
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
      // 组编辑上下文：选中作用于该组直接子节点（坐标相对组原点），其余操作同构
      const pool = this.editingGroup ? (this.editingGroup.children ?? []) : this.topLevelNodes
      return pool.filter((n) => state.selection.includes(n.id))
    },
    /** 双击进入的编辑组：沿路径栈自顶层逐层解析（嵌套组递归进入；路径断裂回落 null） */
    editingGroup(): ComponentNode | null {
      let pool = this.topLevelNodes
      let g: ComponentNode | null = null
      for (const id of this.editingGroupPath) {
        g = pool.find((n) => n.id === id && n.type === 'group') ?? null
        if (!g) return null
        pool = g.children ?? []
      }
      return g
    },
    /** 面包屑链（页 → 各级组名）：点击任一级退到该层 */
    editingGroupChain(): { id: string; name: string }[] {
      const out: { id: string; name: string }[] = []
      let pool = this.topLevelNodes
      for (const id of this.editingGroupPath) {
        const g = pool.find((n) => n.id === id && n.type === 'group')
        if (!g) break
        out.push({ id: g.id, name: g.name || g.id })
        pool = g.children ?? []
      }
      return out
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
      this.doc = normalizeDoc(detail.doc) // 补全模板/历史工程缺省字段（bindings/locked/z 等）
      this.currentPageId = detail.doc.pages[0]?.id ?? ''
      this.selection = []
      this.editingGroupPath = []
      this.editingGroupId = ''
      this.dirty = false
      this.saveError = ''
      history.clearAll()
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
        this.lastSavedAt = new Date().toTimeString().slice(0, 8)
        return true
      } catch (err) {
        const status = (err as { response?: { status?: number } })?.response?.status
        // 有响应 = 服务端拒绝（422/500），无响应才是断网；两者排障方向完全不同，
        // 不能把 422 显示成「断网」让用户去查网络/容器。
        this.saveError = status === 409 ? 'conflict' : status ? 'server' : 'network'
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
      history.push(this.currentPageId, JSON.stringify(this.currentPage), mergeKey)
      this.historyVersion++
    },

    /** 交互未产生实际变化时回退快照（纯点击不入历史） */
    cancelChange(): void {
      history.cancelLast(this.currentPageId)
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
      this.selection = this.selection.filter((id) => alive.has(id) || !!this.findNodeDeep(id))
      this._syncEditingGroup()
      this.historyVersion++
      this._markDirty()
    },

    undo(): void {
      if (!this.currentPage) return
      this._applySnapshot(history.undo(this.currentPageId, JSON.stringify(this.currentPage)))
    },

    redo(): void {
      if (!this.currentPage) return
      this._applySnapshot(history.redo(this.currentPageId, JSON.stringify(this.currentPage)))
    },

    canUndo(): boolean {
      return history.canUndo(this.currentPageId)
    },

    canRedo(): boolean {
      return history.canRedo(this.currentPageId)
    },

    // ---------------- 选中 ----------------

    /** 递归查找节点（含组内任意层级；顶层查找的快速路径） */
    findNodeDeep(id: string): ComponentNode | null {
      const stack = [...this.topLevelNodes]
      while (stack.length) {
        const n = stack.pop()!
        if (n.id === id) return n
        if (n.children) stack.push(...n.children)
      }
      return null
    },

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

    // ---------------- 组编辑上下文（双击组进入，Esc/空白单击退出） ----------------

    /** 进入组内编辑：目标须为当前上下文的直接子级组（逐层进入，防跨层跳入）。
     *  锁定组不可进入（防误改冻结资产；画布双击锁定组会给提示）。 */
    enterGroup(id: string): void {
      const pool = this.editingGroup ? (this.editingGroup.children ?? []) : this.topLevelNodes
      const g = pool.find((n) => n.id === id && n.type === 'group')
      if (!g || g.locked) return
      this.editingGroupPath = [...this.editingGroupPath, id]
      this.editingGroupId = id
      this.selection = []
    },

    /** 退一级（调用方按需 select 回退出的组；已到顶层则无操作副作用只剩清选） */
    exitGroup(): void {
      this.editingGroupPath = this.editingGroupPath.slice(0, -1)
      this.editingGroupId = this.editingGroupPath[this.editingGroupPath.length - 1] ?? ''
      this.selection = []
    },

    /** 一步退回顶层（新增组件落顶层、整 doc 替换等场景） */
    exitAllGroups(): void {
      this.editingGroupPath = []
      this.editingGroupPath = []
      this.editingGroupId = ''
      this.selection = []
    },

    /** 面包屑跳层：截断到前 depth 级（0 = 顶层） */
    exitToGroupLevel(depth: number): void {
      this.editingGroupPath = this.editingGroupPath.slice(0, Math.max(0, depth))
      this.editingGroupId = this.editingGroupPath[this.editingGroupPath.length - 1] ?? ''
      this.selection = []
    },

    /** 快照恢复/删页等 doc 结构变化后校验编辑组仍存在，否则静默退出 */
    _syncEditingGroup(): void {
      if (this.editingGroupId && !this.editingGroup) this.exitGroup()
    },

    // ---------------- 组件变更（离散动作内部自带 beginChange） ----------------

    addComponent(type: WidgetType, x: number, y: number, extraProps?: Record<string, unknown>): string {
      const page = this.currentPage
      const meta = registry.get(type)
      if (!page || !meta) return ''
      this.exitAllGroups() // 新增组件一律落在顶层（坐标为画布绝对坐标）
      // symbol：覆盖默认尺寸（按图元 viewBox 比例）与节点名（图元中文名）
      const symbolAsset = type === 'symbol' ? getSymbol(String(extraProps?.symbolId ?? '')) : undefined
      this.beginChange()
      const node: ComponentNode = {
        id: newComponentId(),
        name: symbolAsset?.label ?? meta.name,
        type,
        x: Math.round(x),
        y: Math.round(y),
        w: symbolAsset?.w ?? meta.defaultSize.w,
        h: symbolAsset?.h ?? meta.defaultSize.h,
        rotate: 0,
        z: (page.components.length ? Math.max(...page.components.map((c) => c.z)) + 1 : 0),
        visible: true,
        locked: false,
        opacity: 1,
        props: { ...meta.defaultProps(), ...(extraProps ?? {}) },
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
      const g = this.editingGroup
      const pool = g ? (g.children ?? []) : page.components
      // 选中项可能已失效（组内删除后残留、快照恢复竞态等）：先收敛到当前上下文里真实存在的 id，
      // 否则「按 Delete 没反应」且会写一条空历史记录
      const ids = this.selection.filter((id) => pool.some((c) => c.id === id))
      if (ids.length === 0) {
        this.selection = []
        return
      }
      this.beginChange()
      if (g) {
        // 组内删除：子组件坐标相对组原点，直接剔除；组删空则连同空组一并移除并退出编辑
        g.children = (g.children ?? []).filter((c) => !ids.includes(c.id))
        this.selection = [] // 组内上下文不自动退出，但已删 id 必须清掉（否则后续操作指向幽灵节点）
        if (g.children.length === 0) {
          page.components = page.components.filter((c) => c.id !== g.id)
          normalizeZ(page)
          this.exitGroup()
        }
      } else {
        page.components = page.components.filter((c) => !ids.includes(c.id))
        normalizeZ(page)
        this.selection = []
      }
      this._markDirty()
    },

    /** 清空当前页全部组件（工具栏"清空画布"，UI 层已确认） */
    clearPage(): void {
      const page = this.currentPage
      if (!page || page.components.length === 0) return
      this.beginChange()
      page.components = []
      this.selection = []
      this.editingGroupPath = []
      this.editingGroupId = ''
      this._markDirty()
    },

    /** 导入 JSON 覆盖当前工程 doc（宽松前端校验，服务端保存时 schema 兜底；跨 doc 替换历史清空） */
    replaceDoc(doc: ProjectDoc): boolean {
      if (!doc || !Array.isArray(doc.pages) || doc.pages.length === 0) return false
      this.doc = normalizeDoc(doc) // 导入数据同口径补全缺省字段
      this.currentPageId = doc.pages[0].id
      this.selection = []
      this.editingGroupPath = []
      this.editingGroupId = ''
      history.clearAll()
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

    /** 拖拽/缩放过程中直接写坐标（历史快照由交互开始时的 beginChange 负责）。
     *  值未变（同一帧重复位置、亚像素抖动取整后相同）直接返回：避免每帧无谓的响应式写入与重渲染 */
    setNodeRect(id: string, patch: Partial<Pick<ComponentNode, 'x' | 'y' | 'w' | 'h' | 'rotate'>>): void {
      const node = this.findNodeDeep(id)
      if (!node) return
      let changed = false
      for (const k of Object.keys(patch) as (keyof typeof patch)[]) {
        if (node[k] !== patch[k]) {
          changed = true
          break
        }
      }
      if (!changed) return
      Object.assign(node, patch)
      this._markDirty()
    },

    /** 手势内写字号（选中集整体缩放的字号跟随；不另开历史记录，与手势 beginChange 同窗） */
    setNodeFontSize(id: string, fontSize: number): void {
      const node = this.findNodeDeep(id)
      if (!node || node.style?.fontSize === fontSize) return
      node.style = { ...(node.style ?? {}), fontSize }
      this._markDirty()
    },

    /** 属性面板通用更新（mergeKey 合并连续输入） */
    updateNode(id: string, patch: Partial<ComponentNode>, mergeKey?: string): void {
      const node = this.findNodeDeep(id)
      if (!node) return
      this.beginChange(mergeKey)
      Object.assign(node, patch)
      this._markDirty()
    },

    /** 多选批量更新公共字段（几何/显隐/锁定等）：单条 undo 记录覆盖全部选中项 */
    updateNodes(patch: Partial<ComponentNode>, mergeKey?: string): void {
      if (this.selection.length === 0) return
      this.beginChange(mergeKey)
      for (const node of this.selectedNodes) Object.assign(node, patch)
      this._markDirty()
    },

    /** 多选批量改样式键（空值=清除该键回落默认）；与 updateNodesStyle 单选路径语义一致 */
    updateNodesStyle(key: string, value: unknown): void {
      if (this.selection.length === 0) return
      this.beginChange(`mstyle:${key}`)
      for (const node of this.selectedNodes) {
        const style: Record<string, unknown> = { ...(node.style ?? {}) }
        if (value === undefined || value === null) delete style[key]
        else style[key] = value as never
        node.style = style
      }
      this._markDirty()
    },

    /** 台账缩略图（编辑器保存前由画布截图写入，随 doc 一并 PUT）。
     *  必须标脏：截图发生在保存动作之前，若此时已有在途保存把 dirty 清掉，缩略图会只留在内存里。 */
    setThumbnail(dataUrl: string): void {
      if (!this.doc || this.doc.project.thumbnail === dataUrl) return
      this.doc.project = { ...this.doc.project, thumbnail: dataUrl }
      this._markDirty()
    },

    updateNodeProps(id: string, key: string, value: unknown): void {
      const node = this.findNodeDeep(id)
      if (!node) return
      this.beginChange(`props:${id}:${key}`)
      node.props = { ...node.props, [key]: value }
      this._markDirty()
    },

    updateNodeStyle(id: string, key: string, value: unknown): void {
      const node = this.findNodeDeep(id)
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
      const g = this.editingGroup
      if (g) {
        // 组内成组：成员与子组坐标同系（相对组原点），剔除后追加，z 接续
        g.children = (g.children ?? []).filter((c) => !this.selection.includes(c.id))
        group.z = g.children.length ? Math.max(...g.children.map((c) => c.z)) + 1 : 0
        g.children.push(group)
      } else {
        page.components = page.components.filter((c) => !this.selection.includes(c.id))
        page.components.push(group)
        normalizeZ(page)
      }
      this.selection = [group.id]
      this._markDirty()
    },

    ungroupSelection(): void {
      const page = this.currentPage
      const targets = this.selectedNodes.filter((n) => n.type === 'group')
      if (!page || targets.length === 0) return
      this.beginChange()
      let newIds: string[] = []
      const eg = this.editingGroup
      for (const g of targets) {
        const children = eg
          ? [...(g.children ?? [])] // 组内解组：子坐标已相对父组，无需偏移还原
          : flattenGroup(g)
        if (eg) {
          const idx = (eg.children ?? []).findIndex((c) => c.id === g.id)
          eg.children!.splice(idx, 1, ...children)
        } else {
          const idx = page.components.findIndex((c) => c.id === g.id)
          page.components.splice(idx, 1, ...children)
        }
        newIds = newIds.concat(children.map((c) => c.id))
      }
      normalizeZ(page)
      if (eg) eg.children = normalizeZOf(eg.children ?? [])
      this.selection = newIds
      this._markDirty()
    },

    // ---------------- 复制 / 粘贴 / 剪切（含 children 递归重生成 id） ----------------

    _cloneWithNewIds(node: ComponentNode): ComponentNode {
      const clone: ComponentNode = JSON.parse(JSON.stringify(node))
      const rename = (n: ComponentNode): void => {
        n.id = newComponentId()
        // 防御：模板/历史数据可能缺 bindings 键（docNormalize 已在入口补全，此处兜底旧内存态）
        n.bindings = (n.bindings ?? []).map((b) => ({ ...b, id: newComponentId() }))
        ;(n.children ?? []).forEach(rename)
      }
      rename(clone)
      return clone
    },

    copySelection(): void {
      if (this.selection.length === 0) return
      this.clipboard = this.selectedNodes.map((n) => JSON.parse(JSON.stringify(n)) as ComponentNode)
      // 记录复制时所在组原点：组内子节点坐标为相对值，跨上下文粘贴时换算
      const g = this.editingGroup
      this.clipboardBase = g ? { x: g.x, y: g.y } : null
    },

    cutSelection(): void {
      this.copySelection()
      this.deleteSelection()
    },

    /** 粘贴：重新生成全部 id（含组内与绑定 id），整体偏移 +10px（连续粘贴阶梯错位），粘贴后选中新节点。
     *  at：页面绝对设计坐标（右键"粘贴到此处"/Ctrl+V 跟随鼠标），以剪贴板包围盒原点对齐；
     *  组编辑上下文内先换算为目标池相对坐标（修复组内"粘贴到此处"偏移组原点的错位）。 */
    pasteClipboard(at?: { x: number; y: number }): void {
      const page = this.currentPage
      if (!page || this.clipboard.length === 0) return
      this.beginChange()
      const eg = this.editingGroup
      // 粘贴目标上下文与来源上下文不一致时换算坐标系（组内相对 ↔ 画布绝对）
      const originX = eg ? (this.clipboardBase ? this.clipboardBase.x - eg.x : -eg.x) : (this.clipboardBase?.x ?? 0)
      const originY = eg ? (this.clipboardBase ? this.clipboardBase.y - eg.y : -eg.y) : (this.clipboardBase?.y ?? 0)
      let offX = 10
      let offY = 10
      if (at) {
        const minX = Math.min(...this.clipboard.map((n) => n.x))
        const minY = Math.min(...this.clipboard.map((n) => n.y))
        // at 为页面绝对坐标：组编辑上下文先转到目标池（eg.children）坐标系
        const atX = eg ? at.x - eg.x : at.x
        const atY = eg ? at.y - eg.y : at.y
        offX = atX - minX - originX
        offY = atY - minY - originY
      }
      const pool = eg ? (eg.children ?? []) : page.components
      const newIds: string[] = []
      let maxZ = pool.length ? Math.max(...pool.map((c) => c.z)) : -1
      for (const raw of this.clipboard) {
        const node = this._cloneWithNewIds(raw)
        node.x = Math.round(node.x + originX + offX)
        node.y = Math.round(node.y + originY + offY)
        node.z = ++maxZ
        pool.push(node)
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

    /** 给顶层组件追加值绑定（拖变量到画布生成组件的收尾步骤）。
     *  故意不另开历史记录：与紧邻的 addComponent（其 beginChange 已快照创建前状态）
     *  合并为同一条 undo；独立改绑定请走 updateNode / PropPanel。 */
    appendBinding(nodeId: string, variableId: string, prop: string): void {
      const node = this.currentPage?.components.find((c) => c.id === nodeId)
      if (!node) return
      if ((node.bindings ?? []).some((b) => b.variableId === variableId && b.prop === prop)) return
      const binding: Binding = { id: newId('bnd'), prop, variableId, mode: 'value' }
      node.bindings = [...(node.bindings ?? []), binding]
      this._markDirty()
    },

    /** Alt+拖动复制的落点：克隆当前选中（原地），改为选中克隆体并返回其 id 列表。
     *  历史：调用方已在拖动开始时 beginChange（快照为复制前状态，一次拖动 = 一条记录）。 */
    duplicateForDrag(): string[] {
      const page = this.currentPage
      const eg = this.editingGroup
      if (!page || this.selection.length === 0) return []
      const pool = eg ? (eg.children ?? []) : page.components
      const newIds: string[] = []
      let maxZ = pool.length ? Math.max(...pool.map((c) => c.z)) : -1
      for (const n of this.selectedNodes) {
        const clone = this._cloneWithNewIds(n)
        clone.z = ++maxZ
        pool.push(clone)
        newIds.push(clone.id)
      }
      this.selection = newIds
      this._markDirty()
      return newIds
    },

    // ---------------- 我的图元（M9 批次2）：doc.assets.mySymbols 资产库 ----------------

    /** 选中组件/组存为我的图元：group 展平为绝对坐标，整体归一化到包围盒原点 */
    saveMySymbol(label: string): string {
      const sel = this.selectedNodes
      const doc = this.doc
      if (sel.length === 0 || !doc) return ''
      const eg = this.editingGroup
      const flat: ComponentNode[] = []
      for (const n of sel) {
        const c = JSON.parse(JSON.stringify(n)) as ComponentNode
        if (eg) {
          // 组编辑上下文中选中的是相对坐标成员：还原绝对坐标（children 内部相对坐标不受影响）
          c.x += eg.x
          c.y += eg.y
          flat.push(c)
          continue
        }
        if (c.type === 'group') flat.push(...flattenGroup(c))
        else flat.push(c)
      }
      const minX = Math.min(...flat.map((n) => n.x))
      const minY = Math.min(...flat.map((n) => n.y))
      for (const n of flat) {
        n.x -= minX
        n.y -= minY
      }
      const sym: MySymbolDef = {
        id: newComponentId(),
        label: label.trim() || `我的图元 ${(doc.assets?.mySymbols.length ?? 0) + 1}`,
        nodes: flat,
        createdAt: new Date().toISOString(),
      }
      if (!doc.assets) doc.assets = { mySymbols: [] }
      doc.assets.mySymbols.push(sym)
      // 资产库非画布内容：不入页面撤销栈，仅标脏保存
      this._markDirty()
      return sym.id
    },

    /** 我的图元拖入/点击插入：克隆 + id 重映射，x/y 为放置原点（左上角，画布绝对坐标） */
    insertMySymbol(id: string, x: number, y: number): void {
      const page = this.currentPage
      const sym = this.doc?.assets?.mySymbols.find((s) => s.id === id)
      if (!page || !sym || sym.nodes.length === 0) return
      this.exitGroup() // 插入一律落顶层
      this.beginChange()
      let maxZ = page.components.length ? Math.max(...page.components.map((c) => c.z)) : -1
      const newIds: string[] = []
      for (const raw of normalizeComponents(sym.nodes)) {
        const node = this._cloneWithNewIds(raw)
        node.x = Math.round(x + node.x)
        node.y = Math.round(y + node.y)
        node.z = ++maxZ
        page.components.push(node)
        newIds.push(node.id)
      }
      this.selection = newIds
      this._markDirty()
    },

    deleteMySymbol(id: string): void {
      const assets = this.doc?.assets
      if (!assets) return
      const before = assets.mySymbols.length
      assets.mySymbols = assets.mySymbols.filter((s) => s.id !== id)
      if (assets.mySymbols.length !== before) this._markDirty()
    },

    /** 行内编辑提交（快照在进入编辑时已入栈，此处直接变更） */
    setEditing(id: string): void {
      this.editingNodeId = id
    },

    commitTextEdit(id: string, text: string): void {
      const node = this.findNodeDeep(id)
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
      const eg = this.editingGroup
      const pool = eg ? (eg.children ?? []) : page.components
      const zs = pool.map((c) => c.z)
      const maxZ = Math.max(...zs)
      const minZ = Math.min(...zs)
      // 用临时分数 z 表达插入位置，再归一化为连续整数
      for (const node of this.selectedNodes) {
        if (op === 'front') node.z = maxZ + 1
        else if (op === 'back') node.z = minZ - 1
        else if (op === 'forward') node.z += 1.5
        else node.z -= 1.5
      }
      if (eg) eg.children = normalizeZOf(pool)
      else normalizeZ(page)
      this._markDirty()
    },

    // ---------------- 页面管理 ----------------

    setCurrentPage(id: string): void {
      if (id === this.currentPageId) return
      this.currentPageId = id
      this.selection = []
      this.editingGroupPath = []
      this.editingGroupId = ''
      // B-3 跨页撤销：历史按页分栈，切页不清——undo/redo 只作用于当前页
      this.historyVersion++
    },

    addPage(): void {
      if (!this.doc) return
      const prevPageId = this.currentPageId
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
      this.editingGroupPath = []
      this.editingGroupId = ''
      history.cancelLast(prevPageId) // 新增页不可 undo 复活；旧页不留无操作条目
      this.historyVersion++
      this._markDirty()
    },

    /** M9 批次3：从画面模板新建页面（模板产出完整 Page；id/order 归一，切换并清历史）。
     *  组件 id 必须整体重生成：模板组件 id 是固定串，二次应用会与首次页面撞 id，
     *  服务端 validate_references「组件 id 重复」422 且脏态持续报错。 */
    applyPageTemplate(name: string, page: Page): void {
      if (!this.doc) return
      const prevPageId = this.currentPageId
      this.beginChange()
      const p = JSON.parse(JSON.stringify(page)) as Page
      p.id = newPageId()
      p.name = name
      p.order = this.doc.pages.length
      p.components = normalizeComponents(p.components.map((c) => this._cloneWithNewIds(c)))
      this.doc.pages.push(p)
      this.currentPageId = p.id
      this.selection = []
      this.editingGroupPath = []
      this.editingGroupId = ''
      history.cancelLast(prevPageId) // 模板新页不可 undo 复活；旧页不留无操作条目
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
        this.selection = []
        this.editingGroupPath = []
        this.editingGroupId = ''
      }
      history.clearPage(id) // 被删页的撤销栈随之丢弃；其余页历史保留
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
