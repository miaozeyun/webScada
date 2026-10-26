<script setup lang="ts">
/**
 * 实时数据仿真台（工程联调，2026-10-26）。
 *
 * 选一个工程 → 前端构造仿真副本 doc（单一 mock 源，不改库内 doc）→ 右侧 RuntimeStage
 * 本地模式渲染画面 → 本页定时把各信号仿真值经 engine.injectValue 注入值池。
 * 因而画面绑定、报警、虚拟变量级联、反控回环全部按真实运行态链路走，但不触达服务端。
 *
 * 设计取舍：
 * - 暂停 = 停止推进仿真时钟（波形恢复后连续，不跳变）；
 * - 倍速 = 仿真时钟步长倍率（0.5×/1×/2×/5×）；
 * - 面板读数直接取 useRuntimeStore（引擎入池后的工程值），保证「看到的=画面用的」。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh, Search, VideoPause, VideoPlay } from '@element-plus/icons-vue'
import type { EChartsCoreOption } from 'echarts/core'
import { useEditorStore } from '@/stores/editor'
import { getProject, listProjects, type ProjectListItem } from '@/api/projects'
import { useRuntimeStore } from '@/runtime/store'
import type { RuntimeEngine } from '@/runtime/engine'
import { buildSimDoc, formatSimValue, simulateValue, type SimSignal } from '@/utils/simulation'
import type { ProjectDoc } from '@/types/doc'
import RuntimeStage from '@/editor/RuntimeStage.vue'
import EchartsBase from '@/widgets/EchartsBase.vue'
import AppBar from '@/components/AppBar.vue'

const route = useRoute()
const router = useRouter()
const runtime = useRuntimeStore()
const editor = useEditorStore()

// ---------------- 工程 ----------------

const projects = ref<ProjectListItem[]>([])
const projectId = ref('')
const previewTitle = ref('仿真预览')
const loadingProject = ref(false)
const searchingProjects = ref(false)
const loadError = ref('')
/** 当前工程条目：远程搜索换关键字时保证选中项不丢（否则下拉只剩原始 id） */
const currentProjectItem = ref<ProjectListItem | null>(null)

const simDoc = ref<ProjectDoc | null>(null)
const signals = ref<SimSignal[]>([])

/** 拉取工程下拉选项（最多 100 条/页；更多靠工程名远程搜索） */
async function fetchProjectOptions(keyword = ''): Promise<void> {
  try {
    const data = await listProjects({ page: 1, size: 100, keyword: keyword || undefined })
    const items = data.items
    const cur = currentProjectItem.value
    if (cur && !items.some((p) => p.id === cur.id)) items.unshift(cur)
    projects.value = items
  } catch {
    /* 拦截器已提示 */
  }
}

async function loadProjects(): Promise<void> {
  await fetchProjectOptions()
  const fromQuery = typeof route.query.project === 'string' ? route.query.project : ''
  const pick = fromQuery || projects.value[0]?.id || ''
  if (pick) await loadProject(pick)
}

/** 远程搜索（250ms 防抖）：工程台账可能远超单页 100 条 */
let projectSearchTimer: number | null = null
function onSearchProjects(query: string): void {
  if (projectSearchTimer !== null) clearTimeout(projectSearchTimer)
  projectSearchTimer = window.setTimeout(() => {
    projectSearchTimer = null
    searchingProjects.value = true
    void fetchProjectOptions(query.trim()).finally(() => {
      searchingProjects.value = false
    })
  }, 250)
}

