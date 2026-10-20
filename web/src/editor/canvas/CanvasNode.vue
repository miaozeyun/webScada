<script setup lang="ts">
/**
 * 画布节点（递归）：几何定位/旋转/透明度在此层，内容渲染委托 WidgetHost。
 * 组节点递归渲染 children（子坐标相对组原点，嵌套 div 天然实现坐标系嵌套）。
 * 编辑器内 visible=false 以 30% 透明度呈现（否则无法再选中改回）；运行态由 M4 处理。
 * 双击文本组件 → 行内编辑（contenteditable，blur/Enter 提交；模式参照 visual-drag-demo）。
 */
import { computed, nextTick, ref } from 'vue'
import type { ComponentNode } from '@/types/doc'
import { useEditorStore } from '@/stores/editor'
import { animationOf } from '@/utils/animation'
import WidgetHost from '@/widgets/WidgetHost.vue'

const props = defineProps<{ node: ComponentNode }>()
const editor = useEditorStore()

const emit = defineEmits<{
  (e: 'node-down', ev: PointerEvent, node: ComponentNode): void
  (e: 'node-dblclick', node: ComponentNode): void
}>()

const isLocked = computed(() => props.node.locked === true)
const isSelected = computed(() => editor.selection.includes(props.node.id))
const isEditing = computed(() => editor.editingNodeId === props.node.id)
const anim = computed(() => animationOf(props.node.animations))

const editEl = ref<HTMLDivElement>()

const boxStyle = computed(() => ({
  left: `${props.node.x}px`,
  top: `${props.node.y}px`,
  width: `${props.node.w}px`,
  height: `${props.node.h}px`,
  transform: props.node.rotate ? `rotate(${props.node.rotate}deg)` : undefined,
  zIndex: props.node.z,
  opacity: props.node.visible === false ? 0.3 : (props.node.opacity ?? 1),
  cursor: isLocked.value ? 'not-allowed' : 'move',
  ...anim.value.style,
}))

function onDown(e: PointerEvent): void {
  // 行内编辑中不进入拖拽（等价于 visual-drag-demo 的 canEdit stopPropagation）
  if (isEditing.value) {
    e.stopPropagation()
    return
  }
  // 阻止默认行为：防文本选择与浏览器原生拖拽劫持 pointer 流（触发 pointercancel 中断拖动）
  e.preventDefault()
  emit('node-down', e, props.node)
}

function onDblClick(): void {
  emit('node-dblclick', props.node)
}

/** 进入编辑态后自动聚焦并全选 */
async function focusEdit(): Promise<void> {
  await nextTick()
  const el = editEl.value
  if (el) {
    el.focus()
    const range = document.createRange()
    range.selectNodeContents(el)
    const sel = window.getSelection()
    sel?.removeAllRanges()
    sel?.addRange(range)
  }
}

function commitEdit(): void {
  const text = editEl.value?.innerText ?? ''
  editor.commitTextEdit(props.node.id, text.replace(/\n$/, ''))
}

function onEditKeydown(e: KeyboardEvent): void {
  e.stopPropagation() // 编辑态不触发画布快捷键（Delete/方向键等）
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    commitEdit()
  }
  if (e.key === 'Escape') {
    editor.setEditing('') // 放弃修改
  }
}
</script>

<template>
  <div
    class="canvas-node"
    :class="[{ selected: isSelected, group: node.type === 'group', editing: isEditing }, anim.cls]"
    :style="boxStyle"
    @pointerdown.stop="onDown($event)"
    @dblclick.stop="onDblClick"
  >
    <WidgetHost :node="node" />
    <!-- 行内文本编辑 -->
    <div
      v-if="isEditing"
      ref="editEl"
      class="inline-edit"
      contenteditable="true"
      @vue:mounted="focusEdit()"
      @blur="commitEdit"
      @keydown="onEditKeydown"
      @pointerdown.stop
    >
      {{ node.props.text }}
    </div>
    <!-- 锁定标识（参照 Shape.vue icon-suo） -->
    <span v-if="isLocked" class="iconfont icon-suo lock-badge" title="已锁定（可选中，不可拖动）"></span>
    <template v-if="node.type === 'group' && node.children">
      <!-- 子组件的按下事件一律上报顶层祖先（M1 约定：选择/拖拽只作用于顶层节点，组为整体） -->
      <CanvasNode v-for="child in node.children" :key="child.id" :node="child" @node-down="(ev, _child) => $emit('node-down', ev, node)" @node-dblclick="$emit('node-dblclick', node)" />
    </template>
  </div>
</template>

<style scoped>
.canvas-node {
  position: absolute;
  box-sizing: border-box;
  /* 画布编辑必备：禁文本选择与原生拖拽，否则浏览器会以 text-drag 劫持并 pointercancel 我们的拖动 */
  user-select: none;
  -webkit-user-select: none;
  -webkit-user-drag: none;
}

/* 选中态参照 visual-drag-demo Shape.vue .active：outline 1px #70c0ff */
.canvas-node.selected {
  outline: 1px solid #70c0ff;
}

.canvas-node.group {
  border: 1px dashed rgba(112, 192, 255, 0.4);
}

.inline-edit {
  position: absolute;
  inset: 0;
  background: #fff;
  color: #606266;
  outline: 1px solid #70c0ff;
  padding: 0 6px;
  display: flex;
  align-items: center;
  cursor: text;
  white-space: pre-wrap;
  user-select: text;
  -webkit-user-select: text;
}

.lock-badge {
  position: absolute;
  top: 0;
  right: 0;
  font-size: 16px;
  color: #909399;
  pointer-events: none;
}
</style>
