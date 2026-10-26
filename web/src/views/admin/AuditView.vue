<script setup lang="ts">
/**
 * 审计日志页（M8 工作包 E，实施契约 §4.4 消费端）。
 * 过滤（操作类型 / 用户 / 目标 / 时间范围）+ 分页 + detail JSON 展开；
 * 服务端固定按 createdAt 倒序；未知 action 按原值灰显兜底。
 */
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh, Search } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import ThemePicker from '@/components/ThemePicker.vue'
import { listAuditLogs, type AuditLogOut } from '@/api/audit'
import { listUsers } from '@/api/users'

const router = useRouter()
const auth = useAuthStore()

type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

// ---- action 元数据（契约 §6.3；未知值原值展示兜底） ----
const ACTION_META: Record<string, { label: string; tag: TagType }> = {
  login: { label: '登录', tag: 'info' },
  write_var: { label: '变量写入', tag: 'warning' },
  alarm_ack: { label: '报警确认', tag: 'danger' },
  alarm_clear: { label: '报警清除', tag: 'danger' },
  project_save: { label: '工程保存', tag: 'primary' },
  share_create: { label: '分享创建', tag: 'success' },
  share_revoke: { label: '分享撤销', tag: 'warning' },
  user_mgmt: { label: '用户管理', tag: 'primary' },
  datasource_test: { label: '数据源测试', tag: 'info' },
}

const actionOptions = Object.entries(ACTION_META).map(([value, meta]) => ({ value, label: meta.label }))

function actionMeta(action: string): { label: string; tag: TagType } {
  return ACTION_META[action] ?? { label: action, tag: 'info' }
}

// models.py AuditLog.target_type 注释口径：project/share/user/alarm/variable（可输入扩展值）
const TARGET_TYPES = ['project', 'share', 'user', 'alarm', 'variable']

// ---- 过滤条件与分页 ----
const filters = reactive({ userId: '', action: '', targetType: '', targetId: '' })
const range = ref<[Date, Date] | null>(null)
const query = reactive({ page: 1, size: 20 })

const loading = ref(false)
const items = ref<AuditLogOut[]>([])
const total = ref(0)

