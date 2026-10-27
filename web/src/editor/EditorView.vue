<script setup lang="ts">
/**
 * 编辑器布局：顶部控制台工具条（分组）+ 左 200px（组件 65% / 图层 35%，可折叠）
 * + 中间画布区 + 右 288px 属性面板（可折叠）+ 底部读数状态栏。
 * 保存链路：dirtySeq 变更 → 3s 防抖 PUT（G2 乐观锁）；断网失败保内存态，冲突给重载入口。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Aim,
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  Bottom,
  CaretLeft,
  CaretRight,
  Delete,
  FolderOpened,
  Lock,
  RefreshLeft,
  RefreshRight,
  Top,
  Unlock,
} from '@element-plus/icons-vue'
import { useEditorStore } from '@/stores/editor'
import { exportProject } from '@/api/projects'
import ShareDialog from '@/editor/ShareDialog.vue'
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
const shareVisible = ref(false)

// ---- 左侧栏上下分区高度（组件库 / 图层），拖动分隔条调整并本地记忆 ----

const PALETTE_H_KEY = 'webscada_editor_palette_h'
const paletteH = ref<number | null>(readStoredPaletteH())

function readStoredPaletteH(): number | null {
  const raw = Number(localStorage.getItem(PALETTE_H_KEY))
  return Number.isFinite(raw) && raw > 0 ? raw : null
}

const leftStyle = computed(() => (paletteH.value ? { '--palette-h': `${paletteH.value}px` } : {}))

/** 分隔条拖动：仅改组件库高度，图层占剩余空间；下限 160px / 图层下限 140px */
function onSplitDown(e: PointerEvent): void {
  const handle = e.currentTarget as HTMLElement
  const left = handle.parentElement
  if (!left) return
  handle.setPointerCapture(e.pointerId)
  const startY = e.clientY
  const startH = left.querySelector('.component-panel')?.getBoundingClientRect().height ?? 0
  const total = left.getBoundingClientRect().height

  const onMove = (ev: PointerEvent): void => {
    const next = startH + (ev.clientY - startY)
    paletteH.value = Math.round(Math.min(Math.max(next, 160), Math.max(total - 140, 160)))
  }
  const onUp = (): void => {
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
    if (paletteH.value) localStorage.setItem(PALETTE_H_KEY, String(paletteH.value))
  }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
}

let uninstallKeyboard: (() => void) | null = null
let saveTimer: ReturnType<typeof setTimeout> | null = null

onMounted(async () => {
  // 覆盖层（预览/数据抽屉/帮助/导入）打开时画布快捷键整体让位（否则 Delete 会在看不见的画布上删组件）
  uninstallKeyboard = installKeyboard(
    editor,
    () => previewVisible.value || dataDrawerVisible.value || helpVisible.value || importVisible.value,
  )
  window.addEventListener('ws:help', openHelp)
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
  window.removeEventListener('ws:help', openHelp)
  if (saveTimer) clearTimeout(saveTimer)
})

// ---- 快捷键帮助（? 键 / 状态栏提示可点开） ----

const helpVisible = ref(false)

function openHelp(): void {
  helpVisible.value = true
}

