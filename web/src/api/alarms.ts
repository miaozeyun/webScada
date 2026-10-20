/**
 * 报警接口（M8，03-接口清单 §2.7 / 实施契约 §4.1）：
 * 服务端单行状态机 status ∈ triggered | acked | cleared；ack 为 operator/admin 专属动作，
 * 成功后服务端向工程在线 WS 广播 alarmAck 帧（前端经 runtime store 事件流联动）。
 * 本模块同时是前端报警呈现的轻量配置点：
 *  - 角色缓存（ack 按钮显隐）：fetchMyRole()
 *  - 报警级别色注入：setAlarmLevelColors()（宿主启动运行态时注入 doc.settings.alarm.levelColors）
 *  - REST ack 成功的页面内联动：onAlarmAcked()（同宿主多组件同步，如 Banner ack → Panel 刷新）
 */
import { http } from './http'
import type { AlarmLevel } from '@/types/doc'

/** 服务端报警状态（M8 单行状态机）；未知值前端一律灰显兜底（契约 §11.8 存量兼容） */
export type AlarmStatus = 'triggered' | 'acked' | 'cleared'

/** 报警列表条目（03 §2.7 AlarmOut；时间 REST=ISO8601 UTC） */
export interface AlarmOut {
  id: number
  /** 触发时规则快照（规则被删后历史仍可读） */
  ruleId: string
  /** 触发时变量 key 快照 */
  variableKey: string
  level: AlarmLevel
  message: string
  /** 工程值字符串快照（变量级换算后，与 WS 帧/界面同口径） */
  value: string | null
  status: AlarmStatus
  triggeredAt: string
  ackedAt?: string | null
  ackedBy?: string | null
  ackedNote?: string | null
  clearedAt?: string | null
}

export interface AlarmListOut {
  total: number
  page: number
  size: number
  items: AlarmOut[]
}

/** ack 响应（triggered→acked；cleared 后补确认只填 ack 字段、status 保持 cleared；幂等） */
export interface AlarmAckOut {
  id: number
  status: AlarmStatus
  ackedAt: string
  ackedBy: string
  ackedNote: string | null
}

/** 列表过滤参数（契约 §4.1：status 缺省=triggered,acked 未恢复集合；variableKey 前缀匹配） */
export interface AlarmListParams {
  /** 多值，逗号拼接后传服务端；空数组=不传（走服务端缺省） */
  status?: string[]
  level?: AlarmLevel | ''
  variableKey?: string
  /** ISO8601，按 triggeredAt 过滤 */
  from?: string
  to?: string
  page?: number
  size?: number
}

export const listAlarms = (projectId: string, params: AlarmListParams = {}) => {
  const q: Record<string, string | number> = {}
  if (params.status && params.status.length > 0) q.status = params.status.join(',')
  if (params.level) q.level = params.level
  if (params.variableKey) q.variableKey = params.variableKey
  if (params.from) q.from = params.from
  if (params.to) q.to = params.to
  q.page = params.page ?? 1
  q.size = params.size ?? 20
  return http.get<AlarmListOut>(`/projects/${projectId}/alarms`, { params: q })
}

/** 报警确认（operator/admin；viewer 403）。note 可选 ≤256 字符；成功后派发页面内 ack 联动事件 */
export async function ackAlarm(projectId: string, alarmId: number, note?: string): Promise<AlarmAckOut> {
  const resp = await http.post<AlarmAckOut>(
    `/projects/${projectId}/alarms/${alarmId}/ack`,
    note ? { note } : {},
  )
  emitAlarmAcked(alarmId)
  return resp
}

// ---- 当前用户角色（ack 按钮显隐依据；会话内缓存一次） ----

export type UserRole = 'admin' | 'operator' | 'viewer'

let cachedRole: UserRole | null | undefined // undefined=未拉取

/**
 * 拉 /auth/me 的 role（M8 起返回 role 字段）。
 * 无 JWT（分享页）或请求失败一律返回 null，调用方据此隐藏 ack 按钮。
 * 缓存策略：会话内缓存；角色变更/登出后刷新页面生效（角色为低频管理操作）。
 */
