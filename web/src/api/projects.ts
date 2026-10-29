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
  /** 台账置顶：恒排列表最前（工程级属性，跨账号/设备持久化） */
  pinned: boolean
  /** 演示只读：编辑器可体验修改，但不会保存（服务端 PUT 403） */
  readonly: boolean
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

/** 变量实时值快照（与 WS snapshot 同构：{key: {v,q,t}}）；hub 未加载时 values 为空 */
export interface VariableValueEntry {
  v: number | boolean | string | null
  q: 'good' | 'stale' | 'bad'
  t: number | null
}
export const getVariableValues = (id: string) =>
  http.get<{ ts: number; values: Record<string, VariableValueEntry> }>(`/projects/${id}/variables/values`)

export const deleteProject = (id: string) => http.delete<void>(`/projects/${id}`)

/** 台账置顶开关：只改工程级标记，不动 doc/revision（不会触发 409 冲突） */
export const setProjectPinned = (id: string, pinned: boolean) =>
  http.patch<ProjectDetail>(`/projects/${id}/pin`, { pinned })

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
export const importProject = (rawDoc: ProjectDoc, opts: { readonly?: boolean } = {}) => {
  const m = migrateDoc(rawDoc)
  if (!m.ok) {
    ElMessage.error(m.message)
    // 标记「已提示过」：调用方 catch 据此避免重复弹窗（本地失败也走同一约定）
    const err = new Error(m.message) as Error & { handled?: boolean }
    err.handled = true
    return Promise.reject(err)
  }
  return http.post<ProjectDetail>('/projects/import', { doc: m.doc, readonly: opts.readonly === true })
}
