<script setup lang="ts">
/**
 * 用户管理页（M8 工作包 E，实施契约 §4.3 消费端）。
 * CRUD + 表单校验（密码 ≥8 / 角色枚举）；409（重名 / 最后一个 admin 保护）与
 * 422（self_delete）由 http 拦截器弹出服务端 message，页面不重复提示。
 */
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import ThemePicker from '@/components/ThemePicker.vue'
import {
  createUser,
  deleteUser,
  listUsers,
  resetUserPassword,
  updateUserRole,
  type UserOut,
  type UserRole,
} from '@/api/users'

const router = useRouter()
const auth = useAuthStore()

type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

// ---- 角色元数据（未知角色按原值灰显兜底，兼容服务端后续扩展） ----
const ROLE_META: Record<UserRole, { label: string; tag: TagType }> = {
  admin: { label: '管理员', tag: 'primary' },
  operator: { label: '操作员', tag: 'warning' },
  viewer: { label: '只读用户', tag: 'info' },
}

function roleMeta(role: string): { label: string; tag: TagType } {
  return (ROLE_META as Record<string, { label: string; tag: TagType }>)[role] ?? { label: role, tag: 'info' }
}

const roleOptions = (Object.keys(ROLE_META) as UserRole[]).map((value) => ({
  value,
  label: ROLE_META[value].label,
}))

// ---- 列表 ----
const loading = ref(false)
const items = ref<UserOut[]>([])
const total = ref(0)
const query = reactive({ keyword: '', page: 1, size: 20 })

async function refresh(resetPage = false): Promise<void> {
  if (resetPage) query.page = 1 // 搜索换关键字后回到第一页（与工程台账同策略）
  loading.value = true
  try {
    const data = await listUsers({ keyword: query.keyword || undefined, page: query.page, size: query.size })
    items.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

onMounted(refresh)

// 分页变化重查：el-pagination 的 current-change/size-change 事件参数是页码/页大小数值，
// 直接绑到 refresh(resetPage) 会被误判为「回第一页」导致翻页失效 → 统一经 watch 驱动
watch([() => query.page, () => query.size], () => void refresh())

// ---- 窄屏：隐藏创建时间列，分页简化（与工程台账一致） ----
const isNarrow = ref(false)
const NARROW_QUERY = '(max-width: 760px)'
let mq: MediaQueryList | null = null

function syncNarrow(e?: MediaQueryListEvent): void {
  isNarrow.value = e ? e.matches : (mq?.matches ?? false)
}

onMounted(() => {
  mq = window.matchMedia(NARROW_QUERY)
  syncNarrow()
  mq.addEventListener('change', syncNarrow)
})

onBeforeUnmount(() => mq?.removeEventListener('change', syncNarrow))

// ---- 新建用户 ----
const createVisible = ref(false)
const creating = ref(false)
const createFormRef = ref<FormInstance>()
const createForm = reactive<{ username: string; password: string; role: UserRole }>({
  username: '',
  password: '',
  role: 'viewer',
})

const createRules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { max: 64, message: '用户名最长 64 个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, message: '密码至少 8 位', trigger: 'blur' },
  ],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
}

function openCreate(): void {
  createForm.username = ''
  createForm.password = ''
  createForm.role = 'viewer'
  createVisible.value = true
}

async function doCreate(): Promise<void> {
  await createFormRef.value?.validate()
  creating.value = true
  try {
    await createUser({ username: createForm.username.trim(), password: createForm.password, role: createForm.role })
    ElMessage.success('用户已创建')
    createVisible.value = false
    refresh()
  } catch {
    /* 409 用户名重复等由拦截器提示，弹窗保留便于改用户名重试 */
  } finally {
    creating.value = false
  }
}

// ---- 修改角色（服务端保护最后一个 admin 降级 → 409） ----
const roleVisible = ref(false)
const savingRole = ref(false)
const roleFormRef = ref<FormInstance>()
const roleForm = reactive<{ id: string; username: string; role: UserRole }>({
  id: '',
  username: '',
  role: 'viewer',
})

const roleRules: FormRules = {
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
}

function openRole(row: UserOut): void {
  roleForm.id = row.id
  roleForm.username = row.username
  roleForm.role = row.role
  roleVisible.value = true
}

async function doSaveRole(): Promise<void> {
  await roleFormRef.value?.validate()
  savingRole.value = true
  try {
    await updateUserRole(roleForm.id, roleForm.role)
    ElMessage.success('角色已更新')
    roleVisible.value = false
    refresh()
  } catch {
    /* 409 最后一个 admin 降级由拦截器提示 */
  } finally {
    savingRole.value = false
  }
}

// ---- 重置密码（admin 通道，无需旧密码 → 204） ----
const pwdVisible = ref(false)
const savingPwd = ref(false)
const pwdFormRef = ref<FormInstance>()
const pwdForm = reactive({ id: '', username: '', newPassword: '' })

const pwdRules: FormRules = {
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, message: '密码至少 8 位', trigger: 'blur' },
  ],
}

