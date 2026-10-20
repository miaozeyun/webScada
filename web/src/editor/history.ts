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
}