async function loadProject(id: string): Promise<void> {
  if (!id) return
  loadingProject.value = true
  loadError.value = ''
  try {
    const detail = await getProject(id)
    if (!detail.doc) throw new Error('该工程没有可用的画面数据')
    const built = buildSimDoc(detail.doc)
    simDoc.value = built.doc
    signals.value = built.signals
    previewTitle.value = `${detail.name} · 仿真预览`
    projectId.value = id
    currentProjectItem.value = detail
    if (!projects.value.some((p) => p.id === id)) projects.value = [detail, ...projects.value]
    resetClock()
    running.value = true
    // 记住选择：刷新页面 / 从编辑器跳转都回到同一工程
    if (route.query.project !== id) void router.replace({ query: { ...route.query, project: id } })
  } catch (err) {
    simDoc.value = null
    signals.value = []
    loadError.value = (err as Error).message || '工程加载失败'
  } finally {
    loadingProject.value = false
  }
}

function onProjectChange(id: string): void {
  void loadProject(id)
}

function reloadProject(): void {
  if (projectId.value) void loadProject(projectId.value)
}

// ---------------- 仿真时钟 ----------------

const TICK_MS = 250
/** 趋势图每秒采一点（4 个 tick），避免 4Hz 重算 ECharts option */
const TREND_EVERY_TICKS = 4
/** 1Hz 采样 × 180 点 = 近 3 分钟滚动窗口 */
const TREND_MAX = 180
/** 趋势图最多同时绘制 8 条线（再多就不可读） */
const TREND_SERIES_LIMIT = 8
/**
 * 单屏最多渲染的信号行。大工程（上千变量）全量渲染会让 4Hz 的读数刷新变成主线程灾难；
 * 超出部分靠搜索缩小范围（全开/全关仍作用于全部信号，不只是可见行）。
 */
const MAX_ROWS = 200
const SPEED_OPTIONS = [0.5, 1, 2, 5] as const

const running = ref(true)
const speed = ref(1)
const elapsedText = ref('00:00')

let timer: number | null = null
let elapsedMs = 0
let tickCount = 0

const stageRef = ref<InstanceType<typeof RuntimeStage> | null>(null)

/** RuntimeStage 通过 defineExpose 暴露引擎；这里窄化取值，避免依赖组件实例的公开类型推导 */
function currentEngine(): RuntimeEngine | null {
  const inst = stageRef.value as unknown as { engine?: RuntimeEngine } | null
  return inst?.engine ?? null
}

function resetClock(): void {
  elapsedMs = 0
  tickCount = 0
  elapsedText.value = '00:00'
  trend.value = {}
  sparkPaths.value = {}
}

function tick(): void {
  if (!running.value || !simDoc.value) return
  // 标签页在后台时不推进仿真（省 CPU/电），回来继续原时钟
  if (document.visibilityState === 'hidden') return
  const eng = currentEngine()
  if (!eng) return
  elapsedMs += TICK_MS * speed.value
  tickCount++
  for (const s of signals.value) {
    if (!s.enabled || s.virtual) continue
    eng.injectValue(s.variableId, simulateValue(s, elapsedMs + s.phaseMs))
  }
  if (tickCount % TREND_EVERY_TICKS === 0) {
    recordTrend()
    updateElapsedText()
  }
}

function updateElapsedText(): void {
  const sec = Math.floor(elapsedMs / 1000)
  const mm = String(Math.floor(sec / 60)).padStart(2, '0')
  const ss = String(sec % 60).padStart(2, '0')
  elapsedText.value = `${mm}:${ss}`
}

function resetSim(): void {
  if (!simDoc.value) return
  // 换 doc 引用 → RuntimeStage watch 重启引擎（画面/报警/历史归零），波形配置保留
  simDoc.value = JSON.parse(JSON.stringify(simDoc.value)) as ProjectDoc
  resetClock()
  running.value = true
}

// ---------------- 趋势 ----------------

const trend = ref<Record<string, [number, number][]>>({})
/** 行内迷你趋势的 SVG points 字符串（1Hz 预计算；渲染期只做查表，避免 4Hz 重渲染时反复拼字符串） */
const sparkPaths = ref<Record<string, string>>({})

