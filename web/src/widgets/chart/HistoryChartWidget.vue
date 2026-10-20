<script setup lang="ts">
/** 历史图表（M7 引入，M8 改造）：优先查询服务端 /history 区间接口（03 §2.10，服务端 historian 入库），
 * 服务端不可达或该区间无入库数据时回落本地分钟桶缓冲（runtime/history，演示/离线兜底）并亮「本地缓存」角标。
 * 运行态右上角可切时间范围（1h/6h/24h/3d），stepMs 随 range 联动（服务端窗口均值降采样）；30s 自动刷新；
 * live 模式仍直接消费引擎内存滚动序列；编辑态显示空态示意。 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import EchartsBase from '../EchartsBase.vue'
import { AXIS, CHART, TITLE_STYLE } from './shared'
import { query } from '@/runtime/history'
import { useRuntimeStore } from '@/runtime/store'
import { useRuntimeApi } from '@/runtime/actions'
import { useEditorStore } from '@/stores/editor'
import { getHistoryProjectId, queryHistory } from '@/api/history'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()
const runtime = useRuntimeStore()
const editor = useEditorStore()

const RANGE_OPTIONS = [
  { label: '1h', ms: 3600_000 },
  { label: '6h', ms: 6 * 3600_000 },
  { label: '24h', ms: 24 * 3600_000 },
  { label: '3d', ms: 3 * 24 * 3600_000 },
]

/** 降采样目标点数：stepMs = rangeMs / 目标点数（服务端窗口均值聚合） */
const STEP_TARGET_POINTS = 200
/** 单序列点数上限（服务端超限自动增大 stepMs，契约 §4.2） */
const MAX_POINTS = 500

const rangeMs = ref(3600_000)
const points = ref<[number, number][]>([])
/** 服务端链路异常（不可达/4xx/5xx）：亮「本地缓存」角标 */
const serverDown = ref(false)
let fetching = false
const variableId = computed(() => String(props.nodeProps.variableId ?? ''))
/** live 模式：直接消费引擎内存滚动序列（小尺寸迷你图，启动即有曲线），不经服务端 */
const live = computed(() => props.nodeProps.live === true)
const api = useRuntimeApi()
const liveSeries = ref<number[]>([])
const liveMode = computed(() => live.value && !!api)
let timer: ReturnType<typeof setInterval> | null = null

/** 工程 id 解析链：组件显式配置（nodeProps.projectId）→ editor store（编辑器预览）→ 宿主注入（分享页/独立运行页） */
const projectId = computed(() => {
  const p = props.nodeProps.projectId
  if (typeof p === 'string' && p) return p
  if (editor.projectId) return editor.projectId
  return getHistoryProjectId()
})

/** 变量 key（服务端 API 以 key 取数）：由绑定用变量 id 经运行时 key→id 索引反查 */
const variableKey = computed(() => {
  const id = variableId.value
  if (!id) return ''
  for (const [key, varId] of runtime.varByKey) {
    if (varId === id) return key
  }
  return ''
})

/** stepMs 联动 range：范围越大步长越大，固定约 200 个聚合点 */
const stepMs = computed(() => Math.max(1000, Math.floor(rangeMs.value / STEP_TARGET_POINTS)))

/** 本地分钟桶兜底查询（服务端不可达/无数据时的演示/离线路径） */
function fallbackLocal(): void {
  points.value = query(variableId.value, Date.now() - rangeMs.value)
}

async function refresh(): Promise<void> {
  if (!variableId.value || fetching) return
  if (liveMode.value) {
    liveSeries.value = api!.historyOf(variableId.value)
    return
  }
  const pid = projectId.value
  const key = variableKey.value
  if (pid && key) {
    fetching = true
    try {
      const resp = await queryHistory(pid, {
        keys: [key],
        from: Date.now() - rangeMs.value,
        to: Date.now(),
        stepMs: stepMs.value,
        maxPoints: MAX_POINTS,
      })
      serverDown.value = false
      const series = resp.series[key]
      if (series && series.length > 0) {
        points.value = series
        return
      }
      // 服务端可达但该区间无入库数据（历史刚启用/变量无采样）→ 本地缓冲兜底显示
    } catch {
      // 服务端不可达：契约要求回落本地缓冲，角标提示数据来源降级
      serverDown.value = true
    } finally {
      fetching = false
    }
  }
  fallbackLocal()
}

onMounted(() => {
  const init = Number(props.nodeProps.rangeMs ?? 3600_000)
  rangeMs.value = RANGE_OPTIONS.some((o) => o.ms === init) ? init : 3600_000
  void refresh()
  timer = setInterval(() => void refresh(), liveMode.value ? 1000 : 30_000)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})

/** 紧凑模式（移动端小尺寸）：隐标题/坐标轴文字，边距最小化 */
const compact = computed(() => props.nodeProps.compact === true)

const option = computed(() => ({
  title: compact.value
    ? { show: false }
    : { text: String(props.nodeProps.title ?? '历史趋势'), left: 'center', textStyle: TITLE_STYLE },
  tooltip: { trigger: 'axis', valueFormatter: (v: number) => `${v}${props.nodeProps.unit ?? ''}` },
  grid: compact.value ? { left: 4, right: 6, top: 6, bottom: 4 } : { left: 44, right: 16, top: 40, bottom: 28 },
  xAxis: liveMode.value
    ? { type: 'category', data: liveSeries.value.map((_, i) => String(i + 1)), show: false }
    : { type: 'time', ...AXIS, axisLabel: { show: !compact.value, color: CHART.text }, axisTick: { show: !compact.value } },
  yAxis: {
    type: 'value', name: compact.value ? '' : String(props.nodeProps.unit ?? ''), nameTextStyle: { color: CHART.text }, scale: true, ...AXIS,
    axisLabel: { show: !compact.value, color: CHART.text },
    splitLine: { show: !compact.value && !liveMode.value, lineStyle: { color: CHART.split } },
  },
  series: [
    {
      type: 'line',
      showSymbol: false,
      smooth: true,
      data: liveMode.value ? liveSeries.value : points.value,
      lineStyle: { color: CHART.signal, width: 2 },
      areaStyle: { color: CHART.signalArea },
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
    <!-- 服务端降级角标：当前曲线来自本地分钟桶（服务端不可达或区间无数据） -->
    <span v-if="runtime.running && serverDown && !compact" class="local-badge" title="服务端历史不可达，当前展示本地缓冲">本地缓存</span>
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
  color: #c0c4cc;
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 3px;
  cursor: pointer;
}

.range-btn.active {
  background: #0b7285;
  border-color: #0b7285;
  color: #fff;
}

/* 服务端降级角标（M8）：左上角，避免与右上图内范围切换条重叠。
   画布内容不随界面主题，固定深浅底都可读的琥珀色 */
.local-badge {
  position: absolute;
  top: 6px;
  left: 10px;
  z-index: 2;
  padding: 1px 6px;
  border: 1px solid rgba(184, 116, 0, 0.45);
  border-radius: 3px;
  background: rgba(184, 116, 0, 0.14);
  color: #d9a441;
  font-size: 10px;
  line-height: 1.5;
  pointer-events: none;
}

.empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #909399;
  font-size: 12px;
  pointer-events: none;
}
</style>
