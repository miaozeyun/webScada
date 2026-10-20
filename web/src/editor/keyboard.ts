/** 编辑器快捷键：删除/撤销/重做/方向键微调/空格平移/Esc/Ctrl+A 全选。输入控件聚焦时忽略。 */
import type { useEditorStore } from '@/stores/editor'

type EditorStore = ReturnType<typeof useEditorStore>

function isTypingTarget(e: KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null
  if (!t) return false
  const tag = t.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || t.isContentEditable
}

export function installKeyboard(store: EditorStore): () => void {
  const onKeyDown = (e: KeyboardEvent): void => {
    if (isTypingTarget(e)) return
    const mod = e.ctrlKey || e.metaKey

    if (e.code === 'Space') {
      e.preventDefault()
      store.spaceHeld = true
      return
    }
    if (!mod && (e.key === 'Delete' || e.key === 'Backspace')) {
      e.preventDefault()
      store.deleteSelection()
      return
    }
    if (mod && e.key.toLowerCase() === 'z') {
      e.preventDefault()
      if (e.shiftKey) store.redo()
      else store.undo()
      return
    }
    if (mod && e.key.toLowerCase() === 'y') {
      e.preventDefault()
      store.redo()
      return
    }
    if (e.key === 'Escape') {
      store.clearSelection()
      store.closeContextMenu()
      return
    }
    // 复制/剪切/粘贴/直接复制/组合/拆分/全选（快捷键集合参照 visual-drag-demo）
    if (mod) {
      const k = e.key.toLowerCase()
      if (k === 'a') {
        e.preventDefault()
        store.select(store.topLevelNodes.map((n) => n.id))
        return
      }
      if (k === 'c') {
        e.preventDefault()
        store.copySelection()
        return
      }
      if (k === 'x') {
        e.preventDefault()
        store.cutSelection()
        return
      }
      if (k === 'v') {
        e.preventDefault()
        store.pasteClipboard()
        return
      }
      if (k === 'd') {
        e.preventDefault()
        store.duplicateSelection()
        return
      }
      if (k === 'g') {
        e.preventDefault()
        if (e.shiftKey) store.ungroupSelection()
        else store.groupSelection()
        return
      }
    }
    if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) {
      if (store.selection.length === 0) return
      e.preventDefault()
      const step = e.shiftKey ? 10 : 1
      const map: Record<string, [number, number]> = {
        ArrowUp: [0, -step],
        ArrowDown: [0, step],
        ArrowLeft: [-step, 0],
        ArrowRight: [step, 0],
      }
      const [dx, dy] = map[e.key]
      store.nudgeSelection(dx, dy)
    }
  }

  const onKeyUp = (e: KeyboardEvent): void => {
    if (e.code === 'Space') store.spaceHeld = false
  }

  window.addEventListener('keydown', onKeyDown)
  window.addEventListener('keyup', onKeyUp)
  return () => {
    window.removeEventListener('keydown', onKeyDown)
    window.removeEventListener('keyup', onKeyUp)
  }
}