function recordTrend(): void {
  const now = Date.now()
  // 主趋势只记图表实际绘制的 ≤8 条：此前「全开」数百信号会每秒复制数百个 180 点数组
  const next: Record<string, [number, number][]> = { ...trend.value }
  for (const s of chartSignals.value) {
    const raw = runtime.values.get(s.variableId)
    if (typeof raw !== 'number' && typeof raw !== 'boolean') continue
    const num = typeof raw === 'number' ? raw : raw ? 1 : 0
    const arr = (next[s.variableId] ?? []).slice(-(TREND_MAX - 1))
    arr.push([now, num])
    next[s.variableId] = arr
  }
  trend.value = next

  const eng = currentEngine()
  if (!eng) return
  const paths: Record<string, string> = {}
  for (const s of visibleSignals.value) {
    if (!s.enabled || s.type === 'string') continue
    const h = eng.historyOf(s.variableId)
    if (h.length > 1) paths[s.variableId] = pathOf(h.slice(-40))
  }
  sparkPaths.value = paths
}

/** 采样序列 → 100×30 viewBox 内的归一化折线 points */
function pathOf(vals: number[]): string {
  let lo = vals[0]
  let hi = vals[0]
  for (const v of vals) {
    if (v < lo) lo = v
    if (v > hi) hi = v
  }
  const span = hi - lo || 1
  let out = ''
  for (let i = 0; i < vals.length; i++) {
    const x = ((i / (vals.length - 1)) * 100).toFixed(2)
    const y = (28 - ((vals[i] - lo) / span) * 26).toFixed(2)
    out += i ? ` ${x},${y}` : `${x},${y}`
  }
  return out
}

const CHART_COLORS = ['#0f766e', '#b45309', '#1d4ed8', '#b91c1c', '#6d28d9', '#047857', '#c2410c', '#0e7490']

const chartSignals = computed(() => signals.value.filter((s) => s.enabled && s.type !== 'string').slice(0, TREND_SERIES_LIMIT))

const chartOption = computed<EChartsCoreOption>(() => ({
  animation: false,
  color: CHART_COLORS,
  grid: { left: 54, right: 18, top: 30, bottom: 26 },
  legend: { top: 0, type: 'scroll', itemWidth: 12, itemHeight: 8, textStyle: { fontSize: 11 } },
  tooltip: { trigger: 'axis', valueFormatter: (v: unknown) => (typeof v === 'number' ? v.toFixed(2) : String(v)) },
  xAxis: {
    type: 'time',
    axisLabel: { formatter: '{HH}:{mm}:{ss}', fontSize: 10, color: '#7b8794' },
    axisLine: { lineStyle: { color: '#d6dde5' } },
  },
  yAxis: {
    type: 'value',
    scale: true,
    axisLabel: { fontSize: 10, color: '#7b8794' },
    splitLine: { lineStyle: { color: '#eef2f6' } },
  },
  series: chartSignals.value.map((s) => ({
    name: `${s.label}${s.unit ? `（${s.unit}）` : ''}`,
    type: 'line',
    showSymbol: false,
    smooth: true,
    lineStyle: { width: 1.5 },
    data: trend.value[s.variableId] ?? [],
  })),
}))

/** 行内迷你趋势：1Hz 预计算的 points（见 recordTrend） */
function sparkPoints(s: SimSignal): string {
  return sparkPaths.value[s.variableId] ?? ''
}

// ---------------- 信号面板 ----------------

const search = ref('')

const filteredSignals = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return signals.value
  return signals.value.filter((s) => s.label.toLowerCase().includes(q) || s.key.toLowerCase().includes(q))
})

const visibleSignals = computed(() => filteredSignals.value.slice(0, MAX_ROWS))
const hiddenCount = computed(() => Math.max(0, filteredSignals.value.length - visibleSignals.value.length))

const baseCount = computed(() => signals.value.filter((s) => !s.virtual).length)
const enabledCount = computed(() => signals.value.filter((s) => !s.virtual && s.enabled).length)
const virtualCount = computed(() => signals.value.filter((s) => s.virtual).length)

