<script setup lang="ts">
/**
 * 运行态舞台（M3/M4/M6/M7 共用，M8 扩展 server 模式）：编辑器预览与分享页的公共渲染层。
 * 职责：启动/停止 RuntimeEngine、页面切换、按 screen.mode 自适应缩放、
 * 报警呈现（通知 + 声音 + 右上徽标）。
 * M7：提供 RuntimeApi/事件执行注入（反控与事件行为）、lockPan 画面锁定、embed 纯画面嵌入。
 * M8：server 模式——值流/报警由服务端 WS 驱动（浏览器直连数据源仅保留编辑器连接测试）。
 * 分享页传 serverToken（shareToken）；编辑器预览有 reportProjectId + 本地 JWT 时自动启用。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Close, FullScreen } from '@element-plus/icons-vue'
import { ElNotification } from 'element-plus'
import type { ProjectDoc } from '@/types/doc'
import { RuntimeEngine, type ServerRuntimeOptions } from '@/runtime/engine'
import { useRuntimeStore, type ServerStatus } from '@/runtime/store'
import { provideRuntime } from '@/runtime/actions'
import { addAlarmRecord } from '@/api/alarms'
import PreviewNode from './PreviewNode.vue'

const props = withDefaults(
  defineProps<{
    doc: ProjectDoc
    title: string
    /** 登录态下的预览（同时作为 server 模式的工程 id 来源） */
    reportProjectId?: string
    /** M8：分享 token（传参即以分享通道连服务端值流，只读） */
    serverToken?: string
    closable?: boolean
    /** M7：写通道开关（编辑器预览 true；分享页 false 只读）。
     *  注意必须显式默认 true——boolean 类型 prop 未传时 Vue 会转换为 false。 */
    writable?: boolean
    /** M7：纯画面嵌入（隐藏标题栏，供 iframe 场景；等价 URL ?embed=1） */
    embed?: boolean
  }>(),
  { closable: false, writable: true, embed: false },
)

const emit = defineEmits<{ (e: 'close'): void; (e: 'serverReload'): void }>()

const engine = new RuntimeEngine()
const runtime = useRuntimeStore()
const bodyEl = ref<HTMLDivElement>()
const bodySize = ref({ w: 0, h: 0 })
const currentPageId = ref(props.doc.pages[0]?.id ?? '')

// ---- 大屏全屏（监控值班场景）：舞台容器自身进入全屏，画面重新自适应 ----
const stageEl = ref<HTMLDivElement>()
const isFullscreen = ref(false)

function toggleFullscreen(): void {
  if (document.fullscreenElement) {
    void document.exitFullscreen()
  } else {
    void stageEl.value?.requestFullscreen?.().catch(() => {
      /* 浏览器策略拒绝（如未激活的 iframe）时静默 */
    })
  }
}

function onFullscreenChange(): void {
  isFullscreen.value = document.fullscreenElement === stageEl.value
  measure()
}

const pages = computed(() => [...props.doc.pages].sort((a, b) => a.order - b.order))
const page = computed(() => props.doc.pages.find((p) => p.id === currentPageId.value) ?? null)

// ---- M8：server 模式选项（分享 token 优先；编辑器预览回落本地 JWT） ----
const serverOpts = computed<ServerRuntimeOptions | null>(() => {
  if (props.serverToken) {
    return { projectId: props.doc.project.id, token: props.serverToken, page: currentPageId.value }
  }
  const jwt = localStorage.getItem('webscada_token')
  if (props.reportProjectId && jwt) return { projectId: props.reportProjectId, token: jwt, page: currentPageId.value }
  return null
})

// M7：运行态能力注入（事件动作 / 控制组件写通道）；须在 setup 同步调用
const writable = computed(() => props.writable !== false)
provideRuntime(
  {
    engine,
    doc: props.doc,
    switchPage: (pageId: string) => {
      if (pages.value.some((p) => p.id === pageId)) currentPageId.value = pageId
    },
  },
  writable.value,
)

const embed = computed(() => props.embed === true)

const fit = computed(() => {
  const p = page.value
  if (!p) return { sx: 1, sy: 1 }
  const { w: vw, h: vh } = bodySize.value
  const dw = p.screen.designWidth
  const dh = p.screen.designHeight
  switch (p.screen.mode) {
    case 'fit-width': return { sx: vw / dw, sy: vw / dw }
    case 'fit-height': return { sx: vh / dh, sy: vh / dh }
    case 'stretch': return { sx: vw / dw, sy: vh / dh }
    case 'fit-contain':
    default: {
      const s = Math.min(vw / dw, vh / dh)
      return { sx: s, sy: s }
    }
  }
})

