/**
 * 8 向缩放数学：对称点锚定算法 —— 移植自 visual-drag-demo
 * （MIT License, Copyright (c) 2021 谭光志，见仓库根 THIRD_PARTY_NOTICES.md）
 *
 * 核心思想：拖动某柄时，"对角对称点"在世界坐标系固定不动；把鼠标位置与对称点
 * 逆旋转回轴对齐坐标系求新宽高，再正旋转回世界系求新左上角。任意旋转角精确成立。
 * 改良点：本移植全部在【设计坐标系】计算（原实现在缩放画布上有近似误差），
 * 鼠标位置由调用方先换算为设计坐标。
 */

export interface Pt {
  x: number
  y: number
}

/** 点绕圆心旋转（正角度=顺时针，屏幕坐标系） */
export function calculateRotatedPointCoordinate(point: Pt, center: Pt, rotate: number): Pt {
  const rad = (rotate * Math.PI) / 180
  return {
    x: (point.x - center.x) * Math.cos(rad) - (point.y - center.y) * Math.sin(rad) + center.x,
    y: (point.x - center.x) * Math.sin(rad) + (point.y - center.y) * Math.cos(rad) + center.y,
  }
}

/** 两点中点 */
export function getCenterPoint(p1: Pt, p2: Pt): Pt {
  return { x: p1.x + (p2.x - p1.x) / 2, y: p1.y + (p2.y - p1.y) / 2 }
}

export function mod360(deg: number): number {
  return (deg + 360) % 360
}

/** 组件几何（设计坐标） */
export interface RectStyle {
  x: number
  y: number
  w: number
  h: number
  rotate: number
}

/** 8 向（沿用项目命名：nw/n/ne/e/se/s/sw/w） */
export type Dir8 = 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w'

/** 柄在未旋转坐标系中的位置（用于计算对称点与旋转参考） */
export function handlePoint(style: RectStyle, dir: Dir8): Pt {
  const { x, y, w, h } = style
  const map: Record<Dir8, Pt> = {
    nw: { x, y },
    n: { x: x + w / 2, y },
    ne: { x: x + w, y },
    e: { x: x + w, y: y + h / 2 },
    se: { x: x + w, y: y + h },
    s: { x: x + w / 2, y: y + h },
    sw: { x, y: y + h },
    w: { x, y: y + h / 2 },
  }
  return map[dir]
}

/**
 * 计算缩放后的几何。
 * @param style    当前几何（就地修改，同时返回）
 * @param dir      拖动的柄方向
 * @param curPos   鼠标当前设计坐标
 * @param lockProportion  是否锁定宽高比（Shift）
 * @param center   拖动开始时的组件中心
 * @param startHandle    拖动开始时柄的位置（设计坐标）
 */
export function calcResize(
  style: RectStyle,
  dir: Dir8,
  curPos: Pt,
  lockProportion: boolean,
  center: Pt,
  startHandle: Pt,
): RectStyle {
  const symmetricPoint: Pt = { x: center.x * 2 - startHandle.x, y: center.y * 2 - startHandle.y }
  const proportion = style.w / style.h

  // 与原实现一致：角柄用中心-对称点法；边柄（t/b/l/r）用旋转中点投影法
  switch (dir) {
    case 'nw':
      cornerResize(style, curPos, symmetricPoint, lockProportion, proportion, 'nw')
      break
    case 'ne':
      cornerResize(style, curPos, symmetricPoint, lockProportion, proportion, 'ne')
      break
    case 'se':
      cornerResize(style, curPos, symmetricPoint, lockProportion, proportion, 'se')
      break
    case 'sw':
      cornerResize(style, curPos, symmetricPoint, lockProportion, proportion, 'sw')
      break
    case 'n':
      edgeResize(style, curPos, symmetricPoint, startHandle, lockProportion, proportion, 'v')
      break
    case 's':
      edgeResize(style, curPos, symmetricPoint, startHandle, lockProportion, proportion, 'v')
      break
    case 'w':
      edgeResize(style, curPos, symmetricPoint, startHandle, lockProportion, proportion, 'h')
      break
    case 'e':
      edgeResize(style, curPos, symmetricPoint, startHandle, lockProportion, proportion, 'h')
      break
  }
  return style
}

