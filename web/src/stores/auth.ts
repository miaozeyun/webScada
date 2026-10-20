/** 认证状态：token 持久化于 localStorage（无状态 JWT，注销即丢弃 + jti 黑名单）。 */
import { defineStore } from 'pinia'
import { loginApi, logoutApi } from '@/api/auth'

const TOKEN_KEY = 'webscada_token'
const USERNAME_KEY = 'webscada_username'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    username: localStorage.getItem(USERNAME_KEY) || '',
  }),
  actions: {
    async login(username: string, password: string) {
      const data = await loginApi(username, password)
      localStorage.setItem(TOKEN_KEY, data.access_token)
      localStorage.setItem(USERNAME_KEY, username)
      this.username = username
    },
    async logout() {
      // 服务端 jti 黑名单尽力而为；本地清理始终执行
      try {
        await logoutApi()
      } catch {
        /* 拦截器已提示，继续本地清理 */
      }
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USERNAME_KEY)
      this.username = ''
    },
  },
})
