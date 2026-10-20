<script setup lang="ts">
/**
 * 编辑器布局：顶部控制台工具条（分组）+ 左 200px（组件 65% / 图层 35%，可折叠）
 * + 中间画布区 + 右 288px 属性面板（可折叠）+ 底部读数状态栏。
 * 保存链路：dirtySeq 变更 → 3s 防抖 PUT（G2 乐观锁）；断网失败保内存态，冲突给重载入口。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, ArrowLeft, CaretLeft, CaretRight, Delete, FullScreen, RefreshRight } from '@element-plus/icons-vue'
import { useEditorStore } from '@/stores/editor'
import { exportProject } from '@/api/projects'
import { createShare } from '@/api/shares'
import { downloadJson, fileTimestamp } from '@/utils/download'
import type { ProjectDoc } from '@/types/doc'
import { installKeyboard } from '@/editor/keyboard'
import CanvasStage from '@/editor/canvas/CanvasStage.vue'

/** 画布引用：保存前截取首页缩略图（台账卡片视图） */
const stageRef = ref<InstanceType<typeof CanvasStage>>()
import ThemePicker from '@/components/ThemePicker.vue'
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

// ---- 自动保存（3s 防抖；保存前刷新首页缩略图，失败不阻断保存链路） ----
async function saveWithThumbnail(): Promise<boolean> {
  try {
    const shot = await stageRef.value?.captureThumbnail()
    if (shot) editor.setThumbnail(shot)
  } catch {
    /* 截图失败保留旧缩略图 */
  }
  return editor.save()
}

watch(
  () => editor.dirtySeq,
  () => {
    if (saveTimer) clearTimeout(saveTimer)
    saveTimer = setTimeout(() => void saveWithThumbnail(), 3000)
  },
)