export async function fetchMyRole(): Promise<UserRole | null> {
  if (cachedRole !== undefined) return cachedRole
  if (!localStorage.getItem('webscada_token')) {
    cachedRole = null
    return null
  }
  try {
    const me = await http.get<{ role?: string }>('/auth/me')
    cachedRole = me.role === 'admin' || me.role === 'operator' || me.role === 'viewer' ? me.role : null
  } catch {
    cachedRole = null
  }
  return cachedRole
}

/** 清空角色缓存（测试/登出场景用） */
export function resetRoleCache(): void {
  cachedRole = undefined
}

// ---- 报警级别色（运行态主题）：宿主注入 → editor doc → 内置默认，三级回退 ----

export type LevelColors = Record<AlarmLevel, string>

/** 与演示案例默认值一致（utils/demos/shared.ts）；仅当宿主未注入且 doc 不可达时兜底 */
const DEFAULT_LEVEL_COLORS: LevelColors = { info: '#3b82f6', warn: '#f59e0b', critical: '#ef4444' }

let injectedLevelColors: Partial<LevelColors> | null = null

/** 运行态宿主（RuntimeStage/分享页）启动时注入 doc.settings.alarm.levelColors；传 null 恢复默认 */
export function setAlarmLevelColors(colors: Partial<LevelColors> | null): void {
  injectedLevelColors = colors
}

/** 解析当前生效的级别色（WidgetHost S2 报警态 / AlarmBanner 共用） */
export function resolveLevelColors(docColors?: Partial<LevelColors> | null): LevelColors {
  return {
    info: injectedLevelColors?.info ?? docColors?.info ?? DEFAULT_LEVEL_COLORS.info,
    warn: injectedLevelColors?.warn ?? docColors?.warn ?? DEFAULT_LEVEL_COLORS.warn,
    critical: injectedLevelColors?.critical ?? docColors?.critical ?? DEFAULT_LEVEL_COLORS.critical,
  }
}

// ---- REST ack 成功的页面内联动（DOM 自定义事件，同页多组件同步） ----

const ACK_EVENT = 'webscada:alarm-acked'

/** ack 成功后广播（ackAlarm 成功路径内部自动派发） */
export function emitAlarmAcked(alarmId: number): void {
  window.dispatchEvent(new CustomEvent(ACK_EVENT, { detail: { alarmId } }))
}

/** 订阅 ack 联动；返回取消订阅函数 */
export function onAlarmAcked(handler: (alarmId: number) => void): () => void {
  const fn = (e: Event): void => {
    const detail = (e as CustomEvent<{ alarmId: number }>).detail
    handler(detail?.alarmId ?? -1)
  }
  window.addEventListener(ACK_EVENT, fn)
  return () => window.removeEventListener(ACK_EVENT, fn)
}

// ---- 废弃兼容（M5 旧前端上报通道，契约 §4.1：M8 前端停用） ----
// 以下导出仅为 A 包 RuntimeStage 完成服务端改造前的编译兼容保留；集成阶段随调用点一并删除。

export interface AlarmRecordIn {
  ruleId: string
  variableKey: string
  level: 'info' | 'warn' | 'critical'
  message: string
  value: string | null
  status: 'active' | 'recovered'
}

export interface AlarmRecordOut extends AlarmRecordIn {
  id: number
  triggeredAt: string
  recoveredAt: string | null
}

/** @deprecated M8 起报警由服务端判定入库，前端不再上报（服务端仅为旧版本保留兼容端点） */
export const addAlarmRecord = (projectId: string, data: AlarmRecordIn) =>
  http.post<void>(`/projects/${projectId}/alarm-records`, data)

/** @deprecated 改用 listAlarms（单行状态机契约） */
export const listAlarmRecords = (projectId: string, params?: { page?: number; size?: number }) =>
  http.get<AlarmRecordOut[]>(`/projects/${projectId}/alarm-records`, { params })
