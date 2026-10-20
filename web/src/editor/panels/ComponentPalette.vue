<script setup lang="ts">
/** 组件面板（样式参照 visual-drag-demo ComponentList.vue）：
 * 80×40 图标网格 + iconfont 图标；拖拽（HTML5 DnD）到画布任意位置，或点击放置到当前可视区中心。 */
import { paletteByCategory, registry } from '@/widgets/registry'
import { useEditorStore } from '@/stores/editor'

const editor = useEditorStore()
const basics = paletteByCategory('basic')

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
    <div
      v-for="meta in basics"
      :key="meta.type"
      class="list"
      draggable="true"
      :title="meta.name"
      @dragstart="onDragStart($event, meta.type)"
      @click="onClick(meta.type)"
    >
      <span class="iconfont" :class="'icon-' + meta.icon"></span>
      <span class="label">{{ meta.name }}</span>
    </div>
    <div class="palette-tip">拖入画布任意位置，或点击放到画布中心。图表/设备组件在 M2 阶段注册。</div>
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

.palette-tip {
  grid-column: 1 / -1;
  color: #909399;
  font-size: 12px;
  line-height: 1.6;
}
</style>
