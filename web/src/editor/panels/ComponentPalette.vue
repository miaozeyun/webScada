<script setup lang="ts">
/**
 * 组件面板（M9 批次1/2/3 五 Tab 化，对标 BY组态左侧面板）：
 * - 「组件」：注册组件按 category 分组；拖拽（HTML5 DnD）到画布，或点击放置到可视区中心。
 * - 「图元库」：assets/symbols 自绘行业图元，搜索 + 分类过滤。
 * - 「装饰」：decor 注册组件（标题栏等）+ decor 分类图元（边框/底纹）。
 * - 「模板」：画面模板一键新建整页（pageTemplates）。
 * - 「我的」：选中组件/组存为可复用图元（doc.assets.mySymbols）。
 */
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, FolderAdd } from '@element-plus/icons-vue'
import { useEditorStore } from '@/stores/editor'
import { paletteByCategory, registry } from '@/widgets/registry'
import WidgetIcon from '@/widgets/WidgetIcon.vue'
import MySymbolThumb from '@/editor/panels/MySymbolThumb.vue'
import { CATEGORY_LABELS, symbolAssets } from '@/assets/symbols'
import type { SymbolAsset } from '@/assets/symbols'
import { PAGE_TEMPLATES } from '@/utils/pageTemplates'

const editor = useEditorStore()
const tab = ref<'widgets' | 'symbols' | 'decor' | 'templates' | 'mine'>('widgets')

const TABS = [
  { key: 'widgets', label: '组件', title: '注册组件' },
  { key: 'symbols', label: '图元库', title: '行业图元库' },
  { key: 'decor', label: '装饰', title: '画面装饰' },
  { key: 'templates', label: '模板', title: '画面模板' },
  { key: 'mine', label: '我的', title: '我的图元' },
] as const

const GROUPS = [
  { label: '基础', category: 'basic' as const },
  { label: '图表', category: 'chart' as const },
  { label: '设备', category: 'device' as const },
]

// ---- 图元库 ----

const keyword = ref('')
const activeCategory = ref<string>('all')

const categories = computed(() => {
  const seen = new Map<string, number>()
  for (const s of symbolAssets) {
    if (s.category === 'decor') continue // 装饰类走独立 Tab
    seen.set(s.category, (seen.get(s.category) ?? 0) + 1)
  }
  return [...seen.entries()].map(([id, count]) => ({ id, label: CATEGORY_LABELS[id] ?? id, count }))
})

const filteredSymbols = computed<SymbolAsset[]>(() => {
  const kw = keyword.value.trim().toLowerCase()
  return symbolAssets.filter((s) => {
    if (s.category === 'decor') return false
    if (activeCategory.value !== 'all' && s.category !== activeCategory.value) return false
    if (!kw) return true
    return s.label.toLowerCase().includes(kw) || s.id.toLowerCase().includes(kw)
  })
})

// ---- 装饰 ----

const decorSymbols = computed(() => symbolAssets.filter((s) => s.category === 'decor'))
const decorWidgets = computed(() => paletteByCategory('decor'))

// ---- 我的图元 ----

const mySymbols = computed(() => editor.doc?.assets?.mySymbols ?? [])

async function saveFromSelection(): Promise<void> {
  if (editor.selection.length === 0) return
  try {
    const { value } = await ElMessageBox.prompt('图元名称', '存为我的图元', {
      inputValue: editor.selectedNodes[0]?.name ?? '我的图元',
      inputValidator: (v: string) => v.trim().length > 0 || '名称不能为空',
    })
    editor.saveMySymbol(value)
    ElMessage.success('已存入我的图元')
  } catch {
    /* 取消 */
  }
}

function removeMySymbol(id: string): void {
  editor.deleteMySymbol(id)
}

// ---- 通用：拖拽 / 放置 ----

function onDragStart(e: DragEvent, type: string): void {
  // 双类型写入：标准类型 + text/plain 兜底（Firefox dataTransfer 兼容）
  e.dataTransfer?.setData('application/x-widget', type)
  e.dataTransfer?.setData('text/plain', type)
  e.dataTransfer!.effectAllowed = 'copy'
}

function onSymbolDragStart(e: DragEvent, id: string): void {
  onDragStart(e, `symbol|${id}`)
}

