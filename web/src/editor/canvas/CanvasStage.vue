<script setup lang="ts">
/**
 * 画布容器：视口（平移/缩放）+ 页面（设计尺寸）+ 交互状态机。
 * 交互：拖拽移动（吸附）、8 向缩放、旋转、框选、空格/中键平移、Ctrl+滚轮缩放（25%~400%）、拖入组件。
 * 快照协议：move/resize/rotate 在 pointerdown 时 beginChange，未实际移动在 up 时 cancelChange
 * （保证"一次拖拽全程仅 1 条 undo 记录、纯点击零记录"）。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ComponentNode } from '@/types/doc'
import { useEditorStore } from '@/stores/editor'
import { registry } from '@/widgets/registry'
import { bboxIntersect, clamp, nodesBBox } from '@/utils/coord'
import { calcResize, handlePoint } from '@/utils/resize'
import { computeSnap } from './AlignGuides'
import CanvasNode from './CanvasNode.vue'
import ContextMenu from '../ContextMenu.vue'
import MarqueeSelect from './MarqueeSelect.vue'
import SelectionLayer from './SelectionLayer.vue'
import type { ResizeDir } from './types'

const editor = useEditorStore()
const viewportEl = ref<HTMLDivElement>()

const page = computed(() => editor.currentPage)
const pageStyle = computed(() => ({
  width: `${page.value?.screen.designWidth ?? 1920}px`,
  height: `${page.value?.screen.designHeight ?? 1080}px`,
  background: page.value?.background.color ?? '#0b1220',
}))

const stageStyle = computed(() => ({
  transform: `translate(${editor.pan.x}px, ${editor.pan.y}px) scale(${editor.zoom})`,
  transformOrigin: '0 0',
}))

// ---------------- 坐标换算 ----------------

function toDesign(e: { clientX: number; clientY: number }): { x: number; y: number } {
  const rect = viewportEl.value!.getBoundingClientRect()
  return {
    x: (e.clientX - rect.left - editor.pan.x) / editor.zoom,
    y: (e.clientY - rect.top - editor.pan.y) / editor.zoom,
  }
}

// ---------------- 缩放（Ctrl+滚轮，光标为锚点） ----------------

const MIN_ZOOM = 0.25
const MAX_ZOOM = 4

function onWheel(e: WheelEvent): void {
  if (!e.ctrlKey && !e.metaKey) return
  e.preventDefault()
  const rect = viewportEl.value!.getBoundingClientRect()
  const cx = e.clientX - rect.left
  const cy = e.clientY - rect.top
  const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1
  const newZoom = clamp(editor.zoom * factor, MIN_ZOOM, MAX_ZOOM)
  // 保持光标下设计坐标不变：cursor = pan + design*zoom
  const dx = (cx - editor.pan.x) / editor.zoom
  const dy = (cy - editor.pan.y) / editor.zoom
  editor.setPan(cx - dx * newZoom, cy - dy * newZoom)
  editor.setZoom(newZoom)
}

// ---------------- 交互状态机 ----------------

type DragState =
  | { kind: 'pan'; startX: number; startY: number; panX: number; panY: number }
  | { kind: 'move'; startDesign: { x: number; y: number }; origins: Map<string, { x: number; y: number; w: number; h: number }>; moved: boolean }
  | { kind: 'resize'; dir: ResizeDir; id: string; startDesign: { x: number; y: number }; rect0: { x: number; y: number; w: number; h: number; rotate: number }; center0: { x: number; y: number }; handle0: { x: number; y: number }; shift: boolean; moved: boolean }
  | { kind: 'rotate'; id: string; center: { x: number; y: number }; a0: number; rotate0: number; moved: boolean }
  | { kind: 'marquee'; start: { x: number; y: number }; additive: boolean }

const drag = ref<DragState | null>(null)
const guides = ref<{ linesX: number[]; linesY: number[] }>({ linesX: [], linesY: [] })
const marquee = ref<{ x: number; y: number; w: number; h: number } | null>(null)

/**
 * 拖拽期间用 window 级监听（visual-drag-demo 模式），不用 setPointerCapture：
 * pointer capture 会把后续 pointerup/click/dblclick 的 target 重定向到捕获元素，
 * 导致节点上的 dblclick（行内编辑）永远收不到事件。
 */
