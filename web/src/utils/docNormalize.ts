/** doc 字段规范化：模板预置/历史工程/导入数据可能缺省可选字段（bindings/locked/z/…），
 *  读取时统一补全，避免运行时消费点（克隆 id 重映射、绑定遍历等）踩 undefined。
 *  z 缺省时按所在层级序号补值（模板组件按声明顺序叠放）。 */
import type { ComponentNode, ProjectDoc } from '@/types/doc'

function normalizeNode(n: ComponentNode, index: number): ComponentNode {
  const children = n.children?.map(normalizeNode)
  return {
    ...n,
    rotate: n.rotate ?? 0,
    z: n.z ?? index,
    visible: n.visible ?? true,
    locked: n.locked ?? false,
    opacity: n.opacity ?? 1,
    props: n.props ?? {},
    bindings: n.bindings ?? [],
    children,
  }
}

/** 递归补全工程 doc 全部页面组件的可选字段（原对象浅拷贝，不修改入参） */
export function normalizeDoc(doc: ProjectDoc): ProjectDoc {
  doc.pages = doc.pages.map((p) => ({ ...p, components: normalizeComponents(p.components) }))
  return doc
}

/** 单个组件列表的同口径补全（模板新建页面 / 我的图元插入等入口） */
export function normalizeComponents(nodes: ComponentNode[]): ComponentNode[] {
  return nodes.map(normalizeNode)
}
