<script setup lang="ts">
/**
 * 实时表格（工厂可用阶段二 Task 6）：按数据列清单逐变量取实时值成表（参数列表形态，
 * 每列定义 = 一行「参数 | 当前值」，沿既有静态表格组件的参数列表语义）。
 * 取值走 WidgetHost 既有绑定通道的运行态变量池（useRuntimeStore 的 values/varByKey/
 * degradedVars/activeAlarms，与 WidgetHost S1/S2 同源），不自接 WS、不经绑定数组。
 * 质量位非 good 灰显（--ws-text-3）、报警行警示色（--ws-alert，优先级高于灰显，同 K12 口径）。
 * columns JSON：[{key,label,precision?,unit?}]（key=变量 key；precision/unit 缺省回落变量定义，
 * 分享页无 editor doc——需在列内显式配置才能生效）。
 */
import { computed } from 'vue'
import type { VariableDef } from '@/types/doc'
import { useRuntimeStore } from '@/runtime/store'
import { useEditorStore } from '@/stores/editor'
import { buildRealtimeRows, type RealtimeColumnDef, type RealtimeRow, type RealtimeVarCell } from '@/utils/tableRows'

const props = defineProps<{ nodeProps: Record<string, unknown> }>()

const runtime = useRuntimeStore()
const editor = useEditorStore()

/** 数据列清单：JSON 解析（坏输入回落空清单 → 空态提示，不抛错打断画布） */
const columns = computed<RealtimeColumnDef[]>(() => {
  try {
    const parsed: unknown = JSON.parse(String(props.nodeProps.columns ?? '[]'))
    if (!Array.isArray(parsed)) return []
    return parsed.filter((c): c is RealtimeColumnDef => {
      if (!c || typeof c !== 'object') return false
      const o = c as Record<string, unknown>
      return typeof o.key === 'string' && o.key !== '' && typeof o.label === 'string'
    })
  } catch {
    return []
  }
})

const colByKey = computed<Map<string, RealtimeColumnDef>>(() => new Map(columns.value.map((c) => [c.key, c])))

/** 变量定义索引（key → VariableDef）：编辑器/预览可用；分享页 editor.doc 为空，precision/unit 须列内显式配置 */
const varDefsByKey = computed<Map<string, VariableDef>>(() => {
  const m = new Map<string, VariableDef>()
  for (const v of editor.doc?.variables ?? []) m.set(v.key, v)
  return m
})

/** 活动报警涉及的变量 key 集：服务端帧带 variableKey 直用；编辑器本地引擎事件（id=规则 id）
 *  按 规则→variableId→key 反查——与 WidgetHost resolveAlarmVarId 同口径 */
const alarmKeys = computed<Set<string>>(() => {
  const keys = new Set<string>()
  if (!runtime.running) return keys
  for (const ev of runtime.activeAlarms.values()) {
    const active = ev.status
      ? ev.status === 'triggered' || ev.status === 'acked'
      : ev.type === 'active'
    if (!active) continue
    if (ev.variableKey) {
      keys.add(ev.variableKey)
      continue
    }
    const varId = editor.doc?.alarmRules.find((r) => r.id === ev.id)?.variableId
    if (!varId) continue
    for (const [key, id] of runtime.varByKey) {
      if (id === varId) {
        keys.add(key)
        break
      }
    }
  }
  return keys
})

/** getVar：key → 单元格（未知 key 返回 undefined → '--' 空行）；读运行态响应式 Map，值变即重算 */
function getVar(key: string): RealtimeVarCell | undefined {
  const varId = runtime.varByKey.get(key)
  if (!varId) return undefined
  return {
    // 无值（未上报/编辑态）→ null → '--'；bad 质量位由引擎保留上一显示值，不闪空
    value: runtime.values.get(varId) ?? null,
    quality: runtime.degradedVars.get(varId) ?? 'good',
    alarm: alarmKeys.value.has(key),
    precision: colByKey.value.get(key)?.precision ?? varDefsByKey.value.get(key)?.precision ?? undefined,
  }
}

const rows = computed<RealtimeRow[]>(() => buildRealtimeRows(columns.value, getVar))

const showQuality = computed(() => props.nodeProps.showQuality === true)
const showUnit = computed(() => props.nodeProps.showUnit !== false)

/** 单位：列内显式 → 变量定义；占位 '--' 行不拼（避免「-- ℃」歧义） */
function unitText(row: RealtimeRow): string {
  if (!showUnit.value || row.text === '--') return ''
  const col = colByKey.value.get(row.key)
  if (typeof col?.unit === 'string') return col.unit
  return varDefsByKey.value.get(row.key)?.unit ?? ''
}

/** 质量位文案（03 §2.10：good=有效 / stale=超时值保留 / bad=不可信） */
function qualityText(q: RealtimeRow['quality']): string {
  return q === 'good' ? '正常' : q === 'stale' ? '超时' : '异常'
}
</script>

<template>
  <div class="realtime-table">
    <table v-if="rows.length">
      <thead>
        <tr>
          <th class="col-label">参数</th>
          <th class="col-value">当前值</th>
          <th v-if="showQuality" class="col-q">质量</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.key" :class="{ 'row-alarm': row.alarm }">
          <td class="cell-label" :class="{ dim: row.dim && !row.alarm }">{{ row.label }}</td>
          <td class="cell-value ws-readout" :class="{ dim: row.dim && !row.alarm }">
            {{ row.text }}<span v-if="unitText(row)" class="unit">{{ unitText(row) }}</span>
          </td>
          <td v-if="showQuality" class="cell-q" :class="`q-${row.quality}`">{{ qualityText(row.quality) }}</td>
        </tr>
      </tbody>
    </table>
    <!-- 空态：未配置/坏 JSON 共用（全局 .ws-canvas-empty 骨架，深浅画布均可读） -->
    <div v-else class="ws-canvas-empty">未配置数据列——在右侧属性填写 columns JSON</div>
  </div>
</template>

<style scoped>
.realtime-table {
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

/* 表头：透明底（画布底色透过），仅下边线分隔 */
th {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--ws-text-2);
  border-bottom: 2px solid var(--ws-steel-3);
}

.col-value,
.cell-value {
  text-align: right;
}

.col-q,
.cell-q {
  text-align: right;
}

/* 质量位非 good 灰显（03 §2.10）：stale/bad 值不可信，用弱化文字色表达 */
.dim {
  color: var(--ws-text-3);
}

/* 报警行警示色（优先级高于灰显：报警态须强调，同 WidgetHost S2 > S1 口径） */
.row-alarm .cell-value {
  color: var(--ws-alert);
  font-weight: 600;
}

.unit {
  margin-left: 4px;
  font-size: 0.85em;
  color: inherit;
  opacity: 0.7;
}

/* 质量列：超时警示黄 / 异常警示红（正常为辅助灰，弱化不抢值列） */
.cell-q.q-good {
  color: var(--ws-text-3);
}
.cell-q.q-stale {
  color: var(--ws-warn);
}
.cell-q.q-bad {
  color: var(--ws-alert);
}
</style>