function setAllEnabled(v: boolean): void {
  for (const s of signals.value) if (!s.virtual) s.enabled = v
  const n = enabledCount.value
  if (v && n > 200) {
    ElMessage.warning(`已启用 ${n} 个信号，数量较多时画面刷新会变慢（可搜索后逐个关闭）`)
  }
}

function displayValue(s: SimSignal): string {
  return formatSimValue(s, runtime.values.get(s.variableId) as number | boolean | string | undefined)
}

/** 数值输入步长按量程自适应（100 量程用 1，0.5 量程用 0.001） */
function stepFor(s: SimSignal): number {
  const span = Math.abs(s.max - s.min)
  if (span >= 100) return 1
  if (span >= 10) return 0.1
  if (span >= 1) return 0.01
  return 0.001
}

function onWaveChange(s: SimSignal): void {
  if (s.wave !== 'manual') return
  // 切到手动时以当前值为初值，避免画面从 0 跳一下
  const cur = runtime.values.get(s.variableId)
  if (typeof cur === 'number' && s.type === 'number') s.manualNumber = cur
  else if (typeof cur === 'boolean' && s.type === 'boolean') s.manualBool = cur
  else if (typeof cur === 'string' && s.type === 'string') s.manualText = cur
}

function injectNow(s: SimSignal): void {
  const eng = currentEngine()
  if (!eng) {
    ElMessage.warning('仿真预览尚未就绪，请稍候')
    return
  }
  const value = s.type === 'number' ? s.manualNumber : s.type === 'boolean' ? s.manualBool : s.manualText
  eng.injectValue(s.variableId, value)
  recordTrend()
}

// ---------------- 快捷键与导航 ----------------

/** 输入类元素里的按键不劫持（选中输入框时空格是字符/展开下拉） */
function isTypingTarget(e: KeyboardEvent): boolean {
  const el = e.target as HTMLElement | null
  if (!el) return false
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || tag === 'BUTTON' || el.isContentEditable
}

/** 值班/联调常用：空格暂停继续，R 重置（不抢输入框与按钮的原生键盘行为） */
function onKeydown(e: KeyboardEvent): void {
  if (e.defaultPrevented || isTypingTarget(e) || e.ctrlKey || e.metaKey || e.altKey) return
  if (e.code === 'Space') {
    if (!simDoc.value) return
    e.preventDefault()
    running.value = !running.value
  } else if (e.key === 'r' || e.key === 'R') {
    if (simDoc.value) resetSim()
  }
}

function openEditor(): void {
  if (projectId.value) router.push(`/editor/${projectId.value}`)
}

// ---------------- 生命周期 ----------------

onMounted(() => {
  // 仿真台不是编辑器上下文：清掉编辑器残留的 projectId，否则画面内历史图/历史表
  // 会按「上一次编辑的工程」去服务端取数（与当前仿真工程不符）
  editor.projectId = ''
  void loadProjects()
  timer = window.setInterval(tick, TICK_MS)
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
  window.removeEventListener('keydown', onKeydown)
  if (projectSearchTimer !== null) clearTimeout(projectSearchTimer)
})

</script>