async function backToList(): Promise<void> {
  if (editor.dirty) {
    const ok = await saveWithThumbnail()
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
  saveWithThumbnail().then((ok) => {
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

// ---- 底部状态栏读数（整数像素，避免拖动时小数跳动） ----
const primaryRect = computed(() => {
  const n = editor.primarySelected
  if (!n) return null
  return {
    x: Math.round(n.x),
    y: Math.round(n.y),
    w: Math.round(n.w),
    h: Math.round(n.h),
  }
})

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
    const ok = await saveWithThumbnail()
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
    const ok = await saveWithThumbnail()
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
    <!-- 顶部控制台工具条：按用途分组，分隔线降低视觉噪音 -->
    <header class="toolbar">
      <div class="tb-group tb-project">
        <button class="tb-back ws-ghost-btn" type="button" title="返回工程台账" @click="backToList">
          <el-icon :size="13"><ArrowLeft /></el-icon>
          <span>工程</span>
        </button>
        <span class="project-name" :title="editor.projectName">{{ editor.projectName }}</span>
      </div>

      <span class="tb-sep" aria-hidden="true"></span>

      <div class="tb-group">
        <el-button text size="small" title="粘贴工程 JSON 覆盖当前工程" @click="openImport">导入</el-button>
        <el-button text size="small" title="导出工程 JSON 文件（服务端脱敏）" @click="exportJson">导出</el-button>
      </div>

      <span class="tb-sep" aria-hidden="true"></span>

      <div class="tb-group">
        <el-button text size="small" :disabled="!editor.canUndo()" title="Ctrl+Z" @click="editor.undo()">撤销</el-button>
        <el-button text size="small" :disabled="!editor.canRedo()" title="Ctrl+Shift+Z" @click="editor.redo()">重做</el-button>
      </div>

      <span class="tb-sep" aria-hidden="true"></span>

      <div class="tb-group">
        <el-button text size="small" :disabled="!canGroup" title="Ctrl+G" @click="editor.groupSelection()">组合</el-button>
        <el-button text size="small" :disabled="!canUngroup" title="Ctrl+Shift+G" @click="editor.ungroupSelection()">拆分</el-button>
        <el-button text size="small" :disabled="!hasSelection" title="置顶" @click="editor.orderSelection('front')">置顶</el-button>
        <el-button text size="small" :disabled="!hasSelection" title="上移一层" @click="editor.orderSelection('forward')">上移</el-button>
        <el-button text size="small" :disabled="!hasSelection" title="下移一层" @click="editor.orderSelection('backward')">下移</el-button>
        <el-button text size="small" :disabled="!hasSelection" title="置底" @click="editor.orderSelection('back')">置底</el-button>
        <el-button text size="small" :disabled="!hasSelection" :title="allLocked ? '解锁' : '锁定'" @click="toggleLock">
          {{ allLocked ? '解锁' : '锁定' }}
        </el-button>
        <el-button text size="small" type="danger" :icon="Delete" :disabled="!hasSelection" title="Delete" @click="editor.deleteSelection()">删除</el-button>
        <el-button text size="small" type="danger" :disabled="editor.topLevelNodes.length === 0" title="清空当前页全部组件" @click="clearCanvas">清空画布</el-button>
      </div>

      <span class="tb-sep" aria-hidden="true"></span>

      <div class="tb-group">
        <el-dropdown :disabled="editor.selectedNodes.length < 2" @command="onAlign">
          <el-button text size="small" :disabled="editor.selectedNodes.length < 2">
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
      </div>

      <span class="tb-spacer" />

      <!-- 固定区：数据/预览/分享/缩放/保存始终可见，对象操作区在窄屏内横向滚动 -->
      <div class="tb-fixed">
        <ThemePicker />
        <el-button text size="small" title="数据源 / 变量 / 报警规则" :disabled="!editor.doc" @click="dataDrawerVisible = true">数据</el-button>
        <el-button text size="small" :disabled="!editor.doc" @click="previewVisible = true">预览</el-button>
        <el-button text size="small" :disabled="!editor.doc" title="生成匿名只读分享链接" @click="shareProject">分享</el-button>

        <span class="tb-fixed-sep" aria-hidden="true"></span>

        <span class="zoom-label">缩放</span>
        <input v-model.number="zoomPct" class="zoom-input ws-readout" aria-label="画布缩放百分比" />
        <span class="zoom-unit">%</span>
        <el-button class="fit-btn" text size="small" :icon="FullScreen" title="适应画布" @click="fitView" />

        <el-button v-if="editor.saveError === 'conflict'" size="small" type="warning" plain :icon="RefreshRight" @click="reloadAfterConflict">载入最新</el-button>
        <el-button class="save-btn" size="small" :loading="editor.saving" :disabled="!editor.dirty" @click="manualSave">保存</el-button>
      </div>
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
          <div v-if="loading" class="loading-block">
            <span class="ws-spinner" role="status" aria-label="加载中" />
            <span>正在载入工程…</span>
          </div>
          <div v-else-if="loadError" class="loading-block error">{{ loadError }}</div>
          <CanvasStage v-else ref="stageRef" />
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

    <!-- 底部读数状态栏：编辑定位与视图状态一眼可见 -->
    <footer class="statusbar">
      <span class="sb-save" :class="saveStatus.cls"><i class="led"></i>{{ saveStatus.text }}</span>
      <span class="sb-rule" aria-hidden="true"></span>
      <span class="sb-item">页面<b>{{ editor.currentPage?.name ?? '—' }}</b></span>
      <span class="sb-item">选中<b class="ws-readout">{{ editor.selection.length }}</b></span>
      <span v-if="primaryRect" class="sb-readout sb-rect">
        X {{ primaryRect.x }} · Y {{ primaryRect.y }} · W {{ primaryRect.w }} · H {{ primaryRect.h }}
      </span>
      <span class="sb-spacer" />
      <span class="sb-hint">Ctrl+滚轮缩放 · 空格拖动画布</span>
      <span class="sb-readout sb-zoom">{{ zoomPct }}%</span>
    </footer>

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
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--ws-canvas);
  color: var(--ws-text);
}

/* ---- 顶部控制台工具条 ---- */
.toolbar {
  display: flex;
  align-items: center;
  gap: 2px;
  height: var(--ws-topbar-h);
  padding: 0 10px;
  flex-shrink: 0;
  white-space: nowrap;
  overflow-x: auto;
  overflow-y: hidden;
  background: var(--ws-ink);
  color: var(--ws-text-inverse);
  border-bottom: 1px solid var(--ws-ink-edge);
}

.toolbar::-webkit-scrollbar {
  height: 4px;
}

.toolbar::-webkit-scrollbar-thumb {
  background: var(--ws-inv-line);
  border: none;
}

.tb-group {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}

.tb-sep {
  width: 1px;
  height: 18px;
  margin: 0 4px;
  background: var(--ws-inv-line);
  flex-shrink: 0;
}

.tb-spacer {
  flex: 1;
  min-width: 12px;
}

/* 返回按钮外观走全局 .ws-ghost-btn */

.tb-project {
  gap: 8px;
  margin-right: 4px;
}

.project-name {
  max-width: 172px;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 13px;
  font-weight: 600;
  color: var(--ws-inv-88);
}

/* 工具条内按钮：深底幽灵按钮 */
.toolbar :deep(.el-button.is-text) {
  color: var(--ws-inv-75);
  padding-left: 5px;
  padding-right: 5px;
}

.toolbar :deep(.el-button.is-text:hover) {
  color: #fff;
  background: var(--ws-inv-hover);
}

.toolbar :deep(.el-button.is-text.is-disabled) {
  color: var(--ws-inv-42);
  background: transparent;
}

.toolbar :deep(.el-button.is-text.el-button--danger) {
  color: var(--ws-alert-bright);
}

.toolbar :deep(.el-button.is-text.el-button--danger:hover) {
  color: #fff;
  background: var(--ws-alert-a16);
}

.toolbar :deep(.el-button--warning.is-plain) {
  --el-button-text-color: var(--ws-warn-bright);
  --el-button-bg-color: var(--ws-warn-a14);
  --el-button-border-color: var(--ws-warn-line);
  --el-button-hover-bg-color: var(--ws-warn-a28);
  --el-button-hover-border-color: var(--ws-warn-bright);
  --el-button-hover-text-color: #fff;
}

/* 缩放读数 */
.zoom-label {
  margin-left: 2px;
  font-size: 11px;
  color: var(--ws-inv-42);
}

.zoom-input {
  width: 48px;
  height: 24px;
  padding: 0 4px;
  border: 1px solid var(--ws-inv-line);
  border-radius: var(--ws-radius);
  background: rgba(8, 16, 24, 0.35);
  color: var(--ws-inv-88);
  font-size: 12px;
  text-align: right;
  outline: none;
}

.zoom-input:focus {
  border-color: var(--ws-signal-bright);
}

.zoom-unit {
  font-size: 11px;
  color: var(--ws-inv-42);
}

/* 保存区：横向溢出时始终固定在右侧可见，左侧渐隐遮住滚动内容 */
.tb-fixed {
  position: sticky;
  right: 0;
  z-index: 3;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  padding-left: 12px;
  background: var(--ws-ink);
}

.tb-fixed-sep {
  width: 1px;
  height: 18px;
  margin: 0 3px;
  background: var(--ws-inv-line);
  flex-shrink: 0;
}

.tb-fixed::before {
  content: '';
  position: absolute;
  left: -16px;
  top: 0;
  bottom: 0;
  width: 16px;
  background: linear-gradient(90deg, transparent, var(--ws-ink));
  pointer-events: none;
}

/* 保存：实体白色按键，控制台质感 */
.save-btn {
  --el-button-bg-color: var(--ws-text-inverse);
  --el-button-border-color: var(--ws-text-inverse);
  --el-button-text-color: var(--ws-ink);
  --el-button-hover-bg-color: #ffffff;
  --el-button-hover-border-color: #ffffff;
  --el-button-hover-text-color: var(--ws-ink);
  --el-button-active-bg-color: var(--ws-inverse-press);
  --el-button-active-border-color: var(--ws-inverse-press);
  --el-button-disabled-bg-color: var(--ws-inv-line);
  --el-button-disabled-border-color: transparent;
  --el-button-disabled-text-color: var(--ws-inv-60);
  font-weight: 600;
  letter-spacing: 0.08em;
}

/* ---- 工作区 ---- */
main {
  flex: 1;
  min-height: 0;
  position: relative;
  background: var(--ws-canvas);
}

.left,
.right {
  position: absolute;
  top: 0;
  height: 100%;
  z-index: 2;
  background: var(--ws-panel);
  color: var(--ws-text);
  display: flex;
  flex-direction: column;
  transition: width 0.25s ease;
}

.left {
  left: 0;
  width: 200px;
  border-right: 1px solid var(--ws-steel-3);
}

.left.inactive {
  width: 10px;
  overflow: hidden;
}

.right {
  right: 0;
  width: 288px;
  border-left: 1px solid var(--ws-steel-3);
}

.right.inactive {
  width: 10px;
  overflow: hidden;
}

.right :deep(.attr-container) {
  height: 100%;
}

.center {
  margin: 0 288px 0 200px;
  height: 100%;
  display: flex;
  flex-direction: column;
  transition: margin 0.25s ease;
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

/* 面板折叠钮：方形标签页耳朵 */
.show-list {
  position: absolute;
  z-index: 9;
  top: 38%;
  width: 14px;
  height: 54px;
  padding: 0;
  border: 1px solid var(--ws-steel-3);
  background: var(--ws-panel);
  color: var(--ws-text-3);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: margin 0.25s ease;
}

.show-list:hover {
  color: var(--ws-signal);
  background: var(--ws-signal-soft);
}

.left-btn {
  left: 0;
  margin-left: 200px;
  border-left: none;
  border-radius: 0 2px 2px 0;
}

.left.inactive ~ .left-btn {
  margin-left: 10px;
}

.right-btn {
  right: 0;
  margin-right: 288px;
  border-right: none;
  border-radius: 2px 0 0 2px;
}

.right.inactive ~ .right-btn {
  margin-right: 10px;
}

.loading-block {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--ws-text-3);
  font-size: 13px;
}

.loading-block.error {
  color: var(--ws-alert);
}

/* ---- 底部读数状态栏 ---- */
.statusbar {
  height: var(--ws-statusbar-h);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 0 12px;
  background: var(--ws-ink);
  color: var(--ws-inv-60);
  font-size: 11px;
  overflow: hidden;
}

.sb-save {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
  color: var(--ws-inv-60);
}

.sb-save .led {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}

.sb-save.ok { color: var(--ws-ok-bright); }
.sb-save.dirty,
.sb-save.saving { color: var(--ws-warn-bright); }
.sb-save.error { color: var(--ws-alert-bright); }

.sb-rule {
  width: 1px;
  height: 12px;
  flex-shrink: 0;
  background: var(--ws-inv-line);
}

.sb-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
}

.sb-item b {
  font-weight: 500;
  color: var(--ws-inv-88);
}

.sb-rect {
  color: var(--ws-inv-42);
  white-space: nowrap;
}

.sb-spacer {
  flex: 1;
}

.sb-hint {
  white-space: nowrap;
  color: var(--ws-inv-42);
}

.sb-zoom {
  min-width: 38px;
  text-align: right;
  color: var(--ws-signal-bright);
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
}

.dialog-footer > :not(:first-child) {
  margin-left: 10px;
}

@media (max-width: 900px) {
  .sb-hint {
    display: none;
  }
}

/* 窄屏收窄固定区：保留配色 / 数据 / 预览 / 分享 / 保存，隐藏缩放读数 */
@media (max-width: 720px) {
  .zoom-label,
  .zoom-unit,
  .zoom-input,
  .fit-btn {
    display: none;
  }

  .tb-fixed {
    gap: 4px;
    padding-left: 8px;
  }

  .sb-rect {
    display: none;
  }
}
</style>
