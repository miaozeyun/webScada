/**
 * 编辑态实时数据：绑定效果在编辑画布直接可见（无需切预览）。
 *
 * 独立 RuntimeEngine 实例（server 只读通道）驱动共享 runtime store——
 * 编辑画布的 WidgetHost 同样读 runtime.overrides，值/绑定色/报警态/质量位自然生效；
 * 与预览（RuntimeStage 自建实例）互不干扰。反控不可达：writable=false 且
 * 编辑画布未 provideRuntime，控制组件在编辑态本就不响应写。
 *
 * 注意：RuntimeStage 卸载会 stop 自己的实例并清共享 store（overrides/报警），
 * 故预览关闭、doc 脏变更（重新索引绑定）后由宿主（EditorView）调用 start() 重建快照。
 */
import type { ProjectDoc } from '@/types/doc'
import { RuntimeEngine } from './engine'
import { useRuntimeStore } from './store'

let engine: RuntimeEngine | null = null

/** 启动/重启编辑态实时通道（幂等：先停旧实例）。需要登录 token（编辑器场景必有）。 */
export function startEditorLive(doc: ProjectDoc, projectId: string): void {
  stopEditorLive()
  const token = localStorage.getItem('webscada_token')
  if (!token) return
  engine = new RuntimeEngine()
  engine.start(doc, { writable: false, server: { projectId, token } })
}

/** 关闭实时：停通道并冻结最后一帧 overrides（engine.stop 会清共享 store，
 *  直接清空会让绑定读数回落数字 0 / 占位文案，视觉上像「数据丢了」）。 */
export function stopEditorLive(): void {
  if (!engine) return
  const runtime = useRuntimeStore()
  const frozen = new Map(runtime.overrides)
  engine.stop()
  engine = null
  for (const [key, value] of frozen) runtime.overrides.set(key, value)
}

export function isEditorLiveRunning(): boolean {
  return engine !== null
}
