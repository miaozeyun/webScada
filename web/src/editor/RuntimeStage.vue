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
import { Bell, Close, FullScreen, MuteNotification } from '@element-plus/icons-vue'
import { ElNotification } from 'element-plus'
import type { ProjectDoc } from '@/types/doc'
import { RuntimeEngine, type ServerRuntimeOptions } from '@/runtime/engine'
import { useRuntimeStore, type ServerStatus } from '@/runtime/store'
import { provideRuntime } from '@/runtime/actions'
import { addAlarmRecord, setAlarmLevelColors } from '@/api/alarms'
import AlarmBanner from '@/components/alarm/AlarmBanner.vue'
import AlarmPanel from '@/components/alarm/AlarmPanel.vue'
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
    /** 无顶栏展示（分享页）：隐藏标题栏/页签，禁滚动条，仅保留右上角悬浮全屏按钮 */
    chromeless?: boolean
    /** 嵌入容器（仿真台等）：absolute 铺满定位父级而非 fixed 全屏，层级降为普通内容层 */
    docked?: boolean
  }>(),
  { closable: false, writable: true, embed: false, chromeless: false, docked: false },
)

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'serverReload'): void
  /** 预览默认只读：用户显式确认后才允许反控写真实设备 */
  (e: 'enableWrite'): void
}>()

const engine = new RuntimeEngine()
const runtime = useRuntimeStore()

// 仿真台需要向本引擎注入仿真值（injectValue，仅 local 模式生效）；其余宿主不使用
defineExpose({ engine })

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
/** 分享页无顶栏（embed 优先：iframe 场景连悬浮按钮也不要） */
const bare = computed(() => props.chromeless === true && !embed.value)
/** 无顶栏/嵌入时画面即视口：禁滚动条，页面按 mode 自适应铺满 */
const noScroll = computed(() => embed.value || bare.value)
/** 无顶栏时舞台底色跟页面底色：留白区与画面同色，视觉上「铺满」视口 */
const stageBg = computed(() => (noScroll.value ? (page.value?.background.color ?? '#0d1823') : undefined))

/** M9 批次5：画面方向强制——视口方向与设定不符时页面旋转 90°（横屏画面在竖屏手机上强制横看，反之亦然） */
const rotated = computed(() => {
  const o = page.value?.screen.orientation ?? 'auto'
  if (o === 'auto') return false
  const viewLandscape = bodySize.value.w >= bodySize.value.h
  return viewLandscape !== (o === 'landscape')
})

const fit = computed(() => {
  const p = page.value
  if (!p) return { sx: 1, sy: 1 }
  // 旋转态：视口宽高互换后再套用自适应规则（页面按"旋转后的可用视口"计算缩放）
  const { w: vw0, h: vh0 } = bodySize.value
  const vw = rotated.value ? vh0 : vw0
  const vh = rotated.value ? vw0 : vh0
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
  transform: rotated.value
    ? `translate(-50%, -50%) rotate(90deg) scale(${fit.value.sx}, ${fit.value.sy})`
    : `scale(${fit.value.sx}, ${fit.value.sy})`,
  position: rotated.value ? ('absolute' as const) : undefined,
  left: rotated.value ? '50%' : undefined,
  top: rotated.value ? '50%' : undefined,
}))

/** 旋转态外层占位（宽高 = 旋转后的页面尺寸 × 缩放），保持 flex 居中与滚动正确 */
const wrapStyle = computed(() => {
  const p = page.value
  if (!rotated.value || !p) return undefined
  return {
    width: `${p.screen.designHeight * fit.value.sy}px`,
    height: `${p.screen.designWidth * fit.value.sx}px`,
  }
})

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

// ---- 报警呈现接线（2026-10-26）：横幅/面板此前已实现但无宿主，运行大屏只有弹窗 ----

/** 报警确认的项目上下文：编辑器预览=reportProjectId（有 JWT，可 ack）；
 *  分享页留空（匿名只读；AlarmPanel 的 REST 需要 JWT，避免 401）。 */
