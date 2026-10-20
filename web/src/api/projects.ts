/** 工程管理接口（03-接口清单 §2.3/§2.4）。 */
import type { ProjectDoc } from '@/types/doc'
import { http } from './http'

export interface ProjectListItem {
  id: string
  name: string
  description: string | null
  revision: number
  updatedAt: string
}

export interface ProjectListOut {
  total: number
  page: number
  size: number
  items: ProjectListItem[]
}

export interface ProjectDetail extends ProjectListItem {
  createdAt: string
  /** 所有出口脱敏后的 doc（G6） */
  doc: ProjectDoc | null
}

export const listProjects = (params: { keyword?: string; page: number; size: number }) =>
  http.get<ProjectListOut>('/projects', { params })

export const createProject = (data: { name: string; description?: string }) =>
  http.post<ProjectDetail>('/projects', data)

export const getProject = (id: string) => http.get<ProjectDetail>(`/projects/${id}`)

export const deleteProject = (id: string) => http.delete<void>(`/projects/${id}`)

/** 整体保存：全量 doc + baseRevision 乐观锁（G2，冲突 409） */
export const updateProject = (id: string, doc: ProjectDoc, baseRevision: number) =>
  http.put<{ revision: number; updatedAt: string }>(`/projects/${id}`, { doc, baseRevision })

/** 导出：JSON body（凭证已脱敏），前端 Blob 触发下载（G7） */
export const exportProject = (id: string) => http.get<ProjectDoc>(`/projects/${id}/export`)

/** 导入：JSON body 形态（前端 FileReader 读文件后提交） */
export const importProject = (doc: ProjectDoc) => http.post<ProjectDetail>('/projects/import', { doc })
