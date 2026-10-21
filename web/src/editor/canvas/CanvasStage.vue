<script setup lang="ts">
/**
 * 画布容器：视口（平移/缩放）+ 页面（设计尺寸）+ 交互状态机。
 * 交互：拖拽移动（吸附）、8 向缩放、旋转、框选、空格/中键平移、Ctrl+滚轮缩放（25%~400%）、
 * 滚轮/触控板平移（Shift=水平）、Alt+拖动复制、拖到视口边缘自动平移、拖入组件 ghost 预览、
 * 双击文本行内编辑、双击组进入组内编辑（Esc/空白单击退出）。
 * 快照协议：move/resize/rotate 在 pointerdown 时 beginChange，未实际移动在 up 时 cancelChange
 * （保证"一次拖拽全程仅 1 条 undo 记录、纯点击零记录"）；Alt 复制的克隆发生在首次移动时。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import html2canvas from 'html2canvas'
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
const pageEl = ref<HTMLDivElement>()

/** 首页缩略图（台账卡片视图）：临时隐藏编辑器装饰层（网格/选框/参考线/行内编辑），
 *  按设计尺寸整页截图，输出 320px 宽 JPEG dataURL；空页或失败返回 null（保留旧图）。
 *  供 EditorView 保存前调用，随 doc 一并 PUT。 */
const THUMB_WIDTH = 320

async function captureThumbnail(): Promise<string | null> {
  const el = pageEl.value
  const p = page.value
  if (!el || !p || p.components.length === 0) return null
  el.classList.add('capturing')
  try {
    const canvas = await html2canvas(el, {
      width: p.screen.designWidth,
      height: p.screen.designHeight,
      windowWidth: p.screen.designWidth,
      windowHeight: p.screen.designHeight,
      scale: THUMB_WIDTH / p.screen.designWidth,
      backgroundColor: p.background.color,
      logging: false,
      useCORS: true,
    })
    return canvas.toDataURL('image/jpeg', 0.72)
  } catch {
    return null
  } finally {
    el.classList.remove('capturing')
  }
}

defineExpose({ captureThumbnail })

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

// ---------------- 缩放与平移（滚轮） ----------------

const MIN_ZOOM = 0.25
const MAX_ZOOM = 4

function onWheel(e: WheelEvent): void {
  // Firefox 行模式归一到像素
  const unit = e.deltaMode === 1 ? 16 : 1
  if (e.ctrlKey || e.metaKey) {
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
    return
  }
  // 滚轮/触控板平移画布（Shift=水平）；视口自身无滚动条，接管无副作用
  e.preventDefault()
  const dx = e.shiftKey ? e.deltaX * unit + e.deltaY * unit : e.deltaX * unit
  const dy = e.shiftKey ? 0 : e.deltaY * unit
  editor.setPan(editor.pan.x - dx, editor.pan.y - dy)
}

// ---------------- 交互状态机 ----------------

type DragState =
  | { kind: 'pan'; startX: number; startY: number; panX: number; panY: number }
  | { kind: 'move'; startDesign: { x: number; y: number }; origins: Map<string, { x: number; y: number; w: number; h: number }>; alt: boolean; moved: boolean }
  | { kind: 'resize'; dir: ResizeDir; id: string; startDesign: { x: number; y: number }; rect0: { x: number; y: number; w: number; h: number; rotate: number }; center0: { x: number; y: number }; handle0: { x: number; y: number }; shift: boolean; moved: boolean }
  | { kind: 'rotate'; id: string; center: { x: number; y: number }; a0: number; rotate0: number; moved: boolean }
  | { kind: 'marquee'; start: { x: number; y: number }; additive: boolean }

const drag = ref<DragState | null>(null)
const guides = ref<{ linesX: number[]; linesY: number[] }>({ linesX: [], linesY: [] })
const marquee = ref<{ x: number; y: number; w: number; h: number } | null>(null)

/** 拖动实时读数：move = 选中集新位置；rotate = 角度（resize 的 W×H 由 SelectionLayer 徽标承担） */
const readout = ref<{ x: number; y: number; text: string } | null>(null)

/** 组编辑上下文的吸附线偏移：参考线画在 page 坐标系，组内命中值是相对组原点的 */
const guideOffset = computed(() => {
  const g = editor.editingGroup
  return g ? { x: g.x, y: g.y } : { x: 0, y: 0 }
})

/**
 * 拖拽期间用 window 级监听（visual-drag-demo 模式），不用 setPointerCapture：
 * pointer capture 会把后续 pointerup/click/dblclick 的 target 重定向到捕获元素，
 * 导致节点上的 dblclick（行内编辑）永远收不到事件。
 */