const alarmProjectId = computed(() => (props.serverToken ? '' : (props.reportProjectId ?? '')))

/** 未确认报警数（顶栏徽标口径；含已确认会虚高） */
const unackedCount = computed(() => runtime.unackedAlarmCount)

/** 报警明细抽屉（仅编辑预览；分享页用横幅展开查看，避免匿名 REST 401） */
const alarmPanelOpen = ref(false)

function openAlarmPanel(): void {
  if (alarmProjectId.value) alarmPanelOpen.value = true
}

// ---- 数据新鲜度：值班大屏必须能看出画面已冻结 ----

const nowMs = ref(Date.now())
let nowTimer: number | null = null

/** 服务端值流超过该时长无任何值帧 → 视为数据停更（画面冻结） */
const STALE_AFTER_MS = 15000
const valueStale = computed(() => {
  if (!serverOpts.value) return false
  if (!runtime.lastValueAt) return false
  return nowMs.value - runtime.lastValueAt > STALE_AFTER_MS
})

/** 浏览器网络离线（比 15s 值停更更早发现；现场拔网线/断 WiFi） */
const browserOffline = ref(typeof navigator !== 'undefined' && navigator.onLine === false)
function onBrowserOnline(): void {
  browserOffline.value = !navigator.onLine
}

/** 断线/停更提示（分享页 chromeless 时 header 不渲染，必须叠在画面上） */
const connectionAlert = computed<{ text: string; bad: boolean } | null>(() => {
  if (!serverOpts.value) return null
  if (browserOffline.value) return { text: '网络已断开，画面数据已停止更新', bad: true }
  const s = runtime.serverStatus as ServerStatus
  if (s === 'offline') return { text: '实时数据连接已断开，正在重连…', bad: true }
  if (s === 'error') return { text: '实时数据连接失败，请检查网络或链接', bad: true }
  if (s === 'connecting') return { text: '正在连接实时数据…', bad: false }
  if (valueStale.value) {
    const sec = Math.max(1, Math.round((nowMs.value - runtime.lastValueAt) / 1000))
    return { text: `实时数据已停止更新（最后更新于 ${fmtClock(runtime.lastValueAt)}，${sec} 秒前）`, bad: true }
  }
  return null
})