const SHORTCUTS: { group: string; items: [string, string][] }[] = [
  {
    group: '基础',
    items: [
      ['Ctrl + Z / Ctrl + Shift + Z', '撤销 / 重做'],
      ['Ctrl + A', '全选当前页组件'],
      ['Delete / Backspace', '删除选中'],
      ['Ctrl + C / X / V', '复制 / 剪切 / 粘贴（阶梯偏移）'],
      ['Ctrl + D', '原地复制一份'],
      ['Ctrl + G / Ctrl + Shift + G', '组合 / 拆分'],
      ['?（Shift + /）', '打开本帮助'],
    ],
  },
  {
    group: '画布视图',
    items: [
      ['Ctrl + 滚轮', '以光标为锚缩放（25%–400%）'],
      ['滚轮 / 触控板双指', '平移画布（Shift = 水平）'],
      ['空格 + 拖动 / 中键拖动', '平移画布'],
      ['Ctrl + 0 / Ctrl + 1', '缩放 100% / 适应画布'],
    ],
  },
  {
    group: '编辑组件',
    items: [
      ['拖动（贴边自动平移）', '移动组件，与其他组件/画布边吸附对齐'],
      ['Alt + 拖动', '复制一份再拖（原件留在原地）'],
      ['方向键 / Shift + 方向键', '微调 1px / 10px'],
      ['双击文本', '行内编辑文字'],
      ['双击组', '进入组内编辑（Esc / 空白单击退出）'],
      ['拖动旋转柄', '旋转，近 15° 倍数自动吸附'],
      ['Shift + 拖缩放柄', '锁定宽高比缩放'],
    ],
  },
]

// ---- 自动保存（3s 防抖；保存前刷新首页缩略图，失败不阻断保存链路） ----

/** 缩略图截取节流：html2canvas 整页渲染会占用主线程（连续编辑时每次自动保存都截 = 周期性卡顿），
 *  自动保存路径最快每 60s 截一次；手动保存/导出/分享/离开走 force 立即刷新 */
const THUMB_MIN_INTERVAL_MS = 60_000
let lastThumbAt = 0

async function saveWithThumbnail(force = false): Promise<boolean> {
  // 截图是异步的：期间若自动保存定时器先触发，会先把「无缩略图」的 doc 落库，
  // 随后本次 save() 因 dirty 已清而直接返回——缩略图永远进不了库（台账空图的根因之一）
  if (saveTimer) {
    clearTimeout(saveTimer)
    saveTimer = null
  }
  if (force || Date.now() - lastThumbAt >= THUMB_MIN_INTERVAL_MS) {
    lastThumbAt = Date.now()
    try {
      const shot = await stageRef.value?.captureThumbnail()
      if (shot) editor.setThumbnail(shot)
    } catch {
      /* 截图失败保留旧缩略图 */
    }
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
    const ok = await saveWithThumbnail(true)
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
  saveWithThumbnail(true).then((ok) => {
    if (ok) ElMessage.success('已保存')
  })
}

/** 打开实时数据仿真台：仿真读的是服务端已保存版本，有脏改动先保存，避免仿真旧画面 */
async function openSimulator(): Promise<void> {
  if (!editor.projectId) return
  if (editor.dirty) {
    const ok = await saveWithThumbnail(true)
    if (!ok) ElMessage.warning('保存未成功，将以服务端已保存版本进行仿真')
  }
  void router.push({ path: '/simulator', query: { project: editor.projectId } })
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
  if (editor.saveError === 'server') return { text: '保存被服务端拒绝（见提示）', cls: 'error' }
  if (editor.dirty) return { text: '未保存（自动保存中）', cls: 'dirty' }
  return { text: '已保存', cls: 'ok' }
})

// ---- 状态栏活信号：连接指示（navigator.onLine）与页面尺寸读数 ----

const online = ref(navigator.onLine)

function syncOnline(): void {
  online.value = navigator.onLine
}

onMounted(() => {
  window.addEventListener('online', syncOnline)
  window.addEventListener('offline', syncOnline)
  window.addEventListener('resize', syncNarrow)
})
onBeforeUnmount(() => {
  window.removeEventListener('online', syncOnline)
  window.removeEventListener('offline', syncOnline)
  window.removeEventListener('resize', syncNarrow)
})

/** 窄屏（手机/平板竖屏）编辑器不可用：明确拦截，别给用户一个坏掉的界面 */
const narrowScreen = ref(typeof window !== 'undefined' && window.innerWidth < 1024)
function syncNarrow(): void {
  narrowScreen.value = window.innerWidth < 1024
}

function backToProjects(): void {
  router.push('/projects')
}