<template>
  <div class="sim-page">
    <AppBar scope="实时数据仿真台">
      <template #actions>
        <button class="ws-ghost-btn" type="button" @click="router.push('/projects')">返回台账</button>
        <button class="ws-ghost-btn" type="button" :disabled="!projectId" @click="openEditor">在编辑器中打开</button>
      </template>
    </AppBar>

    <div class="sim-toolbar">
      <div class="tb-left">
        <span class="tb-label">工程</span>
        <el-select
          v-model="projectId"
          class="project-select"
          filterable
          remote
          :remote-method="onSearchProjects"
          placeholder="搜索 / 选择工程"
          :loading="loadingProject || searchingProjects"
          @change="onProjectChange"
        >
          <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
        <el-button size="small" :loading="loadingProject" @click="reloadProject">重新载入</el-button>
        <span class="status-chip" :class="{ 'is-live': running, 'is-idle': !running }">
          <span class="dot" aria-hidden="true"></span>
          {{ running ? '仿真中' : '已暂停' }}
          <span class="elapsed ws-readout">{{ elapsedText }}</span>
        </span>
        <span v-if="runtime.activeAlarmCount" class="alarm-chip" title="当前激活报警数">⚠ {{ runtime.activeAlarmCount }} 条报警</span>
      </div>
      <div class="tb-right">
        <el-button
          size="small"
          :icon="running ? VideoPause : VideoPlay"
          :disabled="!simDoc"
          title="暂停 / 继续仿真时钟（快捷键：空格）"
          @click="running = !running"
        >
          {{ running ? '暂停' : '继续' }}
        </el-button>
        <span class="tb-label">倍速</span>
        <el-select v-model="speed" size="small" class="speed-select">
          <el-option v-for="v in SPEED_OPTIONS" :key="v" :label="`${v}×`" :value="v" />
        </el-select>
        <el-button size="small" :icon="Refresh" :disabled="!simDoc" title="重置仿真时钟与画面（快捷键：R）" @click="resetSim">
          重置
        </el-button>
      </div>
    </div>

    <main class="sim-body">
      <aside class="signal-panel">
        <div class="panel-head">
          <span class="panel-title">
            信号 <span class="count ws-readout">{{ enabledCount }}/{{ baseCount }}</span>
            <span v-if="virtualCount" class="count">· 虚拟 {{ virtualCount }}</span>
          </span>
          <div class="panel-actions">
            <el-button link size="small" @click="setAllEnabled(true)">全开</el-button>
            <el-button link size="small" @click="setAllEnabled(false)">全关</el-button>
          </div>
        </div>
        <div class="panel-search">
          <el-input v-model="search" size="small" clearable placeholder="搜索变量名 / key" :prefix-icon="Search" />
        </div>
        <div class="signal-list">
          <article v-for="s in visibleSignals" :key="s.variableId" class="signal-row" :class="{ 'is-off': !s.enabled && !s.virtual }">
            <div class="row-head">
              <el-checkbox v-model="s.enabled" size="small" :disabled="s.virtual" />
              <span class="row-label" :title="`${s.label}（${s.key}）`">{{ s.label }}</span>
              <span v-if="s.virtual" class="row-tag">表达式</span>
              <span class="row-unit">{{ s.unit || '' }}</span>
              <span class="row-value ws-readout">{{ displayValue(s) }}</span>
            </div>

            <div v-if="s.enabled && !s.virtual" class="row-controls">
              <el-select
                v-model="s.wave"
                size="small"
                class="wave-select"
                :disabled="s.type === 'string'"
                :title="s.type === 'string' ? '文本量只支持手动注入' : '仿真波形'"
                @change="onWaveChange(s)"
              >
                <el-option label="正弦" value="sine" />
                <el-option label="斜坡" value="ramp" />
                <el-option label="随机" value="random" />
                <el-option label="方波" value="square" />
                <el-option label="手动" value="manual" />
              </el-select>
              <template v-if="s.wave !== 'manual' && s.type === 'number'">
                <el-input-number v-model="s.min" size="small" :step="stepFor(s)" controls-position="right" class="num" />
                <span class="tilde">~</span>
                <el-input-number v-model="s.max" size="small" :step="stepFor(s)" controls-position="right" class="num" />
                <span class="lbl">周期</span>
                <el-input-number v-model="s.periodSec" size="small" :min="1" :max="3600" :step="1" controls-position="right" class="num-sm" />
                <span class="lbl">s</span>
              </template>
              <template v-else>
                <el-input-number v-if="s.type === 'number'" v-model="s.manualNumber" size="small" :step="stepFor(s)" controls-position="right" class="num" />
                <el-switch v-else-if="s.type === 'boolean'" v-model="s.manualBool" size="small" />
                <el-input v-else v-model="s.manualText" size="small" class="text-input" placeholder="文本值" />
                <el-button size="small" @click="injectNow(s)">注入</el-button>
              </template>
            </div>

            <div v-if="s.enabled || s.virtual" class="row-spark">
              <svg viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true">
                <polyline :points="sparkPoints(s)" />
              </svg>
            </div>
          </article>

          <p v-if="!filteredSignals.length" class="panel-empty">
            {{ simDoc ? '没有匹配的信号' : '选择工程后显示变量列表' }}
          </p>
          <p v-else-if="hiddenCount" class="panel-more">
            另有 {{ hiddenCount }} 条未显示（单屏最多 {{ MAX_ROWS }} 条），输入关键字缩小范围
          </p>
        </div>
      </aside>

      <section class="workspace">
        <div class="preview-box">
          <RuntimeStage v-if="simDoc" ref="stageRef" :doc="simDoc" :title="previewTitle" docked quiet />
          <div v-if="loadingProject" class="preview-loading">
            <span class="ws-spinner" role="status" aria-label="加载中" />
            <span>正在载入工程…</span>
          </div>
          <div v-else class="preview-empty">
            <svg viewBox="0 0 48 48" aria-hidden="true">
              <rect x="5.5" y="9.5" width="37" height="29" />
              <path d="M5.5 17.5 H42.5 M11.5 13.5 H13 M15.5 13.5 H17" />
              <path d="M12 30 L18 30 L21 22 L26 35 L30 27 L36 27" />
            </svg>
            <p class="empty-title">选择一个工程</p>
            <p class="empty-desc">{{ loadError || '载入后右侧会实时驱动画面、报警与趋势曲线。' }}</p>
          </div>
        </div>

        <div class="trend-box">
          <div class="trend-head">
            <span class="panel-title">实时趋势</span>
            <span class="trend-hint">近 3 分钟 · 最多 {{ TREND_SERIES_LIMIT }} 条已启用数值信号</span>
          </div>
          <EchartsBase class="trend-chart" :option="chartOption" />
        </div>
      </section>
    </main>
  </div>