function openPwd(row: UserOut): void {
  pwdForm.id = row.id
  pwdForm.username = row.username
  pwdForm.newPassword = ''
  pwdVisible.value = true
}

async function doResetPwd(): Promise<void> {
  await pwdFormRef.value?.validate()
  savingPwd.value = true
  try {
    await resetUserPassword(pwdForm.id, pwdForm.newPassword)
    ElMessage.success('密码已重置')
    pwdVisible.value = false
  } catch {
    /* 校验失败由拦截器提示 */
  } finally {
    savingPwd.value = false
  }
}

// ---- 删除（不能删自己：前端禁用 + 服务端 422 self_delete 兜底；最后一个 admin 409） ----
async function doDelete(row: UserOut): Promise<void> {
  const hint = row.role === 'admin' ? '若这是最后一个管理员，操作将被服务端拒绝。' : '该操作不可恢复。'
  try {
    await ElMessageBox.confirm(`确定删除用户「${row.username}」？${hint}`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteUser(row.id)
    ElMessage.success('已删除')
    refresh()
  } catch {
    /* 409 / 422 由拦截器提示 */
  }
}

async function onLogout(): Promise<void> {
  await auth.logout()
  router.push('/login')
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <div class="admin-page">
    <header class="app-bar">
      <div class="bar-brand">
        <svg class="bar-mark" viewBox="0 0 32 32" aria-hidden="true">
          <rect x="0.75" y="0.75" width="30.5" height="30.5" />
          <path d="M5 21 H11 L14 12 L18 24 L21 16 H27" />
        </svg>
        <span class="bar-name">webScada</span>
        <span class="bar-divider" aria-hidden="true"></span>
        <span class="bar-scope">系统管理 · 用户管理</span>
      </div>
      <div class="bar-user">
        <nav class="bar-nav">
          <button class="bar-link is-active" type="button">用户管理</button>
          <button class="bar-link" type="button" @click="router.push('/admin/audit')">审计日志</button>
          <button class="bar-link" type="button" @click="router.push('/projects')">返回台账</button>
        </nav>
        <ThemePicker />
        <span class="user-name">{{ auth.username }}</span>
        <button class="bar-action" type="button" @click="onLogout">退出登录</button>
      </div>
    </header>

    <main class="workspace">
      <div class="page-head">
        <div>
          <h1>用户管理</h1>
          <p class="page-desc">
            管理平台账号与角色：admin 拥有全部权限，operator 可编辑工程与确认报警，viewer 只读。
          </p>
        </div>
        <div class="ledger-count" aria-label="用户总数">
          <span class="count-value ws-readout">{{ total }}</span>
          <span class="count-label">个账号</span>
        </div>
      </div>

      <div class="action-bar">
        <div class="search">
          <el-input
            v-model="query.keyword"
            placeholder="按用户名搜索"
            clearable
            :prefix-icon="Search"
            @keyup.enter="refresh(true)"
            @clear="refresh(true)"
          />
          <el-button @click="refresh(true)">搜索</el-button>
        </div>
        <span class="spacer" />
        <el-button type="primary" :icon="Plus" @click="openCreate">新建用户</el-button>
      </div>

      <section class="ledger">
        <el-table v-loading="loading" :data="items" stripe>
          <el-table-column prop="username" label="用户名" :min-width="isNarrow ? 130 : 180">
            <template #default="{ row }">
              <span class="cell-name" :title="row.username">{{ row.username }}</span>
            </template>
          </el-table-column>
          <el-table-column label="角色" width="120">
            <template #default="{ row }">
              <el-tag size="small" :type="roleMeta(row.role).tag">{{ roleMeta(row.role).label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column v-if="!isNarrow" label="创建时间" width="180">
            <template #default="{ row }">
              <span class="time ws-readout">{{ fmtTime(row.createdAt) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" :width="isNarrow ? 210 : 230" align="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openRole(row)">改角色</el-button>
              <el-button link size="small" @click="openPwd(row)">重置密码</el-button>
              <el-tooltip
                v-if="row.username === auth.username"
                content="不能删除当前登录账号"
                placement="top"
              >
                <span class="op-forbidden">删除</span>
              </el-tooltip>
              <el-button v-else link type="danger" size="small" @click="doDelete(row)">删除</el-button>
            </template>
          </el-table-column>

          <template #empty>
            <div class="empty">
              <p class="empty-title">暂无匹配的用户</p>
              <p class="empty-desc">调整搜索关键字，或新建一个账号。</p>
            </div>
          </template>
        </el-table>

        <div class="ledger-foot">
          <el-pagination
            v-model:current-page="query.page"
            v-model:page-size="query.size"
            :total="total"
            :page-sizes="[10, 20, 50]"
            :layout="isNarrow ? 'prev, pager, next' : 'total, sizes, prev, pager, next'"
          />
        </div>
      </section>
    </main>

    <!-- 新建用户 -->
    <el-dialog v-model="createVisible" title="新建用户" width="420px">
      <el-form ref="createFormRef" label-position="top" :rules="createRules" :model="createForm" @submit.prevent>
        <el-form-item label="用户名" prop="username">
          <el-input v-model="createForm.username" maxlength="64" placeholder="登录账号，最长 64 字符" />
        </el-form-item>
        <el-form-item label="初始密码" prop="password">
          <el-input
            v-model="createForm.password"
            type="password"
            show-password
            placeholder="至少 8 位"
          />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-select v-model="createForm.role" placeholder="选择角色">
            <el-option v-for="opt in roleOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="doCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 修改角色 -->
    <el-dialog v-model="roleVisible" :title="`修改角色：${roleForm.username}`" width="380px">
      <el-form ref="roleFormRef" label-position="top" :rules="roleRules" :model="roleForm" @submit.prevent>
        <el-form-item label="角色" prop="role">
          <el-select v-model="roleForm.role" placeholder="选择角色">
            <el-option v-for="opt in roleOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
          <p class="field-hint">若这是最后一个管理员，降级将被服务端拒绝（409）。</p>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="roleVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingRole" @click="doSaveRole">保存</el-button>
      </template>
    </el-dialog>

    <!-- 重置密码 -->
    <el-dialog v-model="pwdVisible" :title="`重置密码：${pwdForm.username}`" width="380px">
      <el-form ref="pwdFormRef" label-position="top" :rules="pwdRules" :model="pwdForm" @submit.prevent>
        <el-form-item label="新密码" prop="newPassword">
          <el-input v-model="pwdForm.newPassword" type="password" show-password placeholder="至少 8 位" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingPwd" @click="doResetPwd">重置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.admin-page {
  min-height: 100vh;
  background: var(--ws-canvas);
  display: flex;
  flex-direction: column;
}

/* ---- 控制台顶栏（与工程台账同构） ---- */
.app-bar {
  height: 48px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: var(--ws-ink);
  color: var(--ws-text-inverse);
}

.bar-brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.bar-mark {
  width: 22px;
  height: 22px;
  fill: none;
  stroke: var(--ws-signal-bright);
  stroke-width: 1.6;
  stroke-linejoin: round;
  stroke-linecap: round;
}

.bar-name {
  font-family: var(--ws-font-tech);
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.1em;
}

.bar-divider {
  width: 1px;
  height: 16px;
  background: rgba(238, 244, 247, 0.22);
}

.bar-scope {
  font-size: 13px;
  color: rgba(238, 244, 247, 0.7);
}

.bar-user {
  display: flex;
  align-items: center;
  gap: 16px;
}

.bar-nav {
  display: flex;
  align-items: center;
  gap: 4px;
}

.bar-link {
  padding: 4px 10px;
  border: none;
  border-radius: var(--ws-radius);
  background: transparent;
  color: rgba(238, 244, 247, 0.72);
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
}

.bar-link:hover {
  background: rgba(27, 167, 184, 0.12);
  color: #fff;
}

.bar-link.is-active {
  background: rgba(27, 167, 184, 0.2);
  color: #fff;
}

.user-name {
  font-family: var(--ws-font-tech);
  font-size: 12px;
  letter-spacing: 0.03em;
  color: rgba(238, 244, 247, 0.72);
}

.bar-action {
  padding: 4px 10px;
  border: 1px solid rgba(238, 244, 247, 0.22);
  border-radius: var(--ws-radius);
  background: transparent;
  color: rgba(238, 244, 247, 0.82);
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
}

.bar-action:hover {
  border-color: var(--ws-signal-bright);
  background: rgba(27, 167, 184, 0.12);
  color: #fff;
}

/* ---- 工作区 ---- */
.workspace {
  width: 100%;
  max-width: 1280px;
  margin: 0 auto;
  padding: 30px 32px 44px;
}

.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
}

.page-head h1 {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  letter-spacing: 0.01em;
  color: var(--ws-text);
}

.page-desc {
  margin: 7px 0 0;
  font-size: 13px;
  color: var(--ws-text-3);
  max-width: 640px;
}

.ledger-count {
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex-shrink: 0;
}

.count-value {
  font-size: 28px;
  font-weight: 600;
  color: var(--ws-text);
}

.count-label {
  font-size: 12px;
  color: var(--ws-text-3);
}

.action-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 22px 0 14px;
}

.search {
  display: flex;
  align-items: center;
  gap: 8px;
}

.search :deep(.el-input) {
  width: 260px;
}

.spacer {
  flex: 1;
}

/* ---- 台账面板 ---- */
.ledger {
  background: var(--ws-panel);
  border: 1px solid var(--ws-steel-3);
  box-shadow: var(--ws-shadow-panel);
}

.ledger :deep(.el-table) {
  --el-table-border-color: var(--ws-steel-2);
}

.ledger :deep(.el-table::before) {
  display: none;
}

.cell-name {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
  color: var(--ws-text);
}

.time {
  color: var(--ws-text-3);
  font-size: 12px;
}

.op-forbidden {
  margin: 0 12px;
  font-size: 12px;
  color: var(--ws-text-3);
  opacity: 0.65;
  cursor: not-allowed;
}

.ledger-foot {
  display: flex;
  justify-content: flex-end;
  padding: 10px 14px;
  border-top: 1px solid var(--ws-steel-2);
}

/* ---- 空态 ---- */
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 36px 0 30px;
}

.empty-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--ws-text-2);
}

.empty-desc {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--ws-text-3);
}

/* ---- 对话框表单 ---- */
.field-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--ws-text-3);
}

/* ---- 窄屏 ---- */
@media (max-width: 860px) {
  .workspace {
    padding: 20px 16px 32px;
  }

  .ledger-count {
    display: none;
  }

  .action-bar {
    flex-wrap: wrap;
  }

  .search {
    width: 100%;
  }

  .search :deep(.el-input) {
    flex: 1;
    width: auto;
  }

  .spacer {
    display: none;
  }
}

@media (max-width: 480px) {
  .app-bar {
    padding: 0 14px;
  }

  .bar-brand {
    gap: 8px;
  }

  .bar-scope,
  .bar-nav,
  .user-name {
    display: none;
  }
}
</style>
