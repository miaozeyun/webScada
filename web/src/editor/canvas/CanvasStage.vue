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
import { ElMessage } from 'element-plus'
import { FullScreen, Minus, Plus } from '@element-plus/icons-vue'
import type { ComponentNode } from '@/types/doc'
import { useEditorStore } from '@/stores/editor'
import { registry } from '@/widgets/registry'
import { bboxIntersect, clamp, nodesBBox } from '@/utils/coord'
import { newId } from '@/utils/nanoid'
import { rotateMembersAbout, scaleMembersAbout, type MemberGeom } from '@/utils/multiTransform'
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
    // 按需加载：html2canvas 体积大，只有「保存时生成缩略图」用得到，不应计入编辑器首屏包
    const { default: html2canvas } = await import('html2canvas')
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
  } catch (err) {
    // 截图失败不阻断保存，但必须留痕：此前静默 catch 让台账缩略图长期为空且无从排查
    console.warn('[thumbnail] 画面截图失败：', err)
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

/** 手势期间的视口矩形缓存：pointermove 里反复 getBoundingClientRect 会强制同步布局（拖动掉帧源） */
let vpRect: DOMRect | null = null

function beginGesture(): void {
  vpRect = viewportEl.value?.getBoundingClientRect() ?? null
}

function endGesture(): void {
  vpRect = null
}

/** 画布按下时收走面板输入框焦点：节点 pointerdown 会 preventDefault（阻止原生焦点转移），
 *  焦点留在属性面板输入框里会让 Delete/方向键等快捷键被键盘层按「输入中」吞掉。 */
function blurTypingTarget(): void {
  const el = document.activeElement as HTMLElement | null
  if (!el) return
  const tag = el.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable) el.blur()
}

function toDesign(e: { clientX: number; clientY: number }): { x: number; y: number } {
  const rect = vpRect ?? viewportEl.value!.getBoundingClientRect()
  return {
    x: (e.clientX - rect.left - editor.pan.x) / editor.zoom,
    y: (e.clientY - rect.top - editor.pan.y) / editor.zoom,
  }
}

// ---------------- 悬停轨迹（Ctrl+V 粘贴落点跟随鼠标） ----------------

/** 视口矩形缓存重建：pointerenter/窗口 resize 时一次量测。
 *  pan/zoom 只改内层 stage 的 transform（合成器层），不改变视口自身矩形，无需逐事件量测。 */
function refreshHoverRect(): void {
  vpRect = viewportEl.value?.getBoundingClientRect() ?? null
}

function onHoverMove(e: PointerEvent): void {
  editor.lastPointerDesign = toDesign(e)
}

function onHoverLeave(): void {
  // 离开画布：清空记录，Ctrl+V 回落 +10px 阶梯偏移（纯键盘路径）
  editor.lastPointerDesign = null
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
    // 缩放后光标下的设计坐标已变，悬停轨迹同步刷新（滚轮不触发 pointermove）
    editor.lastPointerDesign = toDesign(e)
    return
  }
  // 滚轮/触控板平移画布（Shift=水平）；视口自身无滚动条，接管无副作用
  e.preventDefault()
  const dx = e.shiftKey ? e.deltaX * unit + e.deltaY * unit : e.deltaX * unit
  const dy = e.shiftKey ? 0 : e.deltaY * unit
  editor.setPan(editor.pan.x - dx, editor.pan.y - dy)
  editor.lastPointerDesign = toDesign(e)
}

// ---------------- 交互状态机 ----------------

type DragState =
  | { kind: 'pan'; startX: number; startY: number; panX: number; panY: number }
  | { kind: 'move'; startDesign: { x: number; y: number }; origins: Map<string, { x: number; y: number; w: number; h: number }>; alt: boolean; moved: boolean }
  | { kind: 'resize'; dir: ResizeDir; id: string; startDesign: { x: number; y: number }; rect0: { x: number; y: number; w: number; h: number; rotate: number }; center0: { x: number; y: number }; handle0: { x: number; y: number }; shift: boolean; moved: boolean }
  | { kind: 'rotate'; id: string; center: { x: number; y: number }; a0: number; rotate0: number; moved: boolean }
  | { kind: 'multi-resize'; dir: ResizeDir; startDesign: { x: number; y: number }; bbox0: { x: number; y: number; w: number; h: number }; members: MemberGeom[]; moved: boolean }
  | { kind: 'multi-rotate'; center: { x: number; y: number }; a0: number; members: MemberGeom[]; moved: boolean }
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

