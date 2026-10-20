/** 成组/解组：组节点递归 children，组内坐标为相对组原点（02 §2.6）。 */
import type { ComponentNode, Page } from '@/types/doc'
import { nodesBBox } from '@/utils/coord'
import { newComponentId } from '@/utils/nanoid'

/** 把多个顶层节点打成组：组 bbox = 成员包围盒；成员坐标转为相对组原点 */
export function buildGroup(members: ComponentNode[]): ComponentNode | null {
  if (members.length < 2) return null
  const box = nodesBBox(members)
  return {
    id: newComponentId(),
    name: `组（${members.length}）`,
    type: 'group',
    x: box.x,
    y: box.y,
    w: box.w,
    h: box.h,
    rotate: 0,
    z: Math.max(...members.map((m) => m.z)),
    visible: true,
    locked: false,
    opacity: 1,
    props: {},
    bindings: [],
    children: members.map((m) => ({ ...m, x: m.x - box.x, y: m.y - box.y })),
  }
}

/** 解组：子组件坐标还原为绝对坐标（组x+子x），children 顺序即原 z 相对顺序 */
export function flattenGroup(group: ComponentNode): ComponentNode[] {
  return (group.children ?? []).map((c) => ({
    ...c,
    x: c.x + group.x,
    y: c.y + group.y,
    children: c.children ? [...c.children] : undefined,
  }))
}

/** z 序归一化：按当前 z 升序重排并赋连续值 0..n-1（z 大者在上） */
export function normalizeZ(page: Page): void {
  const sorted = [...page.components].sort((a, b) => a.z - b.z)
  sorted.forEach((n, i) => {
    n.z = i
  })
  page.components = sorted
}