let lastEv: { clientX: number; clientY: number; shiftKey: boolean } | null = null

function bindWindowDrag(): void {
  const move = (ev: PointerEvent) => {
    lastEv = ev
    processDrag(ev)
  }
  const up = (ev: PointerEvent) => {
    onPointerUp(ev)
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', up)
    window.removeEventListener('pointercancel', up)
    stopEdgePan()
  }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', up)
  window.addEventListener('pointercancel', up)
}

// ---- 视口边缘自动平移：指针贴边时按深入程度平移画布，移动/框选跟随（rAF 驱动，指针静止也持续） ----

let panRAF = 0

function startEdgePan(): void {
  if (panRAF) return
  const tick = (): void => {
    const st = drag.value
    const vp = viewportEl.value
    if (!st || !vp || !lastEv || (st.kind !== 'move' && st.kind !== 'marquee')) {
      panRAF = 0
      return
    }
    const rect = vp.getBoundingClientRect()
    const EDGE = 30
    const SPEED = 28
    let vx = 0
    let vy = 0
    if (lastEv.clientX < rect.left + EDGE) vx = -((rect.left + EDGE - lastEv.clientX) / EDGE) * SPEED
    else if (lastEv.clientX > rect.right - EDGE) vx = ((lastEv.clientX - (rect.right - EDGE)) / EDGE) * SPEED
    if (lastEv.clientY < rect.top + EDGE) vy = -((rect.top + EDGE - lastEv.clientY) / EDGE) * SPEED
    else if (lastEv.clientY > rect.bottom - EDGE) vy = ((lastEv.clientY - (rect.bottom - EDGE)) / EDGE) * SPEED
    if (vx || vy) {
      editor.setPan(editor.pan.x + vx, editor.pan.y + vy)
      processDrag(lastEv) // pan 变化后按指针重算，组件跟手跟视口
    }
    panRAF = requestAnimationFrame(tick)
  }
  panRAF = requestAnimationFrame(tick)
}

function stopEdgePan(): void {
  if (panRAF) cancelAnimationFrame(panRAF)
  panRAF = 0
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

  editor.beginChange() // 交互开始前快照（提交点=按下；Alt 复制时快照即复制前状态）
  const start = toDesign(e)
  const origins = new Map<string, { x: number; y: number; w: number; h: number }>()
  for (const n of editor.selectedNodes) {
    origins.set(n.id, { x: n.x, y: n.y, w: n.w, h: n.h })
  }
  drag.value = { kind: 'move', startDesign: start, origins, alt: e.altKey, moved: false }
  bindWindowDrag()
  startEdgePan()
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
  startEdgePan()
}

// ---- 统一 move / up（edge-pan 复用：ev 只需 clientX/clientY/shiftKey） ----

