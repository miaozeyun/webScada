<script setup lang="ts">
/**
 * 组件面板（M9 批次1/2/3 五 Tab 化，对标业界主流组态左侧面板）：
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
  { key: 'symbols', label: '图元', title: '行业图元库' },
  { key: 'decor', label: '装饰', title: '画面装饰' },
  { key: 'templates', label: '模板', title: '画面模板' },
  { key: 'mine', label: '我的', title: '我的图元' },
] as const

const GROUPS = [
  { label: '基础', category: 'basic' as const },
  { label: '图表', category: 'chart' as const },
  { label: '设备', category: 'device' as const },
]

// ---- 注册组件：名称/类型关键字过滤（与图元库搜索同交互） ----

const widgetKeyword = ref('')

const filteredGroups = computed(() =>
  GROUPS.map((g) => ({ ...g, items: paletteByCategory(g.category) })).map((g) => ({
    ...g,
    items: g.items.filter(
      (m) =>
        !widgetKeyword.value.trim() ||
        m.name.toLowerCase().includes(widgetKeyword.value.trim().toLowerCase()) ||
        m.type.toLowerCase().includes(widgetKeyword.value.trim().toLowerCase()),
    ),
  })).filter((g) => g.items.length > 0),
)

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

// 面板头右侧读数：当前 Tab 条目计数（tab 内放不下 badge，移到标题栏读数位）
const headCount = computed(() => {
  switch (tab.value) {
    case 'widgets':
      return GROUPS.reduce((sum, g) => sum + paletteByCategory(g.category).length, 0)
    case 'symbols':
      return filteredSymbols.value.length
    case 'decor':
      return decorWidgets.value.length + decorSymbols.value.length
    case 'templates':
      return PAGE_TEMPLATES.length
    case 'mine':
      return mySymbols.value.length
  }
})

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

/** 拖入画布的落点预览尺寸：画布据此渲染放置 ghost（dragend/drop 清除） */
function onDragStart(e: DragEvent, type: string, hint?: { w: number; h: number; label: string }): void {
  // 双类型写入：标准类型 + text/plain 兜底（Firefox dataTransfer 兼容）
  e.dataTransfer?.setData('application/x-widget', type)
  e.dataTransfer?.setData('text/plain', type)
  e.dataTransfer!.effectAllowed = 'copy'
  editor.dropHint = hint ?? null
}

function onDragEnd(): void {
  editor.dropHint = null
}

function onSymbolDragStart(e: DragEvent, asset: SymbolAsset): void {
  onDragStart(e, `symbol|${asset.id}`, { w: asset.w, h: asset.h, label: asset.label })
}