function fmtClock(ms: number): string {
  if (!ms) return '—'
  const d = new Date(ms)
  const p = (n: number): string => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

// ---- 分享页可用性：竖屏提示 / 多页面导航 ----

const portraitHint = ref(true) // 用户可关闭，避免每次刷新都挡画面
const isPortrait = computed(() => bodySize.value.h > bodySize.value.w)
const showPortraitHint = computed(
  () => bare.value && !rotated.value && isPortrait.value && portraitHint.value,
)

/** 分享页页签：chromeless 时 header 隐藏，多页面工程客户原本无法翻页 */
const showPageNav = computed(() => bare.value && pages.value.length > 1)


// ---- 报警呈现：通知 + 声音（settings.alarm.soundEnabled / rule.sound） ----

let audioCtx: AudioContext | null = null
let lastBeepAt = 0 // soundThrottleSec 节流（02 契约 settings.alarm.soundThrottleSec，默认 60s）

/** 浏览器自动播放策略：AudioContext 必须在用户手势里 resume 才能出声。
 *  值班大屏常年无操作 → 此前报警音永远不响且静默吞掉。 */
const audioUnlocked = ref(false)
const soundMuted = ref(false)
const soundEnabled = computed(() => props.doc.settings?.alarm?.soundEnabled !== false)
const audioActive = computed(() => soundEnabled.value && !soundMuted.value)
const soundLabel = computed(() => {
  if (!audioUnlocked.value) return '点击启用报警音'
  if (soundMuted.value) return '报警音已静音'
  return '报警音已启用'
})

/** 声音按钮：未解锁时点击即解锁；已解锁时切换静音 */
function toggleSound(): void {
  if (!audioUnlocked.value) {
    soundMuted.value = false
    unlockAudio()
    return
  }
  soundMuted.value = !soundMuted.value
}

function ensureAudioCtx(): AudioContext | null {
  try {
    audioCtx = audioCtx ?? new AudioContext()
    return audioCtx
  } catch {
    return null
  }
}

/** 首次用户手势：解锁音频（点击画面任意处、按键、全屏按钮均会触发） */
function unlockAudio(): void {
  const ctx = ensureAudioCtx()
  if (!ctx) return
  if (ctx.state === 'running') {
    audioUnlocked.value = true
    return
  }
  void ctx
    .resume()
    .then(() => {
      audioUnlocked.value = ctx.state === 'running'
    })
    .catch(() => {
      /* 策略拒绝：保持未解锁提示，下次手势重试 */
    })
}

function beepThrottled(level: string): void {
  if (!audioActive.value || !audioUnlocked.value) return
  const throttleSec = props.doc.settings?.alarm?.soundThrottleSec ?? 60
  const now = Date.now()
  if (now - lastBeepAt < throttleSec * 1000) return
  lastBeepAt = now
  beep(level)
}

function beep(level: string): void {
  const ctx = ensureAudioCtx()
  if (!ctx) return
  try {
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.connect(gain)
    gain.connect(ctx.destination)
    osc.frequency.value = level === 'critical' ? 880 : 660
    gain.gain.value = 0.08
    osc.start()
    osc.stop(ctx.currentTime + 0.18)
  } catch {
    /* 浏览器策略限制时静默 */
  }
}

/** 未确认报警持续提醒：每 5s 检查一次，内部按 soundThrottleSec 节流。
 *  与 ack 解耦修复：确认后未确认计数下降，提醒自然停止。 */
let remindTimer: number | null = null
function remindTick(): void {
  if (!audioActive.value || !audioUnlocked.value || unackedCount.value <= 0) return
  let level = 'warn'
  for (const ev of runtime.activeAlarms.values()) {
    if (ev.status !== 'acked' && ev.status !== 'cleared' && ev.level === 'critical') {
      level = 'critical'
      break
    }
  }
  beepThrottled(level)
}

function onAlarmEvent(
  ev: { id: string; type: 'active' | 'recovered'; level: string; message: string; value?: number | boolean | string },
  rule?: { variableId: string; sound?: boolean | null },
): void {
  const title = ev.type === 'active' ? `报警：${ev.level}` : '报警恢复'
  ElNotification({
    title,
    message: ev.message,
    type: ev.type === 'active' ? (ev.level === 'critical' ? 'error' : 'warning') : 'success',
    duration: 4500,
    position: 'bottom-right', // 避开右上角标题栏的「退出」按钮
  })
  // 规则级提示音开关（DataDrawer 表单里的「提示音」）：false 时不响
  if (ev.type === 'active' && rule?.sound !== false) beepThrottled(ev.level)
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
  // 级别色注入：此前全仓无调用者，doc.settings.alarm.levelColors 实际不生效
  setAlarmLevelColors(props.doc.settings?.alarm?.levelColors ?? null)
  // 首次用户手势解锁报警音（浏览器自动播放策略）
  stageEl.value?.addEventListener('pointerdown', unlockAudio)
  window.addEventListener('keydown', unlockAudio)
  window.addEventListener('online', onBrowserOnline)
  window.addEventListener('offline', onBrowserOnline)
  nowTimer = window.setInterval(() => {
    nowMs.value = Date.now()
  }, 1000)
  remindTimer = window.setInterval(remindTick, 5000)
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
  stageEl.value?.removeEventListener('pointerdown', unlockAudio)
  window.removeEventListener('keydown', unlockAudio)
  window.removeEventListener('online', onBrowserOnline)
  window.removeEventListener('offline', onBrowserOnline)
  if (nowTimer !== null) {
    clearInterval(nowTimer)
    nowTimer = null
  }
  if (remindTimer !== null) {
    clearInterval(remindTimer)
    remindTimer = null
  }
  setAlarmLevelColors(null)
  engine.stop()
  // AudioContext 是浏览器稀缺资源（同页上限约 6 个），预览反复开关不释放会累积泄漏
  if (audioCtx) {
    void audioCtx.close().catch(() => {})
    audioCtx = null
  }
})
</script>

