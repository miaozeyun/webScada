<script setup lang="ts">
/**
 * 模拟数据配置（数据源 tab 顶部入口「配置模拟数据」）。
 *
 * 集中配置所有「模拟」数据源下变量的波形（正弦/三角/随机/方波/保持），以及保持型的定值。
 * 只是 mock 变量的便捷编辑器——变量本身仍在「变量」tab 增删；值由服务端 collector
 * MockSource 按波形生成，运行态经 /api/v1/ws/runtime 推送，本面板不造数、不建额外 WS。
 *
 * 波形属于 doc 数据：改动直接改 editor.doc 并 _markDirty（3s 防抖保存 + 服务端差量重载），
 * 与变量表单里的「模拟波形」是同一份字段（不另存一套）。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { useEditorStore } from '@/stores/editor'
import { getVariableValues, type VariableValueEntry } from '@/api/projects'
import type { DataSource, MockSpec, SimProtocol, VariableDef } from '@/types/doc'

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{
  (e: 'update:visible', v: boolean): void
  (e: 'add-variable', dsId: string): void
}>()

const editor = useEditorStore()

const PROTO_LABEL: Record<SimProtocol, string> = {
  websocket: 'WebSocket',
  rest: 'REST',
  mqtt: 'MQTT',
  modbus: 'Modbus TCP',
  opcua: 'OPC UA',
}

type MockSource = Extract<DataSource, { type: 'mock' }>

const mockSources = computed<MockSource[]>(
  () => (editor.doc?.datasources ?? []).filter((d): d is MockSource => d.type === 'mock'),
)

/** 行模型：把 MockSpec 联合类型拍平成可编辑字段（Vue 模板里不做类型窄化） */
interface MockRow {
  v: VariableDef
  dsId: string
  dsName: string
  dsProtocol: SimProtocol | null
  kind: MockSpec['kind']
  min: number
  max: number
  periodMs: number
  intervalMs: number
  /** 保持型：当前默认值（文本形态，按变量类型回写） */
  holdValue: string
}

const KIND_OPTIONS: { label: string; value: MockSpec['kind'] }[] = [
  { label: '正弦', value: 'sine' },
  { label: '三角', value: 'ramp' },
  { label: '随机', value: 'random' },
  { label: '方波', value: 'square' },
  { label: '保持（定值）', value: 'hold' },
]

const filterDs = ref('')

function specOf(v: VariableDef): MockSpec {
  return v.mock ?? { kind: 'sine', min: 0, max: 100, periodMs: 30000 }
}

const rows = computed<MockRow[]>(() => {
  const out: MockRow[] = []
  for (const v of editor.doc?.variables ?? []) {
    if (v.expr) continue // 虚拟变量由表达式驱动，不参与模拟
    const ds = mockSources.value.find((d) => d.id === v.datasourceId)
    if (!ds) continue
    if (filterDs.value && ds.id !== filterDs.value) continue
    const spec = specOf(v)
    out.push({
      v,
      dsId: ds.id,
      dsName: ds.name,
      dsProtocol: ds.config?.simProtocol ?? null,
      kind: spec.kind,
      min: 'min' in spec ? spec.min : 'offValue' in spec ? spec.offValue : 0,
      max: 'max' in spec ? spec.max : 'onValue' in spec ? spec.onValue : 100,
      periodMs: 'periodMs' in spec ? spec.periodMs : 30000,
      intervalMs: spec.kind === 'random' ? spec.intervalMs : 1000,
      holdValue: v.defaultValue === null || v.defaultValue === undefined ? '' : String(v.defaultValue),
    })
  }
  return out
})

/** el-input-number 清空时 v-model 会变 null：回退缺省值，避免把 null 写进 MockSpec 触发 422 */
function num(v: unknown, fallback: number): number {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : fallback
}

/** 行 → MockSpec 回写（与 DataDrawer.buildMock 口径一致：方波用 min/max 当关/开值） */
function applyRow(row: MockRow): void {
  const min = num(row.min, 0)
  const max = num(row.max, 100)
  switch (row.kind) {
    case 'sine':
    case 'ramp':
      row.v.mock = { kind: row.kind, min, max, periodMs: Math.max(500, num(row.periodMs, 30000)) }
      break
    case 'random':
      row.v.mock = { kind: 'random', min, max, intervalMs: Math.max(100, num(row.intervalMs, 1000)) }
      break
    case 'square':
      row.v.mock = { kind: 'square', onValue: max, offValue: min, periodMs: Math.max(500, num(row.periodMs, 30000)) }
      break
    case 'hold':
      row.v.mock = { kind: 'hold' }
      break
  }
  editor._markDirty()
}

/** 保持型定值：按变量类型转换，空串 = 清空（启动时不再推初值） */
function applyHold(row: MockRow): void {
  const raw = row.holdValue.trim()
  if (raw === '') {
    row.v.defaultValue = null
  } else if (row.v.type === 'number') {
    const n = Number(raw)
    if (!Number.isFinite(n)) {
      ElMessage.warning('定值需为数字')
      row.holdValue = row.v.defaultValue === null || row.v.defaultValue === undefined ? '' : String(row.v.defaultValue)
      return
    }
    row.v.defaultValue = n
  } else if (row.v.type === 'boolean') {
    row.v.defaultValue = raw === 'true' || raw === '1'
  } else {
    row.v.defaultValue = raw
  }
  editor._markDirty()
}

// ---- 实时值：打开期间 2s 轮询（复用 /projects/:id/values，不建 WS）----
const values = ref<Record<string, VariableValueEntry>>({})
const loading = ref(false)
let timer: number | null = null

