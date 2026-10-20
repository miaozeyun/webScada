/**
 * 事件与行为（M7）：运行态组件事件 → 动作执行；控制组件（开关/多档/输入框）的
 * 写通道经 RuntimeApi 注入。编辑态无 provider → 渲染静态缺省、不响应交互。
 */
import { inject, provide, type InjectionKey } from 'vue'
import { ElMessage } from 'element-plus'
import type { ComponentNode, EventActionDef, EventTrigger, ProjectDoc } from '@/types/doc'
import type { RuntimeEngine } from './engine'
import { useRuntimeStore } from './store'

/** 运行态能力注入（RuntimeStage provide；WidgetHost 内的控制组件 inject） */
export interface RuntimeApi {
  writable: boolean
  write(variableId: string, value: number | boolean | string): Promise<void>
  /** 控制组件直接取变量当前值（无绑定时渲染自身状态） */
  valueOf(variableId: string): number | boolean | string | undefined
  /** 运行态内存滚动序列（近 60 点，live 迷你趋势图用） */
  historyOf(variableId: string): number[]
}

export const RUNTIME_API: InjectionKey<RuntimeApi> = Symbol('runtime-api')

/** 事件分发注入（RuntimeStage provide；PreviewNode 在 DOM 事件里调用） */
export type NodeEventRunner = (node: ComponentNode, trigger: EventTrigger) => void

export const RUNTIME_EVENTS: InjectionKey<NodeEventRunner> = Symbol('runtime-events')

export function useRuntimeApi(): RuntimeApi | null {
  return inject(RUNTIME_API, null)
}

export function useNodeEventRunner(): NodeEventRunner | null {
  return inject(RUNTIME_EVENTS, null)
}

export interface ActionContext {
  engine: RuntimeEngine
  doc: ProjectDoc
  switchPage(pageId: string): void
}

/** 全工程节点扁平索引（toggleVisible 需要查目标当前显隐） */
function flattenNodes(doc: ProjectDoc): Map<string, ComponentNode> {
  const map = new Map<string, ComponentNode>()
  const walk = (nodes: ComponentNode[]): void => {
    for (const n of nodes) {
      map.set(n.id, n)
      if (n.children) walk(n.children)
    }
  }
  for (const p of doc.pages) walk(p.components)
  return map
}

/** 动作执行器（唯一实现点；写失败/引用失效给用户反馈，不中断其它动作） */
export async function runActions(actions: EventActionDef[], ctx: ActionContext): Promise<void> {
  const runtime = useRuntimeStore()
  const nodeById = flattenNodes(ctx.doc)
  for (const act of actions) {
    try {
      switch (act.type) {
        case 'writeVar': {
          if (!act.variableId) break
          // 写入值支持表达式（'1' / 'tank.level + 1'）；解析失败按原字符串处理
          let value: number | boolean | string
          try {
            value = ctx.engine.evalValueExpr(act.value ?? '0')
          } catch {
            value = act.value ?? 0
          }
          await ctx.engine.write(act.variableId, value)
          break
        }
        case 'showPopup':
          if (act.targetId) ctx.engine.setNodeVisible(act.targetId, true)
          break
        case 'hidePopup':
          if (act.targetId) ctx.engine.setNodeVisible(act.targetId, false)
          break
        case 'toggleVisible': {
          if (!act.targetId) break
          const target = nodeById.get(act.targetId)
          // 优先级：override.visible > popup 默认隐藏 > node.visible
          const current = runtime.overrides.get(act.targetId)?.visible
            ?? (target?.popup ? false : target?.visible !== false)
          ctx.engine.setNodeVisible(act.targetId, !current)
          break
        }
        case 'switchPage':
          if (act.pageId) ctx.switchPage(act.pageId)
          break
        case 'openUrl':
          if (act.url) window.open(act.url, '_blank', 'noopener')
          break
      }
    } catch (err) {
      ElMessage.error(`动作执行失败（${act.type}）：${(err as Error).message}`)
    }
  }
}

/** RuntimeStage 侧组装：provide 两个注入键 */
export function provideRuntime(ctx: ActionContext, writable: boolean): void {
  provide(RUNTIME_API, {
    writable,
    write: (variableId, value) => ctx.engine.write(variableId, value),
    valueOf: (variableId) => useRuntimeStore().values.get(variableId),
    historyOf: (variableId) => ctx.engine.historyOf(variableId),
  })
  provide(RUNTIME_EVENTS, (node, trigger) => {
    for (const ev of node.events ?? []) {
      if (ev.trigger === trigger) void runActions(ev.actions, ctx)
    }
  })
}