function onMySymbolDragStart(e: DragEvent, sym: { id: string; label: string; nodes: { x: number; y: number; w: number; h: number }[] }): void {
  // 我的图元可能由多个组件构成：取成员包围盒作为整体 ghost
  const minX = Math.min(...sym.nodes.map((n) => n.x))
  const minY = Math.min(...sym.nodes.map((n) => n.y))
  const maxX = Math.max(...sym.nodes.map((n) => n.x + n.w))
  const maxY = Math.max(...sym.nodes.map((n) => n.y + n.h))
  onDragStart(e, `mysym|${sym.id}`, { w: Math.round(maxX - minX), h: Math.round(maxY - minY), label: sym.label })
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
    <div class="panel-head">
      <span>{{ TABS.find((t) => t.key === tab)?.title }}</span>
      <span class="head-count ws-readout" :title="`${headCount} 项`">{{ headCount }}</span>
    </div>
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
      </button>
    </div>

    <!-- Tab 1：注册组件（缩略图卡片，竖排图标 + 名称） -->
    <div v-show="tab === 'widgets'" class="symbol-panel">
      <div class="symbol-toolbar">
        <input v-model="widgetKeyword" class="symbol-search" type="text" placeholder="搜索组件…" />
      </div>
      <div class="component-list">
        <template v-for="g in filteredGroups" :key="g.category">
          <div class="group-title">{{ g.label }}<span class="group-count ws-readout">{{ g.items.length }}</span></div>
          <div
            v-for="meta in g.items"
            :key="meta.type"
            class="list"
            draggable="true"
            :title="meta.name"
            @dragstart="onDragStart($event, meta.type, { w: meta.defaultSize.w, h: meta.defaultSize.h, label: meta.name })"
            @dragend="onDragEnd"
            @click="onClick(meta.type)"
          >
            <span class="list-icon"><WidgetIcon :meta="meta" /></span>
            <span class="label">{{ meta.name }}</span>
          </div>
        </template>
        <div v-if="filteredGroups.length === 0" class="symbol-empty">无匹配组件</div>
      </div>
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
          @dragstart="onSymbolDragStart($event, asset)"
          @dragend="onDragEnd"
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
          @dragstart="onDragStart($event, meta.type, { w: meta.defaultSize.w, h: meta.defaultSize.h, label: meta.name })"
          @dragend="onDragEnd"
          @click="onClick(meta.type)"
        >
          <span class="symbol-thumb"><WidgetIcon :meta="meta" /></span>
          <span class="symbol-name">{{ meta.name }}</span>
        </div>
        <div
          v-for="asset in decorSymbols"
          :key="asset.id"
          class="symbol-item"
          draggable="true"
          :title="`${asset.label}（配合降低透明度使用）`"
          @dragstart="onSymbolDragStart($event, asset)"
          @dragend="onDragEnd"
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
          @dragstart="onMySymbolDragStart($event, sym)"
          @dragend="onDragEnd"
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
/* 高度由编辑器左栏的 --palette-h 控制（分隔条可拖），缺省 65% */
.component-panel {
  position: relative;
  height: var(--palette-h, 65%);
  min-height: 160px;
  display: flex;
  flex-direction: column;
  border-bottom: 1px solid var(--ws-steel-3);
}

/* 底部渐隐：提示列表可继续滚动，而不是被硬切一刀 */
.component-panel::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 16px;
  background: linear-gradient(180deg, transparent, var(--ws-panel));
  pointer-events: none;
}

/* 面板标题：工程分区短标题 + 右侧条目读数 */
.panel-head {
  position: relative;
  height: var(--ws-panel-head-h);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 12px;
  background: var(--ws-steel-0);
  border-bottom: 1px solid var(--ws-steel-2);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--ws-text-2);
}

.panel-head::before {
  content: '';
  position: absolute;
  left: 0;
  top: 9px;
  bottom: 9px;
  width: 3px;
  background: var(--ws-signal);
}

.head-count {
  min-width: 18px;
  text-align: right;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--ws-signal);
}

/* Tab 条（组件 / 图元 / 装饰 / 模板 / 我的）：分段控件，激活项为浅青药丸 */
.palette-tabs {
  flex-shrink: 0;
  display: flex;
  gap: 2px;
  padding: 5px 8px;
  border-bottom: 1px solid var(--ws-steel-2);
  background: var(--ws-panel);
}

.tab {
  position: relative;
  flex: 1;
  min-width: 0;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: var(--ws-radius);
  background: transparent;
  font-size: 11px;
  color: var(--ws-text-3);
  cursor: pointer;
  white-space: nowrap;
  transition: background-color var(--ws-duration-fast) var(--ws-ease), color var(--ws-duration-fast) var(--ws-ease), border-color var(--ws-duration-fast) var(--ws-ease);
}

.tab:hover {
  background: var(--ws-steel-1);
  color: var(--ws-text);
}

.tab.active {
  border-color: var(--ws-signal-a18);
  background: var(--ws-signal-soft);
  color: var(--ws-signal);
  font-weight: 600;
}

.component-list {
  flex: 1;
  min-height: 0;
  padding: 2px 8px 10px;
  display: grid;
  grid-gap: 6px;
  grid-template-columns: repeat(auto-fill, minmax(56px, 1fr));
  align-content: start;
  overflow-y: auto;
}

.group-title {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 1px 1px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.1em;
  color: var(--ws-text-3);
  text-transform: uppercase;
}

