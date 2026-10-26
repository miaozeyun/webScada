<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, CopyDocument, Delete, Download, Grid, Menu, Plus, Search, Upload, VideoPlay } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { meApi } from '@/api/auth'
import type { UserInfo } from '@/api/auth'
import {
  cloneProject,
  createProject,
  deleteProject,
  exportProject,
  importProject,
  listProjects,
  type ProjectListItem,
} from '@/api/projects'
import { sanitizeDocForExport } from '@/utils/sanitize'
import { buildStressDoc } from '@/utils/stressDoc'
import { DEMO_CASES, seedCaseHistory } from '@/utils/demos'
import { downloadJson, fileTimestamp } from '@/utils/download'
import type { ProjectDoc } from '@/types/doc'
import ThemePicker from '@/components/ThemePicker.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

/** 开发者工具（压测工程生成）默认隐藏：面向最终用户的菜单不出现开发功能；?dev=1 显式开启 */
const devTools = ref(route.query.dev === '1')

// ---- 系统管理入口（M8 RBAC）：仅 admin 可见；角色经 /auth/me 拉取（auth store 未持久化 role） ----
const isAdmin = ref(false)

onMounted(async () => {
  try {
    const me = await meApi()
    isAdmin.value = (me as UserInfo & { role?: string }).role === 'admin'
  } catch {
    /* 拉取失败按非 admin 处理（401 由拦截器接管跳登录） */
  }
})

function onAdminNav(cmd: string): void {
  router.push(cmd)
}

// ---- 列表 ----
const loading = ref(false)
const items = ref<ProjectListItem[]>([])
const total = ref(0)
const query = reactive({ keyword: '', page: 1, size: 20 })

// 分页/每页条数变化即刷新（v-model 驱动，勿绑 @current-change=refresh——数值参数会被误判为 resetPage）
watch([() => query.page, () => query.size], () => { refresh() })

