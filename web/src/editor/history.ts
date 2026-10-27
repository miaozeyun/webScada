/**
 * undo/redo 历史栈：页面级 JSON 快照（D7=A 拍板）。
 * - 深拷贝用 JSON 序列化实现（G22：不使用 structuredClone）
 * - 提交式入栈：调用方在交互开始（松手/防抖合并后）调用 push
 * - mergeKey：属性面板连续编辑等场景，同 key 800ms 内合并为一条记录
 * - 上限 50 步，淘汰最旧
 */
export class HistoryStack {
  private undoStack: string[] = []
  private redoStack: string[] = []
  private lastKey = ''
  private lastTime = 0

  constructor(private readonly limit = 50) {}

  /** 推入变更前快照；mergeKey 相同且在合并窗口内时跳过（并入上一条记录） */
  push(snapshot: string, mergeKey?: string): void {
    const now = Date.now()
    if (mergeKey !== undefined && mergeKey !== '' && mergeKey === this.lastKey && now - this.lastTime < 800) {
      this.lastTime = now
      this.redoStack = []
      return
    }
    this.undoStack.push(snapshot)
    if (this.undoStack.length > this.limit) {
      this.undoStack.shift() // 淘汰最旧
    }
    this.redoStack = []
    this.lastKey = mergeKey ?? ''
    this.lastTime = now
  }

  /** 撤销：返回要恢复的快照；current 为当前状态（转入 redo 栈） */
  undo(current: string): string | null {
    if (this.undoStack.length === 0) return null
    const snap = this.undoStack.pop()!
    this.redoStack.push(current)
    this.lastKey = ''
    return snap
  }

  /** 重做：返回要恢复的快照 */
  redo(current: string): string | null {
    if (this.redoStack.length === 0) return null
    const snap = this.redoStack.pop()!
    this.undoStack.push(current)
    this.lastKey = ''
    return snap
  }

  /** 撤销刚推入的记录（如拖拽未实际移动时回退快照，保证"一次拖拽仅 1 条记录且纯点击无记录"） */
  cancelLast(): void {
    this.undoStack.pop()
    this.lastKey = ''
  }

  clear(): void {
    this.undoStack = []
    this.redoStack = []
    this.lastKey = ''
  }

  get canUndo(): boolean {
    return this.undoStack.length > 0
  }

  get canRedo(): boolean {
    return this.redoStack.length > 0
  }

  /** undo 栈当前条目数（PageHistory 全局配额统计用） */
  get size(): number {
    return this.undoStack.length
  }

  /** 淘汰最旧一条（全局上限触发时由 PageHistory 调用） */
  popOldest(): void {
    this.undoStack.shift()
    this.lastKey = ''
  }
}

/**
 * 跨页撤销管理（B-3）：每页独立 HistoryStack + 全局 undo 条目总量上限。
 * - 切页不清栈：undo/redo 只作用于当前页（页内快照互不串扰）
 * - 全局超限（默认 200）时按 LRU 淘汰「最久未活动页」的栈底条目，防多页快照内存膨胀
 * - 整 doc 替换（load/replaceDoc）才 clearAll；删页 clearPage
 */
export class PageHistory {
  private stacks = new Map<string, HistoryStack>()
  private lru: string[] = []

  constructor(
    private readonly perPage = 50,
    private readonly globalLimit = 200,
  ) {}

  private touch(pageId: string): void {
    const i = this.lru.indexOf(pageId)
    if (i >= 0) this.lru.splice(i, 1)
    this.lru.push(pageId)
  }

  private stackOf(pageId: string): HistoryStack {
    let s = this.stacks.get(pageId)
    if (!s) {
      s = new HistoryStack(this.perPage)
      this.stacks.set(pageId, s)
      this.touch(pageId)
    }
    return s
  }

  private totalUndo(): number {
    let n = 0
    for (const s of this.stacks.values()) n += s.size
    return n
  }

  private evictOverflow(except: string): void {
    while (this.totalUndo() > this.globalLimit) {
      // 最久未活动页先掏栈底；只剩当前页时由 perPage 上限兜底，不误伤
      const victim = this.lru.find((id) => id !== except && (this.stacks.get(id)?.size ?? 0) > 0)
      if (!victim) return
      const s = this.stacks.get(victim)!
      s.popOldest()
      if (s.size === 0 && !s.canRedo) this.stacks.delete(victim)
      this.touch(victim)
    }
  }

  push(pageId: string, snapshot: string, mergeKey?: string): void {
    this.stackOf(pageId).push(snapshot, mergeKey)
    this.touch(pageId)
    this.evictOverflow(pageId)
  }

  cancelLast(pageId: string): void {
    this.stacks.get(pageId)?.cancelLast()
  }

  undo(pageId: string, current: string): string | null {
    const s = this.stacks.get(pageId)
    if (!s) return null
    this.touch(pageId)
    return s.undo(current)
  }

  redo(pageId: string, current: string): string | null {
    const s = this.stacks.get(pageId)
    if (!s) return null
    this.touch(pageId)
    return s.redo(current)
  }

  canUndo(pageId: string): boolean {
    return this.stacks.get(pageId)?.canUndo ?? false
  }

  canRedo(pageId: string): boolean {
    return this.stacks.get(pageId)?.canRedo ?? false
  }

  clearPage(pageId: string): void {
    this.stacks.delete(pageId)
    const i = this.lru.indexOf(pageId)
    if (i >= 0) this.lru.splice(i, 1)
  }

  clearAll(): void {
    this.stacks.clear()
    this.lru = []
  }
}
