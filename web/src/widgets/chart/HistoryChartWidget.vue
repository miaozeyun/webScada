<script setup lang="ts">
/** 历史图表（M7，对齐 BY「历史图表」）：查询 history 服务（分钟桶，localStorage 持久化）。
 * 运行态右上角可切时间范围（1h/6h/24h/3d）；30s 自动刷新；编辑态显示空态示意。 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import EchartsBase from '../EchartsBase.vue'
import { query } from '@/runtime/history'
import { useRuntimeStore } from '@/runtime/store'
import { useRuntimeApi } from '@/runtime/actions'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()
const runtime = useRuntimeStore()

const RANGE_OPTIONS = [
  { label: '1h', ms: 3600_000 },
  { label: '6h', ms: 6 * 3600_000 },
  { label: '24h', ms: 24 * 3600_000 },
  { label: '3d', ms: 3 * 24 * 3600_000 },
]

const rangeMs = ref(3600_000)
const points = ref<[number, number][]>([])
const variableId = computed(() => String(props.nodeProps.variableId ?? ''))
/** live 模式：直接消费引擎内存滚动序列（小尺寸迷你图，启动即有曲线） */
const live = computed(() => props.nodeProps.live === true)
const api = useRuntimeApi()
const liveSeries = ref<number[]>([])
const liveMode = computed(() => live.value && !!api)
let timer: ReturnType<typeof setInterval> | null = null

function refresh(): void {
  if (!variableId.value) return
  if (liveMode.value) {
    liveSeries.value = api!.historyOf(variableId.value)
    return
  }
  points.value = query(variableId.value, Date.now() - rangeMs.value)
}

onMounted(() => {
  const init = Number(props.nodeProps.rangeMs ?? 3600_000)
  rangeMs.value = RANGE_OPTIONS.some((o) => o.ms === init) ? init : 3600_000
  refresh()
  timer = setInterval(refresh, liveMode.value ? 1000 : 30_000)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})

const AXIS = { axisLabel: { color: '#909399' }, axisLine: { lineStyle: { color: '#c0c4cc' } }, splitLine: { lineStyle: { color: 'rgba(148,163,184,0.2)' } } }

/** 紧凑模式（移动端小尺寸）：隐标题/坐标轴文字，边距最小化 */
const compact = computed(() => props.nodeProps.compact === true)

const option = computed(() => ({
  title: compact.value
    ? { show: false }
    : { text: String(props.nodeProps.title ?? '历史趋势'), left: 'center', textStyle: { color: '#909399', fontSize: 14 } },
  tooltip: { trigger: 'axis', valueFormatter: (v: number) => `${v}${props.nodeProps.unit ?? ''}` },
  grid: compact.value ? { left: 4, right: 6, top: 6, bottom: 4 } : { left: 44, right: 16, top: 40, bottom: 28 },
  xAxis: liveMode.value
    ? { type: 'category', data: liveSeries.value.map((_, i) => String(i + 1)), show: false }
    : { type: 'time', ...AXIS, axisLabel: { show: !compact.value, color: '#909399' }, axisTick: { show: !compact.value } },
  yAxis: {
    type: 'value', name: compact.value ? '' : String(props.nodeProps.unit ?? ''), nameTextStyle: { color: '#909399' }, scale: true, ...AXIS,
    axisLabel: { show: !compact.value, color: '#909399' },
    splitLine: { show: !compact.value && !liveMode.value, lineStyle: { color: 'rgba(148,163,184,0.2)' } },
  },
  series: [
    {
      type: 'line',
      showSymbol: false,
      smooth: true,
      data: liveMode.value ? liveSeries.value : points.value,
      lineStyle: { color: '#1ba7b8', width: 2 },
      areaStyle: { color: 'rgba(64,158,255,0.12)' },
    },
  ],
}))

const hasData = computed(() => (liveMode.value ? liveSeries.value.length > 0 : points.value.length > 0))
</script>

<template>
  <div class="history-chart">
    <EchartsBase :option="option" />
    <div v-if="runtime.running && !compact" class="range-bar">
      <button
        v-for="o in RANGE_OPTIONS"
        :key="o.ms"
        type="button"
        class="range-btn"
        :class="{ active: rangeMs === o.ms }"
        @click="rangeMs = o.ms; refresh(); $event.stopPropagation()"
      >
        {{ o.label }}
      </button>
    </div>
    <div v-if="!variableId" class="empty">配置变量（组件属性 variableId）</div>
    <div v-else-if="!hasData && !runtime.running" class="empty">运行后开始采集历史</div>
  </div>
</template>

<style scoped>
.history-chart {
  position: relative;
  width: 100%;
  height: 100%;
}

.range-bar {
  position: absolute;
  top: 6px;
  right: 10px;
  display: flex;
  gap: 3px;
  opacity: 0.35;
  transition: opacity 0.2s;
  z-index: 2;
}

.history-chart:hover .range-bar {
  opacity: 1;
}

.range-btn {
  border: 1px solid rgba(148, 163, 184, 0.5);
  background: rgba(15, 23, 42, 0.65);
  color: #cbd5e1;
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 3px;
  cursor: pointer;
}

.range-btn.active {
  background: #2563eb;
  border-color: #2563eb;
  color: #fff;
}

.empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  font-size: 12px;
  pointer-events: none;
}
</style>