const pageSize = computed(() => {
  const s = editor.currentPage?.screen
  return s ? `${s.designWidth} × ${s.designHeight}` : '—'
})

// ---- 工具栏状态 ----
const hasSelection = computed(() => editor.selection.length > 0)
const canGroup = computed(() => editor.selectedNodes.length >= 2 && editor.selectedNodes.every((n) => !n.locked))
const canUngroup = computed(() => editor.selectedNodes.some((n) => n.type === 'group' && !n.locked))
const allLocked = computed(() => hasSelection.value && editor.selectedNodes.every((n) => n.locked))

function toggleLock(): void {
  editor.selectedNodes.forEach((n) => editor.updateNode(n.id, { locked: !allLocked.value }))
}

const zoomPct = computed(() => Math.round(editor.zoom * 100))

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
    const ok = await saveWithThumbnail(true)
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

/** 文件菜单：导入 / 导出 / 清空当前页（破坏性操作收进菜单，工具栏只留高频命令） */
function onFileCommand(cmd: string): void {
  if (cmd === 'import') openImport()
  else if (cmd === 'export') void exportJson()
  else if (cmd === 'clear') void clearCanvas()
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

// ---- 分享（M6 / 2026-10-26 重做为发布管理对话框）----

async function shareProject(): Promise<void> {
  // 先保存，保证分享快照包含最新修改
  if (editor.dirty) {
    const ok = await saveWithThumbnail(true)
    if (!ok) {
      ElMessage.warning('本地有未保存修改且保存失败，请先处理再分享')
      return
    }
  }
  shareVisible.value = true
}
</script>

<template>
  <div class="home">
    <!-- 窄屏拦截：390px 下画布会被左右面板挤到不可见，直接给明确指引 -->
    <div v-if="narrowScreen" class="narrow-block">
      <p class="nb-title">请使用桌面浏览器编辑</p>
      <p class="nb-desc">编辑器需要至少 1024px 宽度。手机端可以查看已分享的大屏画面。</p>
      <el-button type="primary" @click="backToProjects">返回工程台账</el-button>
    </div>

    <!-- 顶部控制台工具条：工程标识 | 文件 | 历史 | 结构 | 层级 | 视图 | 交付，
         高频命令用图标位 + 悬浮说明，破坏性命令收进「文件」菜单 -->
    <header class="toolbar">
      <div class="tb-group tb-project">
        <button class="tb-back ws-ghost-btn" type="button" title="返回工程台账" @click="backToList">
          <el-icon :size="13"><ArrowLeft /></el-icon>
          <span>工程</span>
        </button>
        <span class="project-name" :title="editor.projectName">{{ editor.projectName }}</span>
        <span class="tb-dirty" :class="saveStatus.cls" :title="saveStatus.text" aria-hidden="true"></span>
      </div>

      <span class="tb-sep" aria-hidden="true"></span>

      <div class="tb-group">
        <el-dropdown trigger="click" placement="bottom-start" @command="onFileCommand">
          <button class="tb-btn" type="button" title="导入 / 导出 / 清空当前页">
            <el-icon :size="14"><FolderOpened /></el-icon>
            <span>文件</span>
            <el-icon :size="10" class="tb-caret"><ArrowDown /></el-icon>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="import">导入 JSON…</el-dropdown-item>
              <el-dropdown-item command="export">导出 JSON…</el-dropdown-item>
              <el-dropdown-item command="clear" divided :disabled="editor.topLevelNodes.length === 0">清空当前页…</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>

      <span class="tb-sep" aria-hidden="true"></span>

      <div class="tb-group">
        <button class="tb-btn is-icon" type="button" :disabled="!editor.canUndo()" title="撤销（Ctrl+Z）" @click="editor.undo()">
          <el-icon :size="15"><RefreshLeft /></el-icon>
        </button>
        <button class="tb-btn is-icon" type="button" :disabled="!editor.canRedo()" title="重做（Ctrl+Shift+Z）" @click="editor.redo()">
          <el-icon :size="15"><RefreshRight /></el-icon>
        </button>
      </div>

      <span class="tb-sep" aria-hidden="true"></span>

      <div class="tb-group">
        <button class="tb-btn" type="button" :disabled="!canGroup" title="组合选中组件（Ctrl+G）" @click="editor.groupSelection()">组合</button>
        <button class="tb-btn" type="button" :disabled="!canUngroup" title="拆散组合（Ctrl+Shift+G）" @click="editor.ungroupSelection()">拆分</button>
        <el-dropdown trigger="click" :disabled="editor.selectedNodes.length < 2" @command="onAlign">
          <button class="tb-btn" type="button" :disabled="editor.selectedNodes.length < 2" title="对齐 / 分布（选中 ≥2 个）">
            <el-icon :size="13"><Aim /></el-icon>
            <span>对齐</span>
            <el-icon :size="10" class="tb-caret"><ArrowDown /></el-icon>
          </button>
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

      <span class="tb-sep" aria-hidden="true"></span>

      <div class="tb-group">
        <button class="tb-btn is-icon" type="button" :disabled="!hasSelection" title="置顶" @click="editor.orderSelection('front')">
          <el-icon :size="15"><Top /></el-icon>
        </button>
        <button class="tb-btn is-icon" type="button" :disabled="!hasSelection" title="上移一层" @click="editor.orderSelection('forward')">
          <el-icon :size="15"><ArrowUp /></el-icon>
        </button>
        <button class="tb-btn is-icon" type="button" :disabled="!hasSelection" title="下移一层" @click="editor.orderSelection('backward')">
          <el-icon :size="15"><ArrowDown /></el-icon>
        </button>
        <button class="tb-btn is-icon" type="button" :disabled="!hasSelection" title="置底" @click="editor.orderSelection('back')">
          <el-icon :size="15"><Bottom /></el-icon>
        </button>
      </div>

      <div class="tb-group tb-group-tail">
        <button class="tb-btn is-icon" type="button" :disabled="!hasSelection" :class="{ 'is-on': allLocked }" :title="allLocked ? '解锁' : '锁定'" @click="toggleLock">
          <el-icon :size="15"><Unlock v-if="allLocked" /><Lock v-else /></el-icon>
        </button>
        <button class="tb-btn is-icon is-danger" type="button" :disabled="!hasSelection" title="删除（Delete）" @click="editor.deleteSelection()">
          <el-icon :size="15"><Delete /></el-icon>
        </button>
      </div>

      <span class="tb-spacer" />

      <!-- 固定区：配色/数据/预览/分享/保存始终可见，左侧命令区在窄屏内横向滚动 -->
      <div class="tb-fixed">
        <ThemePicker />
        <span class="tb-fixed-sep" aria-hidden="true"></span>
        <button class="tb-btn" type="button" title="数据源 / 变量 / 报警规则" :disabled="!editor.doc" @click="dataDrawerVisible = true">数据</button>
        <button class="tb-btn" type="button" :disabled="!editor.doc" @click="previewVisible = true">预览</button>
        <button
          class="tb-btn"
          type="button"
          :disabled="!editor.doc"
          title="实时数据仿真（基于已保存版本，不修改工程）"
          @click="openSimulator"
        >
          仿真
        </button>
        <button class="tb-btn" type="button" :disabled="!editor.doc" title="生成匿名只读分享链接" @click="shareProject">分享</button>

        <span class="tb-fixed-sep" aria-hidden="true"></span>

        <el-button v-if="editor.saveError === 'conflict'" size="small" type="warning" plain :icon="RefreshRight" @click="reloadAfterConflict">载入最新</el-button>
        <el-button class="save-btn" size="small" :loading="editor.saving" :disabled="!editor.dirty" title="立即保存（Ctrl+S）" @click="manualSave">保存</el-button>
      </div>
    </header>

    <main>
      <!-- 左侧：组件列表（上）+ 图层列表（下） -->
      <section class="left" :class="{ inactive: !leftList }" :style="leftStyle">
        <ComponentPalette />
        <div class="left-split" title="拖动调整组件库与图层高度" @pointerdown.prevent="onSplitDown">
          <i aria-hidden="true"></i>
        </div>
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
      <span v-if="editor.lastSavedAt" class="sb-item">保存于<b class="ws-readout">{{ editor.lastSavedAt }}</b></span>
      <span class="sb-rule" aria-hidden="true"></span>
      <span class="sb-item">页面<b>{{ editor.currentPage?.name ?? '—' }}</b></span>
      <span class="sb-item">尺寸<b class="ws-readout">{{ pageSize }}</b></span>
      <span class="sb-item">选中<b class="ws-readout">{{ editor.selection.length }}</b></span>
      <span v-if="primaryRect" class="sb-readout sb-rect">
        X {{ primaryRect.x }} · Y {{ primaryRect.y }} · W {{ primaryRect.w }} · H {{ primaryRect.h }}
      </span>
      <span class="sb-spacer" />
      <button class="sb-hint" type="button" title="快捷键帮助（? 键）" @click="openHelp">Ctrl+滚轮缩放 · 空格拖动画布 · ? 快捷键</button>
      <span class="sb-net" :class="online ? 'on' : 'off'" :title="online ? '连接正常' : '网络已断开'">
        <i class="led"></i>{{ online ? '在线' : '离线' }}
      </span>
      <span class="sb-readout sb-zoom">{{ zoomPct }}%</span>
    </footer>

    <!-- 运行态预览（M4，engine 驱动） -->
    <PreviewOverlay v-if="previewVisible" @close="previewVisible = false" />

    <!-- 工程数据管理（M3/M5） -->
    <DataDrawer v-if="dataDrawerVisible" @close="dataDrawerVisible = false" />

    <!-- 分享与发布管理（2026-10-26）：有效期/刷新快照/撤销/未发布变更提示 -->
    <ShareDialog
      v-model="shareVisible"
      :project-id="editor.projectId"
      :project-name="editor.projectName"
      :project-updated-at="editor.doc?.project?.updatedAt"
    />

    <!-- 快捷键帮助（? 键 / 状态栏入口） -->
    <el-dialog v-model="helpVisible" title="快捷键" width="560px" :close-on-click-modal="true">
      <div class="help-grid">
        <section v-for="sec in SHORTCUTS" :key="sec.group">
          <h4>{{ sec.group }}</h4>
          <div v-for="[key, desc] in sec.items" :key="key" class="help-row">
            <kbd>{{ key }}</kbd>
            <span>{{ desc }}</span>
          </div>
        </section>
      </div>
    </el-dialog>

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
  /* 三栏宽度集中在此，折叠态与中部 margin 都由此推导 */
  --left-w: 236px;
  --right-w: 288px;
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
  gap: 1px;
  height: var(--ws-topbar-h);
  padding: 0 8px;
  flex-shrink: 0;
  white-space: nowrap;
  overflow-x: auto;
  overflow-y: hidden;
  background: linear-gradient(180deg, var(--ws-ink-2), var(--ws-ink) 62%);
  color: var(--ws-text-inverse);
  border-bottom: 1px solid var(--ws-ink-edge);
  box-shadow: 0 1px 0 rgba(255, 255, 255, 0.04) inset;
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
  gap: 1px;
  flex-shrink: 0;
}