.group-count {
  font-size: 10px;
  letter-spacing: 0.02em;
  color: var(--ws-text-3);
  opacity: 0.85;
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

/* 缩略卡：三列密排（图标居上、名称居下），40 个组件一屏可见过半 */
.list {
  min-width: 0;
  height: 54px;
  padding: 7px 3px 5px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  border: 1px solid var(--ws-steel-2);
  border-radius: var(--ws-radius);
  background: var(--ws-panel);
  color: var(--ws-text-2);
  cursor: grab;
  user-select: none;
  text-align: center;
  transition: border-color var(--ws-duration-fast) var(--ws-ease), background-color var(--ws-duration-fast) var(--ws-ease),
    color var(--ws-duration-fast) var(--ws-ease), box-shadow var(--ws-duration-fast) var(--ws-ease);
}

.list:active {
  cursor: grabbing;
}

.list:hover {
  border-color: var(--ws-signal);
  background: var(--ws-signal-soft);
  color: var(--ws-signal);
  box-shadow: 0 2px 6px rgba(11, 114, 133, 0.12);
}

/* 图标台：统一 22px 见方刻度底，线宽与图元库缩略图一致 */
.list-icon {
  width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--ws-text-2);
}

.list:hover .list-icon {
  color: var(--ws-signal);
}

.label {
  max-width: 100%;
  font-size: 11px;
  line-height: 1.15;
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
  background: var(--ws-steel-0);
  color: var(--ws-text);
  font-size: 12px;
  outline: none;
  transition: border-color var(--ws-duration-fast) var(--ws-ease), background-color var(--ws-duration-fast) var(--ws-ease),
    box-shadow var(--ws-duration-fast) var(--ws-ease);
}

.symbol-search::placeholder {
  color: var(--ws-text-3);
}

.symbol-search:focus {
  border-color: var(--ws-signal);
  background: var(--ws-panel);
  box-shadow: 0 0 0 2px var(--ws-signal-a12);
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
  padding: 2px 9px;
  border: 1px solid var(--ws-steel-2);
  border-radius: 999px;
  background: var(--ws-panel);
  font-size: 11px;
  line-height: 16px;
  color: var(--ws-text-2);
  cursor: pointer;
  transition: border-color var(--ws-duration-fast) var(--ws-ease), background-color var(--ws-duration-fast) var(--ws-ease), color var(--ws-duration-fast) var(--ws-ease);
}

.cat:hover {
  border-color: var(--ws-signal);
  color: var(--ws-signal);
}

.cat.active {
  border-color: var(--ws-signal);
  background: var(--ws-signal-soft);
  color: var(--ws-signal);
  font-weight: 600;
}

.symbol-grid {
  flex: 1;
  min-height: 0;
  padding: 0 8px 8px;
  display: grid;
  grid-gap: 6px;
  grid-template-columns: repeat(auto-fill, minmax(58px, 1fr));
  align-content: start;
  overflow-y: auto;
}

.decor-grid {
  padding-top: 8px;
}

.symbol-item {
  position: relative;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  padding: 5px 2px 4px;
  border: 1px solid var(--ws-steel-2);
  border-radius: var(--ws-radius);
  background: var(--ws-panel);
  cursor: grab;
  user-select: none;
  transition: border-color var(--ws-duration-fast) var(--ws-ease), background-color var(--ws-duration-fast) var(--ws-ease),
    box-shadow var(--ws-duration-fast) var(--ws-ease);
}

.symbol-item:active {
  cursor: grabbing;
}

.symbol-item:hover {
  border-color: var(--ws-signal);
  background: var(--ws-signal-soft);
  box-shadow: 0 2px 6px rgba(11, 114, 133, 0.12);
}

/* 缩略图衬底：浅钢灰刻度台，灰线图元在白面板上清晰可辨 */
.symbol-thumb {
  width: 44px;
  height: 44px;
  padding: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--ws-steel-2);
  border-radius: 2px;
  background: var(--ws-steel-0);
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
  border-radius: var(--ws-radius);
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
  transition: border-color var(--ws-duration-fast) var(--ws-ease), background-color var(--ws-duration-fast) var(--ws-ease),
    transform var(--ws-duration-fast) var(--ws-ease);
}

.tpl-item:hover {
  border-color: var(--ws-signal);
  background: var(--ws-signal-soft);
  transform: translateY(-1px);
}

.tpl-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--ws-text);
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
    grid-template-columns: repeat(auto-fill, minmax(50px, 1fr));
  }
}
</style>
