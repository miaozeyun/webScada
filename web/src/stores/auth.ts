/** 认证状态：token 持久化于 localStorage（无状态 JWT，注销即丢弃 + jti 黑名单）；
 * 记住我终端另存 7 天 refresh token，access 过期由 http.ts 401 单飞刷新轮换（阶段二 Task 3）。 */
import { defineStore } from 'pinia'
import { loginApi, logoutApi } from '@/api/auth'
import { REFRESH_KEY, TOKEN_KEY } from '@/api/http'

const USERNAME_KEY = 'webscada_username'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    username: localStorage.getItem(USERNAME_KEY) || '',
  }),
  actions: {
    async login(username: string, password: string, rememberMe = false) {
      const data = await loginApi(username, password, rememberMe)
      localStorage.setItem(TOKEN_KEY, data.access_token)
      // 未勾记住我：清掉本终端残留的旧 refresh（换账号/退订「记住我」场景）
      if (data.refresh_token) localStorage.setItem(REFRESH_KEY, data.refresh_token)
      else localStorage.removeItem(REFRESH_KEY)
      localStorage.setItem(USERNAME_KEY, username)
      this.username = username
    },
    async logout() {
      // 服务端 jti 黑名单 + refresh 吊销尽力而为；本地清理始终执行
      const refreshToken = localStorage.getItem(REFRESH_KEY) || undefined
      try {
        await logoutApi(refreshToken)
      } catch {
        /* 拦截器已提示，继续本地清理 */
      }
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(REFRESH_KEY)
      localStorage.removeItem(USERNAME_KEY)
      this.username = ''
    },
  },
})