function onMySymbolDragStart(e: DragEvent, id: string): void {
  onDragStart(e, `mysym|${id}`)
}

/** 点击放置：当前可视区中心（而非设计坐标中心——画布可能平移/缩放） */
function placeAtCenter(w: number, h: number): { x: number; y: number } | null {
  const vp = document.querySelector('.canvas-viewport')?.getBoundingClientRect()
  if (!vp) return null
  return {
    x: (vp.width / 2 - editor.pan.x) / editor.zoom - w / 2,
    y: (vp.height / 2 - editor.pan.y) / editor.zoom - h / 2,
  }
}

function onClick(type: string): void {
  const meta = registry.get(type as never)
  if (!meta) return
  const p = placeAtCenter(meta.defaultSize.w, meta.defaultSize.h)
  if (p) editor.addComponent(type as never, p.x, p.y)
}

function onSymbolClick(asset: SymbolAsset): void {
  const p = placeAtCenter(asset.w, asset.h)
  if (p) editor.addComponent('symbol', p.x, p.y, { symbolId: asset.id })
}

function onMySymbolClick(id: string): void {
  const p = placeAtCenter(200, 200)
  if (p) editor.insertMySymbol(id, p.x, p.y)
}

function onTemplateClick(t: (typeof PAGE_TEMPLATES)[number]): void {
  editor.applyPageTemplate(t.name, t.build())
  ElMessage.success(`已从模板新建页面「${t.name}」`)
}
</script>

<template>
  <div class="component-panel">
    <div class="panel-head">组件库</div>
    <div class="palette-tabs">
      <button
        v-for="t in TABS"
        :key="t.key"
        class="tab"
        :class="{ active: tab === t.key }"
        :title="t.title"
        @click="tab = t.key"
      >
        {{ t.label }}
        <span v-if="t.key === 'symbols'" class="badge">{{ filteredSymbols.length }}</span>
        <span v-if="t.key === 'mine'" class="badge">{{ mySymbols.length }}</span>
      </button>
    </div>

    <!-- Tab 1：注册组件 -->
    <div v-show="tab === 'widgets'" class="component-list">
      <template v-for="g in GROUPS" :key="g.category">
        <div class="group-title">{{ g.label }}</div>
        <div
          v-for="meta in paletteByCategory(g.category)"
          :key="meta.type"
          class="list"
          draggable="true"
          :title="meta.name"
          @dragstart="onDragStart($event, meta.type)"
          @click="onClick(meta.type)"
        >
          <WidgetIcon :meta="meta" />
          <span class="label">{{ meta.name }}</span>
        </div>
      </template>
    </div>

    <!-- Tab 2：行业图元库 -->
    <div v-show="tab === 'symbols'" class="symbol-panel">
      <div class="symbol-toolbar">
        <input v-model="keyword" class="symbol-search" type="text" placeholder="搜索图元…" />
      </div>
      <div class="symbol-categories">
        <button class="cat" :class="{ active: activeCategory === 'all' }" @click="activeCategory = 'all'">全部</button>
        <button
          v-for="c in categories"
          :key="c.id"
          class="cat"
          :class="{ active: activeCategory === c.id }"
          @click="activeCategory = c.id"
        >
          {{ c.label }}
        </button>
      </div>
      <div class="symbol-grid">
        <div
          v-for="asset in filteredSymbols"
          :key="asset.id"
          class="symbol-item"
          draggable="true"
          :title="`${asset.label}（${asset.id}）`"
          @dragstart="onSymbolDragStart($event, asset.id)"
          @click="onSymbolClick(asset)"
        >
          <span class="symbol-thumb" v-html="asset.svg" />
          <span class="symbol-name">{{ asset.label }}</span>
        </div>
        <div v-if="filteredSymbols.length === 0" class="symbol-empty">无匹配图元</div>
      </div>
    </div>

    <!-- Tab 3：画面装饰 -->
    <div v-show="tab === 'decor'" class="symbol-panel">
      <div class="symbol-grid decor-grid">
        <div
          v-for="meta in decorWidgets"
          :key="meta.type"
          class="symbol-item"
          draggable="true"
          :title="meta.name"
          @dragstart="onDragStart($event, meta.type)"
          @click="onClick(meta.type)"
        >
          <WidgetIcon :meta="meta" />
          <span class="symbol-name">{{ meta.name }}</span>
        </div>
        <div
          v-for="asset in decorSymbols"
          :key="asset.id"
          class="symbol-item"
          draggable="true"
          :title="`${asset.label}（配合降低透明度使用）`"
          @dragstart="onSymbolDragStart($event, asset.id)"
          @click="onSymbolClick(asset)"
        >
          <span class="symbol-thumb" v-html="asset.svg" />
          <span class="symbol-name">{{ asset.label }}</span>
        </div>
      </div>
    </div>

    <!-- Tab 4：画面模板（点击新建整页） -->
    <div v-show="tab === 'templates'" class="symbol-panel">
      <div class="tpl-tip">点击模板将在当前工程新建一个页面</div>
      <div class="tpl-list">
        <button v-for="t in PAGE_TEMPLATES" :key="t.id" class="tpl-item" @click="onTemplateClick(t)">
          <span class="tpl-name">{{ t.name }}</span>
          <span class="tpl-desc">{{ t.desc }}</span>
        </button>
      </div>
    </div>

    <!-- Tab 5：我的图元 -->
    <div v-show="tab === 'mine'" class="symbol-panel">
      <div class="symbol-toolbar">
        <button class="my-save" :disabled="editor.selection.length === 0" @click="saveFromSelection">
          <el-icon :size="12"><FolderAdd /></el-icon>
          将选中组件存为图元
        </button>
      </div>
      <div class="symbol-grid">
        <div
          v-for="sym in mySymbols"
          :key="sym.id"
          class="symbol-item my-item"
          draggable="true"
          :title="`${sym.label}（${sym.nodes.length} 个组件）`"
          @dragstart="onMySymbolDragStart($event, sym.id)"
          @click="onMySymbolClick(sym.id)"
        >
          <MySymbolThumb :nodes="sym.nodes" />
          <span class="symbol-name">{{ sym.label }}</span>
          <span class="my-del" title="删除图元" @click.stop="removeMySymbol(sym.id)">
            <el-icon :size="12"><Delete /></el-icon>
          </span>
        </div>
        <div v-if="mySymbols.length === 0" class="symbol-empty">
          选中画布组件（可多选/成组）后点上方按钮，<br />或右键菜单「存为我的图元」
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.component-panel {
  height: 65%;
  display: flex;
  flex-direction: column;
  border-bottom: 1px solid var(--ws-steel-3);
}

