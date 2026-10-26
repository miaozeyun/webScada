/** 工程管理接口（03-接口清单 §2.3/§2.4）。 */
import { ElMessage } from 'element-plus'
import type { ProjectDoc } from '@/types/doc'
import { migrateDoc } from '@/utils/migrateDoc'
import { http } from './http'

export interface ProjectListItem {
  id: string
  name: string
  description: string | null
  revision: number
  updatedAt: string
  /** 首页缩略图（JPEG dataURL，卡片视图用；编辑器保存前截图写入） */
  thumbnail: string | null
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

/** 模板克隆：新工程 id/名称，画面/绑定/报警/数据源原样复制（OEM 一模板 N 台设备） */
export const cloneProject = (id: string, name: string) =>
  http.post<ProjectDetail>(`/projects/${id}/clone`, { name })

export const getProject = (id: string) => http.get<ProjectDetail>(`/projects/${id}`)

export const deleteProject = (id: string) => http.delete<void>(`/projects/${id}`)

/** 整体保存：全量 doc + baseRevision 乐观锁（G2，冲突 409） */
export const updateProject = (id: string, doc: ProjectDoc, baseRevision: number) =>
  http.put<{ revision: number; updatedAt: string }>(`/projects/${id}`, { doc, baseRevision })

/** 导出：JSON body（凭证已脱敏），前端 Blob 触发下载（G7） */
export const exportProject = (id: string) => http.get<ProjectDoc>(`/projects/${id}/export`)

/**
 * 导入：JSON body 形态（前端 FileReader 读文件后提交）。
 * 提交前统一跑 migrateDoc（M8 契约 §7.1，G8 迁移唯一实现点在前端）：
 * 旧版本文件逐版升级后再提交；too_new/invalid 在本地直接拒绝、不发请求
 * （服务端无迁移逻辑，N-1 窗口仅灰度缓冲）。失败经 ElMessage 弹出原因
 * （调用方 catch 块按「拦截器已提示」处理，不再重复弹窗）。
 */
export const importProject = (rawDoc: ProjectDoc) => {
  const m = migrateDoc(rawDoc)
  if (!m.ok) {
    ElMessage.error(m.message)
    return Promise.reject(new Error(m.message))
  }
  return http.post<ProjectDetail>('/projects/import', { doc: m.doc })
}
