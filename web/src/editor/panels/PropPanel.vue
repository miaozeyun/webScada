<script setup lang="ts">
/**
 * 属性面板（结构/样式参照 visual-drag-demo：无选中=CanvasAttr 画布属性标题；单选=el-collapse 分区表单）：
 * 单选显示 基础/几何/显示/样式/组件属性(schema 驱动)；多选提示成组。
 * 连续编辑经 mergeKey 合并为一条 undo 记录（history.ts 800ms 窗口）。
 */
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { useEditorStore } from '@/stores/editor'
import { registry, type PropSchemaItem } from '@/widgets/registry'
import { newId } from '@/utils/nanoid'
import type { AdaptiveMode, Binding, ComponentAnimations, ValueMapping } from '@/types/doc'

const editor = useEditorStore()

const node = computed(() => editor.primarySelected)
const multi = computed(() => editor.selectedNodes.length > 1)
const meta = computed(() => (node.value ? registry.get(node.value.type) : null))

const activeSections = ref(['basic', 'geometry', 'display', 'style', 'bindings', 'animations', 'props'])

const ADAPTIVE_OPTIONS: { label: string; value: AdaptiveMode }[] = [
  { label: 'fixed 原始像素', value: 'fixed' },
  { label: 'fit-width 宽度铺满', value: 'fit-width' },
  { label: 'fit-height 高度铺满', value: 'fit-height' },
  { label: 'fit-contain 等比缩放居中（推荐）', value: 'fit-contain' },
  { label: 'stretch 拉伸铺满（可能变形）', value: 'stretch' },
]

// ---- 数值字段辅助（geometry 输入） ----
function num(v: number | undefined, fallback: number): number {
  return v ?? fallback
}

function setRect(key: 'x' | 'y' | 'w' | 'h' | 'rotate' | 'z' | 'opacity', value: number | undefined): void {
  if (!node.value || value === undefined || Number.isNaN(value)) return
  editor.updateNode(node.value.id, { [key]: value }, `rect:${node.value.id}:${key}`)
}

function getProp(item: PropSchemaItem): unknown {
  const v = node.value?.props[item.key]
  return v === undefined ? item.defaultValue : v
}

function setProp(item: PropSchemaItem, value: unknown): void {
  if (!node.value) return
  editor.updateNodeProps(node.value.id, item.key, value)
}

type StyleKey = 'fill' | 'color' | 'fontSize' | 'fontWeight' | 'textAlign' | 'borderRadius' | 'stroke' | 'strokeWidth'

function getStyle(key: StyleKey): unknown {
  return (node.value?.style as Record<string, unknown> | undefined)?.[key]
}

function setStyle(key: StyleKey, value: unknown): void {
  if (!node.value) return
  // 空值（清空颜色选择等）= 删除该样式键，回落组件默认外观
  editor.updateNodeStyle(node.value.id, key, value === '' || value === null ? undefined : value)
}

// ---- 绑定（M3）：变量 → props.*/style.*/visible/opacity，value/color/visibility 三模式 ----

const variables = computed(() => editor.doc?.variables ?? [])
const varLabel = (id: string): string => variables.value.find((v) => v.id === id)?.label ?? '（变量已删除）'

const PROP_OPTIONS = [
  { label: 'props.value（数值类单值）', value: 'props.value' },
  { label: 'props.percent（进度条）', value: 'props.percent' },
  { label: 'props.text（文本）', value: 'props.text' },
  { label: 'props.data（图表历史序列）', value: 'props.data' },
  { label: 'style.color（颜色/文字色）', value: 'style.color' },
  { label: 'style.fill（填充）', value: 'style.fill' },
  { label: 'visible（显隐）', value: 'visible' },
  { label: 'opacity（不透明度）', value: 'opacity' },
]

const bindForm = reactive({
  prop: 'props.value',
  variableId: '',
  mode: 'value' as Binding['mode'],
  // color/visibility 的枚举映射（变量值字符串 → 显示值/颜色）
  mapRows: [
    { k: 'true', v: '#f56c6c' },
    { k: 'false', v: '#67c23a' },
  ],
})

