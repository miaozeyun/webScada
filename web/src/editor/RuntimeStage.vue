<script setup lang="ts">
/**
 * 运行态舞台（M3/M4/M6 共用）：编辑器预览与分享页的公共渲染层。
 * 职责：启动/停止 RuntimeEngine、页面切换、按 screen.mode 自适应缩放、
 * 报警呈现（通知 + 声音 + 右上徽标 + 服务端记录上报）。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Close } from '@element-plus/icons-vue'
import { ElNotification } from 'element-plus'
import type { ProjectDoc } from '@/types/doc'
import { RuntimeEngine } from '@/runtime/engine'
import { useRuntimeStore } from '@/runtime/store'
import { addAlarmRecord } from '@/api/alarms'
import PreviewNode from './PreviewNode.vue'

const props = defineProps<{
  doc: ProjectDoc
  title: string
  /** 登录态下的预览才上报报警记录（分享页匿名不上报） */
  reportProjectId?: string
  closable?: boolean
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

const engine = new RuntimeEngine()
const runtime = useRuntimeStore()
const bodyEl = ref<HTMLDivElement>()
const bodySize = ref({ w: 0, h: 0 })
const currentPageId = ref(props.doc.pages[0]?.id ?? '')

const pages = computed(() => [...props.doc.pages].sort((a, b) => a.order - b.order))
const page = computed(() => props.doc.pages.find((p) => p.id === currentPageId.value) ?? null)

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

function onAlarmEvent(ev: { id: string; type: 'active' | 'recovered'; level: string; message: string }): void {
  const title = ev.type === 'active' ? `报警：${ev.level}` : '报警恢复'
  ElNotification({
    title,
    message: ev.message,
    type: ev.type === 'active' ? (ev.level === 'critical' ? 'error' : 'warning') : 'success',
    duration: 4500,
  })
  if (ev.type === 'active') beep(ev.level)
  if (props.reportProjectId && localStorage.getItem('webscada_token')) {
    // 上报失败静默（预览不因记录失败中断）
    addAlarmRecord(props.reportProjectId, {
      ruleId: ev.id,
      variableKey: '',
      level: ev.level as 'info' | 'warn' | 'critical',
      message: ev.message,
      value: null,
      status: ev.type,
    }).catch(() => {})
  }
}

onMounted(() => {
  measure()
  window.addEventListener('resize', measure)
  engine.start(props.doc, { onAlarmEvent })
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', measure)
  engine.stop()
})
</script>

<template>
  <div class="runtime-stage">
    <header class="stage-bar">
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
    <div ref="bodyEl" class="stage-body">
      <div v-if="page" class="stage-page" :style="pageStyle">
        <PreviewNode
          v-for="node in page.components.filter((c) => c.visible !== false)"
          :key="node.id"
          :node="node"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.runtime-stage {
  position: fixed;
  inset: 0;
  z-index: 2000;
  background: #0b1220;
  display: flex;
  flex-direction: column;
}

.stage-bar {
  height: 40px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 12px;
  background: #fff;
  border-bottom: 1px solid #dcdfe6;
}

.title {
  font-size: 14px;
  font-weight: 600;
  color: #606266;
  white-space: nowrap;
}

.stage-tabs {
  flex: 1;
  display: flex;
  gap: 4px;
  overflow-x: auto;
}

.tab {
  font-size: 13px;
  color: #909399;
  padding: 3px 12px;
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
}

.tab:hover {
  color: #409eff;
  background: #ecf5ff;
}

.tab.active {
  color: #409eff;
  background: #ecf5ff;
  font-weight: 600;
}

.alarm-badge {
  font-size: 13px;
  color: #f56c6c;
  font-weight: 600;
  padding: 2px 10px;
  border: 1px solid #fbc4c4;
  border-radius: 12px;
  white-space: nowrap;
}

.stage-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  align-items: center;
  justify-content: center;
}

.stage-page {
  position: relative;
  flex-shrink: 0;
  transform-origin: center center;
  box-shadow: 0 0 24px rgba(0, 0, 0, 0.4);
  overflow: hidden;
}
</style>