.tb-group-tail {
  margin-left: 2px;
}

.tb-sep {
  width: 1px;
  height: 20px;
  margin: 0 7px;
  background: var(--ws-inv-line);
  flex-shrink: 0;
}

/* 工具条按钮：深底幽灵样式，图标位 28×28，文字位自适应；悬浮才浮出边界 */
.tb-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  height: 28px;
  padding: 0 8px;
  border: 1px solid transparent;
  border-radius: var(--ws-radius);
  background: transparent;
  color: var(--ws-inv-75);
  font-family: inherit;
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
  white-space: nowrap;
  transition: background-color var(--ws-duration-fast) var(--ws-ease), border-color var(--ws-duration-fast) var(--ws-ease), color var(--ws-duration-fast) var(--ws-ease);
}

.tb-btn.is-icon {
  width: 28px;
  padding: 0;
}

.tb-btn:hover:not(:disabled) {
  background: var(--ws-inv-hover);
  border-color: var(--ws-inv-line);
  color: #fff;
}

.tb-btn:active:not(:disabled) {
  background: rgba(8, 16, 24, 0.4);
}

.tb-btn:disabled {
  color: var(--ws-inv-42);
  cursor: default;
}

.tb-btn.is-on {
  background: var(--ws-signal-a12);
  border-color: var(--ws-signal-a45);
  color: var(--ws-signal-bright);
}