async function refresh(): Promise<void> {
  if (!editor.projectId) return
  loading.value = true
  try {
    const resp = await getVariableValues(editor.projectId)
    values.value = resp.values ?? {}
  } catch {
    /* 未保存/未运行/无权限：保持上次快照 */
  } finally {
    loading.value = false
  }
}

function stopPolling(): void {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
}

watch(
  () => props.visible,
  (v) => {
    if (v) {
      void refresh()
      timer = window.setInterval(refresh, 2000)
    } else {
      stopPolling()
    }
  },
)
onBeforeUnmount(stopPolling)

function valueText(key: string): string {
  const e = values.value[key]
  if (!e || e.v == null) return '—'
  if (typeof e.v === 'number') return Number.isInteger(e.v) ? String(e.v) : e.v.toFixed(2)
  return String(e.v)
}

function qualityOf(key: string): { label: string; type: 'success' | 'warning' | 'danger' | 'info' } {
  const entry = values.value[key]
  if (!entry) return { label: '—', type: 'info' }
  if (entry.q === 'stale') return { label: '停更', type: 'warning' }
  if (entry.q === 'bad') return { label: '坏值', type: 'danger' }
  return { label: '正常', type: 'success' }
}

function protoText(p: SimProtocol | null): string {
  return p ? PROTO_LABEL[p] : ''
}

function addSignal(): void {
  emit('add-variable', filterDs.value || mockSources.value[0]?.id || '')
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    title="配置模拟数据"
    width="880px"
    append-to-body
    @update:model-value="emit('update:visible', $event)"
  >
    <div class="mock-bar">
      <el-select v-model="filterDs" size="small" clearable placeholder="全部模拟数据源" style="width: 190px">
        <el-option v-for="d in mockSources" :key="d.id" :label="d.name" :value="d.id" />
      </el-select>
      <el-button size="small" :icon="Refresh" :loading="loading" @click="refresh">刷新实时值</el-button>
      <el-button size="small" type="primary" plain :icon="Plus" @click="addSignal">新增模拟信号</el-button>
      <span class="hint">波形改动保存后 1~2 秒生效</span>
    </div>

    <el-table
      :data="rows"
      size="small"
      max-height="440"
      empty-text="暂无模拟变量：先在「变量」tab 给模拟数据源添加变量"
    >
      <el-table-column label="数据源" width="136">
        <template #default="{ row }">
          <span>{{ row.dsName }}</span>
          <el-tag v-if="row.dsProtocol" size="small" type="info" class="proto-tag">
            {{ protoText(row.dsProtocol) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="变量" min-width="132">
        <template #default="{ row }">
          <div class="cell-mono">{{ row.v.key }}</div>
          <div class="var-label">{{ row.v.label }}</div>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="64">
        <template #default="{ row }">{{ row.v.type }}</template>
      </el-table-column>
      <el-table-column label="波形" width="120">
        <template #default="{ row }">
          <el-select v-model="row.kind" size="small" @change="applyRow(row)">
            <el-option v-for="o in KIND_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="取值（低 / 高）" width="200">
        <template #default="{ row }">
          <template v-if="row.kind !== 'hold'">
            <el-input-number
              v-model="row.min"
              size="small"
              controls-position="right"
              class="num-sm"
              @change="applyRow(row)"
            />
            <span class="tilde">~</span>
            <el-input-number
              v-model="row.max"
              size="small"
              controls-position="right"
              class="num-sm"
              @change="applyRow(row)"
            />
          </template>
          <el-input
            v-else
            v-model="row.holdValue"
            size="small"
            placeholder="定值"
            class="hold-input"
            @change="applyHold(row)"
          />
        </template>
      </el-table-column>
      <el-table-column label="周期 / 间隔" width="118">
        <template #default="{ row }">
          <el-input-number
            v-if="row.kind === 'random'"
            v-model="row.intervalMs"
            size="small"
            :min="100"
            :step="100"
            controls-position="right"
            class="num-sm"
            @change="applyRow(row)"
          />
          <el-input-number
            v-else-if="row.kind !== 'hold'"
            v-model="row.periodMs"
            size="small"
            :min="500"
            :step="500"
            controls-position="right"
            class="num-sm"
            @change="applyRow(row)"
          />
          <span v-else class="hint">—</span>
        </template>
      </el-table-column>
      <el-table-column label="当前值" width="122">
        <template #default="{ row }">
          <span class="cell-mono">{{ valueText(row.v.key) }}</span>
          <el-tag v-if="values[row.v.key]" size="small" :type="qualityOf(row.v.key).type" class="quality-tag">
            {{ qualityOf(row.v.key).label }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>

    <div class="hint footer-hint">
      「模拟 · WebSocket / MQTT / …」只是数据源的协议标注，生成方式与通用模拟一致；需要真实协议报文时，
      请改用对应类型的数据源并接上游服务。
    </div>

    <template #footer>
      <el-button @click="emit('update:visible', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.mock-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.hint {
  color: var(--ws-text-3);
  font-size: 12px;
}

.mock-bar .hint {
  margin-left: auto;
}

.footer-hint {
  margin-top: 10px;
  line-height: 1.6;
}

.num-sm {
  width: 80px;
}

.tilde {
  margin: 0 3px;
  color: var(--ws-text-3);
}

.hold-input {
  width: 112px;
}

.proto-tag {
  margin-left: 4px;
}

.var-label {
  color: var(--ws-text-3);
  font-size: 11px;
}

.cell-mono {
  font-family: var(--ws-font-mono, monospace);
  font-size: 12px;
  word-break: break-all;
}

.quality-tag {
  margin-left: 4px;
}
</style>
