<script setup lang="ts">
/** 组件面板：按 category 分组的图标网格；拖拽（HTML5 DnD）到画布任意位置，或点击放置到当前可视区中心。 */
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
  <div class="component-panel">
    <div class="panel-head">组件库</div>
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
  </div>
</template>

<style scoped>
.component-panel {
  height: 65%;
  display: flex;
  flex-direction: column;
  border-bottom: 1px solid var(--ws-steel-3);
}

/* 面板标题：工程分区短标题 */
.panel-head {
  height: 34px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  padding: 0 10px;
  background: var(--ws-steel-0);
  border-bottom: 1px solid var(--ws-steel-2);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--ws-text-2);
}

.component-list {
  flex: 1;
  min-height: 0;
  padding: 8px;
  display: grid;
  grid-gap: 8px;
  grid-template-columns: repeat(auto-fill, minmax(80px, 1fr));
  align-content: start;
  overflow-y: auto;
}

.group-title {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 5px 1px 0;
  font-size: 10px;
  letter-spacing: 0.08em;
  color: var(--ws-text-3);
}

.group-title::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--ws-steel-2);
}

.group-title:not(:first-child) {
  margin-top: 4px;
}

.list {
  height: 38px;
  padding: 2px 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  border: 1px solid var(--ws-steel-3);
  border-radius: var(--ws-radius);
  background: var(--ws-panel);
  color: var(--ws-text-2);
  cursor: grab;
  user-select: none;
  text-align: center;
}

.list:active {
  cursor: grabbing;
}

.list:hover {
  border-color: var(--ws-signal);
  background: var(--ws-signal-soft);
  color: var(--ws-signal);
}

.label {
  font-size: 11.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 触屏 / 窄面板：减少网格列宽浪费 */
@media (max-width: 1200px) {
  .component-list {
    grid-template-columns: repeat(auto-fill, minmax(76px, 1fr));
  }
}
</style>
