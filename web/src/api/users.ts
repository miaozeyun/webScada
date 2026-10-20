/**
 * 用户管理接口（M8 RBAC，实施契约 §4.3 / 03-接口清单 §2.12）。
 * 全部端点仅 admin 可用；错误信封（409 用户名重复 / 409 最后一个 admin 保护 /
 * 422 self_delete）由 http 拦截器统一弹出服务端 message。
 */
import { http } from './http'

export type UserRole = 'admin' | 'operator' | 'viewer'

export interface UserOut {
  id: string
  username: string
  role: UserRole
  createdAt: string
}

export interface UserListResp {
  total: number
  page: number
  size: number
  items: UserOut[]
}

export interface UserCreateBody {
  username: string
  /** ≥8 位，服务端校验 */
  password: string
  role: UserRole
}

export const listUsers = (params?: { keyword?: string; page?: number; size?: number }) =>
  http.get<UserListResp>('/users', { params })

export const createUser = (data: UserCreateBody) => http.post<UserOut>('/users', data)

/** PUT /users/{id} 仅接受 role（契约冻结）；最后一个 admin 降级 → 409 */
export const updateUserRole = (id: string, role: UserRole) =>
  http.put<UserOut>(`/users/${id}`, { role })

/** admin 重置密码通道：无需旧密码，→ 204 */
export const resetUserPassword = (id: string, newPassword: string) =>
  http.put<void>(`/users/${id}/password`, { newPassword })

/** → 204；删自己 → 422 self_delete，最后一个 admin → 409 */
export const deleteUser = (id: string) => http.delete<void>(`/users/${id}`)
