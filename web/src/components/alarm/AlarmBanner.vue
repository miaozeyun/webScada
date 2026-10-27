<script setup lang="ts">
/**
 * 报警横幅（M8 工作包 D）：运行态顶部展示当前活动报警（alarm/alarmClear WS 帧 → runtime store 联动）。
 * - 排序：级别 critical > warn > info 优先，同级按触发时间倒序；最多展示 maxShow 条，尾部提示「另有 N 条」。
 * - 快捷确认（ack）：按 /auth/me 角色显隐（viewer/未登录隐藏，operator/admin 可见），须传入 projectId
 *   且条目携带服务端报警 id（alarmId/数字 id；前端引擎本地事件仅 ruleId，无 ack 按钮）；成功后经
 *   api/alarms 派发 ack 联动事件，AlarmPanel 等同宿主组件自动刷新。
 * - 存量兼容：未知 level 灰显标签 + 安全橙兜底强调色（契约 §11.8）。
 * 挂接：宿主置于运行画面上方（如 RuntimeStage 顶栏之下）；无活动报警时组件整体不渲染。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowDown, ArrowUp, Close, Promotion } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRuntimeStore } from '@/runtime/store'
import { useEditorStore } from '@/stores/editor'
import { ackAlarm, fetchMyRole, resolveLevelColors, type UserRole } from '@/api/alarms'

const props = withDefaults(
  defineProps<{
    /** ack 用工程 id；缺省（未接入宿主上下文）时不显示确认按钮 */
    projectId?: string
    /** 最多展示条数，超出折叠为「另有 N 条」 */
    maxShow?: number
  }>(),
  { projectId: '', maxShow: 3 },
)

const runtime = useRuntimeStore()
const editor = useEditorStore()

/** 报警事件宽松形态（兼容前端引擎事件与 M8 服务端帧映射） */
interface AlarmEventLike {
  id: string | number
  type?: 'active' | 'recovered'
  level?: string
  message?: string
  value?: number | boolean | string
  at?: number
  status?: string
  variableKey?: string
  variableId?: string
  ruleId?: string
  alarmId?: number
}

const LEVEL_RANK: Record<string, number> = { critical: 3, warn: 2, info: 1 }
const LEVEL_LABEL: Record<string, string> = { critical: '严重', warn: '警告', info: '信息' }

function isAlarmActive(e: AlarmEventLike): boolean {
  if (e.status) return e.status === 'triggered' || e.status === 'acked'
  return e.type === 'active'
}

/** 服务端报警数字 id：alarmId 字段或数字形态 id（前端引擎本地事件 id 为 ruleId 字符串，不可 ack） */
function alarmIdOf(e: AlarmEventLike): number | null {
  if (typeof e.alarmId === 'number') return e.alarmId
  if (typeof e.id === 'number') return e.id
  return null
}

const levelColors = computed(() => resolveLevelColors(editor.doc?.settings.alarm.levelColors))

function levelColor(level: string): string {
  if (level === 'info' || level === 'warn' || level === 'critical') return levelColors.value[level]
  // 未知级别：灰显标签，强调色用安全橙兜底（报警不可无色）
  return 'var(--ws-alert)'
}

/** 本地关闭的单条（非响应式集合，经 refreshTick 触发重算；恢复帧到达后自然从 store 移除） */
const dismissed = new Set<string | number>()
const refreshTick = ref(0)

/** 当前活动报警（已排除本屏隐藏）：级别优先、同级按触发时间倒序 */
const activeItems = computed<AlarmEventLike[]>(() => {
  void refreshTick.value
  const list: AlarmEventLike[] = []
  for (const ev of runtime.activeAlarms.values()) {
    const e = ev as unknown as AlarmEventLike
    if (!isAlarmActive(e) || dismissed.has(e.id)) continue
    list.push(e)
  }
  list.sort((a, b) => {
    const ra = LEVEL_RANK[a.level ?? ''] ?? -1
    const rb = LEVEL_RANK[b.level ?? ''] ?? -1
    if (ra !== rb) return rb - ra
    return (b.at ?? 0) - (a.at ?? 0)
  })
  return list
})

const collapsed = ref(false)
const shownItems = computed(() => (collapsed.value ? [] : activeItems.value.slice(0, props.maxShow)))
const restCount = computed(() => Math.max(0, activeItems.value.length - shownItems.value.length))

function dismiss(e: AlarmEventLike): void {
  dismissed.add(e.id)
  refreshTick.value++
}

/** 报警恢复后从「本屏隐藏」集合里清掉，避免值班长跑时集合无界增长 */
function pruneDismissed(): void {
  if (!dismissed.size) return
  for (const id of [...dismissed]) {
    let stillActive = false
    for (const key of runtime.activeAlarms.keys()) {
      if (String(key) === String(id)) {
        stillActive = true
        break
      }
    }
    if (!stillActive) dismissed.delete(id)
  }
}

