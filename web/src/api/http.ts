/**
 * axios 实例：JWT 注入 + 统一错误信封处理（03-接口清单 §1.2/§1.3）。
 * 响应拦截器直接解包 data，故下方泛型包装即真实返回类型。
 */
import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'

const TOKEN_KEY = 'webscada_token'

const instance = axios.create({ baseURL: '/api/v1', timeout: 15000 })

// 请求拦截：附加 JWT
instance.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 响应拦截：统一错误信封 {code, message, ...}
instance.interceptors.response.use(
  (res) => res.data,
  (err) => {
    const resp = err.response
    if (resp) {
      const { code, message } = resp.data || {}
      if (resp.status === 401) {
        localStorage.removeItem(TOKEN_KEY)
        if (router.currentRoute.value.path !== '/login') {
          router.push({ path: '/login', query: { redirect: router.currentRoute.value.fullPath } })
        }
        ElMessage.error(message || '登录已失效，请重新登录')
      } else if (code === 'REVISION_CONFLICT') {
        // 409 冲突转用户提示（G2/K2）
        ElMessage.error(message || '工程已被他人修改，请刷新后重试')
      } else {
        ElMessage.error(message || `请求失败（${resp.status}）`)
      }
    } else {
      ElMessage.error('网络错误，请检查连接')
    }
    return Promise.reject(err)
  },
)

// 泛型包装（拦截器已解包 data）
export const http = {
  get: <T>(url: string, config?: Parameters<typeof instance.get>[1]) =>
    instance.get(url, config) as unknown as Promise<T>,
  post: <T>(url: string, data?: unknown, config?: Parameters<typeof instance.post>[2]) =>
    instance.post(url, data, config) as unknown as Promise<T>,
  put: <T>(url: string, data?: unknown, config?: Parameters<typeof instance.put>[2]) =>
    instance.put(url, data, config) as unknown as Promise<T>,
  delete: <T>(url: string, config?: Parameters<typeof instance.delete>[1]) =>
    instance.delete(url, config) as unknown as Promise<T>,
}