function bindWindowDrag(): void {
  const move = (ev: PointerEvent) => onPointerMove(ev)
  const up = (ev: PointerEvent) => {
    onPointerUp(ev)
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', up)
    window.removeEventListener('pointercancel', up)
  }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', up)
  window.addEventListener('pointercancel', up)
}

// ---- 节点按下：选中 + 开始移动 ----

function onNodeDown(e: PointerEvent, node: ComponentNode): void {
  if (drag.value || editor.spaceHeld) return
  if (e.button !== 0) return
  // 锁定：可选不可拖（与 visual-drag-demo 一致；解锁入口=图层/右键/工具栏）
  if (node.locked) {
    if (e.ctrlKey || e.metaKey) editor.toggleSelect(node.id)
    else editor.select([node.id])
    return
  }

  if (e.ctrlKey || e.metaKey) {
    editor.toggleSelect(node.id)
    return
  }
  if (!editor.selection.includes(node.id)) {
    editor.select([node.id])
  }

  editor.beginChange() // 交互开始前快照（提交点=按下）
  const start = toDesign(e)
  const origins = new Map<string, { x: number; y: number; w: number; h: number }>()
  for (const n of editor.selectedNodes) {
    origins.set(n.id, { x: n.x, y: n.y, w: n.w, h: n.h })
  }
  drag.value = { kind: 'move', startDesign: start, origins, moved: false }
  bindWindowDrag()
}

// ---- 缩放柄 / 旋转柄 ----

function onResizeStart(dir: ResizeDir, e: PointerEvent): void {
  const node = editor.primarySelected
  if (!node) return
  editor.beginChange()
  const rect0 = { x: node.x, y: node.y, w: node.w, h: node.h, rotate: node.rotate ?? 0 }
  drag.value = {
    kind: 'resize',
    dir,
    id: node.id,
    startDesign: toDesign(e),
    rect0,
    center0: { x: rect0.x + rect0.w / 2, y: rect0.y + rect0.h / 2 },
    handle0: handlePoint(rect0, dir),
    shift: e.shiftKey,
    moved: false,
  }
  bindWindowDrag()
}

function onRotateStart(e: PointerEvent): void {
  const node = editor.primarySelected
  if (!node) return
  editor.beginChange()
  const center = { x: node.x + node.w / 2, y: node.y + node.h / 2 }
  const p = toDesign(e)
  drag.value = {
    kind: 'rotate',
    id: node.id,
    center,
    a0: (Math.atan2(p.y - center.y, p.x - center.x) * 180) / Math.PI,
    rotate0: node.rotate ?? 0,
    moved: false,
  }
  bindWindowDrag()
}

// ---- 视口按下：平移（空格/中键）或框选 ----

function onViewportDown(e: PointerEvent): void {
  if (drag.value) return
  if (editor.spaceHeld || e.button === 1) {
    drag.value = { kind: 'pan', startX: e.clientX, startY: e.clientY, panX: editor.pan.x, panY: editor.pan.y }
    bindWindowDrag()
    return
  }
  if (e.button !== 0) return
  const start = toDesign(e)
  drag.value = { kind: 'marquee', start, additive: e.ctrlKey || e.metaKey }
  marquee.value = { x: start.x, y: start.y, w: 0, h: 0 }
  bindWindowDrag()
}

// ---- 统一 move / up ----

