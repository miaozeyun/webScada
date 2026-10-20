<script setup lang="ts">
/**
 * 工程数据管理（M3/M5）：数据源 / 变量 / 报警规则 三表 CRUD（Drawer + el-tabs）。
 * 直接编辑 editor.doc 对应数组并 _markDirty（走 3s 自动保存链路）；
 * doc 级数据不入页面级 undo 栈（历史为页面快照，语义不含本面板）。
 */
import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { useEditorStore } from '@/stores/editor'
import { newId } from '@/utils/nanoid'
import type {
  AlarmLevel,
  AlarmOp,
  AlarmRule,
  DataSource,
  MockSpec,
  VariableDef,
  VariableType,
} from '@/types/doc'

const emit = defineEmits<{ (e: 'close'): void }>()

const editor = useEditorStore()
const tab = ref<'sources' | 'variables' | 'alarms'>('sources')

const datasources = computed<DataSource[]>(() => editor.doc?.datasources ?? [])
const variables = computed<VariableDef[]>(() => editor.doc?.variables ?? [])
const alarms = computed<AlarmRule[]>(() => editor.doc?.alarmRules ?? [])

function markDirty(): void {
  editor._markDirty()
}

const TYPE_LABEL: Record<string, string> = { mock: '模拟', websocket: 'WebSocket', rest: 'REST', mqtt: 'MQTT' }

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
})

function openDs(ds?: DataSource): void {
  dsVisible.value = true
  if (ds) {
    dsForm.id = ds.id
    dsForm.name = ds.name
    dsForm.type = ds.type
    dsForm.enabled = ds.enabled !== false
    dsForm.url = ds.type === 'mqtt' ? ds.config.brokerUrl : ds.type === 'rest' ? ds.config.url : ds.type === 'websocket' ? ds.config.url : ''
    dsForm.topics = ds.type === 'mqtt' ? (ds.config.topics ?? []).join(', ') : ''
    dsForm.intervalMs = ds.type === 'rest' ? ds.config.intervalMs : 1000
  } else {
    Object.assign(dsForm, { id: '', name: '', type: 'mock', enabled: true, url: '', topics: '', intervalMs: 1000 })
  }
}

function saveDs(): void {
  if (!dsForm.name.trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  const doc = editor.doc!
  const buildConfig = (): DataSource['config'] => {
    switch (dsForm.type) {
      case 'websocket': return { url: dsForm.url }
      case 'rest': return { url: dsForm.url, intervalMs: dsForm.intervalMs }
      case 'mqtt': return { brokerUrl: dsForm.url, topics: dsForm.topics.split(/[,\n]/).map((s) => s.trim()).filter(Boolean), password: '' }
      default: return {}
    }
  }
  if (dsForm.id) {
    const idx = doc.datasources.findIndex((d) => d.id === dsForm.id)
    doc.datasources[idx] = { id: dsForm.id, name: dsForm.name.trim(), type: dsForm.type, enabled: dsForm.enabled, config: buildConfig() } as DataSource
  } else {
    doc.datasources.push({ id: newId('ds'), name: dsForm.name.trim(), type: dsForm.type, enabled: dsForm.enabled, config: buildConfig() } as DataSource)
  }
  dsVisible.value = false
  markDirty()
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
  mockKind: 'sine' as MockSpec['kind'],
  mockMin: 0,
  mockMax: 100,
  mockPeriodMs: 30000,
  mockIntervalMs: 1000,
})

function openVar(v?: VariableDef): void {
  varVisible.value = true
  if (v) {
    Object.assign(varForm, {
      id: v.id, key: v.key, label: v.label, type: v.type,
      unit: v.unit ?? '', defaultValue: v.defaultValue === null || v.defaultValue === undefined ? '' : String(v.defaultValue),
      datasourceId: v.datasourceId, address: v.address ?? '', jsonPath: v.jsonPath ?? '',
      scale: v.scale ?? 1, offset: v.offset ?? 0, precision: v.precision ?? 2,
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
      scale: 1, offset: 0, precision: 2, mockKind: 'sine', mockMin: 0, mockMax: 100, mockPeriodMs: 30000, mockIntervalMs: 1000,
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
    default: return { kind: 'sine', min: varForm.mockMin, max: varForm.mockMax, periodMs: varForm.mockPeriodMs }
  }
}

function saveVar(): void {
  if (!varForm.key.trim() || !varForm.label.trim() || !varForm.datasourceId) {
    ElMessage.warning('请填写 key、名称并选择数据源')
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
    address: varForm.address || undefined,
    jsonPath: varForm.jsonPath || null,
    scale: varForm.scale !== 1 ? varForm.scale : null,
    offset: varForm.offset !== 0 ? varForm.offset : null,
    precision: varForm.type === 'number' ? varForm.precision : null,
    mock: buildMock(),
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
</script>

<template>
  <el-drawer :model-value="true" title="工程数据（数据源 / 变量 / 报警）" size="620px" @close="emit('close')">
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
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="openDs(row)">编辑</el-button>
                <el-button link type="danger" size="small" @click="removeDs(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <!-- 变量 -->
      <el-tab-pane :label="`变量（${variables.length}）`" name="variables">
        <div class="pane">
          <el-button size="small" type="primary" plain :icon="Plus" :disabled="!datasources.length" @click="openVar()">
            新增变量
          </el-button>
          <el-table :data="variables" size="small" empty-text="暂无变量">
            <el-table-column prop="key" label="key" min-width="100" />
            <el-table-column prop="label" label="名称" min-width="90" />
            <el-table-column prop="type" label="类型" width="70" />
            <el-table-column label="数据源" width="90">
              <template #default="{ row }">
                {{ TYPE_LABEL[datasources.find((d) => d.id === row.datasourceId)?.type ?? ''] ?? '—' }}
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
          </el-select>
        </el-form-item>
        <template v-if="dsForm.type !== 'mock'">
          <el-form-item :label="dsForm.type === 'mqtt' ? 'Broker 地址' : 'URL'" required>
            <el-input v-model="dsForm.url" :placeholder="dsForm.type === 'mqtt' ? 'ws://localhost:8083/mqtt' : 'https://…'" />
          </el-form-item>
        </template>
        <el-form-item v-if="dsForm.type === 'mqtt'" label="订阅 Topic">
          <el-input v-model="dsForm.topics" type="textarea" :rows="2" placeholder="逗号或换行分隔，如 plant1/temperature" />
        </el-form-item>
        <el-form-item v-if="dsForm.type === 'rest'" label="轮询间隔">
          <el-input-number v-model="dsForm.intervalMs" :min="500" :step="500" controls-position="right" />
          <span class="form-hint">ms</span>
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
          </el-select>
        </el-form-item>
        <div class="form-row2">
          <el-form-item label="取数地址">
            <el-input v-model="varForm.address" placeholder="mqtt=topic / ws·rest=字段名" />
          </el-form-item>
          <el-form-item label="jsonPath">
            <el-input v-model="varForm.jsonPath" placeholder="data.items[0].v" />
          </el-form-item>
        </div>
        <template v-if="varForm.type === 'number'">
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
              </el-select>
            </el-form-item>
            <el-form-item label="周期/间隔">
              <el-input-number v-model="varForm.mockPeriodMs" :min="500" :step="500" controls-position="right" />
              <span class="form-hint">ms</span>
            </el-form-item>
          </div>
          <div class="form-row2">
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
  </el-drawer>
</template>

<style scoped>
.pane {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.form-row2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  column-gap: 8px;
}

.form-hint {
  margin-left: 6px;
  color: #909399;
  font-size: 12px;
}
</style>