function addBinding(): void {
  if (!node.value) return
  if (!bindForm.variableId) {
    ElMessage.warning('请选择变量（先在工具栏「数据」中定义）')
    return
  }
  const mapping: ValueMapping | null =
    bindForm.mode === 'value'
      ? null
      : {
          kind: 'enum',
          map: Object.fromEntries(bindForm.mapRows.filter((r) => r.k !== '').map((r) => [r.k, r.v])),
        }
  const list = [...(node.value.bindings ?? []), { id: newId('bnd'), prop: bindForm.prop, variableId: bindForm.variableId, mode: bindForm.mode, mapping }]
  editor.updateNode(node.value.id, { bindings: list }, 'bindings')
}

function removeBinding(id: string): void {
  if (!node.value) return
  editor.updateNode(node.value.id, { bindings: node.value.bindings.filter((b) => b.id !== id) }, 'bindings')
}

// ---- 动画（M4）：blink / flow / rotate ----

function setAnim(patch: Partial<ComponentAnimations>): void {
  if (!node.value) return
  editor.updateNode(node.value.id, { animations: { ...(node.value.animations ?? {}), ...patch } }, 'anim')
}
</script>

<template>
  <div class="attr-container">
    <!-- 无选中：画布属性（参照 CanvasAttr.vue） -->
    <template v-if="!node && !multi">
      <p class="attr-title">画布属性</p>
      <div v-if="editor.currentPage" class="attr-body">
        <el-form label-position="left" label-width="80px" size="small">
          <el-form-item label="设计宽度">
            <el-input-number
              :model-value="editor.currentPage.screen.designWidth"
              :min="200" :max="7680" :step="10"
              @change="(v?: number) => editor.updatePage({ designWidth: v ?? 1920 })"
            />
          </el-form-item>
          <el-form-item label="设计高度">
            <el-input-number
              :model-value="editor.currentPage.screen.designHeight"
              :min="200" :max="4320" :step="10"
              @change="(v?: number) => editor.updatePage({ designHeight: v ?? 1080 })"
            />
          </el-form-item>
          <el-form-item label="自适应">
            <el-select
              :model-value="editor.currentPage.screen.mode"
              @update:model-value="editor.updatePage({ mode: $event as AdaptiveMode })"
            >
              <el-option v-for="o in ADAPTIVE_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="背景色">
            <el-color-picker
              :model-value="editor.currentPage.background.color"
              @update:model-value="editor.updatePage({}, $event ?? '#0b1220')"
            />
          </el-form-item>
        </el-form>
        <p class="attr-title sub">使用说明</p>
        <div class="hint">
          · 从左侧"组件"面板拖入组件<br />
          · 拖动移动（自动吸附 5px）；柄缩放；顶柄旋转<br />
          · Ctrl+滚轮缩放画布（25%~400%），空格拖移平移<br />
          · Ctrl+Z 撤销 / Ctrl+Shift+Z 重做（50 步）
        </div>
      </div>
    </template>

    <!-- 多选 -->
    <div v-else-if="multi" class="attr-body">
      <p class="attr-title">多选（{{ editor.selectedNodes.length }} 项）</p>
      <div class="hint">可整体拖动 / 删除 / 成组；属性面板仅支持单选编辑。</div>
      <el-button size="small" style="margin-top: 8px" @click="editor.groupSelection()">合并成组</el-button>
    </div>

    <!-- 单选：折叠分区（参照 CommonAttr.vue 的 el-collapse 结构） -->
    <template v-else-if="node">
      <p class="attr-title">{{ meta?.name ?? node.type }}属性</p>
      <el-scrollbar class="attr-scroll">
        <div class="attr-body">
          <el-collapse v-model="activeSections">
            <el-collapse-item title="基础" name="basic">
              <el-form label-position="left" label-width="60px" size="small">
                <el-form-item label="名称">
                  <el-input :model-value="node.name" maxlength="128" @change="(v: string) => editor.updateNode(node!.id, { name: v }, `name:${node!.id}`)" />
                </el-form-item>
                <el-form-item label="类型">
                  <el-input :model-value="`${meta?.name ?? node.type} (${node.type})`" disabled />
                </el-form-item>
              </el-form>
            </el-collapse-item>

            <el-collapse-item title="几何" name="geometry">
              <div class="grid-2">
                <div class="field">
                  <span>X</span>
                  <el-input-number :model-value="num(node.x, 0)" :step="1" size="small" controls-position="right" @change="(v?: number) => setRect('x', v)" />
                </div>
                <div class="field">
                  <span>Y</span>
                  <el-input-number :model-value="num(node.y, 0)" :step="1" size="small" controls-position="right" @change="(v?: number) => setRect('y', v)" />
                </div>
                <div class="field">
                  <span>宽</span>
                  <el-input-number :model-value="num(node.w, 100)" :min="1" size="small" controls-position="right" @change="(v?: number) => setRect('w', v)" />
                </div>
                <div class="field">
                  <span>高</span>
                  <el-input-number :model-value="num(node.h, 50)" :min="1" size="small" controls-position="right" @change="(v?: number) => setRect('h', v)" />
                </div>
                <div class="field">
                  <span>角度</span>
                  <el-input-number :model-value="num(node.rotate, 0)" :min="0" :max="359" :step="1" size="small" controls-position="right" @change="(v?: number) => setRect('rotate', v)" />
                </div>
                <div class="field">
                  <span>z</span>
                  <el-input-number :model-value="num(node.z, 0)" :min="0" size="small" controls-position="right" @change="(v?: number) => setRect('z', v)" />
                </div>
              </div>
            </el-collapse-item>

            <el-collapse-item title="显示" name="display">
              <div class="switch-row">
                <el-checkbox
                  :model-value="node.visible !== false"
                  label="可见"
                  @change="(v: boolean) => editor.updateNode(node!.id, { visible: v }, `vis:${node!.id}`)"
                />
                <el-checkbox
                  :model-value="node.locked === true"
                  label="锁定"
                  @change="(v: boolean) => editor.updateNode(node!.id, { locked: v }, `lock:${node!.id}`)"
                />
              </div>
              <div class="field">
                <span>透明度</span>
                <el-slider
                  :model-value="(node.opacity ?? 1) * 100"
                  :min="0" :max="100" :step="1"
                  @change="(v: number | number[]) => setRect('opacity', (v as number) / 100)"
                />
              </div>
            </el-collapse-item>

            <el-collapse-item title="样式" name="style">
              <div class="style-grid">
                <div class="field">
                  <span>填充</span>
                  <el-color-picker :model-value="(getStyle('fill') as string) ?? ''" @update:model-value="(v: string | null) => setStyle('fill', v ?? '')" />
                </div>
                <div class="field">
                  <span>文字色</span>
                  <el-color-picker :model-value="(getStyle('color') as string) ?? ''" @update:model-value="(v: string | null) => setStyle('color', v ?? '')" />
                </div>
                <div class="field">
                  <span>边框色</span>
                  <el-color-picker :model-value="(getStyle('stroke') as string) ?? ''" @update:model-value="(v: string | null) => setStyle('stroke', v ?? '')" />
                </div>
                <div class="field">
                  <span>边框宽</span>
                  <el-input-number
                    :model-value="(getStyle('strokeWidth') as number) ?? 1"
                    :min="0" :max="50" size="small" controls-position="right"
                    @change="(v?: number) => v !== undefined && setStyle('strokeWidth', v)"
                  />
                </div>
                <div class="field">
                  <span>圆角</span>
                  <el-input-number
                    :model-value="(getStyle('borderRadius') as number) ?? 0"
                    :min="0" :max="200" size="small" controls-position="right"
                    @change="(v?: number) => v !== undefined && setStyle('borderRadius', v)"
                  />
                </div>
                <div class="field">
                  <span>字号</span>
                  <el-input-number
                    :model-value="(getStyle('fontSize') as number) ?? 14"
                    :min="8" :max="200" size="small" controls-position="right"
                    @change="(v?: number) => v && setStyle('fontSize', v)"
                  />
                </div>
                <div class="field">
                  <span>对齐</span>
                  <el-select
                    :model-value="(getStyle('textAlign') as string) ?? 'left'"
                    size="small"
                    @update:model-value="(v: string) => setStyle('textAlign', v)"
                  >
                    <el-option label="左" value="left" />
                    <el-option label="中" value="center" />
                    <el-option label="右" value="right" />
                  </el-select>
                </div>
              </div>
            </el-collapse-item>

            <el-collapse-item :title="`绑定（${node.bindings?.length ?? 0}）`" name="bindings">
              <div v-if="!variables.length" class="hint">尚无变量。先在顶部工具栏「数据」中添加数据源与变量。</div>
              <div v-for="b in node.bindings ?? []" :key="b.id" class="binding-row">
                <span class="binding-prop">{{ b.prop }}</span>
                <span class="binding-arrow">←</span>
                <span class="binding-var" :title="b.variableId">{{ varLabel(b.variableId) }}</span>
                <span class="binding-mode">{{ b.mode }}</span>
                <el-button link type="danger" size="small" @click="removeBinding(b.id)">删</el-button>
              </div>
              <el-divider style="margin: 8px 0" />
              <div class="bind-form">
                <el-select v-model="bindForm.prop" size="small">
                  <el-option v-for="o in PROP_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
                </el-select>
                <el-select v-model="bindForm.variableId" size="small" placeholder="选择变量">
                  <el-option v-for="v in variables" :key="v.id" :label="`${v.label}（${v.key}）`" :value="v.id" />
                </el-select>
                <el-select v-model="bindForm.mode" size="small" style="width: 110px">
                  <el-option label="值 value" value="value" />
                  <el-option label="颜色 color" value="color" />
                  <el-option label="显隐 visibility" value="visibility" />
                </el-select>
                <template v-if="bindForm.mode !== 'value'">
                  <div v-for="(row, i) in bindForm.mapRows" :key="i" class="map-row">
                    <span class="map-k">值 {{ row.k }}</span>
                    <el-color-picker v-if="bindForm.mode === 'color'" v-model="row.v" size="small" />
                    <el-input v-else v-model="row.v" size="small" placeholder="true / false" style="width: 90px" />
                  </div>
                  <el-button link type="primary" size="small" :icon="Plus"
                    @click="bindForm.mapRows.push({ k: '', v: bindForm.mode === 'color' ? '#409eff' : 'true' })">
                    添加映射行
                  </el-button>
                </template>
                <el-button type="primary" size="small" style="align-self: flex-start" @click="addBinding">添加绑定</el-button>
              </div>
            </el-collapse-item>

            <el-collapse-item title="动画" name="animations">
              <div class="anim-row">
                <span>闪烁</span>
                <el-switch
                  :model-value="node.animations?.blink?.enabled === true"
                  @change="(v: boolean) => setAnim({ blink: { enabled: v, intervalMs: node!.animations?.blink?.intervalMs ?? 1000 } })"
                />
                <el-input-number
                  :model-value="node.animations?.blink?.intervalMs ?? 1000"
                  :min="100" :step="100" size="small" controls-position="right"
                  @change="(v?: number) => setAnim({ blink: { enabled: true, intervalMs: v ?? 1000 } })"
                />
                <span class="form-hint">ms</span>
              </div>
              <div class="anim-row">
                <span>流动</span>
                <el-switch
                  :model-value="node.animations?.flow?.enabled === true"
                  @change="(v: boolean) => setAnim({ flow: { enabled: v, speed: node!.animations?.flow?.speed ?? 40 } })"
                />
                <el-input-number
                  :model-value="node.animations?.flow?.speed ?? 40"
                  :min="5" :max="400" size="small" controls-position="right"
                  @change="(v?: number) => setAnim({ flow: { enabled: true, speed: v ?? 40 } })"
                />
                <span class="form-hint">px/s（管道/直线）</span>
              </div>
              <div class="anim-row">
                <span>旋转</span>
                <el-switch
                  :model-value="node.animations?.rotate?.enabled === true"
                  @change="(v: boolean) => setAnim({ rotate: { enabled: v, clockwise: true, periodMs: node!.animations?.rotate?.periodMs ?? 4000 } })"
                />
                <el-input-number
                  :model-value="node.animations?.rotate?.periodMs ?? 4000"
                  :min="200" :step="500" size="small" controls-position="right"
                  @change="(v?: number) => setAnim({ rotate: { enabled: true, clockwise: true, periodMs: v ?? 4000 } })"
                />
                <span class="form-hint">ms/圈</span>
              </div>
            </el-collapse-item>

            <el-collapse-item v-if="meta && meta.propsSchema.length" :title="`组件属性（${meta.name}）`" name="props">
              <el-form label-position="left" label-width="90px" size="small">
                <el-form-item v-for="item in meta.propsSchema" :key="item.key" :label="item.label">
                  <el-switch v-if="item.type === 'switch'" :model-value="getProp(item) === true" @change="(v: boolean) => setProp(item, v)" />
                  <el-input-number
                    v-else-if="item.type === 'number'"
                    :model-value="(getProp(item) as number)"
                    :min="item.min" :max="item.max" :step="item.step"
                    @change="(v?: number) => v !== undefined && setProp(item, v)"
                  />
                  <el-select
                    v-else-if="item.type === 'select'"
                    :model-value="getProp(item)"
                    @update:model-value="(v: string | number) => setProp(item, v)"
                  >
                    <el-option v-for="o in item.options" :key="String(o.value)" :label="o.label" :value="o.value" />
                  </el-select>
                  <el-input
                    v-else-if="item.type === 'textarea'"
                    :model-value="String(getProp(item) ?? '')"
                    type="textarea" :rows="2"
                    @change="(v: string) => setProp(item, v)"
                  />
                  <el-input v-else :model-value="String(getProp(item) ?? '')" @change="(v: string) => setProp(item, v)" />
                </el-form-item>
              </el-form>
            </el-collapse-item>
          </el-collapse>
        </div>
      </el-scrollbar>
    </template>
  </div>
