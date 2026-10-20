<script setup lang="ts">
/**
 * 选中层：主选中（单选）绘制 8 向缩放柄 + 旋转柄；多选绘制整体包围框（无柄）。
 * M1 约定（风险对策）：缩放柄按轴对齐包围盒工作（不做斜向缩放数学），
 * 选中框不对自身应用 rotate —— 旋转组件的柄位为其未旋转包围盒位置（已知限制）。
 * 柄尺寸按 1/zoom 缩放保持屏幕视觉恒定。
 */
import { computed } from 'vue'
import { RefreshRight } from '@element-plus/icons-vue'
import { useEditorStore } from '@/stores/editor'
import { nodesBBox } from '@/utils/coord'
import type { ResizeDir } from './types'

const emit = defineEmits<{
  (e: 'resize-start', dir: ResizeDir, ev: PointerEvent): void
  (e: 'rotate-start', ev: PointerEvent): void
}>()

const editor = useEditorStore()

const primary = computed(() => editor.primarySelected)
const multiBox = computed(() => {
  const sel = editor.selectedNodes
  return sel.length > 1 ? nodesBBox(sel) : null
})

const handleSize = computed(() => 8 / editor.zoom)
const rotateOffset = computed(() => -34 / editor.zoom)

const DIRS: ResizeDir[] = ['n', 'ne', 'e', 'se', 's', 'sw', 'w', 'nw']

function handlePos(dir: ResizeDir) {
  const n = primary.value!
  const hs = handleSize.value
  const half = n.w / 2
  const halfH = n.h / 2
  const map: Record<ResizeDir, { left: number; top: number }> = {
    n: { left: half, top: 0 },
    ne: { left: n.w, top: 0 },
    e: { left: n.w, top: halfH },
    se: { left: n.w, top: n.h },
    s: { left: half, top: n.h },
    sw: { left: 0, top: n.h },
    w: { left: 0, top: halfH },
    nw: { left: 0, top: 0 },
  }
  const p = map[dir]
  return {
    left: `${p.left - hs / 2}px`,
    top: `${p.top - hs / 2}px`,
    width: `${hs}px`,
    height: `${hs}px`,
  }
}
</script>

<template>
  <div v-if="primary" class="selection-layer">
    <!-- 主选中框（轴对齐） -->
    <div class="sel-box" :style="{ left: `${primary.x}px`, top: `${primary.y}px`, width: `${primary.w}px`, height: `${primary.h}px` }">
      <!-- 旋转柄（顶部上方） -->
      <el-icon
        class="rotate-handle"
        :style="{ top: `${rotateOffset}px`, fontSize: `${20 / editor.zoom}px` }"
        title="拖动旋转（近 15° 倍数自动吸附）"
        @pointerdown.stop="emit('rotate-start', $event)"
      ><RefreshRight /></el-icon>
      <!-- 8 向缩放柄 -->
      <div
        v-for="dir in DIRS"
        :key="dir"
        class="handle"
        :style="handlePos(dir)"
        @pointerdown.stop="emit('resize-start', dir, $event)"
      />
    </div>
    <!-- 多选整体包围框 -->
    <div v-if="multiBox" class="multi-box" :style="{ left: `${multiBox.x}px`, top: `${multiBox.y}px`, width: `${multiBox.w}px`, height: `${multiBox.h}px` }" />
  </div>
</template>

<style scoped>
/* 数值参照 visual-drag-demo Shape.vue：outline 1px var(--ws-select)、柄 8px 白底圆点 1px var(--ws-select) */
.sel-box {
  position: absolute;
  border: 1px solid var(--ws-select);
  box-sizing: border-box;
  pointer-events: none;
}

.multi-box {
  position: absolute;
  border: 1px dashed var(--ws-select);
  pointer-events: none;
}

.handle {
  position: absolute;
  background: var(--ws-panel);
  border: 1px solid var(--ws-select);
  box-sizing: border-box;
  pointer-events: auto;
  cursor: nwse-resize;
  border-radius: 50%;
}

.rotate-handle {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  cursor: grab;
  color: var(--ws-select);
  font-size: 20px;
  font-weight: 600;
  pointer-events: auto;
}

.rotate-handle:active {
  cursor: grabbing;
}
</style>