function processDrag(e: { clientX: number; clientY: number; shiftKey: boolean }): void {
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
    if (!st.moved) {
      if (Math.abs(dx) + Math.abs(dy) <= 2) return
      st.moved = true
      // Alt+拖动 = 复制后拖副本（原组件留在原地）；克隆发生在确认移动时，纯点击零副作用
      if (st.alt) {
        const ids = editor.duplicateForDrag()
        st.origins = new Map(
          ids.map((id) => {
            const n = editor.findNodeDeep(id)!
            return [id, { x: n.x, y: n.y, w: n.w, h: n.h }] as const
          }),
        )
      }
    }

    // 吸附：以选中集包围盒为移动体，与画布/其他组件比较（阈值 5 设计 px）；
    // 组编辑上下文中改为与组内兄弟比较，吸附边界为组框
    const boxes = [...st.origins.values()].map((o) => ({ x: o.x + dx, y: o.y + dy, w: o.w, h: o.h }))
    const movingBox = nodesBBox(boxes)
    const eg = editor.editingGroup
    const others = (eg ? eg.children ?? [] : editor.topLevelNodes)
      .filter((n) => !st.origins.has(n.id))
      .map((n) => ({ x: n.x, y: n.y, w: n.w, h: n.h }))
    const cw = eg ? eg.w : (page.value?.screen.designWidth ?? 1920)
    const ch = eg ? eg.h : (page.value?.screen.designHeight ?? 1080)
    const snap = computeSnap(movingBox, others, cw, ch)
    guides.value = { linesX: snap.linesX, linesY: snap.linesY }

    for (const [id, o] of st.origins) {
      editor.setNodeRect(id, { x: Math.round(o.x + dx + snap.dx), y: Math.round(o.y + dy + snap.dy) })
    }
    // 移动读数：吸附后包围盒位置（组内为相对坐标，读数统一换算成画布绝对坐标）
    const placed = nodesBBox([...st.origins.values()].map((o) => ({ x: o.x + dx + snap.dx, y: o.y + dy + snap.dy, w: o.w, h: o.h })))
    const off = guideOffset.value
    readout.value = {
      x: off.x + placed.x + placed.w / 2,
      y: off.y + placed.y + placed.h,
      text: `X ${Math.round(off.x + placed.x)}  Y ${Math.round(off.y + placed.y)}`,
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
    readout.value = { x: st.center.x, y: st.center.y - 26 / editor.zoom, text: `${deg}°` }
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
  readout.value = null
  if (!st) return

  if (st.kind === 'move' || st.kind === 'resize' || st.kind === 'rotate') {
    // 纯点击/无实际变化：回退快照，不留历史记录（Alt 复制未发生，无副作用）
    if (!st.moved) editor.cancelChange()
    return
  }

  if (st.kind === 'marquee') {
    const rect = marquee.value
    marquee.value = null
    if (!rect || (rect.w < 3 && rect.h < 3)) {
      // 视为空白处单击：组编辑上下文优先退出（并选回该组），否则清空选中（Ctrl 单击不清）
      if (editor.editingGroupId) {
        const gid = editor.editingGroupId
        editor.exitGroup()
        editor.select([gid])
      } else if (!st.additive) {
        editor.clearSelection()
      }
      return
    }
    // 框选命中：组编辑上下文 = 组内直接子节点（相对坐标，rect 换算回组坐标系）
    const eg = editor.editingGroup
    const pool = eg ? eg.children ?? [] : editor.topLevelNodes
    const r = eg ? { x: rect.x - eg.x, y: rect.y - eg.y, w: rect.w, h: rect.h } : rect
    const hit = pool.filter((n) => !n.locked && bboxIntersect(r, { x: n.x, y: n.y, w: n.w, h: n.h }))
    const ids = hit.map((n) => n.id)
    editor.select(st.additive ? [...new Set([...editor.selection, ...ids])] : ids)
  }
}

// ---------------- 右键菜单 / 双击行内编辑与入组 ----------------

function onContextMenu(e: MouseEvent): void {
  e.preventDefault()
  const rect = viewportEl.value!.getBoundingClientRect()
  // 右键命中规则（业界惯例）：
  // - 命中未选中的组件 → 单选它（保持多选若已在选中集），弹组件菜单
  // - 空白 → 清空选中（编辑组上下文则退出并选回该组），弹画布菜单（粘贴到此处）
  const p = toDesign(e)
  const eg = editor.editingGroup
  const pool = eg ? [...(eg.children ?? [])] : [...editor.topLevelNodes]
  const hit = pool
    .filter((n) => p.x >= n.x && p.x <= n.x + n.w && p.y >= n.y && p.y <= n.y + n.h)
    .sort((a, b) => b.z - a.z)[0]
  if (hit) {
    if (!editor.selection.includes(hit.id)) editor.select([hit.id])
  } else if (eg) {
    const gid = eg.id
    editor.exitGroup()
    editor.select([gid])
  } else {
    editor.clearSelection()
  }
  editor.openContextMenu(e.clientX - rect.left, e.clientY - rect.top)
}

/** 双击：文本 → 行内编辑（进入时先入历史快照，blur/Enter 提交）；组 → 进入组内编辑 */
function onNodeDblClick(node: ComponentNode): void {
  if (node.locked) return
  if (node.type === 'group') {
    editor.enterGroup(node.id)
    return
  }
  if (node.type !== 'text') return
  editor.beginChange(`edit:${node.id}`)
  editor.setEditing(node.id)
}

// ---------------- 拖入组件（palette → drop） ----------------

const dragGhost = ref<{ x: number; y: number; w: number; h: number } | null>(null)

function onDragOver(e: DragEvent): void {
  e.preventDefault()
  e.dataTransfer!.dropEffect = 'copy'
  const hint = editor.dropHint
  if (hint) {
    const p = toDesign(e)
    dragGhost.value = { x: p.x - hint.w / 2, y: p.y - hint.h / 2, w: hint.w, h: hint.h }
  }
}

function onDragLeave(): void {
  dragGhost.value = null
}

function onDrop(e: DragEvent): void {
  e.preventDefault()
  dragGhost.value = null
  const raw = e.dataTransfer?.getData('application/x-widget') || e.dataTransfer?.getData('text/plain')
  if (!raw) return
  // 复合载荷：'symbol|<symbolId>'（图元库）/ 'mysym|<资产id>'（我的图元）；普通组件为纯 type
  const [type, id] = raw.split('|')
  const p = toDesign(e)
  if (type === 'mysym' && id) {
    editor.insertMySymbol(id, p.x, p.y)
    return
  }
  if (!registry.has(type as never)) return
  const meta = registry.get(type as never)!
  editor.addComponent(
    type as never,
    p.x - meta.defaultSize.w / 2,
    p.y - meta.defaultSize.h / 2,
    id ? { symbolId: id } : undefined,
  )
}

// ---------------- 缩放快捷键（keyboard.ts 派发 ws:zoom 事件） ----------------

function onZoomCmd(ev: Event): void {
  const detail = (ev as CustomEvent<string>).detail
  if (detail === 'fit') {
    fitToView()
    return
  }
  const z = clamp(Number(detail) / 100, MIN_ZOOM, MAX_ZOOM)
  if (!Number.isFinite(z) || z <= 0) return
  const rect = viewportEl.value?.getBoundingClientRect()
  if (!rect) return
  // 以视口中心为锚点归位
  const cx = rect.width / 2
  const cy = rect.height / 2
  const dx = (cx - editor.pan.x) / editor.zoom
  const dy = (cy - editor.pan.y) / editor.zoom
  editor.setPan(cx - dx * z, cy - dy * z)
  editor.setZoom(z)
}

// ---------------- 空格平移（键盘状态来自 store，由 keyboard.ts 维护） ----------------

const viewportClass = computed(() => ({ panning: editor.spaceHeld }))

/** 缩放 <40% 时网格淡出（点已小于三分之一像素，留着只有噪点；fit-view 常态 50-60% 仍保留大格点） */
const gridOpacity = computed(() => (editor.zoom < 0.4 ? 0 : 1))

/** 空页面引导（中心淡字，不挡交互） */
const showEmptyGuide = computed(() => (page.value?.components.length ?? 0) === 0)

/** 适配视口：整页等比缩放居中（实现在 store.fitToView，工具栏"适应"按钮共用）。 */
function fitToView(): void {
  const vp = viewportEl.value
  if (!vp) return
  editor.fitToView(vp.clientWidth, vp.clientHeight)
}

onMounted(() => {
  viewportEl.value?.addEventListener('wheel', onWheel, { passive: false })
  window.addEventListener('ws:zoom', onZoomCmd)
  fitToView()
})
onBeforeUnmount(() => {
  viewportEl.value?.removeEventListener('wheel', onWheel)
  window.removeEventListener('ws:zoom', onZoomCmd)
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
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <div v-if="page" class="canvas-stage" :style="stageStyle">
      <div ref="pageEl" class="canvas-page" :style="pageStyle">
        <!-- 点阵网格（7.24 小格 / 36.18 大格，着色随主题令牌；缩放 <60% 整层淡出降噪） -->
        <svg class="grid" :style="{ opacity: gridOpacity }" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <pattern id="wsGridDots" width="7.236328125" height="7.236328125" patternUnits="userSpaceOnUse">
              <circle class="dot-minor" cx="0.5" cy="0.5" r="0.7" />
            </pattern>
            <pattern id="wsGridDotsMajor" width="36.181640625" height="36.181640625" patternUnits="userSpaceOnUse">
              <rect width="36.181640625" height="36.181640625" fill="url(#wsGridDots)" />
              <circle class="dot-major" cx="0.5" cy="0.5" r="1.15" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#wsGridDotsMajor)" />
        </svg>
        <!-- 空页面引导：三步上手提示（不参与交互） -->
        <div v-if="showEmptyGuide" class="empty-guide">
          <div class="empty-title">空白画面</div>
          <div class="empty-line">从左侧组件库 <b>拖入</b> 或 <b>点击</b> 放置组件</div>
          <div class="empty-line">右侧属性面板绑定数据与外观</div>
          <div class="empty-line">顶部「预览」查看运行效果 · 修改自动保存</div>
        </div>
        <CanvasNode
          v-for="node in page.components"
          :key="node.id"
          :node="node"
          @node-down="onNodeDown"
          @node-dblclick="onNodeDblClick"
        />
        <SelectionLayer @resize-start="onResizeStart" @rotate-start="onRotateStart" />
        <MarqueeSelect v-if="marquee" :rect="marquee" />
        <!-- 拖入放置 ghost：组件库拖拽经过时按默认尺寸预览落点 -->
        <div
          v-if="dragGhost"
          class="drop-ghost"
          :style="{ left: `${dragGhost.x}px`, top: `${dragGhost.y}px`, width: `${dragGhost.w}px`, height: `${dragGhost.h}px` }"
        />
        <!-- 吸附参考线 -->
        <div v-for="(lx, i) in guides.linesX" :key="`gx${i}`" class="guide-v" :style="{ left: `${lx + guideOffset.x}px` }" />
        <div v-for="(ly, i) in guides.linesY" :key="`gy${i}`" class="guide-h" :style="{ top: `${ly + guideOffset.y}px` }" />
        <!-- 拖动实时读数（位置/角度） -->
        <div
          v-if="readout"
          class="drag-readout"
          :style="{
            left: `${readout.x}px`,
            top: `${readout.y + 8 / editor.zoom}px`,
            fontSize: `${11 / editor.zoom}px`,
            padding: `${2 / editor.zoom}px ${6 / editor.zoom}px`,
            borderRadius: `${2 / editor.zoom}px`,
          }"
        >{{ readout.text }}</div>
      </div>
    </div>
    <div v-else class="canvas-empty">无页面</div>
    <ContextMenu />
  </div>
</template>

<style scoped>
/* 缩略图截图态：隐藏编辑器装饰层（网格/选中框/框选/参考线/行内编辑），只留组件本体 */
.canvas-page.capturing :deep(.grid),
.canvas-page.capturing :deep(.selection-layer),
.canvas-page.capturing :deep(.marquee),
.canvas-page.capturing :deep(.guide-v),
.canvas-page.capturing :deep(.guide-h),
.canvas-page.capturing :deep(.inline-edit),
.canvas-page.capturing :deep(.lock-badge),
.canvas-page.capturing :deep(.drag-readout),
.canvas-page.capturing :deep(.drop-ghost),
.canvas-page.capturing :deep(.group-edit-badge) {
  display: none !important;
}

.canvas-viewport {
  position: relative;
  flex: 1;
  overflow: hidden;
  /* 舞台底：比工作区深一档，画布像被照亮的 HMI 屏；四周暗角由 ::after 承担 */
  background: var(--ws-stage);
  /* pointer 交互接管：禁浏览器手势（拖拽/触摸滚动），全由应用处理 */
  touch-action: none;
}

/* 舞台暗角：向内压暗四周，视觉聚焦画布（分层绘制，不参与交互） */
.canvas-viewport::after {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: radial-gradient(
    115% 85% at 50% 42%,
    transparent 46%,
    var(--ws-stage-vignette) 100%
  );
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
  box-shadow: 0 0 0 1px var(--ws-steel-3), 0 18px 48px var(--ws-stage-vignette);
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

/* 拖动实时读数：与选中框徽标同风格（信号色底反白等宽字），字号 1/zoom 屏幕恒定 */
.drag-readout {
  position: absolute;
  transform: translateX(-50%);
  white-space: nowrap;
  background: var(--ws-select);
  color: #fff;
  font-family: var(--ws-font-tech);
  font-variant-numeric: tabular-nums;
  line-height: 1.3;
  pointer-events: none;
  z-index: 5;
}

/* 拖入放置 ghost：信号色虚线框，中心十字标注落点 */
.drop-ghost {
  position: absolute;
  border: 1.5px dashed var(--ws-select);
  background: var(--ws-signal-soft);
  pointer-events: none;
  z-index: 5;
}

.drop-ghost::after {
  content: '';
  position: absolute;
  left: 50%;
  top: 50%;
  width: 12px;
  height: 12px;
  transform: translate(-50%, -50%);
  border: 1px solid var(--ws-select);
  border-radius: 50%;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.5) inset;
}

/* 空页面引导：画布中央淡字组 */
.empty-guide {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  color: var(--ws-text-3);
  pointer-events: none;
  user-select: none;
}

.empty-title {
  font-size: 20px;
  font-weight: 600;
  letter-spacing: 0.12em;
  color: var(--ws-text-2);
  opacity: 0.75;
}

.empty-line {
  font-size: 13px;
  line-height: 1.2;
}

.empty-line b {
  font-weight: 600;
  color: var(--ws-text-2);
}

/* 点阵网格（minor/major 双档密度，着色随主题令牌；缩放淡出走行内 opacity） */
.grid {
  position: absolute;
  top: 0;
  left: 0;
  z-index: 0;
  pointer-events: none;
  transition: opacity 0.2s ease-out;
}

.grid :deep(.dot-minor) {
  fill: var(--ws-stage-grid);
}

.grid :deep(.dot-major) {
  fill: var(--ws-stage-grid-major);
}
</style>
