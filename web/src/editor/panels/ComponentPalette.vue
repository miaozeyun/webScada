<script setup lang="ts">
/** 组件面板（样式参照 visual-drag-demo ComponentList.vue，按 category 分组）：
 * 80×40 图标网格；拖拽（HTML5 DnD）到画布任意位置，或点击放置到当前可视区中心。 */
import { useEditorStore } from '@/stores/editor'
import { paletteByCategory, registry } from '@/widgets/registry'
import WidgetIcon from '@/widgets/WidgetIcon.vue'

const editor = useEditorStore()

const GROUPS = [
  { label: '基础', category: 'basic' as const },
  { label: '图表', category: 'chart' as const },
  { label: '设备', category: 'device' as const },
]

function onDragStart(e: DragEvent, type: string): void {
  // 双类型写入：标准类型 + text/plain 兜底（Firefox dataTransfer 兼容）
  e.dataTransfer?.setData('application/x-widget', type)
  e.dataTransfer?.setData('text/plain', type)
  e.dataTransfer!.effectAllowed = 'copy'
}

/** 点击放置：当前可视区中心（而非设计坐标中心——画布可能平移/缩放） */
function onClick(type: string): void {
  const vp = document.querySelector('.canvas-viewport')?.getBoundingClientRect()
  const meta = registry.get(type as never)
  if (!vp || !meta) return
  const cx = (vp.width / 2 - editor.pan.x) / editor.zoom
  const cy = (vp.height / 2 - editor.pan.y) / editor.zoom
  editor.addComponent(type as never, cx - meta.defaultSize.w / 2, cy - meta.defaultSize.h / 2)
}
</script>

<template>
  <div class="component-list">
    <template v-for="g in GROUPS" :key="g.category">
      <div class="group-title">{{ g.label }}</div>
      <div
        v-for="meta in paletteByCategory(g.category)"
        :key="meta.type"
        class="list"
        draggable="true"
        :title="meta.name"
        @dragstart="onDragStart($event, meta.type)"
        @click="onClick(meta.type)"
      >
        <WidgetIcon :meta="meta" />
        <span class="label">{{ meta.name }}</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.component-list {
  height: 65%;
  box-sizing: border-box;
  padding: 8px;
  display: grid;
  grid-gap: 10px 10px;
  grid-template-columns: repeat(auto-fill, minmax(84px, 1fr));
  align-content: start;
  overflow-y: auto;
}

.group-title {
  grid-column: 1 / -1;
  font-size: 12px;
  color: #909399;
  padding: 4px 2px 0;
}

.group-title:not(:first-child) {
  margin-top: 6px;
}

.list {
  height: 40px;
  border: 1px solid #ddd;
  cursor: grab;
  text-align: center;
  padding: 2px 5px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  user-select: none;
  color: var(--text-color, #606266);
}

.list:active {
  cursor: grabbing;
}

.list:hover {
  border-color: var(--actived-text-color, #409eff);
  color: var(--actived-text-color, #409eff);
}

.iconfont {
  font-size: 20px;
}

.label {
  font-size: 12px;
}
</style>