async function refresh(resetPage = false): Promise<void> {
  if (resetPage) query.page = 1 // 搜索换关键字后回到第一页（防第 3 页搜索显示空态的矛盾）
  loading.value = true
  try {
    const data = await listProjects({ keyword: query.keyword || undefined, page: query.page, size: query.size })
    items.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

onMounted(refresh)

// ---- 视图模式：表格 / 卡片（首页缩略图），选择持久化 ----
type ViewMode = 'table' | 'card'
const VIEW_STORAGE_KEY = 'webscada_projects_view'
const viewMode = ref<ViewMode>(((): ViewMode => {
  try {
    return localStorage.getItem(VIEW_STORAGE_KEY) === 'card' ? 'card' : 'table'
  } catch {
    return 'table'
  }
})())

watch(viewMode, (v) => {
  try {
    localStorage.setItem(VIEW_STORAGE_KEY, v)
  } catch {
    /* 隐私模式下仅当前会话生效 */
  }
})

// ---- 窄屏：表格只留工程名与操作，分页简化（避免操作列被挤出视口） ----
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

// ---- 新建（创建不携带 doc，G7；空白模板由服务端生成） ----
const createVisible = ref(false)
const createForm = reactive({ name: '', description: '' })

async function doCreate(): Promise<void> {
  await createProject({ name: createForm.name, description: createForm.description || undefined })
  ElMessage.success('工程已创建')
  createVisible.value = false
  createForm.name = ''
  createForm.description = ''
  refresh()
}

// ---- 演示案例生成（M7：对齐业界主流组态 演示站，6 个开箱即用案例） ----
const demoVisible = ref(false)
const demoLoading = ref('')

async function doGenDemo(key: string): Promise<void> {
  const c = DEMO_CASES.find((d) => d.key === key)
  if (!c) return
  demoLoading.value = key
  try {
    const doc = c.build()
    const created = await importProject(doc)
    seedCaseHistory(created.doc ?? doc) // 预置近 6h 历史，图表打开即有曲线
    ElMessage.success(`案例「${c.name}」已生成`)
    refresh()
  } catch {
    /* 校验失败由拦截器弹出 422 详情 */
  } finally {
    demoLoading.value = ''
  }
}

async function doGenAllDemos(): Promise<void> {
  for (const c of DEMO_CASES) {
    demoLoading.value = c.key
    try {
      const doc = c.build()
      const created = await importProject(doc)
      seedCaseHistory(created.doc ?? doc)
    } catch {
      ElMessage.error(`案例「${c.name}」生成失败`)
      break
    }
  }
  demoLoading.value = ''
  ElMessage.success('演示案例已生成')
  refresh()
}

// ---- 压测工程生成（M7：1100 组件性能验证，走 import 端点） ----
const stressing = ref(false)

async function doStress(): Promise<void> {
  try {
    await ElMessageBox.confirm('将创建包含 1100 个组件、20 个 mock 变量的压测工程（用于性能验证）。继续？', '生成压测工程', { type: 'info' })
  } catch {
    return
  }
  stressing.value = true
  try {
    await importProject(buildStressDoc())
    ElMessage.success('压测工程已生成，可进入编辑器验证加载与运行性能')
    refresh()
  } catch {
    /* 校验失败由拦截器弹出 */
  } finally {
    stressing.value = false
  }
}

/** 工具下拉：低频入口从工具条收起，保持主操作清晰 */
function onTool(cmd: string): void {
  if (cmd === 'demo') demoVisible.value = true
  else if (cmd === 'stress') doStress()
}

/** 卡片「更多」下拉：复制 / 导出 / 删除（与表格行操作同源） */
function onCardMore(cmd: string, row: ProjectListItem): void {
  if (cmd === 'clone') openClone(row)
  else if (cmd === 'export') void doExport(row)
  else if (cmd === 'alarms') router.push(`/projects/${row.id}/alarms`)
  else if (cmd === 'delete') void doDelete(row)
}

// ---- 克隆（模板 → 新工程；OEM 一模板 N 台设备的最小闭环） ----
const cloneVisible = ref(false)
const cloneSaving = ref(false)
const cloneName = ref('')
const cloneSource = ref<ProjectListItem | null>(null)

function openClone(row: ProjectListItem): void {
  cloneSource.value = row
  cloneName.value = `${row.name} 副本`
  cloneVisible.value = true
}

async function confirmClone(): Promise<void> {
  const src = cloneSource.value
  const name = cloneName.value.trim()
  if (!src) return
  if (!name) {
    ElMessage.warning('请填写工程名称')
    return
  }
  cloneSaving.value = true
  try {
    await cloneProject(src.id, name)
    cloneVisible.value = false
    ElMessage.success('已复制工程')
    await refresh()
  } finally {
    cloneSaving.value = false
  }
}

// ---- 删除（服务端级联 share_links / alarm_records） ----
async function doDelete(row: ProjectListItem): Promise<void> {
  await ElMessageBox.confirm(`确定删除工程「${row.name}」？该操作不可恢复。`, '删除确认', { type: 'warning' })
  await deleteProject(row.id)
  ElMessage.success('已删除')
  refresh()
}

// ---- 批量删除（2026-10-26）：清理测试/演示工程，避免台账长期堆积 ----
const selectedRows = ref<ProjectListItem[]>([])

function onSelectionChange(rows: ProjectListItem[]): void {
  selectedRows.value = rows
}

async function batchDelete(): Promise<void> {
  const rows = selectedRows.value
  if (!rows.length) return
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${rows.length} 个工程？其分享链接与报警记录会一并删除，且不可恢复。`,
      '批量删除',
      { type: 'warning', confirmButtonText: `删除 ${rows.length} 个`, cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  let ok = 0
  let fail = 0
  for (const row of rows) {
    try {
      await deleteProject(row.id)
      ok++
    } catch {
      fail++
    }
  }
  if (fail) ElMessage.warning(`已删除 ${ok} 个，${fail} 个失败（可重试）`)
  else ElMessage.success(`已删除 ${ok} 个工程`)
  selectedRows.value = []
  refresh(true)
}

// ---- 导出：调导出端点 → 前端二次脱敏（G6 双保险）→ Blob 下载命名（G7） ----
async function doExport(row: ProjectListItem): Promise<void> {
  const doc = await exportProject(row.id)
  const safe = sanitizeDocForExport(doc)
  downloadJson(safe, `${row.name}_schema${doc.schemaVersion}_${fileTimestamp()}.json`)
}

// ---- 导入：读 .json → POST /projects/import（JSON body 形态） ----
const fileInput = ref<HTMLInputElement>()

function pickFile(): void {
  fileInput.value?.click()
}

async function onFileChange(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  try {
    let doc: ProjectDoc
    try {
      doc = JSON.parse(await file.text()) as ProjectDoc
    } catch {
      ElMessage.error('所选文件不是合法的 JSON 文件')
      return
    }
    await importProject(doc)
    ElMessage.success(`已导入工程：${doc.project?.name ?? file.name}`)
    refresh()
  } catch {
    /* 结构/引用校验失败由拦截器弹出 422 错误体（含字段路径） */
  }
  input.value = ''
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
  <div class="projects-page">
    <header class="app-bar">
      <div class="bar-brand">
        <svg class="bar-mark" viewBox="0 0 32 32" aria-hidden="true">
          <rect x="0.75" y="0.75" width="30.5" height="30.5" />
          <path d="M5 21 H11 L14 12 L18 24 L21 16 H27" />
        </svg>
        <span class="bar-name">webScada</span>
        <span class="bar-divider" aria-hidden="true"></span>
        <span class="bar-scope">工程台账</span>
      </div>
      <div class="bar-user">
        <el-dropdown v-if="isAdmin" trigger="click" @command="onAdminNav">
          <button class="bar-action ws-ghost-btn" type="button">
            系统管理<el-icon class="bar-caret"><ArrowDown /></el-icon>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="/admin/users">用户管理</el-dropdown-item>
              <el-dropdown-item command="/admin/audit">审计日志</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <ThemePicker />
        <span class="user-name">{{ auth.username }}</span>
        <button class="bar-action ws-ghost-btn" type="button" @click="onLogout">退出登录</button>
      </div>
    </header>

    <main class="workspace">
      <div class="page-head">
        <div>
          <h1>工程台账</h1>
          <p class="page-desc">管理组态画面、导入导出工程，或从演示案例快速开始。</p>
        </div>
        <div class="ledger-count" aria-label="工程总数">
          <span class="count-value ws-readout">{{ total }}</span>
          <span class="count-label">个工程</span>
        </div>
      </div>

      <div class="action-bar">
        <div class="search">
          <el-input
            v-model="query.keyword"
            placeholder="按名称搜索"
            clearable
            :prefix-icon="Search"
            @keyup.enter="refresh(true)"
            @clear="refresh(true)"
          />
          <el-button @click="refresh(true)">搜索</el-button>
        </div>
        <div class="view-toggle" role="group" aria-label="视图模式">
          <button type="button" :class="{ active: viewMode === 'table' }" title="表格视图" aria-label="表格视图" @click="viewMode = 'table'">
            <el-icon :size="14"><Menu /></el-icon>
          </button>
          <button type="button" :class="{ active: viewMode === 'card' }" title="卡片视图（画面缩略图）" aria-label="卡片视图" @click="viewMode = 'card'">
            <el-icon :size="14"><Grid /></el-icon>
          </button>
        </div>
        <span class="spacer" />
        <input ref="fileInput" type="file" accept=".json,application/json" style="display: none" @change="onFileChange" />
        <el-button :icon="Upload" @click="pickFile">导入工程</el-button>
        <el-dropdown trigger="click" @command="onTool">
          <el-button>
            工具<el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="demo">演示案例…</el-dropdown-item>
              <el-dropdown-item v-if="devTools" command="stress" divided>生成压测工程（开发）</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button
          v-if="selectedRows.length"
          type="danger"
          plain
          :icon="Delete"
          @click="batchDelete"
        >
          删除选中（{{ selectedRows.length }}）
        </el-button>
        <el-button :icon="VideoPlay" title="用仿真数据实时驱动任意工程画面（不修改工程）" @click="router.push('/simulator')">实时仿真</el-button>
        <el-button type="primary" :icon="Plus" @click="createVisible = true">新建工程</el-button>
      </div>

      <section class="ledger">
        <!-- 表格视图 -->
        <el-table
          v-if="viewMode === 'table'"
          v-loading="loading"
          :data="items"
          stripe
          @selection-change="onSelectionChange"
        >
          <el-table-column type="selection" width="44" />
          <el-table-column prop="name" label="工程名称" :min-width="isNarrow ? 150 : 210">
            <template #default="{ row }">
              <span class="name-cell">
                <span class="project-name" :title="row.name">{{ row.name }}</span>
                <!-- 悬停缩略图预览：画面缩略图（无图显示线稿占位），不占行高 -->
                <span class="hover-preview">
                  <img v-if="row.thumbnail" :src="row.thumbnail" alt="" />
                  <svg v-else class="preview-placeholder" viewBox="0 0 48 48" aria-hidden="true">
                    <rect x="5.5" y="9.5" width="37" height="29" />
                    <path d="M5.5 17.5 H42.5 M11.5 13.5 H13 M15.5 13.5 H17" />
                    <path d="M12 30 L18 30 L21 22 L26 35 L30 27 L36 27" />
                  </svg>
                  <span class="preview-caption">{{ row.name }}</span>
                </span>
              </span>
            </template>
          </el-table-column>
          <el-table-column v-if="!isNarrow" prop="description" label="描述" min-width="240" show-overflow-tooltip />
          <el-table-column v-if="!isNarrow" label="版本" width="80" align="center">
            <template #default="{ row }">
              <span class="revision ws-readout">{{ row.revision }}</span>
            </template>
          </el-table-column>
          <el-table-column v-if="!isNarrow" label="更新时间" width="180">
            <template #default="{ row }">
              <span class="time ws-readout">{{ fmtTime(row.updatedAt) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" :width="isNarrow ? 120 : 104" align="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="router.push(`/editor/${row.id}`)">编辑</el-button>
              <el-dropdown trigger="click" @command="(cmd: string) => onCardMore(cmd, row)">
                <el-button link size="small" class="more-btn" @click.stop>
                  ⋯<el-icon class="el-icon--right"><ArrowDown /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="clone" :icon="CopyDocument">复制工程</el-dropdown-item>
                    <el-dropdown-item command="export" :icon="Download">导出 JSON</el-dropdown-item>
                    <el-dropdown-item command="alarms">报警记录</el-dropdown-item>
                    <el-dropdown-item command="delete" :icon="Delete" divided>删除</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </template>
          </el-table-column>

          <template #empty>
            <div class="empty">
              <svg class="empty-mark" viewBox="0 0 48 48" aria-hidden="true">
                <rect x="5.5" y="9.5" width="37" height="29" />
                <path d="M5.5 17.5 H42.5 M11.5 13.5 H13 M15.5 13.5 H17" />
                <path d="M12 30 L18 30 L21 22 L26 35 L30 27 L36 27" />
              </svg>
              <p class="empty-title">台账还是空的</p>
              <p class="empty-desc">新建一个工程，或导入已有的 JSON 工程文件。</p>
              <div class="empty-actions">
                <el-button type="primary" size="small" :icon="Plus" @click="createVisible = true">新建工程</el-button>
                <el-button size="small" :icon="Upload" @click="pickFile">导入工程</el-button>
              </div>
            </div>
          </template>
        </el-table>

        <!-- 卡片视图：首页画面缩略图（编辑器保存时自动截图；老工程无图先占位） -->
        <div v-else v-loading="loading" class="card-grid">
          <article
            v-for="row in items"
            :key="row.id"
            class="project-card"
            :title="`${row.name}（双击进入编辑器）`"
            @dblclick="router.push(`/editor/${row.id}`)"
          >
            <div class="card-thumb" :class="{ 'is-empty': !row.thumbnail }">
              <img v-if="row.thumbnail" :src="row.thumbnail" :alt="`${row.name} 首页画面`" loading="lazy" />
              <template v-else>
                <svg class="thumb-placeholder" viewBox="0 0 48 48" aria-hidden="true">
                  <rect x="5.5" y="9.5" width="37" height="29" />
                  <path d="M5.5 17.5 H42.5 M11.5 13.5 H13 M15.5 13.5 H17" />
                  <path d="M12 30 L18 30 L21 22 L26 35 L30 27 L36 27" />
                </svg>
                <span class="thumb-hint">保存后自动生成预览</span>
              </template>
              <span class="card-rev ws-readout">r{{ row.revision }}</span>
            </div>
            <div class="card-body">
              <span class="card-name">{{ row.name }}</span>
              <span class="card-desc">{{ row.description || '暂无描述' }}</span>
            </div>
            <div class="card-foot">
              <span class="card-time ws-readout">{{ fmtTime(row.updatedAt) }}</span>
              <div class="card-ops">
                <el-button link type="primary" size="small" @click.stop="router.push(`/editor/${row.id}`)">编辑</el-button>
                <el-dropdown trigger="click" @command="(cmd: string) => onCardMore(cmd, row)">
                  <el-button link size="small" @click.stop>
                    更多<el-icon class="el-icon--right"><ArrowDown /></el-icon>
                  </el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="clone">复制工程</el-dropdown-item>
                      <el-dropdown-item command="export">导出</el-dropdown-item>
                      <el-dropdown-item command="alarms">报警记录</el-dropdown-item>
                      <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
            </div>
          </article>

          <div v-if="!loading && items.length === 0" class="empty card-empty">
            <svg class="empty-mark" viewBox="0 0 48 48" aria-hidden="true">
              <rect x="5.5" y="9.5" width="37" height="29" />
              <path d="M5.5 17.5 H42.5 M11.5 13.5 H13 M15.5 13.5 H17" />
              <path d="M12 30 L18 30 L21 22 L26 35 L30 27 L36 27" />
            </svg>
            <p class="empty-title">台账还是空的</p>
            <p class="empty-desc">新建一个工程，或导入已有的 JSON 工程文件。</p>
            <div class="empty-actions">
              <el-button type="primary" size="small" :icon="Plus" @click="createVisible = true">新建工程</el-button>
              <el-button size="small" :icon="Upload" @click="pickFile">导入工程</el-button>
            </div>
          </div>
        </div>

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

    <!-- 演示案例选择 -->
    <el-dialog v-model="demoVisible" title="生成演示案例" width="640px">
      <p class="dialog-lead">全 mock 数据，生成后直接进入编辑器查看，无需外部设备。</p>
      <div class="demo-list">
        <div v-for="c in DEMO_CASES" :key="c.key" class="demo-item">
          <div class="demo-info">
            <div class="demo-name">{{ c.name }}</div>
            <div class="demo-desc">{{ c.description }}</div>
          </div>
          <el-button size="small" type="primary" plain :loading="demoLoading === c.key" @click="doGenDemo(c.key)">
            生成
          </el-button>
        </div>
      </div>
      <template #footer>
        <el-button @click="demoVisible = false">关闭</el-button>
        <el-button type="primary" :loading="demoLoading !== ''" @click="doGenAllDemos">全部生成</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="createVisible" title="新建工程" width="420px">
      <el-form label-position="top">
        <el-form-item label="工程名称" required>
          <el-input v-model="createForm.name" maxlength="128" placeholder="如：一号车间产线" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="createForm.description" type="textarea" :rows="2" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!createForm.name.trim()" @click="doCreate">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="cloneVisible" title="复制工程（模板 → 新设备）" width="440px">
      <el-form label-position="top">
        <el-form-item label="源工程">
          <el-input :model-value="cloneSource?.name" disabled />
        </el-form-item>
        <el-form-item label="新工程名称" required>
          <el-input v-model="cloneName" maxlength="128" placeholder="如：2号机组监控" @keyup.enter="confirmClone" />
        </el-form-item>
        <p class="clone-hint">画面、绑定、报警规则、数据源配置全部复制；新工程独立 revision，改源工程不影响副本。</p>
      </el-form>
      <template #footer>
        <el-button @click="cloneVisible = false">取消</el-button>
        <el-button type="primary" :loading="cloneSaving" :disabled="!cloneName.trim()" @click="confirmClone">复制</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.projects-page {
  min-height: 100vh;
  background: var(--ws-canvas);
  display: flex;
  flex-direction: column;
}

/* ---- 控制台顶栏 ---- */
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

.user-name {
  font-family: var(--ws-font-tech);
  font-size: 12px;
  letter-spacing: 0.03em;
  color: var(--ws-inv-75);
}

/* bar-action 外观走全局 .ws-ghost-btn */

.bar-caret {
  margin-left: 2px;
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

/* ---- 视图切换（表格/卡片） ---- */
.view-toggle {
  display: flex;
  flex-shrink: 0;
  border: 1px solid var(--ws-steel-3);
  border-radius: var(--ws-radius);
  background: var(--ws-panel);
  overflow: hidden;
}

.view-toggle button {
  width: 30px;
  height: 24px;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--ws-text-3);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.view-toggle button + button {
  border-left: 1px solid var(--ws-steel-2);
}

.view-toggle button:hover {
  color: var(--ws-signal);
}

.view-toggle button.active {
  background: var(--ws-signal-soft);
  color: var(--ws-signal);
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

.project-name {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
  color: var(--ws-text);
}

/* 行悬停缩略图预览：浮在行上方，不占布局（纯 CSS，触屏无 hover 不出现） */
.name-cell {
  position: relative;
  display: block;
}

.hover-preview {
  position: absolute;
  left: 0;
  bottom: calc(100% + 6px);
  z-index: 30;
  width: 224px;
  padding: 0;
  border: 1px solid var(--ws-steel-3);
  border-radius: 3px;
  background: var(--ws-panel);
  box-shadow: 0 10px 32px rgba(20, 33, 46, 0.22);
  opacity: 0;
  transform: translateY(4px);
  pointer-events: none;
  transition: opacity 0.14s ease-out, transform 0.14s ease-out;
}

.name-cell:hover .hover-preview {
  opacity: 1;
  transform: translateY(0);
}

.hover-preview img,
.preview-placeholder {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 9;
  object-fit: cover;
  border-radius: 2px 2px 0 0;
  background: var(--ws-steel-1);
}

.preview-placeholder {
  width: 56px;
  aspect-ratio: auto;
  height: 56px;
  margin: 18px auto;
  fill: none;
  stroke: var(--ws-steel-3);
  stroke-width: 1.4;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.hover-preview:has(.preview-placeholder) {
  padding-bottom: 4px;
}

.preview-caption {
  display: block;
  padding: 6px 10px;
  border-top: 1px solid var(--ws-steel-2);
  font-size: 11px;
  color: var(--ws-text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 操作列「更多」：与主链接同基线 */
.more-btn {
  margin-left: 2px;
}

.revision {
  color: var(--ws-text-2);
}

.time {
  color: var(--ws-text-3);
  font-size: 12px;
}

.ledger-foot {
  display: flex;
  justify-content: flex-end;
  padding: 10px 14px;
  border-top: 1px solid var(--ws-steel-2);
}

/* ---- 卡片视图 ---- */
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 12px;
  padding: 14px;
  min-height: 240px;
  align-content: start;
}

.card-empty {
  grid-column: 1 / -1;
}

.project-card {
  display: flex;
  flex-direction: column;
  background: var(--ws-panel);
  border: 1px solid var(--ws-steel-3);
  border-radius: var(--ws-radius);
  overflow: hidden;
  transition: border-color 0.15s ease, box-shadow 0.15s ease, transform 0.15s ease;
}

.project-card:hover {
  border-color: var(--ws-signal);
  box-shadow: 0 6px 18px rgba(20, 33, 46, 0.1);
  transform: translateY(-1px);
}

@media (prefers-reduced-motion: reduce) {
  .project-card,
  .project-card:hover {
    transform: none;
  }
}

.card-thumb {
  position: relative;
  aspect-ratio: 16 / 9;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: var(--ws-steel-1);
  border-bottom: 1px solid var(--ws-steel-2);
  overflow: hidden;
}

/* 无缩略图卡：点阵蓝图底 + 线稿占位，看起来是「待生成」而不是「坏图」 */
.card-thumb.is-empty {
  background-color: var(--ws-steel-0);
  background-image: radial-gradient(var(--ws-steel-3) 1px, transparent 1px);
  background-size: 12px 12px;
  background-position: center;
}

.card-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.thumb-placeholder {
  width: 52px;
  height: 52px;
  padding: 6px;
  border: 1px solid var(--ws-steel-2);
  border-radius: var(--ws-radius);
  background: rgba(255, 255, 255, 0.86);
  fill: none;
  stroke: var(--ws-text-3);
  stroke-width: 1.4;
  stroke-linecap: round;
  stroke-linejoin: round;
  opacity: 0.55;
}

.thumb-hint {
  padding: 1px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.86);
  color: var(--ws-text-3);
  font-size: 11px;
  line-height: 18px;
}

.card-rev {
  position: absolute;
  right: 6px;
  bottom: 6px;
  padding: 1px 6px;
  background: rgba(20, 33, 46, 0.6);
  color: rgba(238, 244, 247, 0.85);
  font-size: 10px;
  border-radius: var(--ws-radius);
}

.card-body {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 10px 12px 4px;
  min-width: 0;
}

.card-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--ws-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.card-desc {
  font-size: 12px;
  color: var(--ws-text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 8px 8px 12px;
}

.card-time {
  font-size: 11px;
  color: var(--ws-text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.card-ops {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

/* ---- 空态 ---- */
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 36px 0 30px;
}

.empty-mark {
  width: 48px;
  height: 48px;
  fill: none;
  stroke: var(--ws-steel-3);
  stroke-width: 1.4;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.empty-title {
  margin: 14px 0 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--ws-text-2);
}

.empty-desc {
  margin: 6px 0 16px;
  font-size: 12px;
  color: var(--ws-text-3);
}

.empty-actions {
  display: flex;
  gap: 8px;
}

/* ---- 对话框 ---- */
.dialog-lead {
  margin: 0 0 14px;
  font-size: 12px;
  color: var(--ws-text-3);
}

.demo-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 52vh;
  overflow-y: auto;
}

.demo-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  background: var(--ws-steel-0);
  border: 1px solid var(--ws-steel-2);
  border-left: 2px solid var(--ws-steel-3);
}

.demo-item:hover {
  border-left-color: var(--ws-signal);
}

.demo-info {
  flex: 1;
  min-width: 0;
}

.demo-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--ws-text);
}

.demo-desc {
  margin-top: 2px;
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
  .user-name {
    display: none;
  }
}

.clone-hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--ws-text-2);
}
</style>
