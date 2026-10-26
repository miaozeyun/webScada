/**
 * axios 实例：JWT 注入 + 统一错误信封处理（03-接口清单 §1.2/§1.3）。
 * 响应拦截器直接解包 data，故下方泛型包装即真实返回类型。
 * 401 单飞刷新（阶段二 Task 3）：并发 401 共享同一次 /auth/refresh，成功后各重放原请求
 * 一次；失败清双凭证跳登录。/auth/login 的 401 是凭证错误而非会话过期，不参与刷新。
 */
import axios from 'axios'
import type { AxiosError, AxiosRequestConfig, InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'
import type { RefreshResp } from './auth'

export const TOKEN_KEY = 'webscada_token'
export const REFRESH_KEY = 'webscada_refresh'

const instance = axios.create({ baseURL: '/api/v1', timeout: 15000 })

// 刷新端点专用裸实例：不挂本文件拦截器，天然不会出现「401 → 刷新 → 401」循环
const bare = axios.create({ baseURL: '/api/v1', timeout: 15000 })

// 请求拦截：附加 JWT
instance.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

/** 带"已重放"标记的请求配置：重放后的 401 不再刷新（每请求最多重放一次，防刷新风暴） */
interface RetriableConfig extends InternalAxiosRequestConfig {
  _retried?: boolean
  silent?: boolean
}

/** 业务请求配置：silent=true 时失败不弹全局提示（轮询类请求避免断网时每轮刷一条 toast） */
export interface RequestOptions extends AxiosRequestConfig {
  silent?: boolean
}

let refreshInflight: Promise<boolean> | null = null

/** 单飞刷新：全应用同时最多一次 /auth/refresh 在途，并发 401 等同一 promise。 */
function refreshSession(): Promise<boolean> {
  if (!refreshInflight) {
    refreshInflight = (async () => {
      const refreshToken = localStorage.getItem(REFRESH_KEY)
      if (!refreshToken) return false
      try {
        const resp = await bare.post<RefreshResp>('/auth/refresh', { refreshToken })
        localStorage.setItem(TOKEN_KEY, resp.data.access_token)
        localStorage.setItem(REFRESH_KEY, resp.data.refresh_token)
        return true
      } catch {
        return false
      } finally {
        refreshInflight = null
      }
    })()
  }
  return refreshInflight
}

/** 会话彻底失效：清双凭证并跳登录（登录页自身不重复跳转） */
function forceLogout(message?: string): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(REFRESH_KEY)
  if (router.currentRoute.value.path !== '/login') {
    router.push({ path: '/login', query: { redirect: router.currentRoute.value.fullPath } })
  }
  ElMessage.error(message || '登录已失效，请重新登录')
}

// 响应拦截：统一错误信封 {code, message, ...}
instance.interceptors.response.use(
  (res) => res.data,
  async (err: AxiosError) => {
    const resp = err.response
    const config = err.config as RetriableConfig | undefined
    const silent = config?.silent === true
    if (resp) {
      const { code, message, errors } = (resp.data || {}) as {
        code?: string
        message?: string
        errors?: { path?: string; message?: string }[]
      }
      // 422 信封带 errors[].path：把第一条具体路径拼进提示，避免「保存失败」而无从下手
      const detail = Array.isArray(errors) && errors.length
        ? `${message || '请求失败'}：${errors.slice(0, 2).map((e) => `${e.path ?? '?'} ${e.message ?? ''}`.trim()).join('；')}${errors.length > 2 ? ` 等 ${errors.length} 项` : ''}`
        : message
      if (resp.status === 401) {
        // 有 refresh 且未重放过 → 单飞刷新成功则重放原请求一次（新 token 由请求拦截器注入）
        if (config && !config._retried && config.url !== '/auth/login' && localStorage.getItem(REFRESH_KEY)) {
          if (await refreshSession()) {
            config._retried = true
            return instance.request(config)
          }
        }
        // 无 refresh / 刷新失败 / 重放后仍 401：会话终结
        forceLogout(message)
      } else if (!silent) {
        if (code === 'REVISION_CONFLICT') {
          // 409 冲突转用户提示（G2/K2）
          ElMessage.error(message || '工程已被他人修改，请刷新后重试')
        } else {
          ElMessage.error(detail || message || `请求失败（${resp.status}）`)
        }
      }
    } else if (!silent) {
      ElMessage.error('网络错误，请检查连接')
    }
    return Promise.reject(err)
  },
)

// 泛型包装（拦截器已解包 data）
export const http = {
  get: <T>(url: string, config?: RequestOptions) =>
    instance.get(url, config) as unknown as Promise<T>,
  post: <T>(url: string, data?: unknown, config?: RequestOptions) =>
    instance.post(url, data, config) as unknown as Promise<T>,
  put: <T>(url: string, data?: unknown, config?: RequestOptions) =>
    instance.put(url, data, config) as unknown as Promise<T>,
  delete: <T>(url: string, config?: RequestOptions) =>
    instance.delete(url, config) as unknown as Promise<T>,
}
