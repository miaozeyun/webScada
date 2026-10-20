/** 画布几何工具：设计坐标系下的包围盒 / 相交 / 旋转。 */

export interface BBox {
  x: number
  y: number
  w: number
  h: number
}

/** 多节点包围盒（输入为绝对坐标） */
export function nodesBBox(nodes: { x: number; y: number; w: number; h: number }[]): BBox {
  if (nodes.length === 0) return { x: 0, y: 0, w: 0, h: 0 }
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const n of nodes) {
    minX = Math.min(minX, n.x)
    minY = Math.min(minY, n.y)
    maxX = Math.max(maxX, n.x + n.w)
    maxY = Math.max(maxY, n.y + n.h)
  }
  return { x: minX, y: minY, w: maxX - minX, h: maxY - minY }
}

export function bboxIntersect(a: BBox, b: BBox): boolean {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y
}

/**
 * 旋转后的中心位移换算：组件绕中心旋转 θ 后，尺寸变化 (dw,dh) 若要保持"对角锚点"固定，
 * 中心需在局部坐标系平移 (dw/2*sx, dh/2*sy)，再旋转到世界系。
 * M1 约定（风险对策）：缩放柄按轴对齐包围盒工作，不做斜向缩放数学。
 */
export function centerShiftForResize(dw: number, dh: number, sx: number, sy: number, rotateDeg: number): { dx: number; dy: number } {
  const rad = (rotateDeg * Math.PI) / 180
  const vx = (dw / 2) * sx
  const vy = (dh / 2) * sy
  return {
    dx: vx * Math.cos(rad) - vy * Math.sin(rad),
    dy: vx * Math.sin(rad) + vy * Math.cos(rad),
  }
}

export function clamp(v: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, v))
}
