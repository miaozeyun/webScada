/** 认证接口（03-接口清单 §2.2）。 */
import { http } from './http'

export interface LoginResp {
  access_token: string
  token_type: string
  expires_in: number
  /** rememberMe=true 才签发；明文仅此一次返回 */
  refresh_token?: string | null
}

/** /auth/refresh 轮换响应。调用方是 http.ts 的单飞刷新（裸实例直发，不经拦截器） */
export interface RefreshResp {
  access_token: string
  token_type: string
  expires_in: number
  refresh_token: string
}

export interface UserInfo {
  id: string
  username: string
  createdAt: string
}

export const loginApi = (username: string, password: string, rememberMe = false) =>
  http.post<LoginResp>('/auth/login', { username, password, rememberMe })

/** 登出：带 refreshToken 时服务端一并吊销（记住我终端登出后 refresh 立即失效） */
export const logoutApi = (refreshToken?: string) =>
  http.post<void>('/auth/logout', refreshToken ? { refreshToken } : undefined)

export const meApi = () => http.get<UserInfo>('/auth/me')

export const changePasswordApi = (oldPassword: string, newPassword: string) =>
  http.put<void>('/auth/password', { oldPassword, newPassword })
