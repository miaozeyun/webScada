<script setup lang="ts">
/**
 * 报警列表面板（M8 工作包 D，契约 §4.1 消费端）：
 * REST 拉取（GET /projects/{id}/alarms）+ 过滤（状态/级别/变量前缀/触发时间区间）+ 分页 + 确认（ack）。
 * 角色控制：/auth/me 的 role 为 viewer 或未登录（分享页）时隐藏确认按钮，operator/admin 可见。
 * 联动刷新：① 任意组件 REST ack 成功（webscada:alarm-acked 事件，api/alarms 派发）；
 *          ② 同工程在线连接的 alarm/alarmClear/alarmAck WS 帧经 runtime store 事件流到达（alarmEvents 增量）。
 * 存量兼容：未知 status/level 一律灰显兜底（契约 §11.8）。
 * 挂接：由宿主（运行页/编辑器抽屉）提供 projectId；组件自身不负责布局容器。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import type { AlarmLevel } from '@/types/doc'
import {
  ackAlarm,
  fetchMyRole,
  listAlarms,
  onAlarmAcked,
  type AlarmOut,
  type UserRole,
} from '@/api/alarms'
import { useRuntimeStore } from '@/runtime/store'

const props = withDefaults(
  defineProps<{
    projectId: string
    /** 轮询刷新间隔（秒）；0=关闭。独立报警中心没有运行态引擎，靠它保持列表新鲜 */
    autoRefreshSec?: number
  }>(),
  { autoRefreshSec: 0 },
)

const runtime = useRuntimeStore()

const rows = ref<AlarmOut[]>([])
const total = ref(0)
const loading = ref(false)
const lastLoadedAt = ref('')
/** 自动刷新失败标记：轮询请求静默（不弹 toast），由这里给出可见但克制的失败提示 */
const lastError = ref(false)

/** 系统级报警（通讯中断）变量 key 为 __comm__:<dsId>，列表里显示可读标签 */
function keyText(key: string): string {
  return key.startsWith('__comm__:') ? '通讯中断' : key
}

// ---- 过滤条件 ----

/** 状态多选；缺省勾选=未恢复集合（与服务端缺省口径一致，契约 §4.1）；清空=回落缺省（不传 status） */
const STATUS_OPTIONS = [
  { value: 'triggered', label: '触发' },
  { value: 'acked', label: '已确认' },
  { value: 'cleared', label: '已恢复' },
]
const statusFilter = ref<string[]>(['triggered', 'acked'])
const levelFilter = ref<AlarmLevel | ''>('')
const keyFilter = ref('')
const rangeFilter = ref<[Date, Date] | null>(null)
const page = ref(1)
const size = ref(20)

/** 请求序号：WS 帧 + 轮询 + 手动刷新可能并发，只允许最后发出的请求落表（防旧响应覆盖新结果） */
let loadSeq = 0

/**
 * @param silent 不显示表格 loading 遮罩（后台刷新）
 * @param quiet  请求失败不弹全局提示（默认随 silent；轮询失败不应每轮刷一条 toast）
 */
