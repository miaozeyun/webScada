/** 分享链接接口（M6，03-接口清单 §2.6）。 */
import type { ProjectDoc } from '@/types/doc'
import { http } from './http'

export interface ShareOut {
  token: string
  expiresAt: string | null
  createdAt: string
}

export interface ShareDoc {
  projectName: string
  doc: ProjectDoc
}

export const createShare = (projectId: string, expiresHours?: number) =>
  http.post<ShareOut>(`/projects/${projectId}/shares`, { expiresHours })

export const revokeShare = (token: string) => http.delete<void>(`/shares/${token}`)

/** 公开访问（无鉴权）：token → 冻结快照 doc */
export const getShareDoc = (token: string) => http.get<ShareDoc>(`/shares/${token}`)