.tb-btn.is-danger:hover:not(:disabled) {
  background: var(--ws-alert-a16);
  border-color: var(--ws-alert-line);
  color: #fff;
}

.tb-caret {
  opacity: 0.5;
  margin-left: -1px;
}

.tb-spacer {
  flex: 1;
  min-width: 12px;
}

/* 返回按钮外观走全局 .ws-ghost-btn */

.tb-project {
  gap: 9px;
  margin-right: 2px;
}

.project-name {
  max-width: 208px;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.01em;
  color: var(--ws-inv-88);
}

/* 工程名右侧的保存态小灯：不抢视觉，但状态随时可读 */
.tb-dirty {
  width: 6px;
  height: 6px;
  margin-left: -3px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--ws-ok-bright);
  box-shadow: 0 0 0 2px rgba(125, 220, 147, 0.16);
}

.tb-dirty.dirty,
.tb-dirty.saving {
  background: var(--ws-warn-bright);
  box-shadow: 0 0 0 2px rgba(245, 194, 91, 0.16);
}

.tb-dirty.saving {
  animation: wsBlink 1s steps(2, jump-none) infinite;
}

.tb-dirty.error {
  background: var(--ws-alert-bright);
  box-shadow: 0 0 0 2px rgba(255, 157, 110, 0.2);
}

