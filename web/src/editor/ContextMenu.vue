<script setup lang="ts">
/**
 * 画布右键菜单（菜单项集合参照 visual-drag-demo，MIT 见 THIRD_PARTY_NOTICES.md）：
 * 组件上：复制/粘贴/剪切/删除/锁定|解锁/置顶/置底/上移/下移/组合|拆分；空白处：粘贴。
 */
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useEditorStore } from '@/stores/editor'

const editor = useEditorStore()

const hasSelection = computed(() => editor.selection.length > 0)
const allLocked = computed(() => editor.selectedNodes.length > 0 && editor.selectedNodes.every((n) => n.locked))
const hasGroup = computed(() => editor.selectedNodes.some((n) => n.type === 'group'))

function run(fn: () => void): void {
  editor.closeContextMenu()
  fn()
}

// 点击任意处/滚轮 关闭菜单
function onGlobalDown(): void {
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
      </template>
      <template v-else>
        <li :class="{ disabled: editor.clipboard.length === 0 }" @click="editor.clipboard.length && run(() => editor.pasteClipboard())">粘贴</li>
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
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
  box-sizing: border-box;
}

li {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 24px;
  padding: 0 20px;
  font-size: 14px;
  height: 34px;
  line-height: 34px;
  color: #606266;
  cursor: pointer;
  white-space: nowrap;
}

li:hover {
  background: #f5f7fa;
}

li.disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

li.danger:hover {
  color: #f56c6c;
}

li.sep {
  height: 1px;
  padding: 0;
  margin: 4px 12px;
  background: #e4e7ed;
  cursor: default;
}

li.sep:hover {
  background: #e4e7ed;
}

kbd {
  color: #c0c4cc;
  font-size: 11px;
  font-family: inherit;
}
</style>
