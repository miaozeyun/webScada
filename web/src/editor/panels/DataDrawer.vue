<script setup lang="ts">
/**
 * 工程数据管理（M3/M5）：数据源 / 变量 / 报警规则 / 通知渠道 四表 CRUD（Drawer + el-tabs）。
 * 直接编辑 editor.doc 对应数组并 _markDirty（走 3s 自动保存链路）；
 * doc 级数据不入页面级 undo 栈（历史为页面快照，语义不含本面板）。
 */
import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Upload } from '@element-plus/icons-vue'
import { useEditorStore } from '@/stores/editor'
import { newId } from '@/utils/nanoid'
import { parsePointCsv, POINT_CSV_COLUMNS } from '@/utils/pointCsv'
import type { PointCsvError, PointCsvRow } from '@/utils/pointCsv'
import { VIRTUAL_DATASOURCE_ID } from '@/types/doc'
import { testDatasource } from '@/api/datasources'
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
const tab = ref<'sources' | 'variables' | 'alarms' | 'notify'>('sources')

const datasources = computed<DataSource[]>(() => editor.doc?.datasources ?? [])
const variables = computed<VariableDef[]>(() => editor.doc?.variables ?? [])
const alarms = computed<AlarmRule[]>(() => editor.doc?.alarmRules ?? [])
const channels = computed<NotifyChannel[]>(() => editor.doc?.settings?.notify?.channels ?? [])

function markDirty(): void {
  editor._markDirty()
}

const TYPE_LABEL: Record<string, string> = { mock: '模拟', websocket: 'WebSocket', rest: 'REST', mqtt: 'MQTT', modbus: 'Modbus TCP' }

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
})