</template>

<style scoped>
.sim-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--ws-canvas);
  overflow: hidden;
}

/* ---- 工具条 ---- */
.sim-toolbar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 9px 16px;
  border-bottom: 1px solid var(--ws-steel-3);
  background: var(--ws-panel);
}

.tb-left,
.tb-right {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.tb-label {
  font-size: 12px;
  color: var(--ws-text-3);
  white-space: nowrap;
}

.project-select {
  width: 260px;
}

.speed-select {
  width: 84px;
}

.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 9px;
  border: 1px solid var(--ws-steel-3);
  border-radius: 999px;
  font-size: 12px;
  color: var(--ws-text-2);
  white-space: nowrap;
}

.status-chip .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ws-text-3);
}

.status-chip.is-live {
  border-color: var(--ws-signal);
  color: var(--ws-signal);
  background: var(--ws-signal-soft);
}

.status-chip.is-live .dot {
  background: var(--ws-signal);
  animation: pulse 1.4s ease-in-out infinite;
}

.status-chip .elapsed {
  font-size: 11px;
  color: var(--ws-text-3);
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.25; }
}

@media (prefers-reduced-motion: reduce) {
  .status-chip.is-live .dot { animation: none; }
}

.alarm-chip {
  padding: 2px 9px;
  border: 1px solid var(--ws-alert-line, #c2410c);
  border-radius: 999px;
  background: var(--ws-alert-a16, rgba(194, 65, 12, 0.12));
  color: var(--ws-alert-bright, #b45309);
  font-size: 12px;
  white-space: nowrap;
}

/* ---- 主体 ---- */
.sim-body {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 12px;
  padding: 12px 16px 16px;
}

.signal-panel {
  width: 420px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--ws-panel);
  border: 1px solid var(--ws-steel-3);
  box-shadow: var(--ws-shadow-panel);
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--ws-steel-2);
}

