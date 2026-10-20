import { createRouter, createWebHistory } from 'vue-router'
import type { UserInfo } from '@/api/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue') },
    { path: '/', redirect: '/projects' },
    { path: '/projects', name: 'projects', component: () => import('@/views/ProjectsView.vue'), meta: { requiresAuth: true } },
    { path: '/editor/:id', name: 'editor', component: () => import('@/editor/EditorView.vue'), meta: { requiresAuth: true } },
    // 系统管理（M8 RBAC）：仅 admin，E 包管理页
    { path: '/admin/users', name: 'admin-users', component: () => import('@/views/admin/UsersView.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
    { path: '/admin/audit', name: 'admin-audit', component: () => import('@/views/admin/AuditView.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
    // 分享页（M6）：匿名只读运行态
    { path: '/s/:token', name: 'share', component: () => import('@/views/ShareView.vue') },
    // 运行态分享页路由 /s/:token（M6）——按阶段加入
    { path: '/:pathMatch(.*)*', redirect: '/projects' },
  ],
})

// ---- 管理页角色守卫（M8 E 包）----
// auth store 仅持久化 username（共享文件不改动），角色经 /auth/me 惰性拉取并模块级缓存；
// 进入 /login 即清缓存，避免换账号后沿用旧角色。
// 动态 import 拉 API 模块：http.ts 顶层 import 了本 router，静态引入会构成循环依赖。
let cachedRole: string | undefined // undefined = 未拉取 / 已失效
let meInflight: Promise<string | undefined> | null = null

/** 惰性拉取当前账号角色（/admin 守卫用；导出供测试驱动） */
export function fetchMyRole(): Promise<string | undefined> {
  if (cachedRole !== undefined) return Promise.resolve(cachedRole)
  if (!meInflight) {
    // 局部引用：完成/作废判定依据（防止误清并发的新请求，也防被作废旧请求写脏缓存）
    const req = import('@/api/auth')
      .then(({ meApi }) => meApi())
      .then((me) => {
        // auth.ts 的 UserInfo 暂无 role 字段（共享文件不改动），按 §4.3 契约窄化；
        // 请求期间已被作废（/login 换账号）→ 结果丢弃不落缓存，避免旧 token 角色污染新会话
        const role = (me as UserInfo & { role?: string }).role
        if (meInflight === req) cachedRole = role
        return role
      })
      .catch(() => undefined) // 失败允许重试；401 已由 http 拦截器接管跳登录
      .finally(() => {
        // 成功/失败均复位 inflight；否则换账号后复用上一账号的已决 promise，viewer 可误过守卫
        if (meInflight === req) meInflight = null
      })
    meInflight = req
    return req
  }
  return meInflight
}

/** 登出/换账号：角色缓存与在途 /auth/me 一并作废（/login 守卫调用；测试可直接调） */
export function invalidateRoleSession(): void {
  cachedRole = undefined
  meInflight = null
}

// 路由守卫：本地无 token 即跳登录（P0 单团队无权限路由，G 决策 D6 已拍板）；M8 起管理页叠加 admin 校验
router.beforeEach(async (to) => {
  const token = localStorage.getItem('webscada_token')
  if (to.meta.requiresAuth && !token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.path === '/login') {
    invalidateRoleSession() // 换账号登录：旧角色缓存与在途 /auth/me 一并作废
    if (token) return '/projects'
    return true
  }
  // 管理页：非 admin（含角色拉取失败）一律重定向回工程台账
  if (to.meta.requiresAdmin) {
    const role = await fetchMyRole()
    if (role !== 'admin') return '/projects'
  }
  return true
})

export default router