</template>

<style scoped>
.attr-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #fff;
  color: #606266;
}

/* 标题（数值参照 CanvasAttr.vue） */
.attr-title {
  text-align: center;
  margin: 0;
  height: 40px;
  line-height: 40px;
  border-bottom: 2px solid #e4e7ed;
  font-size: 14px;
  font-weight: 500;
  color: #606266;
  flex-shrink: 0;
}

.attr-title.sub {
  border-bottom: none;
  font-size: 13px;
  height: 30px;
  line-height: 30px;
}

.attr-body {
  padding: 10px 14px;
  overflow-y: auto;
  box-sizing: border-box;
}

.attr-scroll {
  flex: 1;
  min-height: 0;
}

.grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 10px;
}

.field {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  min-width: 0;
}

.field > span {
  width: 32px;
  flex-shrink: 0;
  color: #909399;
}

/* 面板 288px 内两列布局：输入框 flex 自适应，避免步进按钮截断 */
.field :deep(.el-input-number) {
  width: 100%;
  min-width: 0;
  flex: 1;
}

.field :deep(.el-slider) {
  flex: 1;
}

.style-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 10px;
}

.switch-row {
  display: flex;
  gap: 12px;
  margin-bottom: 8px;
}

.hint {
  color: #909399;
  font-size: 12px;
  line-height: 1.8;
}

.binding-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  padding: 3px 0;
  color: #606266;
}

.binding-prop {
  color: #409eff;
  font-family: Consolas, monospace;
}

.binding-arrow {
  color: #c0c4cc;
}

.binding-var {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.binding-mode {
  font-size: 11px;
  color: #909399;
  border: 1px solid #e4e7ed;
  border-radius: 3px;
  padding: 0 4px;
}

.bind-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.bind-form > .el-select {
  width: 100%;
}

.map-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.map-k {
  width: 70px;
  color: #909399;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.anim-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  padding: 4px 0;
}

.anim-row > span:first-child {
  width: 34px;
  color: #909399;
}

.form-hint {
  color: #909399;
  font-size: 12px;
}
</style>