const pageStyle = computed(() => ({
  width: `${page.value?.screen.designWidth ?? 0}px`,
  height: `${page.value?.screen.designHeight ?? 0}px`,
  background: page.value?.background.color ?? '#0b1220',
  transform: `scale(${fit.value.sx}, ${fit.value.sy})`,
}))

/** 服务端通道状态提示（仅中间态/异常，online 不占视觉） */
const serverHint = computed<{ text: string; cls: string } | null>(() => {
  if (!serverOpts.value) return null
  const s = runtime.serverStatus as ServerStatus
  if (s === 'connecting') return { text: '实时数据连接中…', cls: 'is-warn' }
  if (s === 'offline') return { text: '实时数据已断开，自动重连中', cls: 'is-warn' }
  if (s === 'error') return { text: '实时数据连接失败，请检查登录或链接', cls: 'is-bad' }
  return null
})

function measure(): void {
  const el = bodyEl
  if (el.value) bodySize.value = { w: el.value.clientWidth, h: el.value.clientHeight }
}

// ---- 报警呈现：通知 + 声音（rule.sound）；M8 起记录入库由服务端报警引擎负责 ----

let audioCtx: AudioContext | null = null
let lastBeepAt = 0 // soundThrottleSec 节流（02 契约 settings.alarm.soundThrottleSec，默认 60s）

function beepThrottled(level: string): void {
  const throttleSec = props.doc.settings?.alarm?.soundThrottleSec ?? 60
  const now = Date.now()
  if (now - lastBeepAt < throttleSec * 1000) return
  lastBeepAt = now
  beep(level)
}

function beep(level: string): void {
  try {
    audioCtx = audioCtx ?? new AudioContext()
    const osc = audioCtx.createOscillator()
    const gain = audioCtx.createGain()
    osc.connect(gain)
    gain.connect(audioCtx.destination)
    osc.frequency.value = level === 'critical' ? 880 : 660
    gain.gain.value = 0.08
    osc.start()
    osc.stop(audioCtx.currentTime + 0.18)
  } catch {
    /* 浏览器策略限制时静默 */
  }
}

function onAlarmEvent(
  ev: { id: string; type: 'active' | 'recovered'; level: string; message: string; value?: number | boolean | string },
  rule?: { variableId: string },
): void {
  const title = ev.type === 'active' ? `报警：${ev.level}` : '报警恢复'
  ElNotification({
    title,
    message: ev.message,
    type: ev.type === 'active' ? (ev.level === 'critical' ? 'error' : 'warning') : 'success',
    duration: 4500,
    position: 'bottom-right', // 避开右上角标题栏的「退出」按钮
  })
  if (ev.type === 'active') beepThrottled(ev.level)
  // server 模式不走旧前端上报：服务端 rules_engine 已入库（02 §7.7 修订）
  if (serverOpts.value) return
  if (props.reportProjectId && localStorage.getItem('webscada_token')) {
    // 服务端契约 variableKey 非空：按规则变量 id 反查工程内 key
    const variableKey = props.doc.variables.find((v) => v.id === rule?.variableId)?.key ?? 'unknown'
    // 上报失败静默（预览不因记录失败中断）
    addAlarmRecord(props.reportProjectId, {
      ruleId: ev.id,
      variableKey,
      level: ev.level as 'info' | 'warn' | 'critical',
      message: ev.message,
      value: ev.value === undefined ? null : String(ev.value),
      status: ev.type,
    }).catch(() => {})
  }
}

function startEngine(seedValues?: Map<string, string | number | boolean>): void {
  engine.start(
    props.doc,
    {
      onAlarmEvent,
      writable: writable.value,
      server: serverOpts.value ?? undefined,
      onServerReload: () => emit('serverReload'),
    },
    seedValues,
  )
}

onMounted(() => {
  measure()
  window.addEventListener('resize', measure)
  document.addEventListener('fullscreenchange', onFullscreenChange)
  startEngine()
})

// M8：分享 reload → 宿主替换 doc 引用 → 引擎重启。03 §3.8：已收到的变量值缓存保留（seed 透传，画面不闪空白）
watch(
  () => props.doc,
  (doc, old) => {
    if (doc === old) return
    currentPageId.value = doc.pages[0]?.id ?? ''
    const seed = new Map(engine.snapshotValues())
    engine.stop()
    startEngine(seed)
  },
)

onBeforeUnmount(() => {
  window.removeEventListener('resize', measure)
  document.removeEventListener('fullscreenchange', onFullscreenChange)
  engine.stop()
})
</script>