function openDs(ds?: DataSource): void {
  dsVisible.value = true
  if (ds) {
    dsForm.id = ds.id
    dsForm.name = ds.name
    dsForm.type = ds.type
    dsForm.enabled = ds.enabled !== false
    dsForm.url = ds.type === 'mqtt' ? ds.config.brokerUrl : ds.type === 'modbus' ? ds.config.host : ds.type === 'rest' || ds.type === 'websocket' ? ds.config.url : ''
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
  } else {
    Object.assign(dsForm, { id: '', name: '', type: 'mock', enabled: true, url: '', topics: '', intervalMs: 1000, writeUrl: '', writeMethod: 'POST' as const, writeBodyTemplate: '', writeFrameTemplate: '', writeQos: 0 as const, mbPort: 502, mbUnitId: 1 })
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
        password: '',
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
  if (dsForm.id) {
    const idx = doc.datasources.findIndex((d) => d.id === dsForm.id)
    doc.datasources[idx] = { id: dsForm.id, name: dsForm.name.trim(), type: dsForm.type, enabled: dsForm.enabled, config: buildConfig() } as DataSource
  } else {
    doc.datasources.push({ id: newId('ds'), name: dsForm.name.trim(), type: dsForm.type, enabled: dsForm.enabled, config: buildConfig() } as DataSource)
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
    const r = await testDatasource({ type: dsForm.type, config: buildConfig() as Record<string, unknown> })
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
  const used = variables.value.filter((v) => v.datasourceId === ds.id).length
  try {
    await ElMessageBox.confirm(
      used ? `该数据源下有 ${used} 个变量，删除后变量将失效。确定删除？` : `确定删除数据源「${ds.name}」？`,
      '删除数据源',
      { type: 'warning' },
    )
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
  const item: VariableDef = {
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
    scale: varForm.scale !== 1 ? varForm.scale : null,
    offset: varForm.offset !== 0 ? varForm.offset : null,
    precision: varForm.type === 'number' ? varForm.precision : null,
    mock: isVirtual.value ? null : buildMock(),
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
  const bound = JSON.stringify(editor.doc).includes(`"variableId":"${v.id}"`)
  try {
    await ElMessageBox.confirm(
      bound ? `变量「${v.label}」已被组件绑定，删除后相关绑定失效。确定删除？` : `确定删除变量「${v.label}」？`,
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

/** 与工程已有 key 重复的行（key 唯一且不可改 → 跳过并计数，不报错） */
const csvDupKeys = computed(() => {
  const existing = new Set(variables.value.map((v) => v.key))
  return new Set(csvRows.value.filter((r) => existing.has(r.key)).map((r) => r.key))
})

/** 行内携带 Modbus 字段而目标数据源非 modbus：服务端跨检会整体 422，导入前置拦截 */
const csvModbusConflict = computed(() => {
  if (datasources.value.find((d) => d.id === csvDsId.value)?.type === 'modbus') return 0
  return csvRows.value.filter((r) => r.modbusDataType != null || r.modbusByteOrder != null || r.unitId != null).length
})

const csvImportable = computed(() => csvRows.value.filter((r) => !csvDupKeys.value.has(r.key)))

const csvCanImport = computed(
  () => !!csvDsId.value && csvErrors.value.length === 0 && csvImportable.value.length > 0 && csvModbusConflict.value === 0,
)

/** 逐行构造 VariableDef（字段映射与 saveVar 同构）后追加，doc 级数据变更不入 undo 栈 */
function confirmCsvImport(): void {
  const doc = editor.doc!
  const isMock = datasources.value.find((d) => d.id === csvDsId.value)?.type === 'mock'
  for (const r of csvImportable.value) {
    doc.variables.push({
      id: newId('var'),
      key: r.key,
      label: r.label,
      type: r.type,
      unit: r.unit || null,
      defaultValue: null,
      datasourceId: csvDsId.value,
      address: r.address,
      jsonPath: r.jsonPath || null,
      expr: null,
      writable: r.writable === true,
      writeAddress: r.writeAddress || null,
      // 换算缺省语义与 saveVar 同构：scale=1/offset=0 归一为 null；precision 缺省 2（bitIndex 互斥时为 null）
      scale: r.scale != null && r.scale !== 1 ? r.scale : null,
      offset: r.offset != null && r.offset !== 0 ? r.offset : null,
      precision: r.type === 'number' && r.bitIndex == null ? (r.precision ?? 2) : null,
      bitIndex: r.bitIndex ?? null,
      mock: isMock ? { kind: 'sine', min: 0, max: 100, periodMs: 30000 } : null,
      range: r.range ?? null,
      modbusDataType: r.modbusDataType ?? null,
      modbusByteOrder: r.modbusByteOrder ?? null,
      unitId: r.unitId ?? null,
    })
  }
  const skipped = csvRows.value.length - csvImportable.value.length
  csvVisible.value = false
  ElMessage.success(skipped ? `已导入 ${csvImportable.value.length} 个变量，跳过已有 key ${skipped} 个` : `已导入 ${csvImportable.value.length} 个变量`)
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
  sound: true,
})

const LEVEL_LABEL: Record<AlarmLevel, string> = { info: '提示', warn: '警告', critical: '严重' }

function openAlm(r?: AlarmRule): void {
  almVisible.value = true
  if (r) {
    Object.assign(almForm, {
      id: r.id, name: r.name, variableId: r.variableId, op: r.op, threshold: r.threshold,
      level: r.level, message: r.message, enabled: r.enabled, hysteresis: r.hysteresis ?? 0, sound: r.sound ?? true,
    })
  } else {
    Object.assign(almForm, {
      id: '', name: '', variableId: variables.value[0]?.id ?? '', op: '>', threshold: 90,
      level: 'warn', message: '{label} = {value}（阈值 {threshold}）', enabled: true, hysteresis: 0, sound: true,
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
  <el-drawer :model-value="true" title="工程数据（数据源 / 变量 / 报警 / 通知）" size="620px" @close="emit('close')">
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
          </div>
          <el-table :data="variables" size="small" empty-text="暂无变量">
            <el-table-column prop="key" label="key" min-width="100" />
            <el-table-column prop="label" label="名称" min-width="90" />
            <el-table-column prop="type" label="类型" width="70" />
            <el-table-column label="数据源" width="110">
              <template #default="{ row }">
                <el-tag v-if="row.expr" type="warning" size="small">虚拟</el-tag>
                <template v-else>
                  {{ TYPE_LABEL[datasources.find((d) => d.id === row.datasourceId)?.type ?? ''] ?? '—' }}
                  <el-tag v-if="row.writable" type="success" size="small" style="margin-left: 2px">可写</el-tag>
                </template>
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
          <el-button size="small" type="primary" plain :icon="Plus" :disabled="!variables.length" @click="openAlm()">
            新增规则
          </el-button>
          <el-table :data="alarms" size="small" empty-text="暂无报警规则">
            <el-table-column prop="name" label="名称" min-width="100" />
            <el-table-column label="条件" min-width="130">
              <template #default="{ row }">
                {{ variables.find((v) => v.id === row.variableId)?.label ?? '?' }} {{ row.op }} {{ row.threshold }}
              </template>
            </el-table-column>
            <el-table-column label="级别" width="80">
              <template #default="{ row }">
                <el-tag :type="row.level === 'critical' ? 'danger' : row.level === 'warn' ? 'warning' : 'info'" size="small">
                  {{ LEVEL_LABEL[row.level as AlarmLevel] }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="openAlm(row)">编辑</el-button>
                <el-button link type="danger" size="small" @click="removeAlm(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
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
          </el-select>
        </el-form-item>
        <template v-if="dsForm.type !== 'mock'">
          <el-form-item :label="dsForm.type === 'mqtt' ? 'Broker 地址' : dsForm.type === 'modbus' ? 'PLC/网关 IP' : 'URL'" required>
            <el-input v-model="dsForm.url" :placeholder="dsForm.type === 'mqtt' ? 'ws://localhost:8083/mqtt' : dsForm.type === 'modbus' ? '192.168.1.10' : 'https://…'" />
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
            <el-input v-model="varForm.address" :disabled="isVirtual" placeholder="mqtt=topic / ws·rest=字段名" />
          </el-form-item>
          <el-form-item label="jsonPath">
            <el-input v-model="varForm.jsonPath" :disabled="isVirtual" placeholder="data.items[0].v" />
          </el-form-item>
        </div>
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

    <!-- CSV 批量导入预览（工厂可用阶段一 Task 6） -->
    <el-dialog v-model="csvVisible" title="导入点位 CSV" width="760px" append-to-body>
      <div class="csv-summary">
        <span>{{ csvFileName }}</span>
        <span>解析成功 {{ csvRows.length }} 行</span>
        <span v-if="csvDupKeys.size">将跳过已有 key {{ csvDupKeys.size }} 个</span>
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
            <el-tag v-if="csvDupKeys.has(row.key)" type="info" size="small">跳过</el-tag>
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
          <el-select v-model="almForm.variableId">
            <el-option v-for="v in variables" :key="v.id" :label="v.label" :value="v.id" />
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
          <el-form-item label="提示音"><el-switch v-model="almForm.sound" /></el-form-item>
        </div>
        <el-form-item label="启用"><el-switch v-model="almForm.enabled" /></el-form-item>
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

/* 工具条（变量 tab：新增 / 导入 CSV） */
.toolbar {
  display: flex;
  gap: 8px;
  align-self: flex-start;
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
