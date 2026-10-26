/** 分享链接接口（M6，03-接口清单 §2.6；M8 终审对齐契约字段：expiresAt 入参、url/revokedAt/refreshedAt 出参）。 */
import type { ProjectDoc } from '@/types/doc'
import { http } from './http'

export interface ShareOut {
  token: string
  url: string
  expiresAt: string | null
  revokedAt: string | null
  createdAt: string
  /** 快照最近刷新时间（与工程 updatedAt 比较判断「有未发布变更」） */
  refreshedAt?: string | null
}

export interface ShareItem extends ShareOut {
  lastAccessAt: string | null
}

export interface ShareRefreshOut {
  token: string
  refreshedAt: string
}

/** 公开出参（03 §2.6：{projectId, createdAt, doc}，工程名取 doc.project.name）。 */
export interface ShareDoc {
  projectId: string
  createdAt: string
  doc: ProjectDoc
}

export interface ShareCreateBody {
  /** ISO8601；缺省/null = 永不过期 */
  expiresAt?: string | null
  /** M6 旧字段兼容（expiresAt 未传时生效） */
  expiresHours?: number
}

export const createShare = (projectId: string, body: ShareCreateBody = {}) =>
  http.post<ShareOut>(`/projects/${projectId}/shares`, body)

export const listShares = (projectId: string) =>
  http.get<{ items: ShareItem[] }>(`/projects/${projectId}/shares`)

export const refreshShare = (token: string) => http.post<ShareRefreshOut>(`/shares/${token}/refresh`)

export const revokeShare = (token: string) => http.delete<void>(`/shares/${token}`)

/** 公开访问（无鉴权）：token → 冻结快照 doc */
export const getShareDoc = (token: string) => http.get<ShareDoc>(`/shares/${token}`)