<template>
  <div
    ref="stageEl"
    class="runtime-stage"
    :class="{ 'is-fullscreen': isFullscreen, 'is-docked': docked }"
    :style="stageBg ? { background: stageBg } : undefined"
  >
    <header v-if="!embed && !bare" class="stage-bar">
      <span class="title">{{ title }}</span>
      <span v-if="!writable" class="ro-note" title="预览不写入真实设备；确认要调试反控时再解锁">只读预览</span>
      <button
        v-if="!writable && closable"
        class="ro-enable"
        type="button"
        title="允许预览画面上的控制组件写真实设备（谨慎操作）"
        @click="emit('enableWrite')"
      >
        允许控制
      </button>
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
      <button
        v-if="unackedCount > 0"
        class="alarm-badge"
        :class="{ clickable: !!alarmProjectId }"
        :title="alarmProjectId ? '点击查看全部报警' : '未确认报警数'"
        type="button"
        @click="openAlarmPanel"
      >
        <el-icon><Bell /></el-icon>{{ unackedCount }}
      </button>
      <button
        v-if="soundEnabled"
        class="sound-btn"
        :class="{ dim: !audioActive || !audioUnlocked }"
        type="button"
        :title="soundLabel"
        @click="toggleSound"
      >
        <el-icon><component :is="audioActive && audioUnlocked ? Bell : MuteNotification" /></el-icon>
        <span>{{ soundLabel }}</span>
      </button>
      <span v-if="serverHint" class="server-hint" :class="serverHint.cls">
        {{ serverHint.text }}
        <template v-if="runtime.lastValueAt"> · 最后更新 {{ fmtClock(runtime.lastValueAt) }}</template>
      </span>
      <el-button
        size="small"
        :icon="FullScreen"
        :title="isFullscreen ? '退出全屏' : '全屏（大屏展示）'"
        :aria-label="isFullscreen ? '退出全屏' : '进入全屏'"
        @click="toggleFullscreen"
      />
      <el-button v-if="closable" size="small" :icon="Close" @click="emit('close')">退出</el-button>
    </header>

    <!-- 报警横幅：运行态唯一常驻报警呈现（此前组件写好但无宿主，只剩 4.5s 弹窗） -->
    <AlarmBanner v-if="!embed" :project-id="alarmProjectId" :max-show="3" />

    <!-- 分享页：断线/停更提示（chromeless 无顶栏，必须叠在画面上） -->
    <div v-if="bare && connectionAlert" class="conn-alert" :class="{ bad: connectionAlert.bad }">
      {{ connectionAlert.text }}
    </div>

    <!-- 分享页：无顶栏，仅留右上角悬浮全屏 + 报警音状态（值班大屏场景） -->
    <button
      v-if="bare"
      class="float-fs"
      type="button"
      :title="isFullscreen ? '退出全屏' : '全屏展示'"
      :aria-label="isFullscreen ? '退出全屏' : '全屏展示'"
      @click="toggleFullscreen"
    >
      <el-icon :size="16"><FullScreen /></el-icon>
    </button>
    <button
      v-if="bare && soundEnabled"
      class="float-sound"
      :class="{ dim: !audioActive || !audioUnlocked }"
      type="button"
      :title="soundLabel"
      @click="toggleSound"
    >
      <el-icon :size="16"><component :is="audioActive && audioUnlocked ? Bell : MuteNotification" /></el-icon>
    </button>

    <!-- 分享页：多页面导航（页签原本在 header 内，chromeless 时整条隐藏） -->
    <nav v-if="showPageNav" class="float-pages">
      <button
        v-for="p in pages"
        :key="p.id"
        type="button"
        :class="{ active: p.id === currentPageId }"
        @click="currentPageId = p.id"
      >
        {{ p.name }}
      </button>
    </nav>

    <!-- 分享页竖屏提示：390px 宽下画面缩成中间一条，客户不知道要横屏 -->
    <div v-if="showPortraitHint" class="portrait-hint">
      <p>请将手机横屏查看大屏</p>
      <button type="button" @click="portraitHint = false">仍然查看</button>
    </div>

    <div ref="bodyEl" class="stage-body" :class="{ 'lock-pan': page?.screen.lockPan === true, 'no-scroll': noScroll }">
      <div v-if="page" class="stage-rot-wrap" :style="wrapStyle">
        <div class="stage-page" :style="pageStyle">
          <!-- 全部节点都挂载：静态 visible:false 的组件可能被事件（toggleVisible）/绑定恢复显示，
               显隐统一由 PreviewNode 内部按覆盖层优先级判定 -->
          <PreviewNode v-for="node in page.components" :key="node.id" :node="node" />
        </div>
      </div>
    </div>

    <!-- 报警明细：编辑预览可 ack；分享页无 JWT 不挂载（横幅展开即可查看） -->
    <el-drawer v-model="alarmPanelOpen" title="工程报警" size="760px" append-to-body>
      <AlarmPanel v-if="alarmProjectId" :project-id="alarmProjectId" />
    </el-drawer>
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

