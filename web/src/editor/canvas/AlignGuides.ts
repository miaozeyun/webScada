/**
 * 对齐吸附：阈值 5 设计像素（M1 验收）。
 * 比较对象：移动包围盒的 边/中心 与 其他组件的 边/中心 + 画布 边/中线；
 * 每轴独立取最小差值命中，返回位移与参考线位置。
 * 性能对策（M1 风险）：仅与当前页顶层组件比较，数量级 ≤200，无需视口裁剪。
 */
import type { BBox } from '@/utils/coord'

export interface SnapResult {
  dx: number
  dy: number
  /** 命中的参考线（设计坐标）：linesX 为竖直辅助线的 x 位置，linesY 为水平辅助线的 y 位置 */
  linesX: number[]
  linesY: number[]
}

const THRESHOLD = 5

export function computeSnap(
  moving: BBox,
  others: BBox[],
  canvasW: number,
  canvasH: number,
): SnapResult {
  // 候选目标：其他组件的 边/中心 + 画布 边/中线
  const targetsX: number[] = [0, canvasW / 2, canvasW]
  const targetsY: number[] = [0, canvasH / 2, canvasH]
  for (const o of others) {
    targetsX.push(o.x, o.x + o.w / 2, o.x + o.w)
    targetsY.push(o.y, o.y + o.h / 2, o.y + o.h)
  }

  const movingX = [moving.x, moving.x + moving.w / 2, moving.x + moving.w]
  const movingY = [moving.y, moving.y + moving.h / 2, moving.y + moving.h]

  const resX = bestMatch(movingX, targetsX)
  const resY = bestMatch(movingY, targetsY)

  return {
    dx: resX.delta,
    dy: resY.delta,
    linesX: resX.hit ? [resX.target] : [],
    linesY: resY.hit ? [resY.target] : [],
  }
}

function bestMatch(moving: number[], targets: number[]): { delta: number; hit: boolean; target: number } {
  let best = 0
  let bestAbs = Infinity
  let target = 0
  for (const m of moving) {
    for (const t of targets) {
      const d = t - m
      const abs = Math.abs(d)
      if (abs <= THRESHOLD && abs < bestAbs) {
        bestAbs = abs
        best = d
        target = t
      }
    }
  }
  return { delta: bestAbs <= THRESHOLD ? best : 0, hit: bestAbs <= THRESHOLD, target }
}
