<script setup lang="ts">
/**
 * 编辑器布局（结构/视觉严格参照 visual-drag-demo Home.vue + Toolbar.vue，MIT 见 THIRD_PARTY_NOTICES.md）：
 * 顶部一排小按钮工具栏 + 左 200px（组件 65% / 图层 35%，可折叠）+ 中 #f5f5f5 画布区
 * + 右 288px 属性面板（可折叠），折叠钮为半圆悬浮按钮。
 * 保存链路：dirtySeq 变更 → 3s 防抖 PUT（G2 乐观锁）；断网失败保内存态，冲突给重载入口。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, CaretLeft, CaretRight, Delete, FullScreen, RefreshRight } from '@element-plus/icons-vue'
import { useEditorStore } from '@/stores/editor'
import { exportProject } from '@/api/projects'
import { createShare } from '@/api/shares'
import { downloadJson, fileTimestamp } from '@/utils/download'
import type { ProjectDoc } from '@/types/doc'
import { installKeyboard } from '@/editor/keyboard'
import CanvasStage from '@/editor/canvas/CanvasStage.vue'
import PreviewOverlay from '@/editor/PreviewOverlay.vue'
import ComponentPalette from '@/editor/panels/ComponentPalette.vue'
import DataDrawer from '@/editor/panels/DataDrawer.vue'
import LayerPanel from '@/editor/panels/LayerPanel.vue'
import PageTabs from '@/editor/panels/PageTabs.vue'
import PropPanel from '@/editor/panels/PropPanel.vue'

const route = useRoute()
const router = useRouter()
const editor = useEditorStore()

const loading = ref(true)
const loadError = ref('')
const leftList = ref(true)
const rightList = ref(true)
const previewVisible = ref(false)
const dataDrawerVisible = ref(false)

let uninstallKeyboard: (() => void) | null = null
let saveTimer: ReturnType<typeof setTimeout> | null = null

onMounted(async () => {
  uninstallKeyboard = installKeyboard(editor)
  try {
    await editor.load(String(route.params.id))
  } catch {
    loadError.value = '工程加载失败'
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(() => {
  uninstallKeyboard?.()
  if (saveTimer) clearTimeout(saveTimer)
})

// ---- 自动保存（3s 防抖） ----
watch(
  () => editor.dirtySeq,
  () => {
    if (saveTimer) clearTimeout(saveTimer)
    saveTimer = setTimeout(() => editor.save(), 3000)
  },
)

async function backToList(): Promise<void> {
  if (editor.dirty) {
    const ok = await editor.save()
    if (!ok) {
      try {
        await ElMessageBox.confirm('当前有未保存的修改且保存失败（断网或冲突）。仍要离开吗？离开将丢失本地修改。', '未保存提醒', { type: 'warning' })
      } catch {
        return
      }
    }
  }
  router.push('/projects')
}

function manualSave(): void {
  editor.save().then((ok) => {
    if (ok) ElMessage.success('已保存')
  })
}

async function reloadAfterConflict(): Promise<void> {
  await ElMessageBox.confirm('检测到工程已被他人修改（409）。重新载入将丢弃本地未保存修改。', '版本冲突', { type: 'warning' })
  await editor.reloadFromServer()
  ElMessage.success('已重新载入最新版本')
}

const saveStatus = computed(() => {
  if (editor.saving) return { text: '保存中…', cls: 'saving' }
  if (editor.saveError === 'conflict') return { text: '版本冲突', cls: 'error' }
  if (editor.saveError === 'network') return { text: '保存失败（断网），本地未丢失', cls: 'error' }
  if (editor.dirty) return { text: '未保存（自动保存中）', cls: 'dirty' }
  return { text: '已保存', cls: 'ok' }
})

// ---- 工具栏状态 ----
const hasSelection = computed(() => editor.selection.length > 0)
const canGroup = computed(() => editor.selectedNodes.length >= 2 && editor.selectedNodes.every((n) => !n.locked))
const canUngroup = computed(() => editor.selectedNodes.some((n) => n.type === 'group' && !n.locked))
const allLocked = computed(() => hasSelection.value && editor.selectedNodes.every((n) => n.locked))

function toggleLock(): void {
  editor.selectedNodes.forEach((n) => editor.updateNode(n.id, { locked: !allLocked.value }))
}

const zoomPct = computed({
  get: () => Math.round(editor.zoom * 100),
  set: (v: number) => {
    if (v === undefined || Number.isNaN(v)) return
    editor.setZoom(Math.min(400, Math.max(25, v)) / 100)
  },
})

function fitView(): void {
  const vp = document.querySelector('.canvas-viewport')?.getBoundingClientRect()
  if (vp) editor.fitToView(vp.width, vp.height)
}

const ALIGN_ITEMS = [
  { label: '左对齐', value: 'left' },
  { label: '右对齐', value: 'right' },
  { label: '上对齐', value: 'top' },
  { label: '下对齐', value: 'bottom' },
  { label: '水平居中', value: 'centerX' },
  { label: '垂直居中', value: 'centerY' },
  { label: '横向分布（≥3）', value: 'distributeX' },
  { label: '纵向分布（≥3）', value: 'distributeY' },
] as const

function onAlign(cmd: string): void {
  editor.alignSelection(cmd as never)
}

// ---- 导入 / 导出 / 清空画布（对齐 visual-drag-demo Toolbar 功能集） ----

const importVisible = ref(false)
const importJson = ref('')

function openImport(): void {
  importJson.value = ''
  importVisible.value = true
}

/** el-upload 仅作文件选择器：before-upload 返回 false 阻止上传，内容读入 textarea */
function onImportFile(file: File): boolean {
  const reader = new FileReader()
  reader.onload = () => {
    importJson.value = String(reader.result ?? '')
  }
  reader.readAsText(file)
  return false
}

