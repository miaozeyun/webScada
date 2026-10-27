/**
 * 变量引用扫描：删除变量/数据源前回答「删了会影响谁」。
 *
 * 硬引用（删除会被服务端 422 打回或运行态直接失效）：组件绑定、事件 writeVar、报警规则。
 * 软引用（表达式按 key 引用，删除后求值失败但工程仍可保存）：其它虚拟变量 expr。
 */
import type { ComponentNode, ProjectDoc, VariableDef } from '@/types/doc'

export type UsageKind = 'binding' | 'event' | 'prop' | 'alarm' | 'expr'

export interface VariableUsage {
  kind: UsageKind
  /** 给人看的位置，如「页1 / 1号泵 · 绑定 fill」 */
  where: string
  /** 跳转定位（查找引用面板用）：组件类引用填页面/节点/所属顶层组 id，报警与表达式引用为空串 */
  pageId: string
  nodeId: string
  /** 引用落在组内时的顶层组 id（组编辑上下文仅支持顶层组），顶层引用为 '' */
  groupId: string
}

/** props 里的变量引用可能嵌套（如表格列配置），递归找 id */
function containsId(value: unknown, id: string): boolean {
  if (value === id) return true
  if (Array.isArray(value)) return value.some((v) => containsId(v, id))
  if (value && typeof value === 'object') return Object.values(value).some((v) => containsId(v, id))
  return false
}

function walk(
  nodes: ComponentNode[] | null | undefined,
  pageName: string,
  pageId: string,
  groupId: string,
  out: (node: ComponentNode, where: string, pageId: string, groupId: string) => void,
): void {
  for (const node of nodes ?? []) {
    const where = `${pageName} / ${node.name || node.id}`
    out(node, where, pageId, groupId)
    if (node.children?.length) {
      // 顶层组的 id 即组编辑上下文；嵌套组不另开上下文（editingGroup 只认顶层）
      walk(node.children, pageName, pageId, groupId || (node.type === 'group' ? node.id : ''), out)
    }
  }
}

export function findVariableUsage(doc: ProjectDoc, variable: VariableDef): VariableUsage[] {
  const usages: VariableUsage[] = []
  for (const page of doc.pages) {
    walk(page.components, page.name, page.id, '', (node, where, pageId, groupId) => {
      for (const b of node.bindings ?? []) {
        if (b.variableId === variable.id) usages.push({ kind: 'binding', where: `${where} · 绑定 ${b.prop}`, pageId, nodeId: node.id, groupId })
      }
      // 开关/多档/输入框/历史趋势/历史表格把变量 id 存在 props（registry 的 'variable' 选择器）
      for (const [key, value] of Object.entries(node.props ?? {})) {
        if (containsId(value, variable.id)) usages.push({ kind: 'prop', where: `${where} · 属性 ${key}`, pageId, nodeId: node.id, groupId })
      }
      for (const ev of node.events ?? []) {
        for (const act of ev.actions ?? []) {
          if (act.type === 'writeVar' && act.variableId === variable.id) {
            usages.push({ kind: 'event', where: `${where} · 事件写变量`, pageId, nodeId: node.id, groupId })
          }
        }
      }
    })
  }
  for (const rule of doc.alarmRules) {
    if (rule.variableId === variable.id) usages.push({ kind: 'alarm', where: `报警规则「${rule.name}」`, pageId: '', nodeId: '', groupId: '' })
  }
  // 表达式引用按 key 匹配（标识符口径与 expr 解析器一致：字母/数字/下划线/点）
  const keyRe = new RegExp(`(^|[^A-Za-z0-9_.])${variable.key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}([^A-Za-z0-9_.]|$)`)
  for (const v of doc.variables) {
    if (v.id !== variable.id && v.expr && keyRe.test(v.expr)) {
      usages.push({ kind: 'expr', where: `虚拟变量「${v.label}」的表达式`, pageId: '', nodeId: '', groupId: '' })
    }
  }
  return usages
}

/** 数据源下的变量（删除数据源前阻断用） */
export function variablesOfDatasource(doc: ProjectDoc, datasourceId: string): VariableDef[] {
  return doc.variables.filter((v) => v.datasourceId === datasourceId)
}
