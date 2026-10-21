<script setup lang="ts">
/**
 * 画布右键菜单（菜单项集合参照 visual-drag-demo，MIT 见 THIRD_PARTY_NOTICES.md）：
 * 组件上：复制/粘贴/剪切/删除/锁定|解锁/置顶/置底/上移/下移/组合|拆分；空白处：粘贴。
 */
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useEditorStore } from '@/stores/editor'

const editor = useEditorStore()

const hasSelection = computed(() => editor.selection.length > 0)
const allLocked = computed(() => editor.selectedNodes.length > 0 && editor.selectedNodes.every((n) => n.locked))
const hasGroup = computed(() => editor.selectedNodes.some((n) => n.type === 'group'))
const primaryGroup = computed(() => {
  const n = editor.primarySelected
  return n && n.type === 'group' && !n.locked ? n : null
})

function enterPrimaryGroup(): void {
  const g = primaryGroup.value
  if (g) editor.enterGroup(g.id)
}

/** 右键位置（视口坐标）换算设计坐标：粘贴到此处 */
function menuDesignPoint(): { x: number; y: number } {
  return {
    x: (editor.contextMenu.x - editor.pan.x) / editor.zoom,
    y: (editor.contextMenu.y - editor.pan.y) / editor.zoom,
  }
}

function run(fn: () => void): void {
  editor.closeContextMenu()
  fn()
}

/** M9 批次2：选中组件存为可复用图元（资产面板「我的」Tab） */
async function saveAsMySymbol(): Promise<void> {
  const first = editor.selectedNodes[0]
  if (!first) return
  try {
    const { value } = await ElMessageBox.prompt('图元名称', '存为我的图元', {
      inputValue: first.name,
      inputValidator: (v: string) => v.trim().length > 0 || '名称不能为空',
    })
    editor.saveMySymbol(value)
    ElMessage.success('已存入「我的」图元库')
  } catch {
    /* 取消 */
  }
}

// 点击菜单外任意处关闭菜单。
// 注意不能用"捕获阶段直接关"：close 会让 v-if 摘除菜单 DOM，进行中的 click 失去 target
// 不再派发——菜单项将永远点不动（存量缺陷，2026-10-21 修复：跳过菜单自身内的 pointerdown）。
function onGlobalDown(e: PointerEvent): void {
  if ((e.target as HTMLElement | null)?.closest('.ws-contextmenu')) return
  editor.closeContextMenu()
}
onMounted(() => window.addEventListener('pointerdown', onGlobalDown, true))
onBeforeUnmount(() => window.removeEventListener('pointerdown', onGlobalDown, true))
</script>

<template>
  <div
    v-if="editor.contextMenu.show"
    class="ws-contextmenu"
    :style="{ left: `${editor.contextMenu.x}px`, top: `${editor.contextMenu.y}px` }"
    @pointerdown.stop
    @contextmenu.prevent
  >
    <ul>
      <template v-if="hasSelection">
        <li v-if="!allLocked" @click="run(() => editor.copySelection())">复制 <kbd>Ctrl+C</kbd></li>
        <li v-if="!allLocked" @click="run(() => editor.pasteClipboard())">粘贴 <kbd>Ctrl+V</kbd></li>
        <li v-if="!allLocked" @click="run(() => editor.cutSelection())">剪切 <kbd>Ctrl+X</kbd></li>
        <li v-if="!allLocked" @click="run(() => editor.duplicateSelection())">直接复制 <kbd>Ctrl+D</kbd></li>
        <li class="danger" @click="run(() => editor.deleteSelection())">删除 <kbd>Delete</kbd></li>
        <li class="sep" />
        <li v-if="!allLocked" @click="run(() => editor.updateNode(editor.selection[0], { locked: true }))">锁定</li>
        <li v-if="allLocked" @click="run(() => editor.selectedNodes.forEach((n) => editor.updateNode(n.id, { locked: false })))">解锁</li>
        <li class="sep" />
        <li @click="run(() => editor.orderSelection('front'))">置顶</li>
        <li @click="run(() => editor.orderSelection('forward'))">上移一层</li>
        <li @click="run(() => editor.orderSelection('backward'))">下移一层</li>
        <li @click="run(() => editor.orderSelection('back'))">置底</li>
        <li v-if="!allLocked && editor.selection.length >= 2" class="sep" />
        <li v-if="!allLocked && editor.selection.length >= 2" @click="run(() => editor.groupSelection())">组合 <kbd>Ctrl+G</kbd></li>
        <li v-if="!allLocked && hasGroup" @click="run(() => editor.ungroupSelection())">拆分 <kbd>Ctrl+Shift+G</kbd></li>
        <li v-if="primaryGroup" @click="run(enterPrimaryGroup)">进入组内编辑 <kbd>双击</kbd></li>
        <li v-if="!allLocked" class="sep" />
        <li v-if="!allLocked" @click="run(() => saveAsMySymbol())">存为我的图元</li>
      </template>
      <template v-else>
        <li v-if="editor.editingGroupId" @click="run(() => { const gid = editor.editingGroupId; editor.exitGroup(); if (gid) editor.select([gid]) })">退出组内编辑 <kbd>Esc</kbd></li>
        <li v-if="editor.editingGroupId" class="sep" />
        <li :class="{ disabled: editor.clipboard.length === 0 }" @click="editor.clipboard.length && run(() => editor.pasteClipboard())">粘贴 <kbd>Ctrl+V</kbd></li>
        <li :class="{ disabled: editor.clipboard.length === 0 }" @click="editor.clipboard.length && run(() => editor.pasteClipboard(menuDesignPoint()))">粘贴到此处</li>
      </template>
    </ul>
  </div>
</template>

<style scoped>
.ws-contextmenu {
  position: absolute;
  z-index: 1000;
}

/* 数值参照 visual-drag-demo ContextMenu.vue：#e4e7ed 边框 / 34px 行 / hover #f5f7fa */
ul {
  min-width: 176px;
  margin: 5px 0;
  padding: 6px 0;
  list-style: none;
  background: var(--ws-panel);
  border: 1px solid var(--ws-steel-3);
  border-radius: var(--ws-radius);
  box-shadow: 0 6px 20px rgba(20, 33, 46, 0.14);
  box-sizing: border-box;
}

li {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 24px;
  padding: 0 20px;
  font-size: 13px;
  height: 34px;
  line-height: 34px;
  color: var(--ws-text);
  cursor: pointer;
  white-space: nowrap;
}

li:hover {
  background: var(--ws-signal-soft);
  color: var(--ws-signal);
}

li.disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

li.danger:hover {
  color: var(--ws-alert);
  background: var(--ws-alert-soft);
}

li.sep {
  height: 1px;
  padding: 0;
  margin: 4px 12px;
  background: var(--ws-steel-2);
  cursor: default;
}

li.sep:hover {
  background: var(--ws-steel-2);
}

kbd {
  color: var(--ws-text-3);
  font-size: 11px;
  font-family: var(--ws-font-mono);
}
</style>