function onPointerMove(e: PointerEvent): void {
  const st = drag.value
  if (!st) return

  if (st.kind === 'pan') {
    editor.setPan(st.panX + (e.clientX - st.startX), st.panY + (e.clientY - st.startY))
    return
  }

  const p = toDesign(e)

  if (st.kind === 'move') {
    const dx = p.x - st.startDesign.x
    const dy = p.y - st.startDesign.y
    if (!st.moved && Math.abs(dx) + Math.abs(dy) > 2) st.moved = true
    if (!st.moved) return

    // 吸附：以选中集包围盒为移动体，与画布/其他组件比较（阈值 5 设计 px）
    const boxes = [...st.origins.values()].map((o) => ({ x: o.x + dx, y: o.y + dy, w: o.w, h: o.h }))
    const movingBox = nodesBBox(boxes)
    const others = editor.topLevelNodes
      .filter((n) => !st.origins.has(n.id))
      .map((n) => ({ x: n.x, y: n.y, w: n.w, h: n.h }))
    const cw = page.value?.screen.designWidth ?? 1920
    const ch = page.value?.screen.designHeight ?? 1080
    const snap = computeSnap(movingBox, others, cw, ch)
    guides.value = { linesX: snap.linesX, linesY: snap.linesY }

    for (const [id, o] of st.origins) {
      editor.setNodeRect(id, { x: Math.round(o.x + dx + snap.dx), y: Math.round(o.y + dy + snap.dy) })
    }
    return
  }

  if (st.kind === 'resize') {
    const pdx = p.x - st.startDesign.x
    const pdy = p.y - st.startDesign.y
    if (!st.moved && Math.abs(pdx) + Math.abs(pdy) > 2) st.moved = true
    if (!st.moved) return

    // 对称点锚定算法（移植自 visual-drag-demo，任意旋转角精确；Shift 锁定宽高比）
    const next = calcResize(
      { ...st.rect0 },
      st.dir,
      p,
      e.shiftKey,
      st.center0,
      st.handle0,
    )
    editor.setNodeRect(st.id, { x: next.x, y: next.y, w: next.w, h: next.h })
    return
  }

  if (st.kind === 'rotate') {
    const a = (Math.atan2(p.y - st.center.y, p.x - st.center.x) * 180) / Math.PI
    let deg = st.rotate0 + (a - st.a0)
    if (!st.moved && Math.abs(a - st.a0) > 1) st.moved = true
    // 近 15° 倍数吸附（4° 内）
    const near = Math.round(deg / 15) * 15
    if (Math.abs(deg - near) < 4) deg = near
    // 归一化到 [0, 360)（契约 rotate ge=0 lt=360）
    deg = ((Math.round(deg) % 360) + 360) % 360
    editor.setNodeRect(st.id, { rotate: deg })
    return
  }

  if (st.kind === 'marquee') {
    const x = Math.min(st.start.x, p.x)
    const y = Math.min(st.start.y, p.y)
    marquee.value = { x, y, w: Math.abs(p.x - st.start.x), h: Math.abs(p.y - st.start.y) }
  }
}

function onPointerUp(e: PointerEvent): void {
  const st = drag.value
  drag.value = null
  guides.value = { linesX: [], linesY: [] }
  if (!st) return

  if (st.kind === 'move' || st.kind === 'resize' || st.kind === 'rotate') {
    // 纯点击/无实际变化：回退快照，不留历史记录
    if (!st.moved) editor.cancelChange()
    return
  }

  if (st.kind === 'marquee') {
    const rect = marquee.value
    marquee.value = null
    if (!rect || (rect.w < 3 && rect.h < 3)) {
      // 视为空白处单击：清空选中（Ctrl 单击不清）
      if (!st.additive) editor.clearSelection()
      return
    }
    const hit = editor.topLevelNodes.filter((n) => !n.locked && bboxIntersect(rect, { x: n.x, y: n.y, w: n.w, h: n.h }))
    const ids = hit.map((n) => n.id)
    editor.select(st.additive ? [...new Set([...editor.selection, ...ids])] : ids)
  }
}

// ---------------- 右键菜单 / 双击行内编辑 ----------------

function onContextMenu(e: MouseEvent): void {
  e.preventDefault()
  const rect = viewportEl.value!.getBoundingClientRect()
  editor.openContextMenu(e.clientX - rect.left, e.clientY - rect.top)
}

/** 双击文本组件进入行内编辑（进入时先入历史快照，blur/Enter 提交） */
function onNodeDblClick(node: ComponentNode): void {
  if (node.type !== 'text' || node.locked) return
  editor.beginChange(`edit:${node.id}`)
  editor.setEditing(node.id)
}

// ---------------- 拖入组件（palette → drop） ----------------

function onDragOver(e: DragEvent): void {
  e.preventDefault()
  e.dataTransfer!.dropEffect = 'copy'
}

function onDrop(e: DragEvent): void {
  e.preventDefault()
  const type = e.dataTransfer?.getData('application/x-widget') || e.dataTransfer?.getData('text/plain')
  if (!type || !registry.has(type as never)) return
  const meta = registry.get(type as never)!
  const p = toDesign(e)
  editor.addComponent(type as never, p.x - meta.defaultSize.w / 2, p.y - meta.defaultSize.h / 2)
}

// ---------------- 空格平移（键盘状态来自 store，由 keyboard.ts 维护） ----------------

const viewportClass = computed(() => ({ panning: editor.spaceHeld }))