.panel-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--ws-text-2);
}

.panel-title .count {
  margin-left: 4px;
  font-size: 11px;
  font-weight: 400;
  color: var(--ws-text-3);
}

.panel-actions {
  display: flex;
  gap: 4px;
}

.panel-search {
  padding: 8px 12px;
  border-bottom: 1px solid var(--ws-steel-2);
}

.signal-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.signal-row {
  padding: 7px 12px 8px;
  border-bottom: 1px solid var(--ws-steel-2);
}

.signal-row:hover {
  background: var(--ws-steel-0);
}

.signal-row.is-off {
  opacity: 0.55;
}

.row-head {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.row-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ws-text);
}

.row-tag {
  flex-shrink: 0;
  padding: 0 5px;
  border: 1px solid var(--ws-steel-3);
  border-radius: 2px;
  font-size: 10px;
  line-height: 15px;
  color: var(--ws-text-3);
}

.row-unit {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--ws-text-3);
}

.row-value {
  flex-shrink: 0;
  min-width: 62px;
  text-align: right;
  font-size: 13px;
  font-weight: 600;
  color: var(--ws-signal);
}

.row-controls {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 6px;
  padding-left: 22px;
  flex-wrap: wrap;
}

.wave-select {
  width: 66px;
}

.num {
  width: 78px;
}

.num-sm {
  width: 64px;
}

.text-input {
  width: 140px;
}

.tilde {
  color: var(--ws-text-3);
}

.lbl {
  font-size: 11px;
  color: var(--ws-text-3);
}

.row-spark {
  height: 26px;
  margin-top: 4px;
  padding-left: 22px;
}

.row-spark svg {
  display: block;
  width: 100%;
  height: 26px;
  fill: none;
  stroke: var(--ws-signal);
  stroke-width: 1.2;
  stroke-linejoin: round;
  stroke-linecap: round;
  opacity: 0.8;
}

.panel-empty {
  padding: 28px 12px;
  text-align: center;
  font-size: 12px;
  color: var(--ws-text-3);
}

.panel-more {
  margin: 0;
  padding: 10px 12px 14px;
  border-top: 1px dashed var(--ws-steel-2);
  text-align: center;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--ws-text-3);
}

/* ---- 预览 + 趋势 ---- */
.workspace {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.preview-box {
  position: relative;
  flex: 1;
  min-height: 220px;
  overflow: hidden;
  border: 1px solid var(--ws-steel-3);
  background: #0d1823;
  box-shadow: var(--ws-shadow-panel);
}

.preview-loading {
  position: absolute;
  inset: 0;
  z-index: 5;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  background: rgba(13, 24, 35, 0.55);
  color: rgba(226, 232, 240, 0.9);
  font-size: 13px;
}

.preview-empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: rgba(226, 232, 240, 0.6);
}

.preview-empty svg {
  width: 48px;
  height: 48px;
  fill: none;
  stroke: rgba(226, 232, 240, 0.28);
  stroke-width: 1.4;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.empty-title {
  margin: 8px 0 0;
  font-size: 14px;
  font-weight: 600;
  color: rgba(226, 232, 240, 0.82);
}

.empty-desc {
  margin: 0;
  font-size: 12px;
  color: rgba(226, 232, 240, 0.55);
}

.trend-box {
  height: 218px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--ws-panel);
  border: 1px solid var(--ws-steel-3);
  box-shadow: var(--ws-shadow-panel);
}

.trend-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 7px 12px 0;
}

.trend-hint {
  font-size: 11px;
  color: var(--ws-text-3);
}

.trend-chart {
  flex: 1;
  min-height: 0;
}

/* ---- 窄屏 ---- */
@media (max-width: 960px) {
  .sim-body {
    flex-direction: column;
  }

  .signal-panel {
    width: 100%;
    height: 42%;
  }

  .workspace {
    min-height: 420px;
  }

  .project-select {
    width: 180px;
  }
}
</style>