async function refresh(resetPage = false): Promise<void> {
  if (resetPage) query.page = 1
  loading.value = true
  try {
    const r = range.value
    const data = await listAuditLogs({
      userId: filters.userId || undefined,
      action: filters.action || undefined,
      targetType: filters.targetType || undefined,
      targetId: filters.targetId || undefined,
      from: r ? r[0].toISOString() : undefined, // ISO8601 UTC（契约 §4.4）
      to: r ? r[1].toISOString() : undefined,
      page: query.page,
      size: query.size,
    })
    items.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function resetFilters(): void {
  filters.userId = ''
  filters.action = ''
  filters.targetType = ''
  filters.targetId = ''
  range.value = null
  refresh(true)
}

// ---- 用户筛选下拉：本页仅 admin 可达，可安全消费 /users（首页 100 条作快速选择） ----
const userOptions = ref<{ id: string; username: string }[]>([])

onMounted(refresh)
onMounted(async () => {
  try {
    const data = await listUsers({ page: 1, size: 100 })
    userOptions.value = data.items.map((u) => ({ id: u.id, username: u.username }))
  } catch {
    /* 下拉候选加载失败不阻塞主列表 */
  }
})

// 分页变化重查：el-pagination 的 current-change/size-change 事件参数是页码/页大小数值，
// 直接绑到 refresh(resetPage) 会被误判为「回第一页」导致翻页失效 → 统一经 watch 驱动
watch([() => query.page, () => query.size], () => void refresh())

// ---- 窄屏：隐藏目标 ID / IP 列，分页简化 ----
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

/** detail JSON 展开（对象为空或缺失时给出占位说明） */
function formatDetail(detail: Record<string, unknown> | null | undefined): string {
  if (!detail || Object.keys(detail).length === 0) return '（无附加信息）'
  try {
    return JSON.stringify(detail, null, 2)
  } catch {
    return String(detail)
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
        <span class="bar-scope">系统管理 · 审计日志</span>
      </div>
      <div class="bar-user">
        <nav class="bar-nav">
          <button class="bar-link" type="button" @click="router.push('/admin/users')">用户管理</button>
          <button class="bar-link is-active" type="button">审计日志</button>
          <button class="bar-link" type="button" @click="router.push('/projects')">返回台账</button>
        </nav>
        <ThemePicker />
        <span class="user-name">{{ auth.username }}</span>
        <button class="bar-action ws-ghost-btn" type="button" @click="onLogout">退出登录</button>
      </div>
    </header>

    <main class="workspace">
      <div class="page-head">
        <div>
          <h1>审计日志</h1>
          <p class="page-desc">
            记录登录、工程保存、分享、变量写入、报警确认与用户管理等关键操作，按时间倒序。
          </p>
        </div>
        <div class="ledger-count" aria-label="记录总数">
          <span class="count-value ws-readout">{{ total }}</span>
          <span class="count-label">条记录</span>
        </div>
      </div>

      <div class="filter-bar">
        <el-select
          v-model="filters.action"
          placeholder="操作类型"
          clearable
          class="f-action"
          @change="refresh(true)"
        >
          <el-option v-for="a in actionOptions" :key="a.value" :label="a.label" :value="a.value" />
        </el-select>
        <el-select
          v-model="filters.userId"
          placeholder="操作用户"
          clearable
          filterable
          class="f-user"
          @change="refresh(true)"
        >
          <el-option v-for="u in userOptions" :key="u.id" :label="u.username" :value="u.id" />
        </el-select>
        <el-select
          v-model="filters.targetType"
          placeholder="目标类型"
          clearable
          filterable
          allow-create
          class="f-target"
          @change="refresh(true)"
        >
          <el-option v-for="t in TARGET_TYPES" :key="t" :label="t" :value="t" />
        </el-select>
        <el-input
          v-model="filters.targetId"
          placeholder="目标 ID"
          clearable
          class="f-target-id"
          @keyup.enter="refresh(true)"
          @clear="refresh(true)"
        />
        <el-date-picker
          v-model="range"
          type="datetimerange"
          range-separator="至"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
          class="f-range"
          @change="refresh(true)"
        />
        <el-button type="primary" :icon="Search" @click="refresh(true)">查询</el-button>
        <el-button :icon="Refresh" @click="resetFilters">重置</el-button>
      </div>

      <section class="ledger">
        <el-table v-loading="loading" :data="items" stripe>
          <!-- detail JSON 展开（行首箭头） -->
          <el-table-column type="expand" width="34">
            <template #default="{ row }">
              <pre class="detail-json">{{ formatDetail(row.detail) }}</pre>
            </template>
          </el-table-column>
          <el-table-column label="时间" width="165">
            <template #default="{ row }">
              <span class="time ws-readout">{{ fmtTime(row.createdAt) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="用户" :min-width="isNarrow ? 90 : 120">
            <template #default="{ row }">
              <span class="cell-name" :title="row.username || ''">{{ row.username || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="110">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" :type="actionMeta(row.action).tag">
                {{ actionMeta(row.action).label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="目标类型" width="100">
            <template #default="{ row }">
              <span class="mono">{{ row.targetType || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column v-if="!isNarrow" label="目标 ID" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="mono">{{ row.targetId || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column v-if="!isNarrow" label="来源 IP" width="140">
            <template #default="{ row }">
              <span class="mono">{{ row.ip || '—' }}</span>
            </template>
          </el-table-column>

          <template #empty>
            <div class="empty">
              <p class="empty-title">暂无审计记录</p>
              <p class="empty-desc">调整过滤条件后重试。</p>
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
  background: var(--ws-inv-line);
}

.bar-scope {
  font-size: 13px;
  color: var(--ws-inv-75);
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
  color: var(--ws-inv-75);
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
}

.bar-link:hover {
  background: var(--ws-signal-a12);
  color: #fff;
}

.bar-link.is-active {
  background: var(--ws-signal-a18);
  color: #fff;
}

.user-name {
  font-family: var(--ws-font-tech);
  font-size: 12px;
  letter-spacing: 0.03em;
  color: var(--ws-inv-75);
}

/* bar-action 外观走全局 .ws-ghost-btn */

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

/* ---- 过滤条 ---- */
.filter-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin: 22px 0 14px;
}

.f-action {
  width: 132px;
}

.f-user {
  width: 148px;
}

.f-target {
  width: 128px;
}

.f-target-id {
  width: 210px;
}

.f-range {
  max-width: 360px;
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

.mono {
  font-family: var(--ws-font-mono);
  font-size: 12px;
  color: var(--ws-text-2);
}

.time {
  color: var(--ws-text-3);
  font-size: 12px;
}

/* detail JSON 展开区：等宽字体 + 钢灰底 */
.detail-json {
  margin: 0;
  padding: 10px 12px;
  background: var(--ws-steel-0);
  border: 1px solid var(--ws-steel-2);
  font-family: var(--ws-font-mono);
  font-size: 12px;
  line-height: 1.6;
  color: var(--ws-text-2);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 260px;
  overflow: auto;
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

/* ---- 窄屏 ---- */
@media (max-width: 860px) {
  .workspace {
    padding: 20px 16px 32px;
  }

  .ledger-count {
    display: none;
  }

  .f-range {
    max-width: none;
    flex: 1;
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
