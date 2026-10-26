<script setup lang="ts">
/**
 * 工程数据管理（M3/M5）：数据源 / 变量 / 报警规则 / 通知渠道 四表 CRUD（Drawer + el-tabs）。
 * 直接编辑 editor.doc 对应数组并 _markDirty（走 3s 自动保存链路）；
 * doc 级数据不入页面级 undo 栈（历史为页面快照，语义不含本面板）。
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Bell, Download, Plus, Upload } from '@element-plus/icons-vue'
import { useEditorStore } from '@/stores/editor'
import { newId } from '@/utils/nanoid'
import { buildPointCsv, parsePointCsv, POINT_CSV_COLUMNS } from '@/utils/pointCsv'
import { findVariableUsage, variablesOfDatasource } from '@/utils/usage'
import type { PointCsvError, PointCsvRow } from '@/utils/pointCsv'
import { VIRTUAL_DATASOURCE_ID } from '@/types/doc'
import { browseOpcUa, datasourceStatus, testDatasource } from '@/api/datasources'
import type { DatasourceStatus, OpcUaNode } from '@/api/datasources'
import { listDeliveries, type DeliveryOut } from '@/api/notifications'
import { getVariableValues, type VariableValueEntry } from '@/api/projects'
import type {
  AlarmLevel,
  AlarmOp,
  AlarmRule,
  DataSource,
  MockSpec,
  NotifyChannel,
  NotifyChannelKind,
  NotifyLevel,
  VariableDef,
  VariableType,
} from '@/types/doc'

const emit = defineEmits<{ (e: 'close'): void }>()

const editor = useEditorStore()
const router = useRouter()
const tab = ref<'sources' | 'variables' | 'alarms' | 'notify'>('sources')

/** 跳到报警中心（历史/确认在独立页面，本抽屉只管规则配置）；有脏改动先落库 */
async function openAlarmCenter(): Promise<void> {
  if (!editor.projectId) return
  if (editor.dirty) await editor.save()
  void router.push(`/projects/${editor.projectId}/alarms`)
}

const datasources = computed<DataSource[]>(() => editor.doc?.datasources ?? [])
const variables = computed<VariableDef[]>(() => editor.doc?.variables ?? [])
const alarms = computed<AlarmRule[]>(() => editor.doc?.alarmRules ?? [])
const channels = computed<NotifyChannel[]>(() => editor.doc?.settings?.notify?.channels ?? [])

// ---- 最近投递（outbox 可观测）：切到通知 tab 时拉取，回答「到底发出去没有」 ----
const deliveries = ref<DeliveryOut[]>([])
const deliveryLoading = ref(false)

async function loadDeliveries(): Promise<void> {
  if (!editor.projectId) return
  deliveryLoading.value = true
  try {
    const resp = await listDeliveries(editor.projectId, { limit: 50 })
    deliveries.value = resp.items ?? []
  } catch {
    /* http 拦截器已提示 */
  } finally {
    deliveryLoading.value = false
  }
}

// ---- 数据源运行健康 / 变量实时值（2026-10-26）----
const dsStatus = ref<Record<string, DatasourceStatus>>({})
const dsStatusLoading = ref(false)
let dsStatusTimer: number | null = null

async function loadDsStatus(): Promise<void> {
  if (!editor.projectId) return
  dsStatusLoading.value = true
  try {
    const resp = await datasourceStatus(editor.projectId)
    const map: Record<string, DatasourceStatus> = {}
    for (const it of resp.items ?? []) map[it.dsId] = it
    dsStatus.value = map
  } catch {
    /* 拦截器已提示；保持上次快照 */
  } finally {
    dsStatusLoading.value = false
  }
}

function stopDsPolling(): void {
  if (dsStatusTimer !== null) {
    clearInterval(dsStatusTimer)
    dsStatusTimer = null
  }
}

function startDsPolling(): void {
  stopDsPolling()
  void loadDsStatus()
  dsStatusTimer = window.setInterval(loadDsStatus, 5000)
}

const dsStateMeta: Record<string, { label: string; type: 'success' | 'warning' | 'danger' | 'info' }> = {
  ok: { label: '在线', type: 'success' },
  running: { label: '在线', type: 'success' },
  connected: { label: '在线', type: 'success' },
  connecting: { label: '连接中', type: 'warning' },
  starting: { label: '启动中', type: 'info' },
  reconnecting: { label: '重连中', type: 'warning' },
  error: { label: '断线', type: 'danger' },
  stopped: { label: '已停止', type: 'info' },
}

function dsStateOf(id: string): { label: string; type: 'success' | 'warning' | 'danger' | 'info' } {
  const st = dsStatus.value[id]
  if (!st) return { label: '未在采集', type: 'info' }
  return dsStateMeta[st.state] ?? { label: st.state, type: 'info' }
}

function lastOkText(id: string): string {
  const st = dsStatus.value[id]
  if (!st?.lastOkMs) return '—'
  const sec = Math.max(0, Math.round((Date.now() - st.lastOkMs) / 1000))
  if (sec < 60) return `${sec}s 前`
  if (sec < 3600) return `${Math.round(sec / 60)}min 前`
  return `${Math.round(sec / 3600)}h 前`
}

// 变量实时值：仅切到变量 tab 时拉一次（编辑器不建立额外 WS，避免与运行态争用）
const varValues = ref<Record<string, VariableValueEntry>>({})
const varValuesTs = ref(0)
const varValuesLoading = ref(false)

async function loadVarValues(): Promise<void> {
  if (!editor.projectId) return
  varValuesLoading.value = true
  try {
    const resp = await getVariableValues(editor.projectId)
    varValues.value = resp.values ?? {}
    varValuesTs.value = resp.ts ?? Date.now()
  } catch {
    /* hub 未加载/无权限：保持空 */
  } finally {
    varValuesLoading.value = false
  }
}

function varValueText(key: string): string {
  const e = varValues.value[key]
  if (!e || e.v == null) return '—'
  if (typeof e.v === 'number') return Number.isInteger(e.v) ? String(e.v) : e.v.toFixed(2)
  return String(e.v)
}

function varQuality(key: string): { label: string; type: 'success' | 'warning' | 'danger' | 'info' } {
  const entry = varValues.value[key]
  if (!entry) return { label: '—', type: 'info' }
  if (entry.q === 'stale') return { label: '停更', type: 'warning' }
  if (entry.q === 'bad') return { label: '坏值', type: 'danger' }
  return { label: '正常', type: 'success' }
}

watch(tab, (v) => {
  if (v === 'notify') void loadDeliveries()
  if (v === 'sources') startDsPolling()
  else stopDsPolling()
  if (v === 'variables' || v === 'alarms') void loadVarValues()
})

onMounted(() => {
  if (tab.value === 'sources') startDsPolling()
})
onBeforeUnmount(stopDsPolling)

const DELIVERY_META: Record<string, { label: string; type: 'success' | 'warning' | 'danger' | 'info' }> = {
  sent: { label: '已送达', type: 'success' },
  pending: { label: '待补发', type: 'warning' },
  sending: { label: '发送中', type: 'warning' },
  dead: { label: '死信', type: 'danger' },
}

function deliveryMeta(status: string): { label: string; type: 'success' | 'warning' | 'danger' | 'info' } {
  return DELIVERY_META[status] ?? { label: status, type: 'info' }
}

function fmtDeliveryTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number): string => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 变量表搜索（key/名称/地址/单位），200+ 点工程的日常入口 */
const varKeyword = ref('')
const filteredVariables = computed<VariableDef[]>(() => {
  const k = varKeyword.value.trim().toLowerCase()
  if (!k) return variables.value
  return variables.value.filter((v) =>
    v.key.toLowerCase().includes(k)
    || v.label.toLowerCase().includes(k)
    || (v.address ?? '').toLowerCase().includes(k)
    || (v.expr ?? '').toLowerCase().includes(k)
    || (v.unit ?? '').toLowerCase().includes(k),
  )
})

function markDirty(): void {
  editor._markDirty()
}

const TYPE_LABEL: Record<string, string> = { mock: '模拟', websocket: 'WebSocket', rest: 'REST', mqtt: 'MQTT', modbus: 'Modbus TCP', opcua: 'OPC UA' }

// ================= 数据源 =================

const dsVisible = ref(false)
const dsForm = reactive({
  id: '',
  name: '',
  type: 'mock' as DataSource['type'],
  enabled: true,
  url: '',
  topics: '',
  intervalMs: 1000,
  // M7 写通道配置（按类型展示）
  writeUrl: '',
  writeMethod: 'POST' as 'POST' | 'PUT',
  writeBodyTemplate: '',
  writeFrameTemplate: '',
  writeQos: 0 as 0 | 1,
  // Modbus TCP（M8）：host 复用 url 字段
  mbPort: 502,
  mbUnitId: 1,
  // OPC UA（阶段二 Task 8）：endpointUrl 复用 url 字段；密码留空 = 保留库内密文
  ocUsername: '',
  ocPassword: '',
  ocPublishMs: 1000,
  // MQTT 账号（EMQX 已禁用匿名）：密码留空 = 保留库内密文
  mqUsername: '',
  mqPassword: '',
})

