import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue') },
    { path: '/', redirect: '/projects' },
    { path: '/projects', name: 'projects', component: () => import('@/views/ProjectsView.vue'), meta: { requiresAuth: true } },
    { path: '/editor/:id', name: 'editor', component: () => import('@/editor/EditorView.vue'), meta: { requiresAuth: true } },
    // 分享页（M6）：匿名只读运行态
    { path: '/s/:token', name: 'share', component: () => import('@/views/ShareView.vue') },
    // 运行态分享页路由 /s/:token（M6）——按阶段加入
    { path: '/:pathMatch(.*)*', redirect: '/projects' },
  ],
})

// 路由守卫：本地无 token 即跳登录（P0 单团队无权限路由，G 决策 D6 已拍板）
router.beforeEach((to) => {
  const token = localStorage.getItem('webscada_token')
  if (to.meta.requiresAuth && !token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.path === '/login' && token) {
    return '/projects'
  }
  return true
})

export default router
