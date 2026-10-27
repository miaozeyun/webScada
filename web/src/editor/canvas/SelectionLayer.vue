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

/** 组编辑上下文：子节点坐标相对组原点，选中层整体平移到组坐标系 */
const offset = computed(() => {
  const g = editor.editingGroup
  return g ? { x: g.x, y: g.y } : { x: 0, y: 0 }
})

const handleSize = computed(() => 8 / editor.zoom)
const rotateOffset = computed(() => -34 / editor.zoom)

const DIRS: ResizeDir[] = ['n', 'ne', 'e', 'se', 's', 'sw', 'w', 'nw']

/** 柄在包围盒内的归一化位置（单件用主选中尺寸，多选用选中集包围盒） */
function handlePos(dir: ResizeDir, rect: { w: number; h: number }) {
  const hs = handleSize.value
  const half = rect.w / 2
  const halfH = rect.h / 2
  const map: Record<ResizeDir, { left: number; top: number }> = {
    n: { left: half, top: 0 },
    ne: { left: rect.w, top: 0 },
    e: { left: rect.w, top: halfH },
    se: { left: rect.w, top: rect.h },
    s: { left: half, top: rect.h },
    sw: { left: 0, top: rect.h },
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
    <!-- 主选中框（轴对齐；多选时整体隐藏——柄只作用于主选中件，多选下留着就是「改一个伤一片」的陷阱，
         仅保留下方 multi-box 虚线包围框与整体拖动；待「选中集整体变换」落地后按选中集语义恢复柄） -->
    <div
      v-if="!multiBox"
      class="sel-box"
      :style="{ left: `${offset.x + primary.x}px`, top: `${offset.y + primary.y}px`, width: `${primary.w}px`, height: `${primary.h}px` }"
    >
      <!-- 旋转柄（顶部上方） -->
      <el-icon
        class="rotate-handle"
        :style="{ top: `${rotateOffset}px`, fontSize: `${20 / editor.zoom}px` }"
        title="拖动旋转（近 15° 倍数自动吸附，按住 Shift 临时脱离）"
        @pointerdown.stop="emit('rotate-start', $event)"
      ><RefreshRight /></el-icon>
      <!-- 8 向缩放柄 -->
      <div
        v-for="dir in DIRS"
        :key="dir"
        class="handle"
        :style="handlePos(dir, primary)"
        @pointerdown.stop="emit('resize-start', dir, $event)"
      />
      <!-- 尺寸徽标：右下角 W×H 读数（字号按 1/zoom 补偿保持屏幕恒定） -->
      <span
        class="size-badge"
        :style="{
          top: `${primary.h + 6 / editor.zoom}px`,
          fontSize: `${11 / editor.zoom}px`,
          padding: `${2 / editor.zoom}px ${6 / editor.zoom}px`,
          borderRadius: `${2 / editor.zoom}px`,
        }"
      >{{ Math.round(primary.w) }} × {{ Math.round(primary.h) }}</span>
    </div>
    <!-- 多选整体包围框：选中集整体缩放/旋转柄（角柄等比/边柄单轴/绕中心旋转） -->
    <div
      v-if="multiBox"
      class="multi-box has-handles"
      :style="{ left: `${offset.x + multiBox.x}px`, top: `${offset.y + multiBox.y}px`, width: `${multiBox.w}px`, height: `${multiBox.h}px` }"
    >
      <el-icon
        class="rotate-handle"
        :style="{ top: `${rotateOffset}px`, fontSize: `${20 / editor.zoom}px` }"
        title="拖动整体旋转（近 15° 倍数自动吸附，按住 Shift 临时脱离）"
        @pointerdown.stop="emit('rotate-start', $event)"
      ><RefreshRight /></el-icon>
      <div
        v-for="dir in DIRS"
        :key="dir"
        class="handle"
        :style="handlePos(dir, multiBox)"
        @pointerdown.stop="emit('resize-start', dir, $event)"
      />
      <span
        class="size-badge"
        :style="{
          top: `${multiBox.h + 6 / editor.zoom}px`,
          fontSize: `${11 / editor.zoom}px`,
          padding: `${2 / editor.zoom}px ${6 / editor.zoom}px`,
          borderRadius: `${2 / editor.zoom}px`,
        }"
      >{{ Math.round(multiBox.w) }} × {{ Math.round(multiBox.h) }}</span>
    </div>
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

/* 带柄的多选包围框：柄/旋转柄可交互（盒体本身仍不拦截画布事件） */
.multi-box.has-handles {
  pointer-events: none;
}

.multi-box.has-handles .handle,
.multi-box.has-handles .rotate-handle {
  pointer-events: auto;
}

/* 多选徽标不挡柄：贴包围盒下沿居中 */
.multi-box.has-handles .size-badge {
  pointer-events: none;
}

/* 尺寸徽标：选中框下方居中的等宽读数，信号色底反白 */
.size-badge {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  white-space: nowrap;
  background: var(--ws-select);
  color: var(--ws-text-inverse);
  font-family: var(--ws-font-tech);
  font-variant-numeric: tabular-nums;
  line-height: 1.3;
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
