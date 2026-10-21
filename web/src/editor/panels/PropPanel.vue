<script setup lang="ts">
/**
 * 属性面板（结构/样式参照 visual-drag-demo：无选中=CanvasAttr 画布属性标题；单选=el-collapse 分区表单）：
 * 单选显示 基础/几何/显示/样式/事件/悬停/绑定/动画/弹框(group)/组件属性(schema 驱动)；多选提示成组。
 * 连续编辑经 mergeKey 合并为一条 undo 记录（history.ts 800ms 窗口）。
 */
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { useEditorStore } from '@/stores/editor'
import { registry, type PropSchemaItem } from '@/widgets/registry'
import { newId } from '@/utils/nanoid'
import type {
  AdaptiveMode,
  Binding,
  ComponentAnimations,
  ComponentNode,
  EventActionDef,
  EventTrigger,
  NodeEventDef,
  ValueMapping,
} from '@/types/doc'

const editor = useEditorStore()

const node = computed(() => editor.primarySelected)
const multi = computed(() => editor.selectedNodes.length > 1)
const meta = computed(() => (node.value ? registry.get(node.value.type) : null))

// 面板标题：具名组件用组件名，组合/未知类型给中文可读名
const selectionTitle = computed(() => {
  if (!node.value) return ''
  return meta.value?.name ?? (node.value.type === 'group' ? '组合' : node.value.type)
})

const activeSections = ref(['basic', 'geometry', 'display', 'style', 'bindings', 'animations', 'events', 'props'])

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

// ---- 多选批量编辑（updateNodes/updateNodesStyle：单条 undo 覆盖全部选中项） ----

type BatchRectKey = 'x' | 'y' | 'w' | 'h' | 'rotate' | 'opacity'
const batchRect = reactive<Record<BatchRectKey, number | undefined>>({ x: undefined, y: undefined, w: undefined, h: undefined, rotate: undefined, opacity: undefined })
const multiSections = ref(['m-geometry', 'm-display'])

/** 全部选中项的公共布尔态（混合态按 false 口径显示，点击即整体设定） */
const allVisible = computed(() => editor.selectedNodes.length > 0 && editor.selectedNodes.every((n) => n.visible !== false))
const allLocked = computed(() => editor.selectedNodes.length > 0 && editor.selectedNodes.every((n) => n.locked === true))

function setBatchRect(key: BatchRectKey, value: number | undefined): void {
  if (value === undefined || value === null || Number.isNaN(value)) {
    batchRect[key] = undefined
    return
  }
  batchRect[key] = value
  editor.updateNodes({ [key]: value }, `mrect:${key}`)
}

const MULTI_TEXT_ALIGN = [
  { label: '左对齐', value: 'left' },
  { label: '居中', value: 'center' },
  { label: '右对齐', value: 'right' },
]

