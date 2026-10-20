/** 认证接口（03-接口清单 §2.2）。 */
import { http } from './http'

export interface LoginResp {
  access_token: string
  token_type: string
  expires_in: number
}

export interface UserInfo {
  id: string
  username: string
  createdAt: string
}

export const loginApi = (username: string, password: string) =>
  http.post<LoginResp>('/auth/login', { username, password })

export const logoutApi = () => http.post<void>('/auth/logout')

export const meApi = () => http.get<UserInfo>('/auth/me')

export const changePasswordApi = (oldPassword: string, newPassword: string) =>
  http.put<void>('/auth/password', { oldPassword, newPassword })