/** 角柄：以对称点为锚，逆旋转求新宽高与新左上角（等比锁定时二次归算，忠实原实现） */
function cornerResize(
  style: RectStyle,
  curPos: Pt,
  symmetricPoint: Pt,
  lock: boolean,
  proportion: number,
  corner: 'nw' | 'ne' | 'se' | 'sw',
): void {
  let newCenter = getCenterPoint(curPos, symmetricPoint)
  let a = calculateRotatedPointCoordinate(corner === 'se' || corner === 'sw' ? symmetricPoint : curPos, newCenter, -style.rotate)
  let b = calculateRotatedPointCoordinate(corner === 'se' || corner === 'sw' ? curPos : symmetricPoint, newCenter, -style.rotate)

  let newW = b.x - a.x
  let newH = b.y - a.y

  if (lock) {
    // 等比：按比例回缩，再以对称点重算中心（原实现的二次归算）
    if (newW / newH > proportion) {
      if (corner === 'nw') a.x += Math.abs(newW - newH * proportion)
      else if (corner === 'ne') b.x -= Math.abs(newW - newH * proportion)
      else if (corner === 'se') b.x -= Math.abs(newW - newH * proportion)
      else a.x += Math.abs(newW - newH * proportion)
      newW = newH * proportion
    } else {
      if (corner === 'nw') a.y += Math.abs(newH - newW / proportion)
      else if (corner === 'ne') b.y += Math.abs(newH - newW / proportion)
      else if (corner === 'se') b.y -= Math.abs(newH - newW / proportion)
      else a.y -= Math.abs(newH - newW / proportion)
      newH = newW / proportion
    }
    const rotatedAnchor = calculateRotatedPointCoordinate(corner === 'se' || corner === 'sw' ? b : a, newCenter, style.rotate)
    newCenter = getCenterPoint(rotatedAnchor, symmetricPoint)
    a = calculateRotatedPointCoordinate(corner === 'se' || corner === 'sw' ? symmetricPoint : rotatedAnchor, newCenter, -style.rotate)
    b = calculateRotatedPointCoordinate(corner === 'se' || corner === 'sw' ? rotatedAnchor : symmetricPoint, newCenter, -style.rotate)
    newW = b.x - a.x
    newH = b.y - a.y
  }

  if (newW > 0 && newH > 0) {
    style.w = Math.round(newW)
    style.h = Math.round(newH)
    style.x = Math.round(Math.min(a.x, b.x))
    style.y = Math.round(Math.min(a.y, b.y))
  }
}

/** 边柄：把鼠标位置逆旋转求投影长度（勾股定理），另一维保持（或按等比联动） */
function edgeResize(
  style: RectStyle,
  curPos: Pt,
  symmetricPoint: Pt,
  curPoint: Pt,
  lock: boolean,
  proportion: number,
  axis: 'v' | 'h',
): void {
  if (axis === 'v') {
    const rotatedCur = calculateRotatedPointCoordinate(curPos, curPoint, -style.rotate)
    const rotatedMiddle = calculateRotatedPointCoordinate({ x: curPoint.x, y: rotatedCur.y }, curPoint, style.rotate)
    const newH = Math.sqrt((rotatedMiddle.x - symmetricPoint.x) ** 2 + (rotatedMiddle.y - symmetricPoint.y) ** 2)
    const newCenter = {
      x: rotatedMiddle.x - (rotatedMiddle.x - symmetricPoint.x) / 2,
      y: rotatedMiddle.y + (symmetricPoint.y - rotatedMiddle.y) / 2,
    }
    const w = lock ? newH * proportion : style.w
    style.w = w
    style.h = Math.round(newH)
    style.y = Math.round(newCenter.y - newH / 2)
    style.x = Math.round(newCenter.x - w / 2)
  } else {
    const rotatedCur = calculateRotatedPointCoordinate(curPos, curPoint, -style.rotate)
    const rotatedMiddle = calculateRotatedPointCoordinate({ x: rotatedCur.x, y: curPoint.y }, curPoint, style.rotate)
    const newW = Math.sqrt((rotatedMiddle.x - symmetricPoint.x) ** 2 + (rotatedMiddle.y - symmetricPoint.y) ** 2)
    const newCenter = {
      x: rotatedMiddle.x - (rotatedMiddle.x - symmetricPoint.x) / 2,
      y: rotatedMiddle.y + (symmetricPoint.y - rotatedMiddle.y) / 2,
    }
    const h = lock ? newW / proportion : style.h
    style.h = h
    style.w = Math.round(newW)
    style.x = Math.round(newCenter.x - newW / 2)
    style.y = Math.round(newCenter.y - h / 2)
  }
}

/** 旋转感知光标（移植自原 Shape.vue：柄随组件旋转角映射 resize 光标方向） */
const ANGLE_TO_CURSOR: { start: number; end: number; cursor: string }[] = [
  { start: 338, end: 23, cursor: 'nw' },
  { start: 23, end: 68, cursor: 'n' },
  { start: 68, end: 113, cursor: 'ne' },
  { start: 113, end: 158, cursor: 'e' },
  { start: 158, end: 203, cursor: 'se' },
  { start: 203, end: 248, cursor: 's' },
  { start: 248, end: 293, cursor: 'sw' },
  { start: 293, end: 338, cursor: 'w' },
]

const INITIAL_ANGLE: Record<Dir8, number> = {
  nw: 0,
  n: 45,
  ne: 90,
  e: 135,
  se: 180,
  s: 225,
  sw: 270,
  w: 315,
}

export function cursorForHandle(dir: Dir8, rotate: number): string {
  const angle = mod360(INITIAL_ANGLE[dir] + rotate)
  if (angle < 23 || angle >= 338) return 'nwse-resize'
  const hit = ANGLE_TO_CURSOR.find((a) => a.start <= angle && angle < a.end)
  return `${hit!.cursor}-resize`
}