function openDs(ds?: DataSource): void {
  dsVisible.value = true
  if (ds) {
    dsForm.id = ds.id
    dsForm.name = ds.name
    dsForm.type = ds.type
    dsForm.enabled = ds.enabled !== false
    dsForm.url = ds.type === 'mqtt' ? ds.config.brokerUrl
      : ds.type === 'modbus' ? ds.config.host
        : ds.type === 'opcua' ? ds.config.endpointUrl
          : ds.type === 'rest' || ds.type === 'websocket' ? ds.config.url : ''
    dsForm.topics = ds.type === 'mqtt' ? (ds.config.topics ?? []).join(', ') : ''
    dsForm.intervalMs = (ds.type === 'rest' || ds.type === 'modbus') ? (ds.config.intervalMs ?? 1000) : 1000
    dsForm.writeUrl = ds.type === 'rest' ? (ds.config.writeUrl ?? '') : ''
    dsForm.writeMethod = ds.type === 'rest' ? (ds.config.writeMethod ?? 'POST') : 'POST'
    dsForm.writeBodyTemplate = ds.type === 'rest' ? (ds.config.writeBodyTemplate ?? '') : ''
    dsForm.writeFrameTemplate = ds.type === 'websocket' ? (ds.config.writeFrameTemplate ?? '') : ''
    dsForm.writeQos = ds.type === 'mqtt' ? (ds.config.writeQos ?? 0) : 0
    if (ds.type === 'modbus') {
      dsForm.mbPort = ds.config.port ?? 502
      dsForm.mbUnitId = ds.config.unitId ?? 1
    }
    dsForm.ocUsername = ds.type === 'opcua' ? (ds.config.username ?? '') : ''
    // 密码出口恒脱敏：留空提交 = 服务端保留库内密文（K11）
    dsForm.ocPassword = ''
    dsForm.ocPublishMs = ds.type === 'opcua' ? (ds.config.publishIntervalMs ?? 1000) : 1000
    dsForm.mqUsername = ds.type === 'mqtt' ? (ds.config.username ?? '') : ''
    dsForm.mqPassword = ''
  } else {
    Object.assign(dsForm, { id: '', name: '', type: 'mock', enabled: true, url: '', topics: '', intervalMs: 1000, writeUrl: '', writeMethod: 'POST' as const, writeBodyTemplate: '', writeFrameTemplate: '', writeQos: 0 as const, mbPort: 502, mbUnitId: 1, ocUsername: '', ocPassword: '', ocPublishMs: 1000, mqUsername: '', mqPassword: '' })
  }
}

// 表单当前值 → 数据源 config（saveDs 与连接测试共用，保证测的就是将保存的）
function buildConfig(): DataSource['config'] {
  switch (dsForm.type) {
    case 'websocket':
      return { url: dsForm.url, writeFrameTemplate: dsForm.writeFrameTemplate || null }
    case 'rest':
      return {
        url: dsForm.url,
        intervalMs: dsForm.intervalMs,
        writeUrl: dsForm.writeUrl || null,
        writeMethod: dsForm.writeUrl ? dsForm.writeMethod : null,
        writeBodyTemplate: dsForm.writeBodyTemplate || null,
      }
    case 'mqtt':
      return {
        brokerUrl: dsForm.url,
        topics: dsForm.topics.split(/[,\n]/).map((s) => s.trim()).filter(Boolean),
        writeQos: dsForm.writeQos,
        // EMQX 禁匿名后必须有账号；密码留空 = 服务端合并库内密文（K11）
        username: dsForm.mqUsername.trim() || null,
        password: dsForm.mqPassword,
      }
    case 'modbus':
      return {
        host: dsForm.url.trim(),
        port: dsForm.mbPort,
        unitId: dsForm.mbUnitId,
        intervalMs: dsForm.intervalMs,
      }
    case 'opcua':
      return {
        endpointUrl: dsForm.url.trim(),
        securityMode: 'none',
        username: dsForm.ocUsername.trim() || null,
        // 留空 = 服务端合并库内密文（K11）；显式填写才覆盖
        password: dsForm.ocPassword,
        publishIntervalMs: dsForm.ocPublishMs,
      }
    default:
      return {}
  }
}