async function confirmImport(): Promise<void> {
  let doc: ProjectDoc
  try {
    doc = JSON.parse(importJson.value) as ProjectDoc
  } catch {
    ElMessage.error('JSON 解析失败，请检查格式')
    return
  }
  if (!editor.replaceDoc(doc)) {
    ElMessage.error('数据格式不正确：缺少 pages 数组')
    return
  }
  importVisible.value = false
  ElMessage.success('已导入，稍后自动保存到服务端')
}

/** 导出：先保存本地修改 → 走服务端脱敏接口（G7）→ 下载 JSON 文件 */
async function exportJson(): Promise<void> {
  if (editor.dirty) {
    const ok = await editor.save()
    if (!ok) {
      ElMessage.warning('本地有未保存修改且保存失败（断网或冲突），请先处理再导出')
      return
    }
  }
  try {
    const doc = await exportProject(editor.projectId)
    downloadJson(doc, `${editor.projectName}_${fileTimestamp()}.json`)
  } catch {
    ElMessage.error('导出失败，请检查网络')
  }
}

async function clearCanvas(): Promise<void> {
  if (editor.topLevelNodes.length === 0) return
  try {
    await ElMessageBox.confirm(
      `确定清空页面「${editor.currentPage?.name}」的全部 ${editor.topLevelNodes.length} 个组件？`,
      '清空画布',
      { type: 'warning' },
    )
  } catch {
    return
  }
  editor.clearPage()
}

// ---- 分享（M6）：创建 token → 弹出只读链接 ----

async function shareProject(): Promise<void> {
  // 先保存，保证分享快照包含最新修改
  if (editor.dirty) {
    const ok = await editor.save()
    if (!ok) {
      ElMessage.warning('本地有未保存修改且保存失败，请先处理再分享')
      return
    }
  }
  try {
    const share = await createShare(editor.projectId)
    const url = `${location.origin}/s/${share.token}`
    try {
      await navigator.clipboard.writeText(url)
      ElMessage.success('分享链接已复制')
    } catch {
      /* 剪贴板权限受限时仅展示 */
    }
    ElMessageBox.alert(url, '分享链接（只读，匿名可访问）', { confirmButtonText: '关闭' })
  } catch {
    ElMessage.error('创建分享失败，请检查网络')
  }
}
</script>