/* 嵌入模式（仿真台）：铺满定位父级，不盖住页面其余区域 */
.runtime-stage.is-docked {
  position: absolute;
  z-index: 1;
}

/* 嵌入态点全屏：恢复视口级定位（部分浏览器全屏不覆盖 absolute 定位） */
.runtime-stage.is-docked:fullscreen {
  position: fixed;
  z-index: 2000;
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
  border-bottom: 1px solid var(--ws-ink-edge);
}

.title {
  font-size: 13px;
  font-weight: 600;
  color: var(--ws-text-inverse);
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
  color: var(--ws-inv-60);
  cursor: pointer;
  white-space: nowrap;
}

.tab:hover {
  color: #fff;
  background: var(--ws-inv-hover);
}

.tab.active {
  color: #fff;
  background: var(--ws-signal-a18);
  box-shadow: inset 0 -2px 0 var(--ws-signal-bright);
  font-weight: 600;
}

.alarm-badge {
  padding: 2px 9px;
  border: 1px solid var(--ws-alert-line);
  border-radius: var(--ws-radius);
  background: var(--ws-alert-a16);
  color: var(--ws-alert-bright);
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
  color: var(--ws-warn-bright);
}
.server-hint.is-bad {
  color: var(--ws-alert-bright);
}

.stage-bar :deep(.el-button) {
  color: var(--ws-inv-75);
  background: transparent;
  border-color: var(--ws-inv-line);
}

.stage-bar :deep(.el-button:hover) {
  color: #fff;
  border-color: var(--ws-signal-bright);
  background: var(--ws-signal-a12);
}

.stage-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* M7 画面锁定：禁滚动禁拖拽（业界主流组态「不让实时画面移动」） */
.stage-body.lock-pan {
  overflow: hidden;
  overscroll-behavior: none;
  touch-action: none;
}

/* 分享页/嵌入：画面即视口，任何情况下都不出滚动条 */
.stage-body.no-scroll {
  overflow: hidden;
}

/* 分享页悬浮全屏：贴右上角，半透明深底，不抢画面但随时可点 */
.float-fs {
  position: absolute;
  top: 12px;
  right: 12px;
  /* 页面组件 z-index 可到 9000（弹框组），悬浮按钮必须压在其上 */
  z-index: 9500;
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 1px solid rgba(148, 163, 184, 0.35);
  border-radius: 6px;
  background: rgba(13, 24, 35, 0.55);
  color: rgba(255, 255, 255, 0.82);
  cursor: pointer;
  opacity: 0.7;
  transition: opacity 0.15s ease-out, background-color 0.15s ease-out, border-color 0.15s ease-out;
}

.float-fs:hover,
.float-fs:focus-visible {
  opacity: 1;
  background: rgba(13, 24, 35, 0.82);
  border-color: var(--ws-signal);
  color: #fff;
  outline: none;
}

