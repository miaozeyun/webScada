<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Download, Plus, Search, Upload } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import {
  createProject,
  deleteProject,
  exportProject,
  importProject,
  listProjects,
  type ProjectListItem,
} from '@/api/projects'
import { sanitizeDocForExport } from '@/utils/sanitize'
import { downloadJson, fileTimestamp } from '@/utils/download'
import type { ProjectDoc } from '@/types/doc'

const router = useRouter()
const auth = useAuthStore()

// ---- 列表 ----
const loading = ref(false)
const items = ref<ProjectListItem[]>([])
const total = ref(0)
const query = reactive({ keyword: '', page: 1, size: 20 })

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

// ---- 删除（服务端级联 share_links / alarm_records） ----
async function doDelete(row: ProjectListItem): Promise<void> {
  await ElMessageBox.confirm(`确定删除工程「${row.name}」？该操作不可恢复。`, '删除确认', { type: 'warning' })
  await deleteProject(row.id)
  ElMessage.success('已删除')
  refresh()
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
  <el-container class="page">
    <el-header class="header">
      <div class="header-left">webScada · 工程管理</div>
      <div class="header-right">
        <span class="username">{{ auth.username }}</span>
        <el-button text size="small" @click="onLogout">退出登录</el-button>
      </div>
    </el-header>

    <el-main>
      <div class="toolbar">
        <el-input
          v-model="query.keyword"
          placeholder="按名称搜索"
          clearable
          style="width: 240px"
          :prefix-icon="Search"
          @keyup.enter="refresh(true)"
          @clear="refresh(true)"
        />
        <el-button :icon="Search" @click="refresh(true)">搜索</el-button>
        <span class="spacer" />
        <input ref="fileInput" type="file" accept=".json,application/json" style="display: none" @change="onFileChange" />
        <el-button :icon="Upload" @click="pickFile">导入工程</el-button>
        <el-button type="primary" :icon="Plus" @click="createVisible = true">新建工程</el-button>
      </div>

      <el-table v-loading="loading" :data="items" stripe>
        <el-table-column prop="name" label="工程名称" min-width="180" />
        <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
        <el-table-column prop="revision" label="版本" width="80" align="center" />
        <el-table-column label="更新时间" width="180">
          <template #default="{ row }">{{ fmtTime(row.updatedAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" align="center">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="router.push(`/editor/${row.id}`)">编辑</el-button>
            <el-button size="small" :icon="Download" @click="doExport(row)">导出</el-button>
            <el-button size="small" type="danger" :icon="Delete" @click="doDelete(row)" />
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无工程，点击右上角新建或导入" />
        </template>
      </el-table>

      <el-pagination
        v-model:current-page="query.page"
        v-model:page-size="query.size"
        :total="total"
        :page-sizes="[10, 20, 50]"
        layout="total, sizes, prev, pager, next"
        style="margin-top: 16px; justify-content: flex-end"
        @current-change="refresh"
        @size-change="refresh"
      />
    </el-main>

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
  </el-container>
</template>

<style scoped>
.page {
  height: 100vh;
}

.header {
  background: var(--ws-header-bg);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-left {
  font-size: 16px;
  font-weight: 600;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.username {
  opacity: 0.85;
  font-size: 13px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}

.spacer {
  flex: 1;
}
</style>