function saveDs(): void {
  if (!dsForm.name.trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  const doc = editor.doc!
  const built = buildConfig()
  const prev = dsForm.id ? doc.datasources.find((d) => d.id === dsForm.id) : undefined
  // 同类型编辑：保留表单未覆盖的配置项（timeoutMs / staleTimeoutMs / reconnect* 等），
  // 避免「保存一次丢一批隐藏字段」；换类型则整份替换，防止旧类型字段串入。
  const config = prev && prev.type === dsForm.type ? ({ ...prev.config, ...built } as DataSource['config']) : built
  if (dsForm.id) {
    const idx = doc.datasources.findIndex((d) => d.id === dsForm.id)
    doc.datasources[idx] = { id: dsForm.id, name: dsForm.name.trim(), type: dsForm.type, enabled: dsForm.enabled, config } as DataSource
  } else {
    doc.datasources.push({ id: newId('ds'), name: dsForm.name.trim(), type: dsForm.type, enabled: dsForm.enabled, config } as DataSource)
  }
  dsVisible.value = false
  markDirty()
}

// M8：连接测试统一走服务端 /datasources/test（浏览器直连受 CORS 限制且库内凭证已脱敏）；
// 表单草稿用本次明文 config；已保存数据源传 projectId+datasourceId 由服务端注回凭证
const testing = ref(false)

async function doTest(): Promise<void> {
  testing.value = true
  try {
    const r = await testDatasource({
      type: dsForm.type,
      config: buildConfig() as Record<string, unknown>,
      // 编辑已有源时带上 id：服务端按「空串=保留」注回库内凭证，
      // 否则带鉴权的 MQTT/OPC UA 源在这里会被当成匿名连接而误报失败。
      projectId: dsForm.id ? editor.doc?.project.id : undefined,
      datasourceId: dsForm.id || undefined,
    })
    ElMessage({ type: r.ok ? 'success' : 'error', message: r.ok ? `${r.message}（${r.latencyMs}ms）` : r.message })
  } catch {
    /* 错误信封已由 http 拦截器提示 */
  } finally {
    testing.value = false
  }
}

async function doTestRow(ds: DataSource): Promise<void> {
  try {
    const r = await testDatasource({
      type: ds.type,
      config: ds.config as Record<string, unknown>,
      projectId: editor.doc?.project.id,
      datasourceId: ds.id,
    })
    ElMessage({ type: r.ok ? 'success' : 'error', message: r.ok ? `${r.message}（${r.latencyMs}ms）` : r.message })
  } catch {
    /* 错误信封已由 http 拦截器提示 */
  }
}

async function removeDs(ds: DataSource): Promise<void> {
  const used = variablesOfDatasource(editor.doc!, ds.id)
  if (used.length) {
    // 直接删除会让 doc 进入「每次保存 422」的永久脏态，且报错路径被误读为断网；
    // 必须先把变量迁走或删掉。
    const names = used.slice(0, 5).map((v) => v.label || v.key).join('、')
    await ElMessageBox.alert(
      `该数据源仍被 ${used.length} 个变量引用：${names}${used.length > 5 ? ' 等' : ''}。\n请先删除或改绑这些变量，再删除数据源。`,
      '无法删除数据源',
      { type: 'warning' },
    )
    return
  }
  try {
    await ElMessageBox.confirm(`确定删除数据源「${ds.name}」？`, '删除数据源', { type: 'warning' })
  } catch {
    return
  }
  const doc = editor.doc!
  doc.datasources = doc.datasources.filter((d) => d.id !== ds.id)
  markDirty()
}

// ================= 变量 =================

const varVisible = ref(false)
const varForm = reactive({
  id: '',
  key: '',
  label: '',
  type: 'number' as VariableType,
  unit: '',
  defaultValue: '',
  datasourceId: '',
  address: '',
  jsonPath: '',
  scale: 1,
  offset: 0,
  precision: 2,
  // M7
  expr: '',
  writable: false,
  writeAddress: '',
  mockKind: 'sine' as MockSpec['kind'],
  mockMin: 0,
  mockMax: 100,
  mockPeriodMs: 30000,
  mockIntervalMs: 1000,
})

const isVirtual = computed(() => varForm.datasourceId === VIRTUAL_DATASOURCE_ID)
const selectedDsType = computed(() => datasources.value.find((d) => d.id === varForm.datasourceId)?.type)

// ---- OPC UA 节点浏览（选节点即填地址，不用手抄 ns=2;s=...） ----
const browseVisible = ref(false)
const browseLoading = ref(false)
const browseMessage = ref('')
const browseNodes = ref<OpcUaNode[]>([])
const browseStack = ref<{ nodeId?: string; label: string }[]>([{ label: 'Objects' }])

function opcuaDs() {
  const ds = datasources.value.find((d) => d.id === varForm.datasourceId)
  return ds?.type === 'opcua' ? ds : undefined
}

async function loadBrowse(nodeId?: string): Promise<boolean> {
  const ds = opcuaDs()
  if (!ds) return false
  browseLoading.value = true
  browseMessage.value = ''
  try {
    const r = await browseOpcUa({
      endpoint: ds.config.endpointUrl,
      username: ds.config.username ?? null,
      password: null, // 服务端按端点一致注回库内密文
      nodeId: nodeId ?? null,
      projectId: editor.doc?.project.id,
      datasourceId: ds.id,
    })
    // 失败时保留上一级列表，避免「面包屑在子节点、表格还是父节点」的错位
    if (r.ok) browseNodes.value = r.nodes
    browseMessage.value = r.message
    return r.ok
  } catch {
    browseMessage.value = '浏览失败（详见提示），请检查 Endpoint/凭证'
    return false
  } finally {
    browseLoading.value = false
  }
}

async function openOpcUaBrowse(): Promise<void> {
  if (!opcuaDs()) {
    ElMessage.warning('请先选择 OPC UA 数据源')
    return
  }
  browseStack.value = [{ label: 'Objects' }]
  browseNodes.value = []
  browseVisible.value = true
  await loadBrowse(undefined)
}

async function browseInto(node: OpcUaNode): Promise<void> {
  browseStack.value.push({ nodeId: node.nodeId, label: node.browseName || node.nodeId })
  if (!(await loadBrowse(node.nodeId))) browseStack.value.pop()
}

async function browseUp(): Promise<void> {
  if (browseStack.value.length <= 1) return
  browseStack.value.pop()
  const parent = browseStack.value[browseStack.value.length - 1]
  await loadBrowse(parent.nodeId)
}

function browsePick(node: OpcUaNode): void {
  varForm.address = node.nodeId
  browseVisible.value = false
}

function openVar(v?: VariableDef): void {
  varVisible.value = true
  if (v) {
    Object.assign(varForm, {
      id: v.id, key: v.key, label: v.label, type: v.type,
      unit: v.unit ?? '', defaultValue: v.defaultValue === null || v.defaultValue === undefined ? '' : String(v.defaultValue),
      datasourceId: v.datasourceId, address: v.address ?? '', jsonPath: v.jsonPath ?? '',
      scale: v.scale ?? 1, offset: v.offset ?? 0, precision: v.precision ?? 2,
      expr: v.expr ?? '',
      writable: v.writable === true,
      writeAddress: v.writeAddress ?? '',
      mockKind: v.mock?.kind ?? 'sine',
      mockMin: v.mock && 'min' in v.mock ? v.mock.min : 0,
      mockMax: v.mock && 'max' in v.mock ? v.mock.max : 100,
      mockPeriodMs: v.mock && 'periodMs' in v.mock ? v.mock.periodMs : 30000,
      mockIntervalMs: v.mock?.kind === 'random' ? v.mock.intervalMs : 1000,
    })
  } else {
    Object.assign(varForm, {
      id: '', key: '', label: '', type: 'number', unit: '', defaultValue: '',
      datasourceId: datasources.value[0]?.id ?? '', address: '', jsonPath: '',
      scale: 1, offset: 0, precision: 2,
      expr: '', writable: false, writeAddress: '',
      mockKind: 'sine', mockMin: 0, mockMax: 100, mockPeriodMs: 30000, mockIntervalMs: 1000,
    })
  }
}

function buildMock(): MockSpec | null {
  const ds = datasources.value.find((d) => d.id === varForm.datasourceId)
  if (!ds || ds.type !== 'mock') return null
  switch (varForm.mockKind) {
    case 'random': return { kind: 'random', min: varForm.mockMin, max: varForm.mockMax, intervalMs: varForm.mockIntervalMs }
    case 'ramp': return { kind: 'ramp', min: varForm.mockMin, max: varForm.mockMax, periodMs: varForm.mockPeriodMs }
    case 'square': return { kind: 'square', onValue: varForm.mockMax, offValue: varForm.mockMin, periodMs: varForm.mockPeriodMs }
    case 'hold': return { kind: 'hold' }
    default: return { kind: 'sine', min: varForm.mockMin, max: varForm.mockMax, periodMs: varForm.mockPeriodMs }
  }
}

function saveVar(): void {
  if (!varForm.key.trim() || !varForm.label.trim() || !varForm.datasourceId) {
    ElMessage.warning('请填写 key、名称并选择数据源')
    return
  }
  if (isVirtual.value && !varForm.expr.trim()) {
    ElMessage.warning('虚拟变量必须填写表达式')
    return
  }
  const dup = variables.value.some((v) => v.key === varForm.key.trim() && v.id !== varForm.id)
  if (dup) {
    ElMessage.error('key 已存在（工程内唯一且不可改）')
    return
  }
  const doc = editor.doc!
  const def = varForm.defaultValue === '' ? null : varForm.type === 'number' ? Number(varForm.defaultValue) : varForm.type === 'boolean' ? varForm.defaultValue === 'true' : varForm.defaultValue
  // 编辑已有变量时按「合并写入」而非整对象替换：表单未覆盖的字段
  // （bitIndex / modbusDataType / modbusByteOrder / unitId / range / description）
  // 必须原样保留，否则改个名称就会把 32 位/字节序/从站号清空，历史与报警静默错值。
  const existing = varForm.id ? doc.variables.find((v) => v.id === varForm.id) : undefined
  const targetDs = datasources.value.find((d) => d.id === varForm.datasourceId)
  const modbusFields = targetDs?.type === 'modbus'
    ? {}
    : { modbusDataType: null, modbusByteOrder: null, unitId: null }
  // 位提取变量（仅 CSV 可建）与 scale/offset/precision 在服务端强互斥；
  // 表单不展示 bitIndex，编辑时必须按「有 bitIndex 就清换算三件套」处理，否则保存必 422。
  // boolean/number 都允许 bitIndex（服务端只禁 string）
  const effectiveBitIndex = varForm.type !== 'string' && !isVirtual.value ? (existing?.bitIndex ?? null) : null
  const item: VariableDef = {
    ...(existing ?? {}),
    id: varForm.id || newId('var'),
    key: varForm.key.trim(),
    label: varForm.label.trim(),
    type: varForm.type,
    unit: varForm.unit || null,
    defaultValue: def,
    datasourceId: varForm.datasourceId,
    address: isVirtual.value ? '' : varForm.address || undefined,
    jsonPath: isVirtual.value ? null : varForm.jsonPath || null,
    // M7
    expr: isVirtual.value ? varForm.expr.trim() : null,
    writable: !isVirtual.value && varForm.writable,
    writeAddress: varForm.writeAddress.trim() || null,
    scale: effectiveBitIndex == null && varForm.scale !== 1 ? varForm.scale : null,
    offset: effectiveBitIndex == null && varForm.offset !== 0 ? varForm.offset : null,
    precision: varForm.type === 'number' && effectiveBitIndex == null ? varForm.precision : null,
    bitIndex: effectiveBitIndex,
    mock: isVirtual.value ? null : buildMock(),
    ...modbusFields,
  }
  if (varForm.id) {
    const idx = doc.variables.findIndex((v) => v.id === varForm.id)
    doc.variables[idx] = item
  } else {
    doc.variables.push(item)
  }
  varVisible.value = false
  markDirty()
}

async function removeVar(v: VariableDef): Promise<void> {
  const usages = findVariableUsage(editor.doc!, v)
  const hard = usages.filter((u) => u.kind !== 'expr')
  if (hard.length) {
    // 绑定/事件/报警规则是硬引用：删了服务端引用校验必 422，工程进入永久脏态
    const detail = hard.slice(0, 6).map((u) => `· ${u.where}`).join('\n')
    await ElMessageBox.alert(
      `变量「${v.label}」仍被 ${hard.length} 处引用：\n${detail}${hard.length > 6 ? '\n…' : ''}\n请先解除这些引用。`,
      '无法删除变量',
      { type: 'warning' },
    )
    return
  }
  const exprRefs = usages.filter((u) => u.kind === 'expr')
  try {
    await ElMessageBox.confirm(
      exprRefs.length
        ? `变量「${v.label}」被 ${exprRefs.length} 个虚拟变量的表达式引用，删除后这些表达式会求值失败（工程仍可保存）。确定删除？`
        : `确定删除变量「${v.label}」？`,
      '删除变量',
      { type: 'warning' },
    )
  } catch {
    return
  }
  const doc = editor.doc!
  doc.variables = doc.variables.filter((x) => x.id !== v.id)
  markDirty()
}

// ================= CSV 批量导入（工厂可用阶段一 Task 6） =================

const csvFileInput = ref<HTMLInputElement>()
const csvVisible = ref(false)
const csvFileName = ref('')
const csvRows = ref<PointCsvRow[]>([])
const csvErrors = ref<PointCsvError[]>([])
/** 导入目标数据源：CSV 不含数据源/凭证列（K11），凭证只在数据源表单配置 */
const csvDsId = ref('')

function openCsvPicker(): void {
  csvFileInput.value?.click()
}

/** 变量表导出为点位 CSV（与导入同格式；带 BOM 便于 Excel 直接打开中文） */
function exportCsv(): void {
  const csv = buildPointCsv(variables.value)
  const blob = new Blob([`﻿${csv}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `point_table_${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success(`已导出 ${variables.value.filter((v) => !v.expr).length} 个点位`)
}

function onCsvFileChange(e: Event): void {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // 复位以允许再次选择同一文件
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    const r = parsePointCsv(String(reader.result ?? ''))
    csvFileName.value = file.name
    csvRows.value = r.rows
    csvErrors.value = r.rows.length || r.errors.length ? r.errors : [{ line: 1, message: '文件中没有可导入的数据行' }]
    csvDsId.value = datasources.value[0]?.id ?? ''
    csvVisible.value = true
  }
  reader.onerror = () => ElMessage.error('文件读取失败')
  reader.readAsText(file)
}

/** 已有变量索引：同 key = 更新（upsert，适合业主改版点表后重导），而不是简单跳过 */
const csvExistingByKey = computed(() => new Map(variables.value.map((v) => [v.key, v])))
/** 虚拟变量 key 冲突：CSV 没有 expr 列，覆盖会把虚拟变量改成物理变量 → 跳过并提示 */
const csvVirtualConflicts = computed(() =>
  csvRows.value.filter((r) => csvExistingByKey.value.get(r.key)?.expr != null).map((r) => r.key),
)
const csvUpdateRows = computed(() =>
  csvRows.value.filter((r) => {
    const old = csvExistingByKey.value.get(r.key)
    return old != null && old.expr == null
  }),
)
const csvNewRows = computed(() => csvRows.value.filter((r) => !csvExistingByKey.value.has(r.key)))
/** 已有变量与所选目标源不同：导入时保持原源，不强制改绑 */
const csvCrossDsUpdates = computed(() =>
  csvUpdateRows.value.filter((r) => csvExistingByKey.value.get(r.key)?.datasourceId !== csvDsId.value).length,
)

/** 行内携带 Modbus 字段但该行最终落点不是 modbus：服务端跨检会整体 422，导入前置拦截。
 *  已有变量保持原数据源，所以按「该行实际落点」判定，而不是按所选目标源统一判定。 */
const csvModbusConflict = computed(() => {
  const targetType = datasources.value.find((d) => d.id === csvDsId.value)?.type
  return csvRows.value.filter((r) => {
    if (csvVirtualConflicts.value.includes(r.key)) return false  // 已跳过，不参与冲突判定
    if (r.modbusDataType == null && r.modbusByteOrder == null && r.unitId == null) return false
    const old = csvExistingByKey.value.get(r.key)
    const rowType = old
      ? datasources.value.find((d) => d.id === old.datasourceId)?.type
      : targetType
    return rowType !== 'modbus'
  }).length
})

const csvImportable = computed(() => csvRows.value.filter((r) => !csvVirtualConflicts.value.includes(r.key)))

const csvCanImport = computed(
  () => !!csvDsId.value && csvErrors.value.length === 0 && csvImportable.value.length > 0 && csvModbusConflict.value === 0,
)

/** 逐行构造 VariableDef（字段映射与 saveVar 同构）后追加，doc 级数据变更不入 undo 栈 */
function confirmCsvImport(): void {
  const doc = editor.doc!
  const targetType = datasources.value.find((d) => d.id === csvDsId.value)?.type
  const isMock = targetType === 'mock'
  const defaultMock: MockSpec = { kind: 'sine', min: 0, max: 100, periodMs: 30000 }
  let added = 0
  let updated = 0

  for (const r of csvImportable.value) {
    const old = csvExistingByKey.value.get(r.key)
    // 已有变量保持原数据源：CSV 没有数据源列，若按「导入目标」强制改绑，
    // 一次全表导入会把所有变量搬到同一个源（还会清掉 Modbus 字段），属于灾难性误操作。
    const rowDsType = old
      ? datasources.value.find((d) => d.id === old.datasourceId)?.type
      : targetType
    const rowIsMock = rowDsType === 'mock'
    const rowIsModbus = rowDsType === 'modbus'
    // 位提取与换算三件套跨行合并后仍须互斥（CSV 只做了行内校验）：
    // 本行显式给了任一换算列 → 视为业主改回模拟量，不再继承旧 bitIndex；string 恒不保留
    const rowHasTransform = r.scale != null || r.offset != null || r.precision != null
    const bitIndex = r.type === 'string'
      ? null
      : r.bitIndex != null
        ? r.bitIndex
        : rowHasTransform
          ? null
          : (old?.bitIndex ?? null)
    const fields = {
      label: r.label,
      type: r.type,
      // CSV 省略的列（undefined）保留旧值：业主只改地址的补丁式点表不会误清量程/换算
      unit: r.unit ?? old?.unit ?? null,
      datasourceId: old?.datasourceId ?? csvDsId.value,
      address: r.address,
      jsonPath: r.jsonPath ?? old?.jsonPath ?? null,
      writable: r.writable ?? old?.writable ?? false,
      writeAddress: r.writeAddress ?? old?.writeAddress ?? null,
      // 换算缺省语义与 saveVar 同构：scale=1/offset=0 归一为 null；precision 缺省 2
      scale: bitIndex != null ? null : (r.scale != null ? (r.scale !== 1 ? r.scale : null) : (old?.scale ?? null)),
      offset: bitIndex != null ? null : (r.offset != null ? (r.offset !== 0 ? r.offset : null) : (old?.offset ?? null)),
      precision: bitIndex == null && r.type === 'number' ? (r.precision ?? old?.precision ?? 2) : null,
      bitIndex,
      range: r.range !== undefined ? r.range : (old?.range ?? null),
      modbusDataType: rowIsModbus ? (r.modbusDataType ?? old?.modbusDataType ?? null) : null,
      modbusByteOrder: rowIsModbus ? (r.modbusByteOrder ?? old?.modbusByteOrder ?? null) : null,
      unitId: rowIsModbus ? (r.unitId ?? old?.unitId ?? null) : null,
    }
    if (old) {
      doc.variables[doc.variables.findIndex((v) => v.id === old.id)] = {
        ...old,
        ...fields,
        // mock 波形属于原数据源的本地配置，CSV 不携带：原源是 mock 就保留
        mock: rowIsMock ? (old.mock ?? defaultMock) : null,
      }
      updated += 1
    } else {
      doc.variables.push({
        id: newId('var'),
        key: r.key,
        ...fields,
        defaultValue: null,
        expr: null,
        mock: isMock ? defaultMock : null,
      })
      added += 1
    }
  }

  const skipped = csvVirtualConflicts.value.length
  csvVisible.value = false
  const parts = [`新增 ${added} 个`, `更新 ${updated} 个`]
  if (skipped) parts.push(`跳过虚拟变量冲突 ${skipped} 个`)
  ElMessage.success(`点位导入完成：${parts.join('，')}`)
  markDirty()
}

// ================= 报警规则 =================

const almVisible = ref(false)
const almForm = reactive({
  id: '',
  name: '',
  variableId: '',
  op: '>' as AlarmOp,
  threshold: 90,
  level: 'warn' as AlarmLevel,
  message: '{label} = {value}（阈值 {threshold}）',
  enabled: true,
  hysteresis: 0,
  durationMs: 0,
  sound: true,
})

const LEVEL_LABEL: Record<AlarmLevel, string> = { info: '提示', warn: '警告', critical: '严重' }

function openAlm(r?: AlarmRule): void {
  almVisible.value = true
  if (r) {
    Object.assign(almForm, {
      id: r.id, name: r.name, variableId: r.variableId, op: r.op, threshold: r.threshold,
      level: r.level, message: r.message, enabled: r.enabled, hysteresis: r.hysteresis ?? 0,
      durationMs: r.durationMs ?? 0, sound: r.sound ?? true,
    })
  } else {
    Object.assign(almForm, {
      id: '', name: '', variableId: variables.value[0]?.id ?? '', op: '>', threshold: 90,
      level: 'warn', message: '{label} = {value}（阈值 {threshold}）', enabled: true, hysteresis: 0, durationMs: 0, sound: true,
    })
  }
}

function saveAlm(): void {
  if (!almForm.name.trim() || !almForm.variableId) {
    ElMessage.warning('请填写名称并选择变量')
    return
  }
  const doc = editor.doc!
  const item: AlarmRule = {
    id: almForm.id || newId('alm'),
    name: almForm.name.trim(),
    variableId: almForm.variableId,
    op: almForm.op,
    threshold: Number(almForm.threshold),
    level: almForm.level,
    message: almForm.message || '{label} = {value}',
    enabled: almForm.enabled,
    hysteresis: almForm.hysteresis || null,
    durationMs: almForm.durationMs || null,
    sound: almForm.sound,
  }
  if (almForm.id) {
    const idx = doc.alarmRules.findIndex((r) => r.id === almForm.id)
    doc.alarmRules[idx] = item
  } else {
    doc.alarmRules.push(item)
  }
  almVisible.value = false
  markDirty()
}

async function removeAlm(r: AlarmRule): Promise<void> {
  try {
    await ElMessageBox.confirm(`确定删除报警规则「${r.name}」？`, '删除规则', { type: 'warning' })
  } catch {
    return
  }
  const doc = editor.doc!
  doc.alarmRules = doc.alarmRules.filter((x) => x.id !== r.id)
  markDirty()
}

/** 持续时长按秒输入（工业习惯），存储仍为 ms（契约 durationMs） */
const almDurationSec = computed({
  get: () => Math.round((almForm.durationMs ?? 0) / 1000),
  set: (v: number) => {
    almForm.durationMs = Math.max(0, Math.floor(Number(v) || 0)) * 1000
  },
})

function triggerPred(v: number, op: AlarmOp, t: number): boolean {
  switch (op) {
    case '>':
      return v > t
    case '>=':
      return v >= t
    case '<':
      return v < t
    case '<=':
      return v <= t
    case '==':
      return v === t
    case '!=':
      return v !== t
    default:
      return false
  }
}

/** 试判定：用当前变量值做一次阈值判断（不落库、不外发） */
function testAlarm(r: AlarmRule): void {
  const v = editor.doc?.variables.find((x) => x.id === r.variableId)
  if (!v) {
    ElMessage.warning('规则引用的变量不存在，该规则不会触发')
    return
  }
  if (r.enabled === false) {
    ElMessage.info(`规则「${r.name}」已停用，不会触发`)
    return
  }
  const entry = varValues.value[v.key]
  if (!entry || entry.v === null || entry.v === undefined) {
    ElMessage.warning(`变量 ${v.key} 当前无数据，请在「变量」页刷新实时值后再试`)
    return
  }
  const num = typeof entry.v === 'boolean' ? (entry.v ? 1 : 0) : Number(entry.v)
  if (!Number.isFinite(num)) {
    ElMessage.warning(`变量 ${v.key} 当前值不是数值（${String(entry.v)}），规则不会触发`)
    return
  }
  const hit = triggerPred(num, r.op, r.threshold)
  const quality = entry.q === 'good' ? '正常' : entry.q === 'stale' ? '停更' : '坏值'
  ElMessage({
    message: `试判定：${v.label} = ${num} ${r.op} ${r.threshold} → ${hit ? '满足阈值' : '不满足'}（质量：${quality}）${
      entry.q !== 'good' ? '；质量非正常时服务端不判定' : ''
    }`,
    type: hit ? 'warning' : 'info',
    duration: 6000,
    showClose: true,
  })
}

// ================= 通知渠道（工厂可用阶段二 Task 4：存 doc.settings.notify） =================

const chVisible = ref(false)
const chForm = reactive({
  /** 编辑中的渠道下标（-1 = 新增）；渠道模型无 id，按数组位置定位 */
  idx: -1,
  kind: 'webhook' as NotifyChannelKind,
  url: '',
  /** 钉钉加签密钥：编辑留空 = 保留已存值（服务端合并规则⑤） */
  secret: '',
  clearSecret: false,
  minLevel: 'warn' as NotifyLevel,
  recipientsText: '',
})

const CHANNEL_LABEL: Record<NotifyChannelKind, string> = {
  webhook: 'Webhook',
  dingtalk: '钉钉机器人',
  wecom: '企微机器人',
  email: '邮件',
}

function openCh(idx?: number): void {
  chVisible.value = true
  const ch = idx != null ? channels.value[idx] : undefined
  if (ch) {
    Object.assign(chForm, {
      idx,
      kind: ch.kind,
      url: ch.kind === 'email' ? '' : ch.url,
      secret: ch.kind === 'dingtalk' ? (ch.secret ?? '') : '',
      clearSecret: false,
      minLevel: ch.minLevel ?? 'warn',
      recipientsText: ch.kind === 'email' ? ch.recipients.join('\n') : '',
    })
  } else {
    Object.assign(chForm, { idx: -1, kind: 'webhook', url: '', secret: '', clearSecret: false, minLevel: 'warn' as const, recipientsText: '' })
  }
}

function saveCh(): void {
  let item: NotifyChannel
  if (chForm.kind === 'email') {
    const recipients = chForm.recipientsText.split('\n').map((s) => s.trim()).filter(Boolean)
    if (!recipients.length) {
      ElMessage.warning('请至少填写一个收件人邮箱')
      return
    }
    if (recipients.length > 20) {
      ElMessage.warning('收件人最多 20 个')
      return
    }
    if (recipients.some((r) => !r.includes('@'))) {
      ElMessage.warning('收件人邮箱须包含 @')
      return
    }
    item = { kind: 'email', recipients, minLevel: chForm.minLevel }
  } else {
    const url = chForm.url.trim()
    if (!url.startsWith('https://')) {
      ElMessage.warning('URL 必须以 https:// 开头')
      return
    }
    if (chForm.kind === 'dingtalk') {
      // 编辑留空 = 保留（提交空串触发服务端合并）；新增留空 = 无密钥（提交 null）
      item = {
        kind: 'dingtalk',
        url,
        secret: chForm.clearSecret ? null : (chForm.idx >= 0 ? (chForm.secret || '') : (chForm.secret || null)),
        minLevel: chForm.minLevel,
      }
    } else {
      item = { kind: chForm.kind, url, minLevel: chForm.minLevel }
    }
  }
  const doc = editor.doc!
  if (!doc.settings.notify) doc.settings.notify = { channels: [] }
  if (chForm.idx >= 0) doc.settings.notify.channels[chForm.idx] = item
  else doc.settings.notify.channels.push(item)
  chVisible.value = false
  markDirty()
}

async function removeCh(idx: number): Promise<void> {
  const ch = channels.value[idx]
  if (!ch) return
  try {
    await ElMessageBox.confirm(`确定删除「${CHANNEL_LABEL[ch.kind]}」通知渠道？`, '删除通知渠道', { type: 'warning' })
  } catch {
    return
  }
  const doc = editor.doc!
  doc.settings.notify?.channels.splice(idx, 1)
  markDirty()
}

function channelTarget(ch: NotifyChannel): string {
  if (ch.kind === 'email') {
    return ch.recipients.length <= 2 ? ch.recipients.join('，') : `${ch.recipients[0]} 等 ${ch.recipients.length} 人`
  }
  try {
    return new URL(ch.url).host
  } catch {
    return ch.url
  }
}
</script>

<template>
  <el-drawer :model-value="true" title="工程数据（数据源 / 变量 / 报警 / 通知）" size="780px" @close="emit('close')">
    <el-tabs v-model="tab">
      <!-- 数据源 -->
      <el-tab-pane label="数据源" name="sources">
        <div class="pane">
          <el-button size="small" type="primary" plain :icon="Plus" @click="openDs()">新增数据源</el-button>
          <el-table :data="datasources" size="small" empty-text="暂无数据源">
            <el-table-column prop="name" label="名称" min-width="110" />
            <el-table-column label="类型" width="90">
              <template #default="{ row }">{{ TYPE_LABEL[row.type] }}</template>
            </el-table-column>
            <el-table-column label="启用" width="70">
              <template #default="{ row }">
                <el-tag :type="row.enabled === false ? 'info' : 'success'" size="small">
                  {{ row.enabled === false ? '停' : '启' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="86">
              <template #default="{ row }">
                <el-tag v-if="row.enabled !== false" :type="dsStateOf(row.id).type" size="small">
                  {{ dsStateOf(row.id).label }}
                </el-tag>
                <span v-else class="form-hint">停用</span>
              </template>
            </el-table-column>
            <el-table-column label="最后收数" width="86">
              <template #default="{ row }">{{ row.enabled === false ? '—' : lastOkText(row.id) }}</template>
            </el-table-column>
            <el-table-column label="错误" min-width="120" show-overflow-tooltip>
              <template #default="{ row }">{{ dsStatus[row.id]?.lastError || '—' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="150">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="openDs(row)">编辑</el-button>
                <el-button link type="success" size="small" @click="doTestRow(row)">测试</el-button>
                <el-button link type="danger" size="small" @click="removeDs(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <!-- 变量 -->
      <el-tab-pane :label="`变量（${variables.length}）`" name="variables">
        <div class="pane">
          <div class="toolbar">
            <el-button size="small" type="primary" plain :icon="Plus" :disabled="!datasources.length" @click="openVar()">
              新增变量
            </el-button>
            <el-button size="small" plain :icon="Upload" :disabled="!datasources.length" @click="openCsvPicker">
              导入 CSV
            </el-button>
            <el-button size="small" plain :icon="Download" :disabled="!variables.length" @click="exportCsv">
              导出 CSV
            </el-button>
            <el-button size="small" :loading="varValuesLoading" @click="loadVarValues">刷新实时值</el-button>
            <el-input
              v-model="varKeyword"
              size="small"
              clearable
              placeholder="搜索 key / 名称 / 地址 / 单位"
              class="var-search"
            />
          </div>
          <el-table :data="filteredVariables" size="small" empty-text="暂无变量">
            <el-table-column prop="key" label="key" min-width="110" />
            <el-table-column prop="label" label="名称" min-width="90" />
            <el-table-column prop="type" label="类型" width="70" />
            <el-table-column label="地址 / 表达式" min-width="140">
              <template #default="{ row }">
                <span v-if="row.expr" class="cell-mono">{{ row.expr }}</span>
                <span v-else class="cell-mono">{{ row.address || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="单位" width="64">
              <template #default="{ row }">{{ row.unit || '—' }}</template>
            </el-table-column>
            <el-table-column label="量程" width="100">
              <template #default="{ row }">{{ row.range ? `${row.range.min}~${row.range.max}` : '—' }}</template>
            </el-table-column>
            <el-table-column label="数据源" width="110">
              <template #default="{ row }">
                <el-tag v-if="row.expr" type="warning" size="small">虚拟</el-tag>
                <template v-else>
                  {{ TYPE_LABEL[datasources.find((d) => d.id === row.datasourceId)?.type ?? ''] ?? '—' }}
                  <el-tag v-if="row.writable" type="success" size="small" style="margin-left: 2px">可写</el-tag>
                </template>
              </template>
            </el-table-column>
            <el-table-column label="当前值 / 质量" width="140">
              <template #default="{ row }">
                <span class="cell-mono">{{ varValueText(row.key) }}</span>
                <el-tag
                  v-if="varValues[row.key]"
                  size="small"
                  :type="varQuality(row.key).type"
                  class="quality-tag"
                >
                  {{ varQuality(row.key).label }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="openVar(row)">编辑</el-button>
                <el-button link type="danger" size="small" @click="removeVar(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <!-- 报警规则 -->
      <el-tab-pane :label="`报警（${alarms.length}）`" name="alarms">
        <div class="pane">
          <div class="toolbar">
            <el-button size="small" type="primary" plain :icon="Plus" :disabled="!variables.length" @click="openAlm()">
              新增规则
            </el-button>
            <el-button size="small" :icon="Bell" @click="openAlarmCenter">报警中心</el-button>
          </div>
          <el-table :data="alarms" size="small" empty-text="暂无报警规则">
            <el-table-column prop="name" label="名称" min-width="100" />
            <el-table-column label="条件" min-width="120">
              <template #default="{ row }">
                {{ variables.find((v) => v.id === row.variableId)?.label ?? '?' }} {{ row.op }} {{ row.threshold }}
              </template>
            </el-table-column>
            <el-table-column label="级别" width="70">
              <template #default="{ row }">
                <el-tag :type="row.level === 'critical' ? 'danger' : row.level === 'warn' ? 'warning' : 'info'" size="small">
                  {{ LEVEL_LABEL[row.level as AlarmLevel] }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="启用" width="60">
              <template #default="{ row }">
                <el-tag :type="row.enabled === false ? 'info' : 'success'" size="small">
                  {{ row.enabled === false ? '停' : '启' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="持续" width="64">
              <template #default="{ row }">{{ (row.durationMs ?? 0) > 0 ? `${(row.durationMs ?? 0) / 1000}s` : '立即' }}</template>
            </el-table-column>
            <el-table-column label="回差" width="60">
              <template #default="{ row }">{{ row.hysteresis ?? 0 }}</template>
            </el-table-column>
            <el-table-column label="操作" width="170">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="openAlm(row)">编辑</el-button>
                <el-button link type="success" size="small" @click="testAlarm(row)">试判定</el-button>
                <el-button link type="danger" size="small" @click="removeAlm(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="form-hint">
            试判定用当前变量值做一次阈值判断，不落库、不外发；持续/回差按实际判定生效。
            外发结果见「通知 → 最近投递」。
          </div>
        </div>
      </el-tab-pane>

      <!-- 通知渠道 -->
      <el-tab-pane :label="`通知（${channels.length}）`" name="notify">
        <div class="pane">
          <el-button size="small" type="primary" plain :icon="Plus" @click="openCh()">新增渠道</el-button>
          <el-table :data="channels" size="small" empty-text="暂无通知渠道（外发回落服务端环境变量配置）">
            <el-table-column label="类型" width="100">
              <template #default="{ row }">
                <el-tag :type="row.kind === 'email' ? 'info' : 'success'" size="small">
                  {{ CHANNEL_LABEL[row.kind as NotifyChannelKind] }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="目标" min-width="140">
              <template #default="{ row }">{{ channelTarget(row) }}</template>
            </el-table-column>
            <el-table-column label="级别阈值" width="96">
              <template #default="{ row }">
                <el-tag :type="row.minLevel === 'critical' ? 'danger' : row.minLevel === 'warn' ? 'warning' : 'info'" size="small">
                  {{ LEVEL_LABEL[(row.minLevel ?? 'warn') as AlarmLevel] }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="120">
              <template #default="{ row, $index }">
                <el-button link type="primary" size="small" @click="openCh($index)">编辑</el-button>
                <el-button link type="danger" size="small" @click="removeCh($index)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="form-hint">
            报警触发后按各渠道「级别阈值」过滤外发；工程配置后优先生效，未配置时回落服务端环境变量（Webhook/邮件）。
          </div>

          <el-divider content-position="left">最近投递</el-divider>
          <div class="delivery-bar">
            <el-button size="small" :loading="deliveryLoading" @click="loadDeliveries">刷新</el-button>
            <span class="form-hint">sent=已送达；待补发/发送中=断网重试；死信=多次失败需检查渠道配置。</span>
          </div>
          <el-table :data="deliveries" size="small" max-height="240" empty-text="暂无投递记录（报警外发后在此留痕）">
            <el-table-column label="时间" width="104">
              <template #default="{ row }">{{ fmtDeliveryTime(row.createdAt) }}</template>
            </el-table-column>
            <el-table-column label="事件" width="64">
              <template #default="{ row }">{{ row.event === 'recovery' ? '恢复' : '触发' }}</template>
            </el-table-column>
            <el-table-column label="渠道" min-width="120" show-overflow-tooltip>
              <template #default="{ row }">{{ row.channelLabel }}</template>
            </el-table-column>
            <el-table-column label="状态" width="84">
              <template #default="{ row }">
                <el-tag size="small" :type="deliveryMeta(row.status).type">{{ deliveryMeta(row.status).label }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="尝试" width="56" prop="attempts" />
            <el-table-column label="错误" min-width="130" show-overflow-tooltip>
              <template #default="{ row }">{{ row.lastError || '—' }}</template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 数据源表单 -->
    <el-dialog v-model="dsVisible" :title="dsForm.id ? '编辑数据源' : '新增数据源'" width="480px" append-to-body>
      <el-form label-width="92px" size="small">
        <el-form-item label="名称" required><el-input v-model="dsForm.name" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="dsForm.type">
            <el-option label="模拟（前端生成）" value="mock" />
            <el-option label="WebSocket" value="websocket" />
            <el-option label="REST 轮询" value="rest" />
            <el-option label="MQTT over WS" value="mqtt" />
            <el-option label="Modbus TCP" value="modbus" />
            <el-option label="OPC UA" value="opcua" />
          </el-select>
        </el-form-item>
        <template v-if="dsForm.type !== 'mock'">
          <el-form-item :label="dsForm.type === 'mqtt' ? 'Broker 地址' : dsForm.type === 'modbus' ? 'PLC/网关 IP' : dsForm.type === 'opcua' ? 'Endpoint' : 'URL'" required>
            <el-input v-model="dsForm.url" :placeholder="dsForm.type === 'mqtt' ? 'ws://localhost:8083/mqtt' : dsForm.type === 'modbus' ? '192.168.1.10' : dsForm.type === 'opcua' ? 'opc.tcp://192.168.1.10:4840' : 'https://…'" />
          </el-form-item>
        </template>
        <template v-if="dsForm.type === 'modbus'">
          <el-form-item label="端口">
            <el-input-number v-model="dsForm.mbPort" :min="1" :max="65535" :step="1" />
          </el-form-item>
          <el-form-item label="UnitId">
            <el-input-number v-model="dsForm.mbUnitId" :min="0" :max="255" :step="1" />
          </el-form-item>
          <el-form-item label="轮询间隔">
            <el-select v-model="dsForm.intervalMs">
              <el-option v-for="ms in [500, 1000, 2000, 5000]" :key="ms" :label="`${ms} ms`" :value="ms" />
            </el-select>
          </el-form-item>
        </template>
        <template v-if="dsForm.type === 'opcua'">
          <div class="form-row2">
            <el-form-item label="用户名">
              <el-input v-model="dsForm.ocUsername" placeholder="匿名留空" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="dsForm.ocPassword" type="password" show-password placeholder="留空=保留已存密码" />
            </el-form-item>
          </div>
          <el-form-item label="发布周期">
            <el-input-number v-model="dsForm.ocPublishMs" :min="200" :step="100" controls-position="right" />
            <span class="form-hint">ms（订阅 publishInterval，下限 200）</span>
          </el-form-item>
        </template>
        <template v-if="dsForm.type === 'mqtt'">
          <div class="form-row2">
            <el-form-item label="用户名">
              <el-input v-model="dsForm.mqUsername" placeholder="EMQX 账号，如 webscada_mqtt" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="dsForm.mqPassword" type="password" show-password placeholder="留空=保留已存密码" />
            </el-form-item>
          </div>
        </template>
        <el-form-item v-if="dsForm.type === 'mqtt'" label="订阅 Topic">
          <el-input v-model="dsForm.topics" type="textarea" :rows="2" placeholder="逗号或换行分隔，如 plant1/temperature" />
        </el-form-item>
        <el-form-item v-if="dsForm.type === 'rest'" label="轮询间隔">
          <el-input-number v-model="dsForm.intervalMs" :min="500" :step="500" controls-position="right" />
          <span class="form-hint">ms</span>
        </el-form-item>
        <!-- M7 反控写配置 -->
        <template v-if="dsForm.type === 'rest'">
          <el-divider content-position="left">反控写入</el-divider>
          <el-form-item label="写端点">
            <el-input v-model="dsForm.writeUrl" placeholder="https://…/api/set（空=不可写）" />
          </el-form-item>
          <el-form-item label="写方法">
            <el-select v-model="dsForm.writeMethod" :disabled="!dsForm.writeUrl">
              <el-option label="POST" value="POST" />
              <el-option label="PUT" value="PUT" />
            </el-select>
          </el-form-item>
          <el-form-item label="写请求体">
            <el-input v-model="dsForm.writeBodyTemplate" type="textarea" :rows="2" placeholder='缺省 {"key":value}；占位 {key} {value}' />
          </el-form-item>
        </template>
        <template v-else-if="dsForm.type === 'websocket'">
          <el-divider content-position="left">反控写入</el-divider>
          <el-form-item label="写帧模板">
            <el-input v-model="dsForm.writeFrameTemplate" type="textarea" :rows="2" placeholder='缺省 {"key":value}；占位 {key} {value}' />
          </el-form-item>
        </template>
        <template v-else-if="dsForm.type === 'mqtt'">
          <el-divider content-position="left">反控写入</el-divider>
          <el-form-item label="写 QoS">
            <el-select v-model="dsForm.writeQos">
              <el-option label="0（最多一次）" :value="0" />
              <el-option label="1（至少一次）" :value="1" />
            </el-select>
            <span class="form-hint">写 topic 在变量的「写地址」配置</span>
          </el-form-item>
        </template>
        <el-form-item v-if="dsForm.type !== 'mock'" label="连通测试">
          <el-button size="small" :loading="testing" @click="doTest">测试连接</el-button>
        </el-form-item>
        <el-form-item label="启用"><el-switch v-model="dsForm.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dsVisible = false">取消</el-button>
        <el-button type="primary" @click="saveDs">保存</el-button>
      </template>
    </el-dialog>

    <!-- 变量表单 -->
    <el-dialog v-model="varVisible" :title="varForm.id ? '编辑变量' : '新增变量'" width="560px" append-to-body>
      <el-form label-width="92px" size="small">
        <div class="form-row2">
          <el-form-item label="key" required>
            <el-input v-model="varForm.key" :disabled="!!varForm.id" placeholder="如 plant1.temp" />
          </el-form-item>
          <el-form-item label="名称" required><el-input v-model="varForm.label" /></el-form-item>
        </div>
        <div class="form-row2">
          <el-form-item label="类型">
            <el-select v-model="varForm.type">
              <el-option label="number" value="number" />
              <el-option label="boolean" value="boolean" />
              <el-option label="string" value="string" />
            </el-select>
          </el-form-item>
          <el-form-item label="单位"><el-input v-model="varForm.unit" placeholder="℃ / MPa / …" /></el-form-item>
        </div>
        <el-form-item label="数据源" required>
          <el-select v-model="varForm.datasourceId">
            <el-option v-for="d in datasources" :key="d.id" :label="`${d.name}（${TYPE_LABEL[d.type]}）`" :value="d.id" />
            <el-option label="虚拟（表达式计算）" :value="VIRTUAL_DATASOURCE_ID" />
          </el-select>
        </el-form-item>
        <!-- M7：虚拟变量表达式 -->
        <el-form-item v-if="isVirtual" label="表达式">
          <el-input
            v-model="varForm.expr"
            type="textarea" :rows="2"
            placeholder="引用其它变量 key，如 (temp1 + temp2) / 2；支持 + - * / % 比较 逻辑 三角无、abs/min/max/round"
          />
        </el-form-item>
        <div class="form-row2">
          <el-form-item label="取数地址">
            <el-input v-model="varForm.address" :disabled="isVirtual" placeholder="mqtt=topic / ws·rest=字段名 / opcua=nodeId" />
          </el-form-item>
          <el-form-item label="jsonPath">
            <el-input v-model="varForm.jsonPath" :disabled="isVirtual" placeholder="data.items[0].v" />
          </el-form-item>
        </div>
        <el-form-item v-if="selectedDsType === 'opcua'" label="节点浏览">
          <el-button size="small" @click="openOpcUaBrowse">浏览 OPC UA 地址空间</el-button>
          <span class="form-hint">选中节点后自动填入取数地址</span>
        </el-form-item>
        <!-- M7：反控可写配置 -->
        <template v-if="!isVirtual">
          <el-divider content-position="left">反控（写通道）</el-divider>
          <div class="form-row2">
            <el-form-item label="可写">
              <el-switch v-model="varForm.writable" />
            </el-form-item>
            <el-form-item label="写地址">
              <el-input v-model="varForm.writeAddress" :disabled="!varForm.writable" placeholder="mqtt 写 topic（缺省同取数地址）" />
            </el-form-item>
          </div>
        </template>
        <template v-if="varForm.type === 'number' && !isVirtual">
          <div class="form-row2">
            <el-form-item label="倍率 scale"><el-input-number v-model="varForm.scale" :step="0.1" controls-position="right" /></el-form-item>
            <el-form-item label="偏移 offset"><el-input-number v-model="varForm.offset" controls-position="right" /></el-form-item>
          </div>
          <div class="form-row2">
            <el-form-item label="精度">
              <el-input-number v-model="varForm.precision" :min="0" :max="6" controls-position="right" />
            </el-form-item>
            <el-form-item label="默认值">
              <el-input v-model="varForm.defaultValue" placeholder="运行前初始值" />
            </el-form-item>
          </div>
        </template>
        <template v-else-if="varForm.type === 'number'">
          <el-form-item label="默认值">
            <el-input v-model="varForm.defaultValue" placeholder="运行前初始值（表达式依赖未就绪时）" />
          </el-form-item>
        </template>
        <!-- mock 波形（仅 mock 数据源） -->
        <template v-if="datasources.find((d) => d.id === varForm.datasourceId)?.type === 'mock'">
          <el-divider content-position="left">模拟波形</el-divider>
          <div class="form-row2">
            <el-form-item label="波形">
              <el-select v-model="varForm.mockKind">
                <el-option label="正弦" value="sine" />
                <el-option label="三角" value="ramp" />
                <el-option label="随机" value="random" />
                <el-option label="方波" value="square" />
                <el-option label="保持（反控回环）" value="hold" />
              </el-select>
            </el-form-item>
            <el-form-item v-if="varForm.mockKind !== 'hold'" label="周期/间隔">
              <el-input-number v-model="varForm.mockPeriodMs" :min="500" :step="500" controls-position="right" />
              <span class="form-hint">ms</span>
            </el-form-item>
          </div>
          <div v-if="varForm.mockKind !== 'hold'" class="form-row2">
            <el-form-item label="最小值"><el-input-number v-model="varForm.mockMin" controls-position="right" /></el-form-item>
            <el-form-item label="最大值"><el-input-number v-model="varForm.mockMax" controls-position="right" /></el-form-item>
          </div>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="varVisible = false">取消</el-button>
        <el-button type="primary" @click="saveVar">保存</el-button>
      </template>
    </el-dialog>

    <!-- OPC UA 节点浏览（阶段三）：一层子节点，可下钻/返回/选中 -->
    <el-dialog v-model="browseVisible" title="OPC UA 节点浏览" width="620px" append-to-body>
      <div class="browse-bar">
        <el-button size="small" :disabled="browseStack.length <= 1" @click="browseUp">← 上级</el-button>
        <el-breadcrumb separator="/">
          <el-breadcrumb-item v-for="(s, i) in browseStack" :key="i">{{ s.label }}</el-breadcrumb-item>
        </el-breadcrumb>
      </div>
      <el-alert v-if="browseMessage && !browseNodes.length" :title="browseMessage" type="info" :closable="false" show-icon />
      <el-table v-loading="browseLoading" :data="browseNodes" size="small" max-height="360" empty-text="没有子节点">
        <el-table-column prop="browseName" label="名称" min-width="140" show-overflow-tooltip />
        <el-table-column prop="nodeId" label="NodeId" min-width="220" show-overflow-tooltip />
        <el-table-column label="操作" width="130" align="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="browsePick(row)">选择</el-button>
            <el-button link size="small" @click="browseInto(row)">进入</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="form-hint">「选择」= 用该节点做变量地址；「进入」= 查看它的子节点。最多列 100 个。</div>
      <template #footer><el-button @click="browseVisible = false">关闭</el-button></template>
    </el-dialog>

    <!-- CSV 批量导入预览（工厂可用阶段一 Task 6） -->
    <el-dialog v-model="csvVisible" title="导入点位 CSV" width="760px" append-to-body>
      <div class="csv-summary">
        <span>{{ csvFileName }}</span>
        <span>解析成功 {{ csvRows.length }} 行</span>
        <span v-if="csvNewRows.length">新增 {{ csvNewRows.length }} 个</span>
        <span v-if="csvUpdateRows.length">更新已有 {{ csvUpdateRows.length }} 个</span>
        <span v-if="csvVirtualConflicts.length" class="csv-err">虚拟变量 key 冲突 {{ csvVirtualConflicts.length }} 个（跳过）</span>
        <span v-if="csvErrors.length" class="csv-err">错误 {{ csvErrors.length }} 条</span>
      </div>
      <div class="form-hint csv-header-hint">
        表头固定英文列名（前四列必填）：{{ POINT_CSV_COLUMNS.join(',') }}
      </div>
      <el-form label-width="92px" size="small">
        <el-form-item label="目标数据源" required>
          <el-select v-model="csvDsId">
            <el-option v-for="d in datasources" :key="d.id" :label="`${d.name}（${TYPE_LABEL[d.type]}）`" :value="d.id" />
          </el-select>
          <span class="form-hint">CSV 不设凭证列，凭证在数据源表单配置</span>
        </el-form-item>
        <div v-if="csvCrossDsUpdates" class="form-hint">
          已有变量保持各自原数据源（{{ csvCrossDsUpdates }} 个与所选不同），所选源只用于新增变量。
        </div>
      </el-form>
      <el-alert
        v-if="csvModbusConflict"
        type="error" :closable="false" show-icon
        :title="`${csvModbusConflict} 行携带 Modbus 字段（modbusDataType/modbusByteOrder/unitId），目标数据源须选择 Modbus TCP 类型`"
      />
      <el-table v-if="csvRows.length" :data="csvRows.slice(0, 20)" size="small" max-height="300">
        <el-table-column prop="key" label="key" min-width="110" />
        <el-table-column prop="label" label="名称" min-width="110" />
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            {{ row.type }}<el-tag v-if="row.writable" type="success" size="small" style="margin-left: 2px">可写</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="address" label="地址" min-width="90" />
        <el-table-column label="换算" min-width="110">
          <template #default="{ row }">
            <span v-if="row.bitIndex != null">bit{{ row.bitIndex }}</span>
            <span v-else-if="row.scale != null || row.offset != null || row.precision != null">
              ×{{ row.scale ?? 1 }} +{{ row.offset ?? 0 }} p{{ row.precision ?? '-' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="量程" width="90">
          <template #default="{ row }">{{ row.range ? `${row.range.min} ~ ${row.range.max}` : '' }}</template>
        </el-table-column>
        <el-table-column label="Modbus" min-width="130">
          <template #default="{ row }">
            {{ [row.modbusDataType ?? '', row.modbusByteOrder ?? '', row.unitId != null ? `u${row.unitId}` : ''].filter(Boolean).join('/') }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="70">
          <template #default="{ row }">
            <el-tag v-if="csvVirtualConflicts.includes(row.key)" type="info" size="small">跳过（虚拟变量）</el-tag>
            <el-tag v-else-if="csvUpdateRows.some((r) => r.key === row.key)" type="warning" size="small">更新</el-tag>
            <el-tag v-else type="success" size="small">新增</el-tag>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="csvRows.length > 20" class="form-hint">仅预览前 20 行，共 {{ csvRows.length }} 行</div>
      <div v-if="csvErrors.length" class="csv-errors">
        <div v-for="(e, i) in csvErrors" :key="i">第 {{ e.line }} 行：{{ e.message }}</div>
      </div>
      <template #footer>
        <el-button @click="csvVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!csvCanImport" @click="confirmCsvImport">
          导入{{ csvImportable.length ? `（${csvImportable.length} 个）` : '' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 报警规则表单 -->
    <el-dialog v-model="almVisible" :title="almForm.id ? '编辑规则' : '新增规则'" width="500px" append-to-body>
      <el-form label-width="92px" size="small">
        <el-form-item label="名称" required><el-input v-model="almForm.name" /></el-form-item>
        <el-form-item label="变量" required>
          <el-select v-model="almForm.variableId" filterable>
            <el-option v-for="v in variables" :key="v.id" :label="`${v.label}（${v.key}）`" :value="v.id" />
          </el-select>
        </el-form-item>
        <div class="form-row2">
          <el-form-item label="条件">
            <el-select v-model="almForm.op" style="width: 80px">
              <el-option v-for="op in ['>', '>=', '<', '<=', '==', '!=']" :key="op" :label="op" :value="op" />
            </el-select>
          </el-form-item>
          <el-form-item label="阈值">
            <el-input-number v-model="almForm.threshold" :step="1" controls-position="right" />
          </el-form-item>
        </div>
        <el-form-item label="级别">
          <el-select v-model="almForm.level">
            <el-option label="提示 info" value="info" />
            <el-option label="警告 warn" value="warn" />
            <el-option label="严重 critical" value="critical" />
          </el-select>
        </el-form-item>
        <el-form-item label="消息模板">
          <el-input v-model="almForm.message" placeholder="占位符 {key} {label} {value} {threshold}" />
        </el-form-item>
        <div class="form-row2">
          <el-form-item label="迟滞">
            <el-input-number v-model="almForm.hysteresis" :min="0" :step="1" controls-position="right" />
          </el-form-item>
          <el-form-item label="持续(秒)">
            <el-input-number v-model="almDurationSec" :min="0" :step="1" controls-position="right" />
            <span class="form-hint">0 = 立即触发</span>
          </el-form-item>
        </div>
        <div class="form-row2">
          <el-form-item label="提示音"><el-switch v-model="almForm.sound" /></el-form-item>
          <el-form-item label="启用"><el-switch v-model="almForm.enabled" /></el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="almVisible = false">取消</el-button>
        <el-button type="primary" @click="saveAlm">保存</el-button>
      </template>
    </el-dialog>

    <!-- 通知渠道表单（工厂可用阶段二 Task 4） -->
    <el-dialog v-model="chVisible" :title="chForm.idx >= 0 ? '编辑通知渠道' : '新增通知渠道'" width="500px" append-to-body>
      <el-form label-width="92px" size="small">
        <el-form-item label="类型" required>
          <el-select v-model="chForm.kind" :disabled="chForm.idx >= 0">
            <el-option label="Webhook（通用）" value="webhook" />
            <el-option label="钉钉机器人" value="dingtalk" />
            <el-option label="企业微信机器人" value="wecom" />
            <el-option label="邮件" value="email" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="chForm.kind !== 'email'" label="URL" required>
          <el-input
            v-model="chForm.url"
            :placeholder="chForm.kind === 'dingtalk'
              ? 'https://oapi.dingtalk.com/robot/send?access_token=…'
              : chForm.kind === 'wecom' ? 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…' : 'https://…'"
          />
        </el-form-item>
        <el-form-item v-if="chForm.kind === 'dingtalk'" label="加签密钥">
          <div class="secret-row">
            <el-input
              v-model="chForm.secret"
              type="password" show-password
              :placeholder="chForm.idx >= 0 ? '留空 = 保留已保存密钥' : 'SEC…（机器人安全设置选「加签」时的密钥，可空）'"
            />
            <el-checkbox v-if="chForm.idx >= 0" v-model="chForm.clearSecret">清除</el-checkbox>
          </div>
        </el-form-item>
        <el-form-item v-if="chForm.kind === 'email'" label="收件人" required>
          <el-input v-model="chForm.recipientsText" type="textarea" :rows="4" placeholder="一行一个邮箱，1~20 个" />
        </el-form-item>
        <el-form-item label="级别阈值">
          <el-select v-model="chForm.minLevel">
            <el-option label="提示 info 及以上" value="info" />
            <el-option label="警告 warn 及以上" value="warn" />
            <el-option label="仅严重 critical" value="critical" />
          </el-select>
          <span class="form-hint">低于该级别的报警不向本渠道发送</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="chVisible = false">取消</el-button>
        <el-button type="primary" @click="saveCh">保存</el-button>
      </template>
    </el-dialog>

    <!-- CSV 文件选择（隐藏，避免原生控件样式） -->
    <input ref="csvFileInput" class="hidden-file" type="file" accept=".csv,text/csv" @change="onCsvFileChange" />
  </el-drawer>
</template>

<style scoped>
.pane {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* 新增按钮不随 flex 容器拉伸的全宽横条，保持左对齐的小尺寸主操作 */
.pane > .el-button {
  align-self: flex-start;
}

/* 工具条（变量 tab：新增 / 导入 CSV / 搜索） */
.toolbar {
  display: flex;
  gap: 8px;
  align-self: stretch;
  align-items: center;
}

.var-search {
  width: 220px;
  margin-left: auto;
}

.quality-tag {
  margin-left: 4px;
}

.cell-mono {
  font-family: var(--ws-font-mono, monospace);
  font-size: 12px;
  word-break: break-all;
}

.browse-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.hidden-file {
  display: none;
}

.csv-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 12px;
  color: var(--ws-text-2);
}

.csv-summary .csv-err {
  color: var(--ws-alert);
}

.csv-header-hint {
  display: block;
  margin: 4px 0 10px;
}

.csv-errors {
  margin-top: 8px;
  max-height: 150px;
  overflow: auto;
  color: var(--ws-alert);
  font-size: 12px;
  line-height: 1.9;
}

.form-row2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  column-gap: 8px;
}

/* 钉钉密钥行：密码框 + 清除复选（清除 = 提交 null，服务端删除已存密钥） */
.secret-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.form-hint {
  margin-left: 6px;
  color: var(--ws-text-3);
  font-size: 12px;
}
</style>
