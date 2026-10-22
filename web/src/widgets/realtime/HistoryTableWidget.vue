<script setup lang="ts">
/**
 * 历史表格（工厂可用阶段二 Task 7）：单变量「区间桶快照」表——每行 = 一个时间桶的末值
 * （last 口径，取数走既有 queryHistory agg='last'，与 buildHistoryRows 同构；stepMs 随
 * rangeMs/bucketCount 联动，服务端窗口降采样后前端二次分桶兜稀疏/原始序列）。
 * 沿 RealtimeTableWidget 固化口径：原生表格 + theme.css 令牌、runtime store/editor store 取上下文；
 * 工程 id 解析链与 id→key 反查同 HistoryChartWidget（nodeProps.projectId → editor → 宿主注入）。
 * 60s 定时刷新；失败静默保留上次数据（不闪空）；onUnmounted 清定时器。
 * props：variableKey（'variable' 选择器，存变量 id）、rangeMs（1h/6h/24h 缺省 24h）、
 * bucketCount（时间桶数=行数，缺省 24）。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRuntimeStore } from '@/runtime/store'
import { useEditorStore } from '@/stores/editor'
import { getHistoryProjectId, queryHistory } from '@/api/history'
import { buildHistoryRows, type HistoryRow } from '@/utils/tableRows'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

const runtime = useRuntimeStore()
const editor = useEditorStore()

/** 时间范围档位（属性面板 select 同源；缺省 24h） */
const RANGE_OPTIONS = [
  { label: '1h', ms: 3600_000 },
  { label: '6h', ms: 6 * 3600_000 },
  { label: '24h', ms: 24 * 3600_000 },
]

/** 刷新周期：60s（历史 5s 采样，表格快照无需更高频） */
const REFRESH_MS = 60_000

/** 时间范围：非档位值/旧工程缺失回落 24h */
const rangeMs = computed(() => {
  const v = Number(props.nodeProps.rangeMs)
  return RANGE_OPTIONS.some((o) => o.ms === v) ? v : 24 * 3600_000
})

/** 时间桶数（=行数上限）：非法值回落 24，封顶 120（单页 ≤200 组件规模基线内取整） */
const bucketCount = computed(() => {
  const v = Number(props.nodeProps.bucketCount)
  return Number.isFinite(v) && v >= 1 ? Math.min(Math.floor(v), 120) : 24
})

/** 变量 key（服务端历史接口按 key 取数）：prop variableKey 经 'variable' 选择器存的是变量 id，
 *  经 editor.doc（编辑器/预览）→ runtime.varByKey（运行态/分享页快照索引）反查 */
const variableKey = computed(() => {
  const id = String(props.nodeProps.variableKey ?? '')
  if (!id) return ''
  for (const v of editor.doc?.variables ?? []) {
    if (v.id === id) return v.key
  }
  for (const [key, varId] of runtime.varByKey) {
    if (varId === id) return key
  }
  return ''
})

/** 工程 id 解析链：组件显式配置 → editor store（编辑器预览）→ 宿主注入（分享页/独立运行页） */
const projectId = computed(() => {
  const p = props.nodeProps.projectId
  if (typeof p === 'string' && p) return p
  if (editor.projectId) return editor.projectId
  return getHistoryProjectId()
})

const rows = ref<HistoryRow[]>([])

/** 展示序：最新桶在上（现场最先关心最近时刻） */
const displayRows = computed(() => [...rows.value].reverse())

let timer: ReturnType<typeof setInterval> | null = null
let fetching = false

/** 拉取当前区间：成功才覆盖（含空数据 → 清空为真值）；失败静默保留上次数据 */
async function refresh(): Promise<void> {
  const pid = projectId.value
  const key = variableKey.value
  if (!pid || !key || fetching) return
  fetching = true
  try {
    const to = Date.now()
    const resp = await queryHistory(pid, {
      keys: [key],
      from: to - rangeMs.value,
      to,
      stepMs: Math.max(1000, Math.floor(rangeMs.value / bucketCount.value)),
      maxPoints: bucketCount.value,
      agg: 'last',
    })
    rows.value = buildHistoryRows(resp.series[key], bucketCount.value)
  } catch {
    // 失败静默：保留上次数据（提示由 http 拦截器统一弹出，历史快照表不闪空）
  } finally {
    fetching = false
  }
}

onMounted(() => {
  void refresh()
  timer = setInterval(() => void refresh(), REFRESH_MS)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
  timer = null
})
</script>

<template>
  <div class="history-table">
    <table v-if="displayRows.length">
      <thead>
        <tr>
          <th class="col-time">时间</th>
          <th class="col-value">值</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in displayRows" :key="row.ts">
          <td class="cell-time">{{ row.time }}</td>
          <td class="cell-value ws-readout">{{ row.text }}</td>
        </tr>
      </tbody>
    </table>
    <!-- 空态：未绑变量与区间无数据共用（全局 .ws-canvas-empty 骨架，深浅画布均可读） -->
    <div v-else class="ws-canvas-empty">
      {{ variableKey ? '区间内暂无历史数据' : '未绑定变量——在右侧属性选择' }}
    </div>
  </div>
</template>

<style scoped>
.history-table {
  width: 100%;
  height: 100%;
  overflow: auto;
  box-sizing: border-box;
  background: transparent;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

th,
td {
  padding: 4px 10px;
  text-align: left;
  white-space: nowrap;
  color: inherit;
  border-bottom: 1px solid var(--ws-steel-3);
}

/* 表头：透明底（画布底色透过），仅下边线分隔（与 RealtimeTableWidget 同口径） */
th {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--ws-text-2);
  border-bottom: 2px solid var(--ws-steel-3);
}

/* 值列右对齐（数值位对齐），时间列左对齐 */
.col-value,
.cell-value {
  text-align: right;
}
</style>