/** 指针移动按帧合帧：高刷鼠标/触控板一次手势可发上百个 pointermove，
 *  逐个处理会在一帧内重复写 doc + 重算吸附（卡顿主因）；rAF 内只落最后一次位置。 */
let pendingEv: PointerEvent | null = null
let moveRAF = 0

function flushMove(): void {
  moveRAF = 0
  const ev = pendingEv
  pendingEv = null
  if (ev) processDrag(ev)
}

function bindWindowDrag(): void {
  const move = (ev: PointerEvent) => {
    lastEv = ev
    pendingEv = ev
    if (!moveRAF) moveRAF = requestAnimationFrame(flushMove)
  }
  const up = (ev: PointerEvent) => {
    // 抬起前先把最后一次移动落盘：快速甩动时末帧可能尚未执行
    lastEv = ev
    pendingEv = ev
    if (moveRAF) cancelAnimationFrame(moveRAF)
    flushMove()
    onPointerUp(ev)
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', up)
    window.removeEventListener('pointercancel', up)
    stopEdgePan()
    endGesture()
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
  blurTypingTarget() // 先夺回焦点，Delete 等快捷键才落到画布
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

  beginGesture()
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
  const sel = editor.selectedNodes
  const node = editor.primarySelected
  if (!node) return
  blurTypingTarget()
  beginGesture()
  editor.beginChange()
  // 多选：选中集整体缩放（成员中心随包围盒锚点比例平移，宽高同比；见 utils/multiTransform）
  if (sel.length > 1) {
    const bbox0 = nodesBBox(sel)
    drag.value = {
      kind: 'multi-resize',
      dir,
      startDesign: toDesign(e),
      bbox0,
      members: sel.map(memberGeomOf),
      moved: false,
    }
    bindWindowDrag()
    return
  }
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
  const sel = editor.selectedNodes
  const node = editor.primarySelected
  if (!node) return
  blurTypingTarget()
  beginGesture()
  editor.beginChange()
  // 多选：绕选中集包围盒中心整体旋转（成员 rotate0+θ，中心公转）
  if (sel.length > 1) {
    const bbox = nodesBBox(sel)
    const center = { x: bbox.x + bbox.w / 2, y: bbox.y + bbox.h / 2 }
    const p = toDesign(e)
    drag.value = {
      kind: 'multi-rotate',
      center,
      a0: (Math.atan2(p.y - center.y, p.x - center.x) * 180) / Math.PI,
      members: sel.map(memberGeomOf),
      moved: false,
    }
    bindWindowDrag()
    return
  }
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

/** 选中集成员的变换原值快照（几何 + 字号，手势期间每次从原值重算防漂移） */
function memberGeomOf(n: ComponentNode): MemberGeom {
  return {
    id: n.id,
    x: n.x,
    y: n.y,
    w: n.w,
    h: n.h,
    rotate: n.rotate ?? 0,
    fontSize: n.style?.fontSize,
  }
}

// ---- 视口按下：平移（空格/中键）或框选 ----

function onViewportDown(e: PointerEvent): void {
  if (drag.value) return
  blurTypingTarget()
  beginGesture()
  if (editor.spaceHeld || e.button === 1) {
    drag.value = { kind: 'pan', startX: e.clientX, startY: e.clientY, panX: editor.pan.x, panY: editor.pan.y }
    bindWindowDrag()
    return
  }
  if (e.button !== 0) {
    endGesture() // 右键等非拖拽按键：不进入手势，别留着矩形缓存
    return
  }
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

  if (st.kind === 'multi-resize') {
    const pdx = p.x - st.startDesign.x
    const pdy = p.y - st.startDesign.y
    if (!st.moved && Math.abs(pdx) + Math.abs(pdy) > 2) st.moved = true
    if (!st.moved) return
    // 每帧从原值重算（无累积漂移）；Shift=角柄等比
    const r = scaleMembersAbout(st.bbox0, st.dir, p, st.members, e.shiftKey)
    for (const m of r.members) {
      editor.setNodeRect(m.id, { x: m.x, y: m.y, w: m.w, h: m.h })
      if (m.fontSize !== undefined) editor.setNodeFontSize(m.id, m.fontSize)
    }
    readout.value = {
      x: r.bbox.x + r.bbox.w / 2,
      y: r.bbox.y + r.bbox.h,
      text: `${Math.round(r.bbox.w)} × ${Math.round(r.bbox.h)}`,
    }
    return
  }

  if (st.kind === 'multi-rotate') {
    const a = (Math.atan2(p.y - st.center.y, p.x - st.center.x) * 180) / Math.PI
    let deg = a - st.a0
    if (!st.moved && Math.abs(a - st.a0) > 1) st.moved = true
    if (!st.moved) return
    // 近 15° 倍数吸附（4° 内）；Shift 临时脱离（多选/单选一致）
    if (!e.shiftKey) {
      const near = Math.round(deg / 15) * 15
      if (Math.abs(deg - near) < 4) deg = near
    }
    const out = rotateMembersAbout(st.center, deg, st.members)
    for (const m of out) editor.setNodeRect(m.id, { x: m.x, y: m.y, rotate: m.rotate })
    readout.value = {
      x: st.center.x,
      y: st.center.y - 26 / editor.zoom,
      text: `${Math.round(((deg % 360) + 360) % 360)}°`,
    }
    return
  }

  if (st.kind === 'rotate') {
    const a = (Math.atan2(p.y - st.center.y, p.x - st.center.x) * 180) / Math.PI
    let deg = st.rotate0 + (a - st.a0)
    if (!st.moved && Math.abs(a - st.a0) > 1) st.moved = true
    // 近 15° 倍数吸附（4° 内）；Shift 临时脱离吸附（多选/单选一致）
    if (!e.shiftKey) {
      const near = Math.round(deg / 15) * 15
      if (Math.abs(deg - near) < 4) deg = near
    }
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

  if (st.kind === 'move' || st.kind === 'resize' || st.kind === 'rotate' || st.kind === 'multi-resize' || st.kind === 'multi-rotate') {
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
  blurTypingTarget() // 右键选中的组件随后按 Delete 也要生效
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

/** 双击：文本 → 行内编辑（进入时先入历史快照，blur/Enter 提交）；组 → 进入组内编辑（嵌套组逐层进入） */
function onNodeDblClick(node: ComponentNode): void {
  if (node.type === 'group' && node.locked) {
    // 锁定组双击不再静默失败：给出明确指引（防「双击没反应」的困惑）
    ElMessage.info('该组已锁定，不可进入编辑（先在图层面板或右键解锁）')
    return
  }
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
    // 变量拖拽悬停到可绑定组件上：提示语义从「生成」切到「绑定」（松开即挂值绑定）
    if (Array.from(e.dataTransfer?.types ?? []).includes('application/x-variable')) {
      const hit = hitTestTopLevel(p)
      const label = hit ? `松开绑定到「${hit.name}」` : hint.label
      if (hint.label !== label) editor.dropHint = { ...hint, label }
    }
  }
}

function onDragLeave(): void {
  dragGhost.value = null
}

/** 拖放命中测试：顶层组件按 z 从高到低找包含设计坐标者（组/锁定/隐藏不作绑定目标，落到空白生成） */
function hitTestTopLevel(p: { x: number; y: number }): ComponentNode | null {
  const comps = [...(page.value?.components ?? [])].sort((a, b) => b.z - a.z)
  for (const n of comps) {
    if (n.type === 'group' || n.locked || n.visible === false) continue
    if (p.x >= n.x && p.x <= n.x + n.w && p.y >= n.y && p.y <= n.y + n.h) return n
  }
  return null
}

/** 变量拖放落点：命中已有组件 → 挂值绑定（独立一步 undo）；空白 → 按变量类型生成默认绑定组件
 *  （number→数值读数 / boolean→状态灯 / string→文本，创建+绑定合并为一步 undo）。 */
function dropVariable(varId: string, p: { x: number; y: number }): void {
  const v = editor.doc?.variables.find((it) => it.id === varId)
  if (!v) return
  const hit = hitTestTopLevel(p)
  if (hit) {
    const exists = (hit.bindings ?? []).some((b) => b.variableId === varId && b.prop === 'props.value')
    if (!exists) {
      editor.updateNode(hit.id, { bindings: [...(hit.bindings ?? []), { id: newId('bnd'), prop: 'props.value', variableId: varId, mode: 'value' as const }] }, 'bindings')
    }
    editor.selection = [hit.id]
    return
  }
  const kind = v.type === 'boolean' ? 'status-light' : v.type === 'string' ? 'text' : 'var-display'
  const meta = registry.get(kind as never)!
  const prop = kind === 'text' ? 'props.text' : 'props.value'
  const id = editor.addComponent(kind as never, p.x - meta.defaultSize.w / 2, p.y - meta.defaultSize.h / 2)
  if (id) editor.appendBinding(id, varId, prop)
}

function onDrop(e: DragEvent): void {
  e.preventDefault()
  dragGhost.value = null
  const dt = e.dataTransfer
  // 变量拖放（DataDrawer 变量表 → 画布）：优先于组件载荷处理
  const varId = dt?.getData('application/x-variable') || ''
  const raw = dt?.getData('application/x-widget') || dt?.getData('text/plain') || ''
  const p = toDesign(e)
  if (varId || raw.startsWith('var|')) {
    dropVariable(varId || raw.slice(4), p)
    return
  }
  if (!raw) return
  // 复合载荷：'symbol|<symbolId>'（图元库）/ 'mysym|<资产id>'（我的图元）；普通组件为纯 type
  const [type, id] = raw.split('|')
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

/** 适配视口：整页等比缩放居中（实现在 store.fitToView，缩放坞「适应」按钮共用）。 */
function fitToView(): void {
  const vp = viewportEl.value
  if (!vp) return
  editor.fitToView(vp.clientWidth, vp.clientHeight)
}

// ---------------- 画布浮层：页面铭牌 / 缩放坞 ----------------

/** 空页面引导对准页面中心（屏幕坐标：字号不随缩放变化，任何缩放级别都可读） */
const emptyGuideStyle = computed(() => {
  const p = page.value
  if (!p) return {}
  return {
    left: `${editor.pan.x + (p.screen.designWidth * editor.zoom) / 2}px`,
    top: `${editor.pan.y + (p.screen.designHeight * editor.zoom) / 2}px`,
  }
})

/** 页面铭牌贴住页面左上角（屏幕坐标，不随缩放变形）；页面上沿移出视口即隐去 */
const pageTagVisible = computed(() => !!page.value && editor.pan.y >= 28)
const pageTagStyle = computed(() => ({
  left: `${Math.max(editor.pan.x, 8)}px`,
  top: `${editor.pan.y - 26}px`,
}))

/** 以视口中心为锚点缩放（与 Ctrl+滚轮同口径，快捷键 Ctrl+0/1 复用同一换算） */
function zoomStep(factor: number): void {
  const vp = viewportEl.value
  if (!vp) return
  const cx = vp.clientWidth / 2
  const cy = vp.clientHeight / 2
  const newZoom = clamp(editor.zoom * factor, MIN_ZOOM, MAX_ZOOM)
  const dx = (cx - editor.pan.x) / editor.zoom
  const dy = (cy - editor.pan.y) / editor.zoom
  editor.setPan(cx - dx * newZoom, cy - dy * newZoom)
  editor.setZoom(newZoom)
}

/** 回到 100%（锚点同上） */
function zoomReset(): void {
  if (editor.zoom !== 1) zoomStep(1 / editor.zoom)
}

onMounted(() => {
  viewportEl.value?.addEventListener('wheel', onWheel, { passive: false })
  window.addEventListener('ws:zoom', onZoomCmd)
  window.addEventListener('resize', refreshHoverRect)
  fitToView()
})
onBeforeUnmount(() => {
  viewportEl.value?.removeEventListener('wheel', onWheel)
  window.removeEventListener('ws:zoom', onZoomCmd)
  window.removeEventListener('resize', refreshHoverRect)
  editor.lastPointerDesign = null
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
    @pointerenter="refreshHoverRect"
    @pointermove="onHoverMove"
    @pointerleave="onHoverLeave"
    @contextmenu="onContextMenu"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <!-- 组编辑面包屑（嵌套组逐层进入）：页 / 组A / 组B，点击任一级退到该层；不随画布平移缩放 -->
    <div v-if="editor.editingGroupChain.length" class="group-crumbs" @pointerdown.stop @click.stop @dblclick.stop>
      <button type="button" class="crumb" @click="editor.exitToGroupLevel(0)">{{ page?.name ?? '页面' }}</button>
      <template v-for="(g, i) in editor.editingGroupChain" :key="g.id">
        <span class="crumb-sep">›</span>
        <button
          type="button"
          class="crumb"
          :class="{ active: i === editor.editingGroupChain.length - 1 }"
          @click="editor.exitToGroupLevel(i + 1)"
        >{{ g.name }}</button>
      </template>
    </div>
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
        <CanvasNode
          v-for="node in page.components"
          :key="node.id"
          :node="node"
          @node-down="onNodeDown"
          @node-dblclick="onNodeDblClick"
        />
        <SelectionLayer @resize-start="onResizeStart" @rotate-start="onRotateStart" />
        <MarqueeSelect v-if="marquee" :rect="marquee" />
        <!-- 拖入放置 ghost：组件/变量拖拽经过时按默认尺寸预览落点；变量悬停组件上时提示语义切换 -->
        <div
          v-if="dragGhost"
          class="drop-ghost"
          :style="{ left: `${dragGhost.x}px`, top: `${dragGhost.y}px`, width: `${dragGhost.w}px`, height: `${dragGhost.h}px` }"
        >
          <span v-if="editor.dropHint?.label" class="drop-ghost-label">{{ editor.dropHint.label }}</span>
        </div>
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

    <!-- 空页面引导：画在屏幕空间（不随缩放变小），对准页面中心 -->
    <div v-if="showEmptyGuide" class="empty-guide" :style="emptyGuideStyle">
      <div class="empty-title">空白画面</div>
      <div class="empty-line">从左侧组件库 <b>拖入</b> 或 <b>点击</b> 放置组件</div>
      <div class="empty-line">右侧面板绑定数据与外观，顶部「预览」查看运行效果</div>
      <div class="empty-tip">也可以切到左侧「模板」，一键生成整页画面</div>
    </div>

    <!-- 页面铭牌：贴在页面左上角，屏幕尺寸恒定（缩放不改变字号） -->
    <div v-if="pageTagVisible" class="page-tag" :style="pageTagStyle">
      <span class="page-tag-name">{{ page?.name }}</span>
      <span class="page-tag-size ws-readout">{{ page?.screen.designWidth }} × {{ page?.screen.designHeight }}</span>
    </div>

    <!-- 缩放坞：画布右下角常驻，替代顶部工具条的缩放输入 -->
    <div class="zoom-dock" @pointerdown.stop @click.stop @dblclick.stop>
      <button class="zd-btn" type="button" title="缩小（Ctrl+滚轮）" aria-label="缩小" @click="zoomStep(1 / 1.2)">
        <el-icon :size="13"><Minus /></el-icon>
      </button>
      <button class="zd-value ws-readout" type="button" title="点击回到 100%" @click="zoomReset">
        {{ Math.round(editor.zoom * 100) }}%
      </button>
      <button class="zd-btn" type="button" title="放大（Ctrl+滚轮）" aria-label="放大" @click="zoomStep(1.2)">
        <el-icon :size="13"><Plus /></el-icon>
      </button>
      <span class="zd-sep" aria-hidden="true"></span>
      <button class="zd-btn" type="button" title="适应画布（Ctrl+1）" aria-label="适应画布" @click="fitToView">
        <el-icon :size="13"><FullScreen /></el-icon>
      </button>
    </div>

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
  /* 平移/缩放只改变本层 transform：提升为独立合成层，避免整页重绘（大画幅+图表时尤明显） */
  will-change: transform;
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

/* ghost 标签：变量/图元名与「松开绑定到 X」语义提示，悬浮于 ghost 上沿 */
.drop-ghost-label {
  position: absolute;
  left: 50%;
  bottom: 100%;
  transform: translateX(-50%);
  margin-bottom: 4px;
  padding: 2px 8px;
  border-radius: var(--ws-radius);
  background: var(--ws-ink);
  color: var(--ws-text-inverse);
  font-size: 11px;
  white-space: nowrap;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
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

/* 空页面引导：屏幕空间绘制，固定中性色（深浅画布底色均可读） */
.empty-guide {
  position: absolute;
  z-index: 5;
  width: 420px;
  padding: 26px 26px 22px;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  border: 1px dashed rgba(148, 163, 184, 0.5);
  border-radius: 6px;
  background: rgba(15, 24, 34, 0.62);
  color: rgba(190, 201, 213, 0.95);
  text-align: center;
  pointer-events: none;
  user-select: none;
}

.empty-title {
  margin-bottom: 2px;
  font-size: 20px;
  font-weight: 600;
  letter-spacing: 0.16em;
  text-indent: 0.16em;
  color: rgba(226, 232, 240, 0.9);
}

.empty-line {
  font-size: 13px;
  line-height: 1.6;
}

.empty-line b {
  font-weight: 600;
  color: rgba(240, 245, 250, 0.96);
}

.empty-tip {
  margin-top: 6px;
  padding-top: 10px;
  border-top: 1px solid rgba(148, 163, 184, 0.24);
  width: 100%;
  font-size: 12px;
  color: rgba(148, 163, 184, 0.9);
}

/* 页面铭牌：白底浮签，压在页面左上角外侧（像图纸标签） */
.page-tag {
  position: absolute;
  z-index: 6;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 20px;
  padding: 0 8px;
  border: 1px solid var(--ws-steel-3);
  border-radius: var(--ws-radius);
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 1px 3px rgba(20, 33, 46, 0.1);
  color: var(--ws-text-3);
  font-size: 11px;
  line-height: 1;
  white-space: nowrap;
  pointer-events: none;
}

.page-tag-name {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  font-weight: 600;
  color: var(--ws-text-2);
}

.page-tag-size {
  letter-spacing: 0.02em;
}

/* 缩放坞：玻璃白浮动条，悬浮在画布右下角 */
/* 组编辑面包屑：视口左上角悬浮（不随画布变换），层级可点跳转 */
.group-crumbs {
  position: absolute;
  top: 10px;
  left: 12px;
  z-index: 9100;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border: var(--ws-border);
  border-radius: var(--ws-radius-lg);
  background: var(--ws-panel);
  box-shadow: var(--ws-shadow-panel);
  font-size: 12px;
}

.group-crumbs .crumb {
  padding: 1px 6px;
  border: none;
  border-radius: var(--ws-radius);
  background: transparent;
  color: var(--ws-text-2);
  cursor: pointer;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: background-color var(--ws-duration-fast) var(--ws-ease), color var(--ws-duration-fast) var(--ws-ease);
}

.group-crumbs .crumb:hover {
  background: var(--ws-signal-a12);
  color: var(--ws-text);
}

.group-crumbs .crumb.active {
  color: var(--ws-signal-strong);
  font-weight: 600;
}

.group-crumbs .crumb-sep {
  color: var(--ws-text-3);
}

.zoom-dock {
  position: absolute;
  right: 14px;
  bottom: 14px;
  z-index: 7;
  display: flex;
  align-items: center;
  gap: 1px;
  height: 32px;
  padding: 0 4px;
  border: 1px solid var(--ws-steel-3);
  border-radius: var(--ws-radius-lg);
  /* 不透明底：backdrop-filter 会在每帧画布重绘时重算整块模糊（拖动掉帧源），此处不需要毛玻璃 */
  background: rgba(255, 255, 255, 0.97);
  box-shadow: var(--ws-shadow-float);
}

.zd-btn {
  width: 26px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: none;
  border-radius: 2px;
  background: transparent;
  color: var(--ws-text-2);
  cursor: pointer;
  transition: background-color var(--ws-duration-fast) var(--ws-ease), color var(--ws-duration-fast) var(--ws-ease);
}

.zd-btn:hover {
  background: var(--ws-signal-soft);
  color: var(--ws-signal);
}

.zd-value {
  min-width: 46px;
  height: 26px;
  padding: 0 2px;
  border: none;
  border-radius: 2px;
  background: transparent;
  color: var(--ws-text);
  font-family: var(--ws-font-tech);
  font-variant-numeric: tabular-nums;
  font-size: 11px;
  letter-spacing: 0.03em;
  cursor: pointer;
}

.zd-value:hover {
  background: var(--ws-signal-soft);
  color: var(--ws-signal);
}

.zd-sep {
  width: 1px;
  height: 16px;
  margin: 0 3px;
  background: var(--ws-steel-2);
}

/* 点阵网格（minor/major 双档密度，着色随主题令牌；缩放淡出走行内 opacity） */
.grid {
  position: absolute;
  top: 0;
  left: 0;
  z-index: 0;
  pointer-events: none;
  transition: opacity var(--ws-duration-base) var(--ws-ease);
}

.grid :deep(.dot-minor) {
  fill: var(--ws-stage-grid);
}

.grid :deep(.dot-major) {
  fill: var(--ws-stage-grid-major);
}
</style>