function setBatchStyle(key: StyleKey, value: unknown): void {
  editor.updateNodesStyle(key, value === '' || value === null ? undefined : value)
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
  { label: 'props.percent（进度条/水池液位）', value: 'props.percent' },
  { label: 'props.speed（流动条流速）', value: 'props.speed' },
  { label: 'props.text（文本）', value: 'props.text' },
  { label: 'props.data（图表历史序列）', value: 'props.data' },
  { label: 'style.color（颜色/文字色）', value: 'style.color' },
  { label: 'style.fill（填充）', value: 'style.fill' },
  { label: 'visible（显隐）', value: 'visible' },
  { label: 'opacity（不透明度）', value: 'opacity' },
  { label: 'anim.rotateOn（旋转启停）', value: 'anim.rotateOn' },
  { label: 'anim.rotatePeriod（旋转周期 ms/圈）', value: 'anim.rotatePeriod' },
  { label: 'anim.flowOn（流动启停）', value: 'anim.flowOn' },
  { label: 'anim.blinkOn（闪烁启停）', value: 'anim.blinkOn' },
  { label: 'anim.moveOn（轨迹运动启停）', value: 'anim.moveOn' },
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

// ---- 动画（M4/M7）：blink / flow / rotate / move（轨迹） ----

function setAnim(patch: Partial<ComponentAnimations>): void {
  if (!node.value) return
  editor.updateNode(node.value.id, { animations: { ...(node.value.animations ?? {}), ...patch } }, 'anim')
}

function setMove(patch: Partial<NonNullable<ComponentAnimations['move']>>): void {
  const cur = node.value?.animations?.move ?? { enabled: false, path: '', periodMs: 8000, mode: 'loop' as const }
  setAnim({ move: { ...cur, ...patch } })
}

// ---- 悬停信息（M7） ----

function setTooltip(patch: Partial<NonNullable<ComponentNode['tooltip']>>): void {
  if (!node.value) return
  const cur = node.value.tooltip ?? { enabled: true, template: '' }
  editor.updateNode(node.value.id, { tooltip: { ...cur, ...patch } }, 'tooltip')
}

// ---- 弹框（M7，仅 group） ----

function setPopup(patch: Partial<NonNullable<ComponentNode['popup']>>): void {
  if (!node.value) return
  const cur = node.value.popup ?? { style: 'dialog' as const, title: '', triggerExpr: '' }
  editor.updateNode(node.value.id, { popup: { ...cur, ...patch } }, 'popup')
}

function clearPopup(): void {
  if (!node.value) return
  editor.updateNode(node.value.id, { popup: null }, 'popup')
}

// ---- 事件与行为（M7）：trigger + 动作（一次一条，类型驱动字段） ----

const pages = computed(() => editor.doc?.pages ?? [])
/** 当前页面组件扁平列表（弹框/显隐目标选择用，含组） */
const pageNodes = computed(() => {
  const out: { id: string; name: string }[] = []
  const walk = (nodes: { id: string; name: string; children?: { id: string; name: string }[] | null }[]): void => {
    for (const n of nodes) {
      out.push({ id: n.id, name: n.name })
    }
  }
  walk((editor.currentPage?.components ?? []) as { id: string; name: string; children?: { id: string; name: string }[] | null }[])
  return out
})

const evForm = reactive({
  trigger: 'click' as EventTrigger,
  type: 'writeVar' as EventActionDef['type'],
  variableId: '',
  value: '1',
  targetId: '',
  pageId: '',
  url: '',
})

function addEvent(): void {
  if (!node.value) return
  const act: EventActionDef = { type: evForm.type }
  if (evForm.type === 'writeVar') {
    if (!evForm.variableId) {
      ElMessage.warning('请选择写入变量（且变量需开启可写）')
      return
    }
    act.variableId = evForm.variableId
    act.value = evForm.value
  } else if (evForm.type === 'switchPage') {
    if (!evForm.pageId) {
      ElMessage.warning('请选择目标页面')
      return
    }
    act.pageId = evForm.pageId
  } else if (evForm.type === 'openUrl') {
    if (!evForm.url.trim()) {
      ElMessage.warning('请填写 URL')
      return
    }
    act.url = evForm.url.trim()
  } else {
    if (!evForm.targetId) {
      ElMessage.warning('请选择目标组件')
      return
    }
    act.targetId = evForm.targetId
  }
  const ev: NodeEventDef = { id: newId('evt'), trigger: evForm.trigger, actions: [act] }
  // 同 trigger 多条合并动作列表（语义更顺）
  const exist = (node.value.events ?? []).find((e) => e.trigger === evForm.trigger)
  const events = exist
    ? (node.value.events ?? []).map((e) => (e.id === exist.id ? { ...e, actions: [...e.actions, act] } : e))
    : [...(node.value.events ?? []), ev]
  editor.updateNode(node.value.id, { events }, 'events')
}

function removeEvent(evId: string, actIdx: number): void {
  if (!node.value) return
  const events = (node.value.events ?? [])
    .map((e) => (e.id === evId ? { ...e, actions: e.actions.filter((_, i) => i !== actIdx) } : e))
    .filter((e) => e.actions.length > 0)
  editor.updateNode(node.value.id, { events }, 'events')
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
          <el-form-item label="画面方向">
            <el-select
              :model-value="editor.currentPage.screen.orientation ?? 'auto'"
              @update:model-value="editor.updatePage({ orientation: $event as 'auto' | 'landscape' | 'portrait' })"
            >
              <el-option label="跟随时口" value="auto" />
              <el-option label="强制横屏" value="landscape" />
              <el-option label="强制竖屏" value="portrait" />
            </el-select>
            <span class="form-hint">不符时运行态旋转 90°</span>
          </el-form-item>
          <el-form-item label="背景色">
            <el-color-picker
              :model-value="editor.currentPage.background.color"
              @update:model-value="editor.updatePage({}, $event ?? '#0b1220')"
            />
          </el-form-item>
          <el-form-item label="锁定画面">
            <el-switch
              :model-value="editor.currentPage.screen.lockPan === true"
              @change="(v: string | number | boolean) => editor.updatePage({ lockPan: v === true })"
            />
            <span class="form-hint">运行态禁止滚动/拖拽</span>
          </el-form-item>
        </el-form>
        <p class="attr-title sub">上手提示</p>
        <div class="hint">
          · 从左侧面板把组件拖到画布，点它即可在此改样式<br />
          · 拖动自动对齐；四角柄缩放，顶部柄旋转<br />
          · Ctrl+滚轮缩放视图，空格键拖移画面<br />
          · Ctrl+Z 撤销，Ctrl+Shift+Z 重做
        </div>
      </div>
    </template>

    <!-- 多选：批量编辑公共属性（单条 undo 覆盖全部选中项） -->
    <div v-else-if="multi" class="attr-body">
      <p class="attr-title">多选（{{ editor.selectedNodes.length }} 项）</p>
      <div class="hint">以下修改应用到全部选中项；整体拖动 / 删除 / 成组照常可用。</div>
      <el-collapse v-model="multiSections">
        <el-collapse-item title="几何（同值覆盖）" name="m-geometry">
          <div class="grid-2">
            <div class="field">
              <span>X</span>
              <el-input-number :model-value="batchRect.x" :step="1" size="small" controls-position="right" placeholder="—" @change="(v?: number) => setBatchRect('x', v)" />
            </div>
            <div class="field">
              <span>Y</span>
              <el-input-number :model-value="batchRect.y" :step="1" size="small" controls-position="right" placeholder="—" @change="(v?: number) => setBatchRect('y', v)" />
            </div>
            <div class="field">
              <span>宽</span>
              <el-input-number :model-value="batchRect.w" :min="1" size="small" controls-position="right" placeholder="—" @change="(v?: number) => setBatchRect('w', v)" />
            </div>
            <div class="field">
              <span>高</span>
              <el-input-number :model-value="batchRect.h" :min="1" size="small" controls-position="right" placeholder="—" @change="(v?: number) => setBatchRect('h', v)" />
            </div>
            <div class="field">
              <span>角度</span>
              <el-input-number :model-value="batchRect.rotate" :min="0" :max="359" :step="1" size="small" controls-position="right" placeholder="—" @change="(v?: number) => setBatchRect('rotate', v)" />
            </div>
            <div class="field">
              <span>透明度</span>
              <el-input-number :model-value="batchRect.opacity" :min="0.05" :max="1" :step="0.05" size="small" controls-position="right" placeholder="—" @change="(v?: number) => setBatchRect('opacity', v)" />
            </div>
          </div>
          <p class="hint" style="margin: 6px 0 0">输入后回车即把该值设置到每个选中项（对齐/分布请用顶部工具栏）。</p>
        </el-collapse-item>

        <el-collapse-item title="显示" name="m-display">
          <div class="switch-row">
            <span>全部显示</span>
            <el-switch :model-value="allVisible" @change="(v: boolean) => editor.updateNodes({ visible: v }, 'mvis')" />
          </div>
          <div class="switch-row">
            <span>全部锁定</span>
            <el-switch :model-value="allLocked" @change="(v: boolean) => editor.updateNodes({ locked: v }, 'mlock')" />
          </div>
        </el-collapse-item>

        <el-collapse-item title="样式（同值覆盖）" name="m-style">
          <el-form label-position="left" label-width="60px" size="small">
            <el-form-item label="文字色">
              <el-color-picker :model-value="(editor.primarySelected?.style as Record<string, unknown> | undefined)?.color as string" show-alpha @change="(v: string | null) => setBatchStyle('color', v)" />
            </el-form-item>
            <el-form-item label="填充">
              <el-color-picker :model-value="(editor.primarySelected?.style as Record<string, unknown> | undefined)?.fill as string" show-alpha @change="(v: string | null) => setBatchStyle('fill', v)" />
            </el-form-item>
            <el-form-item label="字号">
              <el-input-number :model-value="(editor.primarySelected?.style as Record<string, unknown> | undefined)?.fontSize as number" :min="8" :max="200" :step="1" size="small" @change="(v?: number) => v !== undefined && setBatchStyle('fontSize', v)" />
            </el-form-item>
            <el-form-item label="对齐">
              <el-select :model-value="(editor.primarySelected?.style as Record<string, unknown> | undefined)?.textAlign as string" placeholder="不修改" clearable size="small" @change="(v: string) => setBatchStyle('textAlign', v)">
                <el-option v-for="o in MULTI_TEXT_ALIGN" :key="o.value" :label="o.label" :value="o.value" />
              </el-select>
            </el-form-item>
          </el-form>
          <p class="hint" style="margin: 0">颜色取主选中项当前值作参考，确认后应用到全部。</p>
        </el-collapse-item>
      </el-collapse>

      <el-button size="small" style="margin-top: 8px" @click="editor.groupSelection()">合并成组</el-button>
    </div>

    <!-- 单选：折叠分区（参照 CommonAttr.vue 的 el-collapse 结构） -->
    <template v-else-if="node">
      <p class="attr-title">{{ selectionTitle }}属性</p>
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
                    @click="bindForm.mapRows.push({ k: '', v: bindForm.mode === 'color' ? '#1ba7b8' : 'true' })">
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
              <div class="anim-row">
                <span>轨迹</span>
                <el-switch
                  :model-value="node.animations?.move?.enabled === true"
                  @change="(v: boolean) => setMove({ enabled: v })"
                />
                <el-input-number
                  :model-value="node.animations?.move?.periodMs ?? 8000"
                  :min="200" :step="500" size="small" controls-position="right"
                  @change="(v?: number) => setMove({ enabled: true, periodMs: v ?? 8000 })"
                />
                <span class="form-hint">ms/趟</span>
              </div>
              <template v-if="node.animations?.move?.enabled">
                <el-input
                  :model-value="node.animations.move.path"
                  size="small"
                  placeholder="SVG path，如 M 0 0 L 300 0 L 300 200（相对组件原点）"
                  @change="(v: string) => setMove({ path: v })"
                />
                <el-radio-group
                  :model-value="node.animations.move.mode"
                  size="small"
                  @update:model-value="(v: string | number | boolean | undefined) => setMove({ mode: v === 'pingpong' ? 'pingpong' : 'loop' })"
                >
                  <el-radio-button value="loop">循环</el-radio-button>
                  <el-radio-button value="pingpong">往返</el-radio-button>
                </el-radio-group>
                <div class="hint">坐标相对组件原点；路径可超出组件框（运动为位移不裁剪）</div>
              </template>
            </el-collapse-item>

            <!-- 事件与行为（M7） -->
            <el-collapse-item :title="`事件（${(node.events ?? []).reduce((n, e) => n + e.actions.length, 0)}）`" name="events">
              <div v-for="ev in node.events ?? []" :key="ev.id" class="event-group">
                <span class="event-trigger">{{ ev.trigger === 'contextmenu' ? '右键' : ev.trigger === 'dblclick' ? '双击' : '单击' }}</span>
                <div class="event-actions">
                  <div v-for="(act, ai) in ev.actions" :key="ai" class="event-row">
                    <span class="event-type">{{ act.type }}</span>
                    <span class="event-target">
                      {{ act.type === 'writeVar' ? `${varLabel(act.variableId ?? '')} = ${act.value}` : act.type === 'switchPage' ? (pages.find(p => p.id === act.pageId)?.name ?? '?') : act.type === 'openUrl' ? act.url : (pageNodes.find(n => n.id === act.targetId)?.name ?? '?') }}
                    </span>
                    <el-button link type="danger" size="small" @click="removeEvent(ev.id, ai)">删</el-button>
                  </div>
                </div>
              </div>
              <el-divider style="margin: 8px 0" />
              <div class="bind-form">
                <div class="form-row2">
                  <el-select v-model="evForm.trigger" size="small">
                    <el-option label="单击" value="click" />
                    <el-option label="双击" value="dblclick" />
                    <el-option label="右键" value="contextmenu" />
                  </el-select>
                  <el-select v-model="evForm.type" size="small">
                    <el-option label="写变量" value="writeVar" />
                    <el-option label="显示弹框" value="showPopup" />
                    <el-option label="隐藏弹框" value="hidePopup" />
                    <el-option label="切换显隐" value="toggleVisible" />
                    <el-option label="切换页面" value="switchPage" />
                    <el-option label="打开网页" value="openUrl" />
                  </el-select>
                </div>
                <el-select v-if="evForm.type === 'writeVar'" v-model="evForm.variableId" size="small" placeholder="选择变量（须可写）">
                  <el-option v-for="v in variables" :key="v.id" :label="`${v.label}（${v.key}）${v.writable ? '' : ' [只读]'}`" :value="v.id" />
                </el-select>
                <el-input v-if="evForm.type === 'writeVar'" v-model="evForm.value" size="small" placeholder="写入值（支持表达式，如 tank.level + 1）" />
                <el-select v-if="evForm.type === 'switchPage'" v-model="evForm.pageId" size="small" placeholder="选择页面">
                  <el-option v-for="p in pages" :key="p.id" :label="p.name" :value="p.id" />
                </el-select>
                <el-input v-if="evForm.type === 'openUrl'" v-model="evForm.url" size="small" placeholder="https://…" />
                <el-select
                  v-if="['showPopup', 'hidePopup', 'toggleVisible'].includes(evForm.type)"
                  v-model="evForm.targetId" size="small" filterable placeholder="选择目标组件"
                >
                  <el-option v-for="n in pageNodes" :key="n.id" :label="n.name" :value="n.id" />
                </el-select>
                <el-button type="primary" size="small" style="align-self: flex-start" @click="addEvent">添加事件</el-button>
              </div>
            </el-collapse-item>

            <!-- 悬停信息（M7） -->
            <el-collapse-item title="悬停信息" name="tooltip">
              <div class="anim-row">
                <span>启用</span>
                <el-switch
                  :model-value="node.tooltip?.enabled === true"
                  @change="(v: boolean) => setTooltip({ enabled: v, template: node!.tooltip?.template ?? '' })"
                />
              </div>
              <el-input
                :model-value="node.tooltip?.template ?? ''"
                type="textarea" :rows="2" size="small"
                placeholder="模板：{变量key} 实时替换，如 出口温度 {plant1.temp} ℃"
                @change="(v: string) => setTooltip({ enabled: true, template: v })"
              />
            </el-collapse-item>

            <!-- 弹框（M7，仅 group） -->
            <el-collapse-item v-if="node.type === 'group'" :title="`弹框${node.popup ? '（已配置）' : ''}`" name="popup">
              <div v-if="!node.popup" class="hint">将本组配置为弹框容器：运行态默认隐藏，由事件（showPopup）或条件表达式触发显示。</div>
              <div class="anim-row">
                <span>启用</span>
                <el-switch
                  :model-value="!!node.popup"
                  @change="(v: boolean) => (v ? setPopup({}) : clearPopup())"
                />
              </div>
              <template v-if="node.popup">
                <el-select
                  :model-value="node.popup.style"
                  size="small"
                  @update:model-value="(v: string | number | boolean | undefined) => setPopup({ style: v === 'menu' ? 'menu' : 'dialog' })"
                >
                  <el-option label="对话框（半透明遮罩）" value="dialog" />
                  <el-option label="菜单（透明遮罩，右键场景）" value="menu" />
                </el-select>
                <el-input
                  :model-value="node.popup.title ?? ''"
                  size="small" placeholder="标题（可选）"
                  @change="(v: string) => setPopup({ title: v })"
                />
                <el-input
                  :model-value="node.popup.triggerExpr ?? ''"
                  type="textarea" :rows="2" size="small"
                  placeholder="条件表达式（可选，真值时自动弹出），如 plant1.temp > 80"
                  @change="(v: string) => setPopup({ triggerExpr: v || null })"
                />
              </template>
            </el-collapse-item>

            <el-collapse-item v-if="meta && meta.propsSchema.length" :title="`组件属性（${meta.name}）`" name="props">
              <el-form label-position="left" label-width="90px" size="small">
                <el-form-item v-for="item in meta.propsSchema" :key="item.key" :label="item.label">
                  <el-select
                    v-if="item.type === 'variable'"
                    :model-value="getProp(item)"
                    clearable
                    filterable
                    @update:model-value="(v: string | number | boolean | undefined) => setProp(item, v === '' || v === undefined ? '' : v)"
                  >
                    <el-option v-for="v in variables" :key="v.id" :label="`${v.label}（${v.key}）`" :value="v.id" />
                  </el-select>
                  <el-color-picker
                    v-else-if="item.type === 'color'"
                    :model-value="String(getProp(item) ?? '')"
                    @update:model-value="(v: string | null) => setProp(item, v ?? '')"
                  />
                  <el-switch v-else-if="item.type === 'switch'" :model-value="getProp(item) === true" @change="(v: boolean) => setProp(item, v)" />
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
  background: var(--ws-panel);
  color: var(--ws-text);
}

/* 面板标题：左对齐 + 左侧信号条，与组件/图层面板同一套分区语言 */
.attr-title {
  position: relative;
  margin: 0;
  height: 34px;
  line-height: 34px;
  padding: 0 14px 0 13px;
  border-bottom: 1px solid var(--ws-steel-2);
  background: var(--ws-steel-0);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--ws-text);
  flex-shrink: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attr-title::before {
  content: '';
  position: absolute;
  left: 0;
  top: 9px;
  bottom: 9px;
  width: 3px;
  background: var(--ws-signal);
}

.attr-title.sub {
  height: 30px;
  line-height: 30px;
  padding-left: 14px;
  background: transparent;
  border-bottom: none;
  font-size: 12px;
  font-weight: 600;
  color: var(--ws-text-2);
}

.attr-title.sub::before {
  display: none;
}

.attr-body {
  padding: 12px 14px;
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
  width: 40px;
  flex-shrink: 0;
  color: var(--ws-text-3);
  white-space: nowrap;
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
  color: var(--ws-text-3);
  font-size: 12px;
  line-height: 1.8;
}

.binding-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  padding: 3px 0;
  color: var(--ws-text);
}

.binding-prop {
  color: var(--ws-signal);
  font-family: var(--ws-font-mono);
}

.binding-arrow {
  color: var(--ws-steel-3);
}

.binding-var {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.binding-mode {
  font-size: 11px;
  color: var(--ws-text-3);
  border: 1px solid var(--ws-steel-2);
  border-radius: var(--ws-radius);
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
  color: var(--ws-text-3);
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
  color: var(--ws-text-3);
}

/* 事件与行为（M7） */
.event-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 4px 0;
}

.event-trigger {
  font-size: 12px;
  color: var(--ws-signal);
  font-weight: 600;
}

.event-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--ws-text);
}

.event-type {
  font-family: var(--ws-font-mono);
  font-size: 11px;
  color: var(--ws-text-3);
  border: 1px solid var(--ws-steel-2);
  border-radius: var(--ws-radius);
  padding: 0 4px;
  flex-shrink: 0;
}

.event-target {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.form-row2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  column-gap: 8px;
}

.form-hint {
  color: var(--ws-text-3);
  font-size: 12px;
}
</style>