<template>
  <div ref="stageEl" class="runtime-stage" :class="{ 'is-fullscreen': isFullscreen }">
    <header v-if="!embed" class="stage-bar">
      <span class="title">{{ title }}</span>
      <nav class="stage-tabs">
        <span
          v-for="p in pages"
          :key="p.id"
          class="tab"
          :class="{ active: p.id === currentPageId }"
          @click="currentPageId = p.id"
        >
          {{ p.name }}
        </span>
      </nav>
      <span v-if="runtime.activeAlarmCount" class="alarm-badge" title="激活中的报警数">
        ⚠ {{ runtime.activeAlarmCount }}
      </span>
      <span v-if="serverHint" class="server-hint" :class="serverHint.cls">{{ serverHint.text }}</span>
      <el-button
        size="small"
        :icon="FullScreen"
        :title="isFullscreen ? '退出全屏' : '全屏（大屏展示）'"
        :aria-label="isFullscreen ? '退出全屏' : '进入全屏'"
        @click="toggleFullscreen"
      />
      <el-button v-if="closable" size="small" :icon="Close" @click="emit('close')">退出</el-button>
    </header>
    <div ref="bodyEl" class="stage-body" :class="{ 'lock-pan': page?.screen.lockPan === true }">
      <div v-if="page" class="stage-page" :style="pageStyle">
        <!-- 全部节点都挂载：静态 visible:false 的组件可能被事件（toggleVisible）/绑定恢复显示，
             显隐统一由 PreviewNode 内部按覆盖层优先级判定 -->
        <PreviewNode v-for="node in page.components" :key="node.id" :node="node" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.runtime-stage {
  position: fixed;
  inset: 0;
  z-index: 2000;
  background: #0d1823;
  display: flex;
  flex-direction: column;
}

/* 全屏态：舞台即视口（fixed inset:0 依旧成立，画面按 screen.mode 重新自适应） */
.runtime-stage:fullscreen {
  background: #0d1823;
}

/* 运行态顶栏：与控制台一致的深墨蓝，画面内容在其下独立呈现 */
.stage-bar {
  height: 44px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 0 14px;
  background: var(--ws-ink);
  border-bottom: 1px solid #0b141d;
}

.title {
  font-size: 13px;
  font-weight: 600;
  color: #eef4f7;
  white-space: nowrap;
}

.stage-tabs {
  flex: 1;
  display: flex;
  gap: 2px;
  overflow-x: auto;
}

.tab {
  padding: 4px 12px;
  border-radius: var(--ws-radius);
  font-size: 12px;
  color: rgba(238, 244, 247, 0.6);
  cursor: pointer;
  white-space: nowrap;
}

.tab:hover {
  color: #fff;
  background: rgba(238, 244, 247, 0.08);
}

.tab.active {
  color: #fff;
  background: rgba(27, 167, 184, 0.16);
  box-shadow: inset 0 -2px 0 var(--ws-signal-bright);
  font-weight: 600;
}

.alarm-badge {
  padding: 2px 9px;
  border: 1px solid rgba(255, 157, 110, 0.45);
  border-radius: var(--ws-radius);
  background: rgba(194, 65, 12, 0.16);
  color: #ffb59b;
  font-family: var(--ws-font-tech);
  font-variant-numeric: tabular-nums;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

/* M8：服务端值流通道状态（连接中/断线/失败） */
.server-hint {
  font-size: 12px;
  white-space: nowrap;
}
.server-hint.is-warn {
  color: var(--ws-signal-amber, #f59e0b);
}
.server-hint.is-bad {
  color: var(--ws-signal-red, #ef4444);
}

.stage-bar :deep(.el-button) {
  color: rgba(238, 244, 247, 0.78);
  background: transparent;
  border-color: rgba(238, 244, 247, 0.24);
}

.stage-bar :deep(.el-button:hover) {
  color: #fff;
  border-color: var(--ws-signal-bright);
  background: rgba(27, 167, 184, 0.12);
}

.stage-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* M7 画面锁定：禁滚动禁拖拽（BY「不让实时画面移动」） */
.stage-body.lock-pan {
  overflow: hidden;
  overscroll-behavior: none;
  touch-action: none;
}

.stage-page {
  position: relative;
  flex-shrink: 0;
  transform-origin: center center;
  box-shadow: 0 0 0 1px rgba(238, 244, 247, 0.07), 0 14px 44px rgba(0, 0, 0, 0.5);
  overflow: hidden;
  /* 运行态页面底色默认深色：未显式设色的文字/控制件统一走浅色，避免黑字黑底 */
  color: #e2e8f0;
}
</style>