/* 面板标题：工程分区短标题 */
.panel-head {
  height: 34px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  padding: 0 10px;
  background: var(--ws-steel-0);
  border-bottom: 1px solid var(--ws-steel-2);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--ws-text-2);
}

/* Tab 条（组件 / 图元库 / 装饰 / 模板 / 我的） */
.palette-tabs {
  height: 32px;
  flex-shrink: 0;
  display: flex;
  border-bottom: 1px solid var(--ws-steel-2);
}

.tab {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  border: none;
  background: transparent;
  font-size: 11px;
  color: var(--ws-text-3);
  cursor: pointer;
  white-space: nowrap;
}

.tab.active {
  color: var(--ws-signal);
  box-shadow: inset 0 -2px 0 var(--ws-signal);
}

.badge {
  min-width: 14px;
  padding: 0 3px;
  border-radius: 7px;
  background: var(--ws-steel-3);
  font-size: 9px;
  line-height: 13px;
  color: var(--ws-text-2);
}

.tab.active .badge {
  background: var(--ws-signal-soft);
  color: var(--ws-signal);
}

.component-list {
  flex: 1;
  min-height: 0;
  padding: 8px;
  display: grid;
  grid-gap: 8px;
  grid-template-columns: repeat(auto-fill, minmax(80px, 1fr));
  align-content: start;
  overflow-y: auto;
}

.group-title {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 5px 1px 0;
  font-size: 10px;
  letter-spacing: 0.08em;
  color: var(--ws-text-3);
}

.group-title::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--ws-steel-2);
}

.group-title:not(:first-child) {
  margin-top: 4px;
}

.list {
  height: 38px;
  padding: 2px 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  border: 1px solid var(--ws-steel-3);
  border-radius: var(--ws-radius);
  background: var(--ws-panel);
  color: var(--ws-text-2);
  cursor: grab;
  user-select: none;
  text-align: center;
}

.list:active {
  cursor: grabbing;
}

