<script setup lang="ts">
/**
 * 属性面板：无选中显示页面属性；单选显示 几何/显示/样式/组件属性(schema 驱动)；多选提示。
 * 连续编辑经 mergeKey 合并为一条 undo 记录（history.ts 800ms 窗口）。
 */
import { computed } from 'vue'
import { useEditorStore } from '@/stores/editor'
import { registry, type PropSchemaItem } from '@/widgets/registry'
import type { AdaptiveMode } from '@/types/doc'

const editor = useEditorStore()

const node = computed(() => editor.primarySelected)
const multi = computed(() => editor.selectedNodes.length > 1)
const meta = computed(() => (node.value ? registry.get(node.value.type) : null))

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

type StyleKey = 'fill' | 'color' | 'fontSize' | 'fontWeight' | 'textAlign' | 'borderRadius'

function getStyle(key: StyleKey): unknown {
  return (node.value?.style as Record<string, unknown> | undefined)?.[key]
}

function setStyle(key: StyleKey, value: unknown): void {
  if (!node.value) return
  // 空值（清空颜色选择等）= 删除该样式键，回落组件默认外观
  editor.updateNodeStyle(node.value.id, key, value === '' || value === null ? undefined : value)
}
</script>

<template>
  <div class="prop-panel">
    <!-- 无选中：页面属性 -->
    <template v-if="!node && !multi">
      <div v-if="editor.currentPage" class="section">
        <div class="section-title">页面属性</div>
        <el-form label-position="left" label-width="90px" size="small">
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
        <div class="section-title" style="margin-top: 12px">使用说明</div>
        <div class="hint">
          · 从左侧"组件"面板拖入组件<br />
          · 拖动移动（自动吸附 5px）；柄缩放；顶柄旋转<br />
          · Ctrl+滚轮缩放画布（25%~400%），空格拖移平移<br />
          · Ctrl+Z 撤销 / Ctrl+Shift+Z 重做（50 步）
        </div>
      </div>
    </template>

    <!-- 多选 -->
    <div v-else-if="multi" class="section">
      <div class="section-title">多选（{{ editor.selectedNodes.length }} 项）</div>
      <div class="hint">可整体拖动 / 删除 / 成组；属性面板仅支持单选编辑。</div>
      <el-button size="small" style="margin-top: 8px" @click="editor.groupSelection()">合并成组</el-button>
    </div>

    <!-- 单选 -->
    <template v-else-if="node">
      <div class="section">
        <div class="section-title">基础</div>
        <el-form label-position="left" label-width="70px" size="small">
          <el-form-item label="名称">
            <el-input :model-value="node.name" maxlength="128" @change="(v: string) => editor.updateNode(node!.id, { name: v }, `name:${node!.id}`)" />
          </el-form-item>
          <el-form-item label="类型">
            <el-input :model-value="`${meta?.name ?? node.type} (${node.type})`" disabled />
          </el-form-item>
        </el-form>
      </div>

      <div class="section">
        <div class="section-title">几何</div>
        <div class="grid-2">
          <div class="field">
            <span>X</span>
            <el-input-number :model-value="num(node.x, 0)" :step="1" size="small" @change="(v?: number) => setRect('x', v)" />
          </div>
          <div class="field">
            <span>Y</span>
            <el-input-number :model-value="num(node.y, 0)" :step="1" size="small" @change="(v?: number) => setRect('y', v)" />
          </div>
          <div class="field">
            <span>宽</span>
            <el-input-number :model-value="num(node.w, 100)" :min="1" size="small" @change="(v?: number) => setRect('w', v)" />
          </div>
          <div class="field">
            <span>高</span>
            <el-input-number :model-value="num(node.h, 50)" :min="1" size="small" @change="(v?: number) => setRect('h', v)" />
          </div>
          <div class="field">
            <span>角度°</span>
            <el-input-number :model-value="num(node.rotate, 0)" :min="0" :max="359" :step="1" size="small" @change="(v?: number) => setRect('rotate', v)" />
          </div>
          <div class="field">
            <span>图层 z</span>
            <el-input-number :model-value="num(node.z, 0)" :min="0" size="small" @change="(v?: number) => setRect('z', v)" />
          </div>
        </div>
      </div>

      <div class="section">
        <div class="section-title">显示</div>
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
      </div>

      <div class="section">
        <div class="section-title">样式</div>
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
            <span>字号</span>
            <el-input-number
              :model-value="(getStyle('fontSize') as number) ?? 14"
              :min="8" :max="200" size="small"
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
      </div>

      <div v-if="meta && meta.propsSchema.length" class="section">
        <div class="section-title">组件属性（{{ meta.name }}）</div>
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
      </div>
    </template>
  </div>
</template>

<style scoped>
.prop-panel {
  padding: 10px 12px;
  color: #cbd5e1;
  overflow-y: auto;
  height: 100%;
  box-sizing: border-box;
}

.section {
  margin-bottom: 18px;
}

.section-title {
  font-size: 12px;
  color: #64748b;
  border-bottom: 1px solid #1e293b;
  padding-bottom: 4px;
  margin-bottom: 8px;
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
}

.field > span {
  width: 42px;
  flex-shrink: 0;
  color: #94a3b8;
}

.field :deep(.el-input-number) {
  width: 100px;
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
  color: #64748b;
  font-size: 12px;
  line-height: 1.8;
}
</style>