async function load(silent = false, quiet = silent): Promise<void> {
  if (!props.projectId) return
  const seq = ++loadSeq
  if (!silent) loading.value = true
  try {
    const params: Parameters<typeof listAlarms>[1] = {
      status: statusFilter.value,
      page: page.value,
      size: size.value,
    }
    if (levelFilter.value) params.level = levelFilter.value
    if (keyFilter.value.trim()) params.variableKey = keyFilter.value.trim()
    if (rangeFilter.value) {
      params.from = rangeFilter.value[0].toISOString()
      params.to = rangeFilter.value[1].toISOString()
    }
    const resp = await listAlarms(props.projectId, params, { silent: quiet })
    if (seq !== loadSeq) return // 已有更新的请求在途
    rows.value = resp.items ?? []
    total.value = resp.total ?? 0
    lastLoadedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    lastError.value = false
  } catch {
    if (seq === loadSeq) lastError.value = true
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

/** 静默刷新合帧：报警风暴时 WS 每帧都会触发，直接调用会把 REST 打爆 */
let silentTimer: ReturnType<typeof setTimeout> | null = null
function scheduleSilentReload(): void {
  if (silentTimer) clearTimeout(silentTimer)
  silentTimer = setTimeout(() => {
    silentTimer = null
    void load(true)
  }, 600)
}

// 过滤变化回第一页重查；变量 key 输入 300ms 防抖
watch([statusFilter, levelFilter, rangeFilter], () => {
  page.value = 1
  void load()
})
let keyDebounce: ReturnType<typeof setTimeout> | null = null
watch(keyFilter, () => {
  if (keyDebounce) clearTimeout(keyDebounce)
  keyDebounce = setTimeout(() => {
    page.value = 1
    void load()
  }, 300)
})
watch([page, size], () => void load())
watch(
  () => props.projectId,
  () => {
    page.value = 1
    void load()
  },
)

// ---- 角色与确认（ack） ----

const role = ref<UserRole | null>(null)
/** viewer / 未登录 / 角色未知 一律不可确认（契约：operator/admin） */
const canAck = computed(() => role.value === 'admin' || role.value === 'operator')

async function onAck(row: AlarmOut): Promise<void> {
  let note: string | undefined
  try {
    const { value } = await ElMessageBox.prompt('确认该条报警？可填写处理说明（≤256 字符）。', '报警确认', {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      inputPlaceholder: '处理说明（可选）',
      inputValidator: (v: string) => !v || v.length <= 256 || '说明不超过 256 字符',
    })
    note = value?.trim() || undefined
  } catch {
    return // 用户取消
  }
  try {
    await ackAlarm(props.projectId, row.id, note)
    ElMessage.success(`报警 #${row.id} 已确认`)
    void load(true)
  } catch {
    /* 失败已由 http 拦截器提示（403=无权限 / 404=报警不存在） */
  }
}

// ---- 联动刷新 ----

let offAcked: (() => void) | null = null
let stopEventsWatch: (() => void) | null = null
let stopAckWatch: (() => void) | null = null
let autoTimer: number | null = null

/** 自动刷新定时器（独立报警中心无 WS 引擎，靠轮询兜底；切到后台时暂停请求） */
function syncAutoTimer(): void {
  if (autoTimer !== null) {
    clearInterval(autoTimer)
    autoTimer = null
  }
  if (props.autoRefreshSec > 0) {
    autoTimer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void load(true)
    }, props.autoRefreshSec * 1000)
  }
}

onMounted(async () => {
  role.value = await fetchMyRole()
  void load()
  syncAutoTimer()
  // 同宿主其它组件（如报警横幅）REST ack 成功 → 静默刷新当前页
  offAcked = onAlarmAcked(scheduleSilentReload)
  // WS alarm/alarmClear/alarmAck 帧经 runtime 事件流到达（A 包 server 模式写入）→ 合帧后静默刷新
  stopEventsWatch = watch(() => runtime.alarmEvents.length, scheduleSilentReload)
  // 远端 alarmAck 帧（他端确认）不经过 alarmEvents：经 serverAckedAlarmIds 登记后触发静默刷新，
  // 避免他端已确认、本端停留「未确认」
  stopAckWatch = watch(() => runtime.serverAckedAlarmIds.size, scheduleSilentReload)
})
watch(() => props.autoRefreshSec, syncAutoTimer)
onBeforeUnmount(() => {
  offAcked?.()
  stopEventsWatch?.()
  stopAckWatch?.()
  if (keyDebounce) clearTimeout(keyDebounce)
  if (silentTimer) clearTimeout(silentTimer)
  if (autoTimer !== null) clearInterval(autoTimer)
})

// ---- 展示映射（未知值灰显兜底） ----

interface TagMeta {
  label: string
  type: 'danger' | 'warning' | 'success' | 'info'
}

const STATUS_META: Record<string, TagMeta> = {
  triggered: { label: '触发', type: 'danger' },
  acked: { label: '已确认', type: 'warning' },
  cleared: { label: '已恢复', type: 'success' },
}
const LEVEL_META: Record<string, TagMeta> = {
  critical: { label: '严重', type: 'danger' },
  warn: { label: '警告', type: 'warning' },
  info: { label: '信息', type: 'info' },
}

function statusMeta(s: string): TagMeta {
  return STATUS_META[s] ?? { label: `${s}（未知）`, type: 'info' }
}
function levelMeta(l: string): TagMeta {
  return LEVEL_META[l] ?? { label: `${l}（未知）`, type: 'info' }
}

/** REST 时间（ISO8601 UTC）→ 本地可读格式 */
function fmtTime(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number): string => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}
</script>