.toolbar :deep(.el-button--warning.is-plain) {
  --el-button-text-color: var(--ws-warn-bright);
  --el-button-bg-color: var(--ws-warn-a14);
  --el-button-border-color: var(--ws-warn-line);
  --el-button-hover-bg-color: var(--ws-warn-a28);
  --el-button-hover-border-color: var(--ws-warn-bright);
  --el-button-hover-text-color: #fff;
}

/* 保存区：横向溢出时始终固定在右侧可见，左侧渐隐遮住滚动内容 */
.tb-fixed {
  position: sticky;
  right: 0;
  z-index: 3;
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  padding-left: 14px;
  background: linear-gradient(180deg, var(--ws-ink-2), var(--ws-ink) 62%);
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
  transition: width var(--ws-duration-slow) var(--ws-ease);
}

.left {
  left: 0;
  width: var(--left-w);
  border-right: 1px solid var(--ws-steel-3);
  box-shadow: var(--ws-shadow-panel-left);
}

.left.inactive {
  width: 10px;
  overflow: hidden;
  background: var(--ws-steel-1);
}

/* 收起时内容整体隐藏：只留一道窄轨，避免文字被挤成竖排残条 */
.left.inactive > *,
.right.inactive > * {
  opacity: 0;
  pointer-events: none;
}

/* 组件库 / 图层分隔条：常态一条细线，hover 变信号色并加宽热区 */
.left-split {
  position: relative;
  height: 5px;
  flex-shrink: 0;
  cursor: row-resize;
  background: var(--ws-steel-1);
  border-top: 1px solid var(--ws-steel-2);
  border-bottom: 1px solid var(--ws-steel-2);
}

