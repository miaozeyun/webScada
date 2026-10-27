/**
 * 选中集整体变换数学（B-2）：等比/单轴缩放与整体旋转的成员几何口径。
 * 运行：cd web && npm test。
 */
import { describe, expect, it } from 'vitest'

import { rotateMembersAbout, scaleMembersAbout, type MemberGeom } from '@/utils/multiTransform'

const members: MemberGeom[] = [
  { id: 'a', x: 100, y: 100, w: 50, h: 40, rotate: 0, fontSize: 16 },
  { id: 'b', x: 200, y: 140, w: 50, h: 40, rotate: 30, fontSize: 20 },
]
const bbox0 = { x: 100, y: 100, w: 150, h: 80 }

describe('scaleMembersAbout', () => {
  it('se 角柄 2 倍：成员相对位置与宽高同比放大，rotate 不变，fontSize 跟随（下限 8）', () => {
    const r = scaleMembersAbout(bbox0, 'se', { x: 400, y: 260 }, members, false)
    expect(r.bbox).toEqual({ x: 100, y: 100, w: 300, h: 160 })
    const a = r.members.find((m) => m.id === 'a')!
    const b = r.members.find((m) => m.id === 'b')!
    // a 左上角相对锚点(100,100)平移 2 倍 → (100,100)；尺寸翻倍
    expect(a).toMatchObject({ x: 100, y: 100, w: 100, h: 80, rotate: 0, fontSize: 32 })
    expect(b).toMatchObject({ x: 300, y: 180, w: 100, h: 80, rotate: 30, fontSize: 40 })
  })

  it('nw 角柄：锚点为右下角，向左上拖出新包围盒（带符号距离正确）', () => {
    const r = scaleMembersAbout(bbox0, 'nw', { x: 50, y: 60 }, members, false)
    expect(r.bbox).toEqual({ x: 50, y: 60, w: 200, h: 120 })
  })

  it('w 边柄单轴：只缩 x，y/h/fontSize 不动', () => {
    const r = scaleMembersAbout(bbox0, 'w', { x: 50, y: 999 }, members, false)
    expect(r.bbox).toEqual({ x: 50, y: 100, w: 200, h: 80 })
    const a = r.members.find((m) => m.id === 'a')!
    expect(a).toMatchObject({ y: 100, h: 40, fontSize: 16 })
    expect(a.w).toBe(67) // 50*(200/150)
  })

  it('越过锚点钳到最小包围盒（不翻转）', () => {
    const r = scaleMembersAbout(bbox0, 'se', { x: 90, y: 90 }, members, false)
    expect(r.bbox.w).toBeGreaterThanOrEqual(12)
    expect(r.bbox.h).toBeGreaterThanOrEqual(12)
  })

  it('Shift 等比：以较大比例统一缩放', () => {
    const r = scaleMembersAbout(bbox0, 'se', { x: 550, y: 180 }, members, true)
    // 期望宽 450 高 80 → 等比取 max(3, 1) = 3 → 450×240
    expect(r.bbox).toEqual({ x: 100, y: 100, w: 450, h: 240 })
  })

  it('字号下限 8：缩到极小不再往下', () => {
    const r = scaleMembersAbout(bbox0, 'se', { x: 112, y: 104 }, members, false)
    const a = r.members.find((m) => m.id === 'a')!
    expect(a.fontSize).toBe(8)
  })
})

describe('rotateMembersAbout', () => {
  it('成员中心绕包围盒中心公转，rotate = rotate0+θ 归一化', () => {
    const center = { x: 175, y: 140 } // bbox 中心
    const r = rotateMembersAbout(center, 90, members)
    const a = r.find((m) => m.id === 'a')!
    const b = r.find((m) => m.id === 'b')!
    // a 中心 (125,120) 绕 (175,140) 顺时针 90° → (195,90)
    expect(a).toMatchObject({ x: 170, y: 70, w: 50, h: 40, rotate: 90 })
    expect(b).toMatchObject({ rotate: 120 }) // 30 + 90
    // b 中心 (225,160) → 旋转后 (160+ ... ) 只验证 rotate 与尺寸不变
    expect(b).toMatchObject({ w: 50, h: 40 })
  })

  it('θ 越过 360 归一化到 [0,360)', () => {
    const r = rotateMembersAbout({ x: 0, y: 0 }, 350, [{ id: 'a', x: 10, y: 10, w: 10, h: 10, rotate: 20 }])
    expect(r[0].rotate).toBe(10)
  })
})