.list:hover {
  border-color: var(--ws-signal);
  background: var(--ws-signal-soft);
  color: var(--ws-signal);
}

.label {
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ---- 图元库 / 装饰 / 我的（共用骨架） ---- */

.symbol-panel {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.symbol-toolbar {
  flex-shrink: 0;
  padding: 8px 8px 4px;
}

.symbol-search {
  width: 100%;
  height: 28px;
  padding: 0 10px;
  border: 1px solid var(--ws-steel-3);
  border-radius: var(--ws-radius);
  background: var(--ws-panel);
  color: var(--ws-text-1);
  font-size: 12px;
  outline: none;
}

.symbol-search:focus {
  border-color: var(--ws-signal);
}

.my-save {
  width: 100%;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  border: 1px dashed var(--ws-steel-3);
  border-radius: var(--ws-radius);
  background: var(--ws-panel);
  color: var(--ws-text-2);
  font-size: 12px;
  cursor: pointer;
}

.my-save:not(:disabled):hover {
  border-color: var(--ws-signal);
  color: var(--ws-signal);
}

.my-save:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.symbol-categories {
  flex-shrink: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 4px 8px 8px;
}

.cat {
  padding: 2px 8px;
  border: 1px solid var(--ws-steel-3);
  border-radius: 10px;
  background: var(--ws-panel);
  font-size: 11px;
  color: var(--ws-text-2);
  cursor: pointer;
}

.cat.active {
  border-color: var(--ws-signal);
  background: var(--ws-signal-soft);
  color: var(--ws-signal);
}

.symbol-grid {
  flex: 1;
  min-height: 0;
  padding: 0 8px 8px;
  display: grid;
  grid-gap: 8px;
  grid-template-columns: repeat(auto-fill, minmax(64px, 1fr));
  align-content: start;
  overflow-y: auto;
}

.decor-grid {
  padding-top: 8px;
}

.symbol-item {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 6px 2px 4px;
  border: 1px solid var(--ws-steel-3);
  border-radius: var(--ws-radius);
  background: var(--ws-panel);
  cursor: grab;
  user-select: none;
}

.symbol-item:active {
  cursor: grabbing;
}

.symbol-item:hover {
  border-color: var(--ws-signal);
  background: var(--ws-signal-soft);
}

.symbol-thumb {
  width: 40px;
  height: 40px;
  color: var(--ws-text-2);
}

.symbol-thumb :deep(svg) {
  width: 100%;
  height: 100%;
  display: block;
}

.symbol-item:hover .symbol-thumb {
  color: var(--ws-signal);
}

.symbol-name {
  max-width: 100%;
  font-size: 11px;
  color: var(--ws-text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.symbol-empty {
  grid-column: 1 / -1;
  padding: 16px 0;
  text-align: center;
  font-size: 12px;
  line-height: 1.7;
  color: var(--ws-text-3);
}

/* 我的图元项：删除角标 */
.my-del {
  position: absolute;
  top: 2px;
  right: 2px;
  display: none;
  padding: 3px;
  border-radius: 4px;
  color: var(--ws-text-3);
  cursor: pointer;
}

.my-item:hover .my-del {
  display: inline-flex;
}

.my-del:hover {
  color: var(--ws-alert);
  background: var(--ws-alert-soft);
}

/* ---- 模板列表 ---- */

.tpl-tip {
  flex-shrink: 0;
  padding: 8px 10px 4px;
  font-size: 11px;
  color: var(--ws-text-3);
}

.tpl-list {
  flex: 1;
  min-height: 0;
  padding: 4px 8px 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow-y: auto;
}

.tpl-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 10px 12px;
  border: 1px solid var(--ws-steel-3);
  border-radius: var(--ws-radius);
  background: var(--ws-panel);
  cursor: pointer;
  text-align: left;
}

.tpl-item:hover {
  border-color: var(--ws-signal);
  background: var(--ws-signal-soft);
}

.tpl-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--ws-text-1);
}

.tpl-item:hover .tpl-name {
  color: var(--ws-signal);
}

.tpl-desc {
  font-size: 11px;
  color: var(--ws-text-3);
}

/* 触屏 / 窄面板：减少网格列宽浪费 */
@media (max-width: 1200px) {
  .component-list {
    grid-template-columns: repeat(auto-fill, minmax(76px, 1fr));
  }
}
</style>
