<script setup lang="ts">
/**
 * 运行态舞台（M3/M4/M6/M7 共用）：编辑器预览与分享页的公共渲染层。
 * 职责：启动/停止 RuntimeEngine、页面切换、按 screen.mode 自适应缩放、
 * 报警呈现（通知 + 声音 + 右上徽标 + 服务端记录上报）。
 * M7：提供 RuntimeApi/事件执行注入（反控与事件行为）、lockPan 画面锁定、embed 纯画面嵌入。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Close } from '@element-plus/icons-vue'
import { ElNotification } from 'element-plus'
import type { ProjectDoc } from '@/types/doc'
import { RuntimeEngine } from '@/runtime/engine'
import { useRuntimeStore } from '@/runtime/store'
import { provideRuntime } from '@/runtime/actions'
import { addAlarmRecord } from '@/api/alarms'
import PreviewNode from './PreviewNode.vue'

const props = withDefaults(
  defineProps<{
    doc: ProjectDoc
    title: string
    /** 登录态下的预览才上报报警记录（分享页匿名不上报） */
    reportProjectId?: string
    closable?: boolean
    /** M7：写通道开关（编辑器预览 true；分享页 false 只读）。
     *  注意必须显式默认 true——boolean 类型 prop 未传时 Vue 会转换为 false。 */
    writable?: boolean
    /** M7：纯画面嵌入（隐藏标题栏，供 iframe 场景；等价 URL ?embed=1） */
    embed?: boolean
  }>(),
  { closable: false, writable: true, embed: false },
)

const emit = defineEmits<{ (e: 'close'): void }>()

const engine = new RuntimeEngine()
const runtime = useRuntimeStore()
const bodyEl = ref<HTMLDivElement>()
const bodySize = ref({ w: 0, h: 0 })
const currentPageId = ref(props.doc.pages[0]?.id ?? '')

const pages = computed(() => [...props.doc.pages].sort((a, b) => a.order - b.order))
const page = computed(() => props.doc.pages.find((p) => p.id === currentPageId.value) ?? null)

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

function measure(): void {
  const el = bodyEl.value
  if (el) bodySize.value = { w: el.clientWidth, h: el.clientHeight }
}

// ---- 报警呈现：通知 + 声音（rule.sound）+ 服务端记录（登录态预览） ----

let audioCtx: AudioContext | null = null

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
  if (ev.type === 'active') beep(ev.level)
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

onMounted(() => {
  measure()
  window.addEventListener('resize', measure)
  engine.start(props.doc, { onAlarmEvent, writable: writable.value })
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', measure)
  engine.stop()
})
</script>

<template>
  <div class="runtime-stage">
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