.left-split i {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 22px;
  height: 2px;
  transform: translate(-50%, -50%);
  border-radius: 1px;
  background: var(--ws-steel-3);
  transition: background-color var(--ws-duration-fast) var(--ws-ease), width var(--ws-duration-fast) var(--ws-ease);
}

.left-split:hover i {
  width: 34px;
  background: var(--ws-signal);
}

.right {
  right: 0;
  width: var(--right-w);
  border-left: 1px solid var(--ws-steel-3);
  box-shadow: var(--ws-shadow-panel-right);
}

.right.inactive {
  width: 10px;
  overflow: hidden;
  background: var(--ws-steel-1);
}

.right :deep(.attr-container) {
  height: 100%;
}

.center {
  margin: 0 var(--right-w) 0 var(--left-w);
  height: 100%;
  display: flex;
  flex-direction: column;
  transition: margin var(--ws-duration-slow) var(--ws-ease);
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
  transition: margin var(--ws-duration-slow) var(--ws-ease);
}

.show-list:hover {
  color: var(--ws-signal);
  background: var(--ws-signal-soft);
}

.left-btn {
  left: 0;
  margin-left: var(--left-w);
  border-left: none;
  border-radius: 0 3px 3px 0;
  box-shadow: 2px 0 6px rgba(20, 33, 46, 0.08);
}

.left.inactive ~ .left-btn {
  margin-left: 10px;
}

.right-btn {
  right: 0;
  margin-right: var(--right-w);
  border-right: none;
  border-radius: 3px 0 0 3px;
  box-shadow: -2px 0 6px rgba(20, 33, 46, 0.08);
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

.sb-net {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
  color: var(--ws-inv-60);
}

.sb-net .led {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}

.sb-net.on {
  color: var(--ws-ok-bright);
}

.sb-net.off {
  color: var(--ws-alert-bright);
}

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
  padding: 2px 6px;
  border: none;
  border-radius: var(--ws-radius);
  background: none;
  color: var(--ws-inv-42);
  font-size: 11px;
  cursor: pointer;
}

.sb-hint:hover {
  color: var(--ws-inv-88);
  background: var(--ws-inv-hover);
}

/* 快捷键帮助表 */
.help-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 18px;
}

.help-grid h4 {
  margin: 0 0 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--ws-text-2);
  border-bottom: 1px solid var(--ws-steel-2);
  padding-bottom: 6px;
}

.help-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 4px 0;
  font-size: 12px;
  color: var(--ws-text-2);
}

.help-row kbd {
  flex-shrink: 0;
  min-width: 130px;
  padding: 1px 6px;
  border: 1px solid var(--ws-steel-3);
  border-radius: 3px;
  background: var(--ws-steel-0);
  color: var(--ws-text);
  font-family: var(--ws-font-mono);
  font-size: 11px;
  text-align: center;
}

.help-row span {
  color: var(--ws-text-3);
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

/* 窄屏拦截层：覆盖整个编辑器，避免把挤坏的界面交给用户 */
.narrow-block {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 24px;
  background: var(--ws-canvas);
  color: var(--ws-text-2);
  text-align: center;
}

.nb-title {
  margin: 0;
  color: var(--ws-text);
  font-size: 18px;
  font-weight: 600;
}

.nb-desc {
  margin: 0 0 8px;
  max-width: 320px;
  line-height: 1.6;
  font-size: 13px;
}

@media (max-width: 900px) {
  .sb-hint {
    display: none;
  }
}

/* 窄屏收窄固定区：保留配色 / 数据 / 预览 / 分享 / 保存，画布读数让位 */
@media (max-width: 720px) {
  .tb-fixed {
    gap: 3px;
    padding-left: 8px;
  }

  .tb-sep {
    margin: 0 4px;
  }

  .sb-rect {
    display: none;
  }
}
</style>