/* 旋转态外层占位（M9 批次5）：非旋转时 auto 尺寸包裹，与原布局一致 */
.stage-rot-wrap {
  position: relative;
  flex-shrink: 0;
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

/* ---- 2026-10-26 报警呈现接线 ---- */

.ro-note {
  flex-shrink: 0;
  padding: 1px 7px;
  border: 1px solid var(--ws-inv-line);
  border-radius: var(--ws-radius);
  color: var(--ws-inv-75);
  font-size: 11px;
}

.ro-enable {
  flex-shrink: 0;
  padding: 2px 9px;
  border: 1px solid var(--ws-warn-bright);
  border-radius: var(--ws-radius);
  background: transparent;
  color: var(--ws-warn-bright);
  font-size: 11px;
  cursor: pointer;
}

.ro-enable:hover {
  background: var(--ws-warn-a16, rgba(245, 158, 11, 0.16));
}

.alarm-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: default;
  font-family: var(--ws-font-tech);
}

.alarm-badge.clickable {
  cursor: pointer;
}

.alarm-badge.clickable:hover {
  background: var(--ws-alert-a40);
}

.sound-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border: 1px solid var(--ws-inv-line);
  border-radius: var(--ws-radius);
  background: transparent;
  color: var(--ws-inv-75);
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}

.sound-btn:hover {
  color: #fff;
  border-color: var(--ws-signal-bright);
}

.sound-btn.dim {
  color: var(--ws-warn-bright);
  border-color: var(--ws-warn-bright);
}

/* 分享页断线/停更：叠在画面上方，红色高对比，不允许被画面内容盖住 */
.conn-alert {
  position: absolute;
  top: 10px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 9600;
  max-width: min(92vw, 720px);
  padding: 7px 16px;
  border: 1px solid var(--ws-warn-line, rgba(245, 158, 11, 0.5));
  border-radius: 8px;
  background: rgba(13, 24, 35, 0.92);
  color: var(--ws-warn-bright, #fbbf24);
  font-size: 13px;
  text-align: center;
}

.conn-alert.bad {
  border-color: var(--ws-alert-bright, #ef4444);
  color: var(--ws-alert-bright, #ef4444);
  font-weight: 600;
}

/* 分享页声音状态：与全屏按钮并排 */
.float-sound {
  position: absolute;
  top: 12px;
  right: 56px;
  z-index: 9500;
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 1px solid rgba(148, 163, 184, 0.35);
  border-radius: 6px;
  background: rgba(13, 24, 35, 0.55);
  color: rgba(255, 255, 255, 0.82);
  cursor: pointer;
  opacity: 0.8;
}

.float-sound.dim {
  color: var(--ws-warn-bright, #fbbf24);
  border-color: var(--ws-warn-bright, #fbbf24);
}

.float-sound:hover {
  opacity: 1;
  color: #fff;
}

/* 分享页多页面导航：底部悬浮页签 */
.float-pages {
  position: absolute;
  bottom: 16px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 9500;
  display: flex;
  gap: 4px;
  padding: 4px;
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 8px;
  background: rgba(13, 24, 35, 0.72);
  max-width: 92vw;
  overflow-x: auto;
}

.float-pages button {
  padding: 4px 12px;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: rgba(255, 255, 255, 0.62);
  font-size: 12px;
  white-space: nowrap;
  cursor: pointer;
}

.float-pages button.active {
  background: var(--ws-signal-a18, rgba(27, 167, 184, 0.18));
  color: #fff;
  font-weight: 600;
  box-shadow: inset 0 -2px 0 var(--ws-signal-bright, #22d3ee);
}

/* 竖屏提示：画面缩成一条时明确引导横屏 */
.portrait-hint {
  position: fixed;
  inset: 0;
  z-index: 9800;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  background: rgba(9, 16, 24, 0.94);
  color: #e2e8f0;
}

.portrait-hint p {
  margin: 0;
  font-size: 16px;
  letter-spacing: 1px;
}

.portrait-hint button {
  padding: 8px 20px;
  border: 1px solid rgba(148, 163, 184, 0.45);
  border-radius: 6px;
  background: transparent;
  color: #e2e8f0;
  font-size: 13px;
  cursor: pointer;
}
</style>
