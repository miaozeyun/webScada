/**
 * 历史区间查询接口（M8，03-接口清单 §2.10 / 实施契约 §4.2）。
 * 服务端 historian 定窗采样入库（history_values），取代浏览器直查；本地分钟桶降级为演示/离线兜底。
 * 认证：JWT（编辑器/运行页任意角色）；分享页由宿主注入 shareToken（Bearer 形态，服务端识别 token 类型）。
 */
import { http } from './http'

export interface HistoryQuery {
  /** 变量 key 列表（≤20，服务端校验）；序列化为逗号分隔 keys 参数 */
  keys: string[]
  /** 起止 epoch 毫秒（含），内部转 ISO8601 UTC；跨度 ≤ HISTORY_RETENTION_DAYS */
  from: number
  to: number
  /** >0 服务端按窗口聚合降采样（口径见 agg）；0/缺省=原始采样点 */
  stepMs?: number
  /** 单序列返回点数上限（≤10000；超出服务端自动增大 stepMs） */
  maxPoints?: number
  /** 窗口聚合口径（阶段二 Task 1）：mean=均值（缺省）/min/max/last=窗口内最后一点/sum=窗口内求和 */
  agg?: 'mean' | 'min' | 'max' | 'last' | 'sum'
}

export interface HistorySeries {
  /** key → [epochMs, 工程值][]（服务端换算流水后；boolean 存 1/0） */
  series: Record<string, [number, number][]>
}

// ---- 分享页通道（宿主注入；编辑器/运行页不调用） ----

let shareToken: string | null = null

/** 分享页宿主注入 shareToken（GET /history 走 Authorization: Bearer <shareToken>）；传 null 恢复 JWT 通道 */
export function setHistoryShareToken(token: string | null): void {
  shareToken = token
}

let runtimeProjectId = ''

/**
 * 运行态宿主注入当前工程 id（组件自身无法从 doc 反查 projectId 的场景，如分享页/独立运行页）；
 * 历史图组件按「组件显式配置 → editor store → 本注入」顺序解析，传空串清除。
 */
export function setHistoryProjectId(projectId: string): void {
  runtimeProjectId = projectId
}

/** 供历史图组件读取宿主注入的工程 id */
export function getHistoryProjectId(): string {
  return runtimeProjectId
}

/** 区间查询；失败由调用方捕获（历史图组件异常时回落本地分钟桶缓冲） */
export function queryHistory(projectId: string, q: HistoryQuery): Promise<HistorySeries> {
  const params: Record<string, string | number> = {
    keys: q.keys.join(','),
    from: new Date(q.from).toISOString(),
    to: new Date(q.to).toISOString(),
  }
  if (q.stepMs && q.stepMs > 0) params.stepMs = q.stepMs
  if (q.maxPoints && q.maxPoints > 0) params.maxPoints = q.maxPoints
  if (q.agg) params.agg = q.agg
  const config = shareToken
    ? { params, headers: { Authorization: `Bearer ${shareToken}` } }
    : { params }
  return http.get<HistorySeries>(`/projects/${projectId}/history`, config)
}