<template>
  <div class="alarm-panel">
    <div class="toolbar">
      <el-select v-model="statusFilter" multiple collapse-tags clearable placeholder="状态（缺省未恢复）" class="f-status">
        <el-option v-for="o in STATUS_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
      </el-select>
      <el-select v-model="levelFilter" clearable placeholder="级别" class="f-level">
        <el-option label="严重" value="critical" />
        <el-option label="警告" value="warn" />
        <el-option label="信息" value="info" />
      </el-select>
      <el-input v-model="keyFilter" clearable placeholder="变量 key 前缀" class="f-key" />
      <el-date-picker
        v-model="rangeFilter"
        type="datetimerange"
        start-placeholder="触发起"
        end-placeholder="触发止"
        class="f-range"
      />
      <span
        v-if="autoRefreshSec > 0"
        class="auto-hint"
        :class="{ 'is-error': lastError }"
        :title="lastError ? '上次自动刷新失败，稍后自动重试' : `每 ${autoRefreshSec} 秒自动刷新，切到后台时暂停`"
      >
        <span class="live-dot" aria-hidden="true" />
        {{ lastError ? '自动刷新失败' : '自动刷新' }}
        <span v-if="lastLoadedAt" class="auto-time ws-readout">· {{ lastLoadedAt }}</span>
      </span>
      <el-button :icon="Refresh" :loading="loading" @click="load()">刷新</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" size="small" class="table" empty-text="当前筛选条件下没有报警记录">
      <el-table-column label="级别" width="84">
        <template #default="{ row }">
          <el-tag :type="levelMeta(row.level).type" :effect="LEVEL_META[row.level] ? 'light' : 'plain'" size="small">
            {{ levelMeta(row.level).label }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="变量" min-width="110" show-overflow-tooltip>
        <template #default="{ row }">{{ keyText(row.variableKey) }}</template>
      </el-table-column>
      <el-table-column label="报警内容" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">
          <span>{{ row.message }}</span>
          <span v-if="row.value !== null && row.value !== undefined" class="cell-val">（{{ row.value }}）</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="92">
        <template #default="{ row }">
          <el-tag :type="statusMeta(row.status).type" :effect="STATUS_META[row.status] ? 'light' : 'plain'" size="small">
            {{ statusMeta(row.status).label }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="触发时间" width="150">
        <template #default="{ row }">{{ fmtTime(row.triggeredAt) }}</template>
      </el-table-column>
      <el-table-column label="恢复时间" width="150">
        <template #default="{ row }">{{ fmtTime(row.clearedAt) }}</template>
      </el-table-column>
      <el-table-column label="确认信息" min-width="150" show-overflow-tooltip>
        <template #default="{ row }">
          <span v-if="row.ackedAt" :title="row.ackedNote || ''">{{ row.ackedBy || '—' }} · {{ fmtTime(row.ackedAt) }}</span>
          <span v-else class="cell-unacked">未确认</span>
        </template>
      </el-table-column>
      <el-table-column v-if="canAck" label="操作" width="96" align="center">
        <template #default="{ row }">
          <el-button v-if="!row.ackedAt" type="warning" size="small" plain @click="onAck(row)">
            {{ row.status === 'cleared' ? '补确认' : '确认' }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="size"
        :total="total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        size="small"
        background
      />
    </div>
  </div>
</template>

<style scoped>
.alarm-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
  min-height: 0;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.f-status {
  width: 230px;
}

.f-level {
  width: 110px;
}

.f-key {
  width: 170px;
}

.f-range {
  max-width: 360px;
}

.auto-hint {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-left: auto;
  padding-right: 4px;
  font-size: 11px;
  color: var(--ws-text-3);
  white-space: nowrap;
}

.live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--ws-signal);
  box-shadow: 0 0 0 3px var(--ws-signal-a12);
}

.auto-hint.is-error {
  color: var(--ws-alert);
}

.auto-hint.is-error .live-dot {
  background: var(--ws-alert);
  box-shadow: 0 0 0 3px var(--ws-alert-a16);
}

.auto-time {
  font-size: 11px;
  color: var(--ws-text-3);
}

.table {
  flex: 1;
  min-height: 0;
}

.cell-val {
  color: var(--ws-text-3);
  font-family: var(--ws-font-tech);
  font-variant-numeric: tabular-nums;
}

.cell-unacked {
  color: var(--ws-alert);
}

.pager {
  display: flex;
  justify-content: flex-end;
  flex-shrink: 0;
}
</style>