<template>
  <div class="home">
    <!-- 顶部工具栏（参照 Toolbar.vue：一排 small 按钮 + 画布比例输入） -->
    <header class="toolbar">
      <el-button text size="small" @click="backToList">工程列表</el-button>
      <span class="project-name">{{ editor.projectName }}</span>
      <span class="save-status" :class="saveStatus.cls">{{ saveStatus.text }}</span>

      <el-button size="small" title="粘贴工程 JSON 覆盖当前工程" @click="openImport">导入</el-button>
      <el-button size="small" title="导出工程 JSON 文件（服务端脱敏）" @click="exportJson">导出</el-button>

      <el-button size="small" :disabled="!editor.canUndo()" title="Ctrl+Z" @click="editor.undo()">撤销</el-button>
      <el-button size="small" :disabled="!editor.canRedo()" title="Ctrl+Shift+Z" @click="editor.redo()">重做</el-button>
      <el-button size="small" :disabled="!canGroup" title="Ctrl+G" @click="editor.groupSelection()">组合</el-button>
      <el-button size="small" :disabled="!canUngroup" title="Ctrl+Shift+G" @click="editor.ungroupSelection()">拆分</el-button>
      <el-button size="small" :disabled="!hasSelection" title="置顶" @click="editor.orderSelection('front')">置顶</el-button>
      <el-button size="small" :disabled="!hasSelection" title="上移一层" @click="editor.orderSelection('forward')">上移</el-button>
      <el-button size="small" :disabled="!hasSelection" title="下移一层" @click="editor.orderSelection('backward')">下移</el-button>
      <el-button size="small" :disabled="!hasSelection" title="置底" @click="editor.orderSelection('back')">置底</el-button>
      <el-button size="small" :disabled="!hasSelection" :title="allLocked ? '解锁' : '锁定'" @click="toggleLock">
        {{ allLocked ? '解锁' : '锁定' }}
      </el-button>
      <el-button size="small" type="danger" plain :icon="Delete" :disabled="!hasSelection" title="Delete" @click="editor.deleteSelection()">删除</el-button>
      <el-button size="small" type="danger" plain :disabled="editor.topLevelNodes.length === 0" title="清空当前页全部组件" @click="clearCanvas">清空画布</el-button>
      <el-dropdown :disabled="editor.selectedNodes.length < 2" @command="onAlign">
        <el-button size="small" :disabled="editor.selectedNodes.length < 2">
          对齐<el-icon class="el-icon--right"><ArrowDown /></el-icon>
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item v-for="a in ALIGN_ITEMS" :key="a.value" :command="a.value"
              :disabled="a.value.startsWith('distribute') && editor.selectedNodes.length < 3">
              {{ a.label }}
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>

      <div class="canvas-config">
        <span>画布比例</span>
        <input v-model.number="zoomPct" />
        %
      </div>
      <el-button size="small" :icon="FullScreen" title="适应画布" @click="fitView" />
      <el-button size="small" title="数据源 / 变量 / 报警规则" :disabled="!editor.doc" @click="dataDrawerVisible = true">数据</el-button>
      <el-button size="small" :disabled="!editor.doc" @click="previewVisible = true">预览</el-button>
      <el-button size="small" :disabled="!editor.doc" title="生成匿名只读分享链接" @click="shareProject">分享</el-button>
      <el-button v-if="editor.saveError === 'conflict'" size="small" type="warning" :icon="RefreshRight" @click="reloadAfterConflict">载入最新</el-button>
      <el-button size="small" type="primary" :loading="editor.saving" :disabled="!editor.dirty" @click="manualSave">保存</el-button>
    </header>

    <main>
      <!-- 左侧：组件列表（上）+ 图层列表（下） -->
      <section class="left" :class="{ inactive: !leftList }">
        <ComponentPalette />
        <LayerPanel />
      </section>
      <button class="show-list left-btn" :title="leftList ? '收起面板' : '展开面板'" @click="leftList = !leftList">
        <el-icon :size="12"><CaretLeft v-if="leftList" /><CaretRight v-else /></el-icon>
      </button>

      <!-- 中间画布 -->
      <section class="center" :style="rightList ? undefined : 'margin-right:10px'">
        <PageTabs />
        <div class="content">
          <div v-if="loading" class="loading-block">加载中…</div>
          <div v-else-if="loadError" class="loading-block error">{{ loadError }}</div>
          <CanvasStage v-else />
        </div>
      </section>

      <!-- 右侧属性列表 -->
      <section class="right" :class="{ inactive: !rightList }">
        <PropPanel />
      </section>
      <button class="show-list right-btn" :title="rightList ? '收起面板' : '展开面板'" @click="rightList = !rightList">
        <el-icon :size="12"><CaretRight v-if="rightList" /><CaretLeft v-else /></el-icon>
      </button>
    </main>

    <!-- 运行态预览（M4，engine 驱动） -->
    <PreviewOverlay v-if="previewVisible" @close="previewVisible = false" />

    <!-- 工程数据管理（M3/M5） -->
    <DataDrawer v-if="dataDrawerVisible" @close="dataDrawerVisible = false" />

    <!-- 导入 JSON（参照 visual-drag-demo Toolbar 的导入对话框：textarea + 文件选择） -->
    <el-dialog v-model="importVisible" title="导入 JSON 数据" width="600px" :close-on-click-modal="false">
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="导入将覆盖当前工程的全部内容（页面/组件/数据源），且不可撤销"
        style="margin-bottom: 12px"
      />
      <el-input v-model="importJson" type="textarea" :rows="14" placeholder="粘贴工程 JSON 数据，或点击下方按钮选择 .json 文件" />
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="importVisible = false">取 消</el-button>
          <el-upload action="/" :before-upload="onImportFile" :show-file-list="false" accept="application/json,.json">
            <el-button>选择 JSON 文件</el-button>
          </el-upload>
          <el-button type="primary" @click="confirmImport">确定导入</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.home {
  /* 变量与取值对照 visual-drag-demo src/styles/global.scss :root */
  --main-bg-color: #fff;
  --secondary-bg-color: #f5f5f5;
  --border-color: #dcdfe6;
  --text-color: #606266;
  --actived-text-color: #409eff;
  --actived-bg-color: #ecf5ff;

  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--main-bg-color);
  color: var(--text-color);
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 10px;
  white-space: nowrap;
  overflow-x: auto;
  flex-shrink: 0;
  background: var(--main-bg-color);
  border-bottom: 1px solid var(--border-color);
}