watch(() => runtime.activeAlarms.size, pruneDismissed)

// ---- 角色与快捷确认 ----

const role = ref<UserRole | null>(null)
const canAck = computed(() => !!props.projectId && (role.value === 'admin' || role.value === 'operator'))

async function onAck(e: AlarmEventLike): Promise<void> {
  const alarmId = alarmIdOf(e)
  if (!alarmId || !props.projectId) return
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
    await ackAlarm(props.projectId, alarmId, note)
    ElMessage.success(`报警 #${alarmId} 已确认`)
  } catch {
    /* 失败已由 http 拦截器提示（403=无权限） */
  }
}

onMounted(async () => {
  role.value = await fetchMyRole()
})
onBeforeUnmount(() => {
  dismissed.clear()
})

function fmtTime(at?: number): string {
  if (!at) return ''
  const d = new Date(at)
  const p = (n: number): string => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}
</script>

<template>
  <div v-if="activeItems.length > 0" class="alarm-banner" :class="{ collapsed }" role="status" aria-live="polite">
    <div class="summary">
      <span class="badge" :style="{ background: levelColor(activeItems[0].level ?? '') }">
        {{ activeItems.length }}
      </span>
      <span class="summary-text">
        {{ activeItems.length }} 条活动报警
        <template v-if="activeItems[0].message">
          · 最高 {{ LEVEL_LABEL[activeItems[0].level ?? ''] ?? '未知级别' }}：{{ activeItems[0].message }}
        </template>
      </span>
      <el-button
        size="small"
        text
        class="fold-btn"
        :icon="collapsed ? ArrowDown : ArrowUp"
        @click="collapsed = !collapsed"
      >
        {{ collapsed ? '展开' : '收起' }}
      </el-button>
    </div>

    <div v-for="e in shownItems" :key="String(e.id)" class="item" :style="{ borderLeftColor: levelColor(e.level ?? '') }">
      <span class="level-tag" :class="{ unknown: !LEVEL_LABEL[e.level ?? ''] }">
        {{ LEVEL_LABEL[e.level ?? ''] ?? '未知' }}
      </span>
      <span class="msg">{{ e.message }}</span>
      <span v-if="e.value !== undefined && e.value !== null" class="val ws-readout">{{ e.value }}</span>
      <span class="time">{{ fmtTime(e.at) }}</span>
      <el-button v-if="canAck && alarmIdOf(e)" type="warning" size="small" plain :icon="Promotion" @click="onAck(e)">
        确认
      </el-button>
      <el-button size="small" text :icon="Close" class="close-btn" title="本屏隐藏" @click="dismiss(e)" />
    </div>

    <div v-if="restCount > 0" class="rest">另有 {{ restCount }} 条活动报警未展示</div>
  </div>
</template>

<style scoped>
.alarm-banner {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px 10px;
  background: var(--ws-ink);
  border-bottom: 1px solid var(--ws-ink-3);
  flex-shrink: 0;
}

.summary {
  display: flex;
  align-items: center;
  gap: 8px;
}

.badge {
  min-width: 20px;
  padding: 1px 7px;
  border-radius: var(--ws-radius);
  color: #fff;
  font-family: var(--ws-font-tech);
  font-size: 12px;
  font-weight: 700;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

.summary-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ws-text-inverse);
  font-size: 12px;
}

.fold-btn {
  color: var(--ws-inv-75);
}

.fold-btn:hover {
  color: #fff;
}

.item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border-left: 3px solid;
  border-radius: var(--ws-radius);
  background: var(--ws-inv-hover);
}

.level-tag {
  flex-shrink: 0;
  padding: 0 6px;
  border-radius: var(--ws-radius);
  font-size: 11px;
  font-weight: 600;
  color: var(--ws-ink);
  background: var(--ws-inv-88);
}

.level-tag.unknown {
  color: var(--ws-text-inverse);
  background: var(--ws-text-3);
}

.msg {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ws-text-inverse);
  font-size: 12px;
}

.val {
  flex-shrink: 0;
  color: var(--ws-signal-bright);
  font-size: 12px;
}

.time {
  flex-shrink: 0;
  color: var(--ws-inv-60);
  font-family: var(--ws-font-tech);
  font-variant-numeric: tabular-nums;
  font-size: 11px;
}

.item :deep(.el-button) {
  color: var(--ws-inv-75);
}

.item :deep(.el-button--warning.is-plain) {
  color: var(--ws-alert-bright);
  border-color: var(--ws-alert-line);
  background: var(--ws-alert-a16);
}

.item :deep(.el-button--warning.is-plain:hover) {
  color: #fff;
  border-color: var(--ws-alert-bright);
  background: var(--ws-alert-a40);
}

.close-btn:hover {
  color: #fff;
}

.rest {
  color: var(--ws-inv-60);
  font-size: 11px;
  padding-left: 11px;
}
</style>