/** 适配视口：整页等比缩放居中（实现在 store.fitToView，工具栏"适应"按钮共用）。 */
function fitToView(): void {
  const vp = viewportEl.value
  if (!vp) return
  editor.fitToView(vp.clientWidth, vp.clientHeight)
}

// 触控板双指滚轮（无 Ctrl）在缩放模式下视为缩放（开发便利）；普通滚轮留给系统滚动
onMounted(() => {
  viewportEl.value?.addEventListener('wheel', onWheel, { passive: false })
  fitToView()
})
onBeforeUnmount(() => {
  viewportEl.value?.removeEventListener('wheel', onWheel)
})

// 切页/换设计尺寸时重新适配
watch(
  () => [editor.currentPageId, page.value?.screen.designWidth, page.value?.screen.designHeight],
  () => fitToView(),
)
</script>

<template>
  <div
    ref="viewportEl"
    class="canvas-viewport"
    :class="viewportClass"
    @pointerdown="onViewportDown"
    @contextmenu="onContextMenu"
    @dragover="onDragOver"
    @drop="onDrop"
  >
    <div v-if="page" class="canvas-stage" :style="stageStyle">
      <div class="canvas-page" :style="pageStyle">
        <!-- 网格线（结构/参数参照 visual-drag-demo Grid.vue：7.24 小格 / 36.18 大格） -->
        <svg class="grid" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <pattern id="wsSmallGrid" width="7.236328125" height="7.236328125" patternUnits="userSpaceOnUse">
              <path d="M 7.236328125 0 L 0 0 0 7.236328125" fill="none" stroke="rgba(127, 127, 127, 0.25)" stroke-width="1" />
            </pattern>
            <pattern id="wsGrid" width="36.181640625" height="36.181640625" patternUnits="userSpaceOnUse">
              <rect width="36.181640625" height="36.181640625" fill="url(#wsSmallGrid)" />
              <path d="M 36.181640625 0 L 0 0 0 36.181640625" fill="none" stroke="rgba(127, 127, 127, 0.5)" stroke-width="1" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#wsGrid)" />
        </svg>
        <CanvasNode
          v-for="node in page.components"
          :key="node.id"
          :node="node"
          @node-down="onNodeDown"
          @node-dblclick="onNodeDblClick"
        />
        <SelectionLayer @resize-start="onResizeStart" @rotate-start="onRotateStart" />
        <MarqueeSelect v-if="marquee" :rect="marquee" />
        <!-- 吸附参考线 -->
        <div v-for="(lx, i) in guides.linesX" :key="`gx${i}`" class="guide-v" :style="{ left: `${lx}px` }" />
        <div v-for="(ly, i) in guides.linesY" :key="`gy${i}`" class="guide-h" :style="{ top: `${ly}px` }" />
      </div>
    </div>
    <div v-else class="canvas-empty">无页面</div>
    <ContextMenu />
    <div class="zoom-badge">{{ Math.round(editor.zoom * 100) }}%</div>
  </div>
</template>

<style scoped>
.canvas-viewport {
  position: relative;
  flex: 1;
  overflow: hidden;
  background: var(--ws-canvas);
  /* pointer 交互接管：禁浏览器手势（拖拽/触摸滚动），全由应用处理 */
  touch-action: none;
}

.canvas-viewport.panning {
  cursor: grab;
}

.canvas-stage {
  position: absolute;
  left: 0;
  top: 0;
}

.canvas-page {
  position: relative;
  box-shadow: 0 0 0 1px var(--ws-steel-3), 0 10px 30px rgba(20, 33, 46, 0.12);
  transform-origin: 0 0;
}

.canvas-empty {
  color: var(--ws-text-3);
  padding: 40px;
}

.guide-v {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--ws-select);
  pointer-events: none;
}

.guide-h {
  position: absolute;
  left: 0;
  right: 0;
  height: 1px;
  background: var(--ws-select);
  pointer-events: none;
}

.zoom-badge {
  position: absolute;
  right: 14px;
  bottom: 14px;
  padding: 2px 8px;
  background: var(--ws-panel);
  border: 1px solid var(--ws-steel-3);
  border-radius: var(--ws-radius);
  color: var(--ws-text-2);
  font-family: var(--ws-font-tech);
  font-variant-numeric: tabular-nums;
  font-size: 12px;
  pointer-events: none;
}

/* 网格线（结构参照 Grid.vue） */
.grid {
  position: absolute;
  top: 0;
  left: 0;
  z-index: 0;
  pointer-events: none;
}
</style>