.project-name {
  font-weight: 600;
  margin: 0 8px 0 4px;
  white-space: nowrap;
}

.save-status {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
  background: #f4f4f5;
  margin-right: 12px;
  white-space: nowrap;
}

.save-status.ok { color: #67c23a; }
.save-status.dirty, .save-status.saving { color: #e6a23c; }
.save-status.error { color: #f56c6c; }

.canvas-config {
  margin: 0 10px;
  font-size: 14px;
  color: var(--text-color);
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.canvas-config span {
  margin-right: 4px;
}

.canvas-config input {
  width: 50px;
  outline: none;
  padding: 0 5px;
  border: 1px solid var(--border-color);
  color: #606266;
  height: 24px;
  box-sizing: border-box;
}

main {
  flex: 1;
  min-height: 0;
  position: relative;
  background: var(--secondary-bg-color);
}

.left,
.right {
  position: absolute;
  height: 100%;
  top: 0;
  transition: all 0.3s;
  background: var(--main-bg-color);
  color: var(--text-color);
  z-index: 2;
}

.left {
  left: 0;
  width: 200px;
}

.left > :first-child {
  border-bottom: 1px solid var(--border-color);
}

.left.inactive {
  width: 10px;
  overflow: hidden;
}

.right {
  right: 0;
  width: 288px;
}

.right.inactive {
  width: 10px;
  overflow: hidden;
}

.center {
  margin: 0 288px 0 200px;
  height: 100%;
  display: flex;
  flex-direction: column;
  transition: all 0.3s;
  min-width: 0;
}

.left.inactive ~ .center {
  margin-left: 10px;
}

.content {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.show-list {
  position: absolute;
  z-index: 9;
  top: 40%;
  transition: all 0.3s;
  background: var(--main-bg-color);
  color: var(--text-color);
  border: 1px solid var(--border-color);
  cursor: pointer;
  display: flex;
  align-items: center;
}

.left-btn {
  left: 0;
  margin-left: 200px;
  border-radius: 0 50% 50% 0;
  padding: 12px 4px 12px 2px;
}

.left.inactive ~ .left-btn {
  margin-left: 10px;
}

.right-btn {
  right: 0;
  margin-right: 288px;
  border-radius: 50% 0 0 50%;
  padding: 12px 2px 12px 4px;
}

.right.inactive ~ .right-btn {
  margin-right: 10px;
}

.loading-block {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #909399;
}

.loading-block.error {
  color: #f56c6c;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
}

.dialog-footer > :not(:first-child) {
  margin-left: 10px;
}
</style>
