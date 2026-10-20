/** 画布交互公共类型。 */
export type ResizeDir = 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w' | 'nw'

/** 缩放柄方向 → x/y 符号（e=+1、w=-1、n=-1、s=+1、边柄另一轴为 0） */
export const DIR_SIGN: Record<ResizeDir, { sx: number; sy: number }> = {
  n: { sx: 0, sy: -1 },
  ne: { sx: 1, sy: -1 },
  e: { sx: 1, sy: 0 },
  se: { sx: 1, sy: 1 },
  s: { sx: 0, sy: 1 },
  sw: { sx: -1, sy: 1 },
  w: { sx: -1, sy: 0 },
  nw: { sx: -1, sy: -1 },
}
