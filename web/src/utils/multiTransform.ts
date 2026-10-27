/**
 * 选中集整体变换数学（B-2）：多选包围盒的 8 向缩放 + 绕中心整体旋转。
 *
 * 口径（与审计校验修正一致）：
 * - 角柄缩放：成员中心随包围盒锚点比例平移、宽高按比例缩放、自身旋转角不变
 *  （等比缩放下这是精确解）；fontSize 跟随几何比例，下限 8px。
 * - 边柄单轴缩放：只动该轴；带自旋转成员的成员级拉伸不精确（保留 rotate 不变），已知限制。
 * - 旋转：成员 rotate = mod360(rotate0 + θ)，中心绕包围盒中心公转。
 * 全部为纯函数，调用方负责一次 beginChange 快照与取整写入。
 */
import type { Dir8 } from './resize'
import { calculateRotatedPointCoordinate, mod360 } from './resize'

export interface Box {
  x: number
  y: number
  w: number
  h: number
}

export interface MemberGeom {
  id: string
  x: number
  y: number
  w: number
  h: number
  rotate: number
  fontSize?: number
}

export interface TransformedMember {
  id: string
  x: number
  y: number
  w: number
  h: number
  rotate: number
  fontSize?: number
}

/** 包围盒最小尺寸（拖到比这小就钳住，防翻转/消失） */
export const MULTI_MIN_BOX = 12
/** 字号下限（再小不可读，钳到 8px） */
export const FONT_MIN = 8

const CORNERS: Dir8[] = ['nw', 'ne', 'se', 'sw']

/** dir 的固定锚点：对角（角柄）或对边（边柄）上的不动点 */
function anchorOf(bbox: Box, dir: Dir8): { x: number; y: number } {
  const east = dir.includes('e')
  const west = dir.includes('w')
  const north = dir.startsWith('n')
  const south = dir.startsWith('s')
  return {
    x: west ? bbox.x + bbox.w : east ? bbox.x : dir === 'n' || dir === 's' ? bbox.x : bbox.x,
    y: south ? bbox.y : north ? bbox.y + bbox.h : bbox.y,
  }
}

/** 按指针位置求新包围盒并变换全部成员（设计坐标；lock=Shift 等比） */
export function scaleMembersAbout(
  bbox0: Box,
  dir: Dir8,
  pointer: { x: number; y: number },
  members: MemberGeom[],
  lock: boolean,
): { bbox: Box; members: TransformedMember[] } {
  const anchor = anchorOf(bbox0, dir)
  const isCorner = CORNERS.includes(dir)
  const axisV = dir === 'n' || dir === 's'
  const axisH = dir === 'e' || dir === 'w'

  // 自由边到锚点的带符号距离（朝锚点外拖为正，越过锚点钳到最小值）
  let dx = dir.includes('e') ? pointer.x - anchor.x : dir.includes('w') ? anchor.x - pointer.x : 0
  let dy = dir.startsWith('s') ? pointer.y - anchor.y : dir.startsWith('n') ? anchor.y - pointer.y : 0

  let w = axisH || isCorner ? Math.max(MULTI_MIN_BOX, dx) : bbox0.w
  let h = axisV || isCorner ? Math.max(MULTI_MIN_BOX, dy) : bbox0.h
  if (isCorner && lock) {
    const s = Math.max(w / bbox0.w, h / bbox0.h)
    w = s * bbox0.w
    h = s * bbox0.h
  }

  // 左上角：自由边随指针（w/h 已含钳制），固定边贴锚点；不动的轴保持原值
  const x0 = dir.includes('w') ? anchor.x - w : dir.includes('e') ? anchor.x : bbox0.x
  const y0 = dir.startsWith('n') ? anchor.y - h : dir.startsWith('s') ? anchor.y : bbox0.y

  const sx = w / bbox0.w
  const sy = h / bbox0.h
  const bbox: Box = { x: x0, y: y0, w, h }

  const out: TransformedMember[] = members.map((m) => {
    // 成员左上角随锚点比例平移（单轴时另一轴不动）；宽高按各自轴向比例缩放
    const mx = anchor.x + (m.x - anchor.x) * (axisH ? sx : axisV ? 1 : sx)
    const my = anchor.y + (m.y - anchor.y) * (axisH ? 1 : axisV ? sy : sy)
    const mw = axisV ? m.w : m.w * sx
    const mh = axisH ? m.h : m.h * sy
    // 字号只在角柄路径跟随几何（单轴不动）；下限 8px
    const fs =
      isCorner && m.fontSize !== undefined
        ? Math.max(FONT_MIN, Math.round(m.fontSize * ((sx + sy) / 2)))
        : m.fontSize
    return {
      id: m.id,
      x: Math.round(mx),
      y: Math.round(my),
      w: Math.max(4, Math.round(mw)),
      h: Math.max(4, Math.round(mh)),
      rotate: m.rotate,
      ...(fs !== undefined ? { fontSize: fs } : {}),
    }
  })
  return { bbox, members: out }
}

/** 绕包围盒中心整体旋转 θ 度：成员中心公转 + rotate0+θ 归一化 [0,360) */
export function rotateMembersAbout(
  center: { x: number; y: number },
  thetaDeg: number,
  members: MemberGeom[],
): TransformedMember[] {
  return members.map((m) => {
    const c = calculateRotatedPointCoordinate({ x: m.x + m.w / 2, y: m.y + m.h / 2 }, center, thetaDeg)
    return {
      id: m.id,
      x: Math.round(c.x - m.w / 2),
      y: Math.round(c.y - m.h / 2),
      w: m.w,
      h: m.h,
      rotate: mod360(Math.round((m.rotate + thetaDeg) * 10) / 10),
      ...(m.fontSize !== undefined ? { fontSize: m.fontSize } : {}),
    }
  })
}
