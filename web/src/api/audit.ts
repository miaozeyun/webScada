/**
 * 审计日志查询接口（M8 RBAC 配套，实施契约 §4.4 / 03-接口清单 §2.13）。
 * 仅 admin 可用；固定按 createdAt 倒序返回。
 */
import { http } from './http'

export interface AuditLogOut {
  id: number
  /** 用户被删后 SET NULL，username 快照仍可读 */
  userId: string | null
  username: string | null
  action: string
  targetType: string | null
  targetId: string | null
  detail: Record<string, unknown> | null
  ip: string | null
  createdAt: string
}

export interface AuditListResp {
  total: number
  page: number
  size: number
  items: AuditLogOut[]
}

export interface AuditQuery {
  userId?: string
  action?: string
  targetType?: string
  targetId?: string
  /** ISO8601（UTC） */
  from?: string
  to?: string
  page?: number
  size?: number
}

export const listAuditLogs = (params?: AuditQuery) =>
  http.get<AuditListResp>('/audit-logs', { params })
