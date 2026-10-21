<script setup lang="ts">
/** 图层面板：z 序降序常驻列表，hover 显示行内操作（上移/下移/显隐/锁定/删除），与画布双向同步。
 * 组编辑上下文（双击组进入）时列出该组直接子成员，并提供返回顶层入口。
 * 成组/解组在顶部工具栏与右键菜单。 */
import { computed } from 'vue'
import { Back, Bottom, Box, Delete, Hide, Lock, Top, Unlock, View } from '@element-plus/icons-vue'
import { useEditorStore } from '@/stores/editor'
import { registry } from '@/widgets/registry'
import WidgetIcon from '@/widgets/WidgetIcon.vue'

const editor = useEditorStore()

// 组编辑上下文：列组内成员；否则列顶层
const pool = computed(() => editor.editingGroup?.children ?? editor.topLevelNodes)

// z 大者在上 → 列表顶部
const layers = computed(() => [...pool.value].sort((a, b) => b.z - a.z))

/** 返回顶层：退出组编辑并重新选中该组（与画布 Esc 行为一致） */
function backToTop(): void {
  const gid = editor.editingGroupId
  editor.exitGroup()
  if (gid) editor.select([gid])
}

function rowClick(e: MouseEvent, id: string): void {
  if (e.ctrlKey || e.metaKey) editor.toggleSelect(id)
  else editor.select([id])
}

function moveLayer(id: string, op: 'forward' | 'backward'): void {
  editor.select([id])
  editor.orderSelection(op)
}

function removeLayer(id: string): void {
  editor.select([id])
  editor.deleteSelection()
}
</script>

<template>
  <div class="layer-panel">
    <div class="panel-head">
      <template v-if="editor.editingGroup">
        <button class="back-btn" title="返回顶层（Esc）" @click="backToTop">
          <el-icon :size="12"><Back /></el-icon>
          <span class="group-name" :title="`${editor.editingGroup.name}（组内成员）`">{{ editor.editingGroup.name }}</span>
        </button>
      </template>
      <template v-else>
        <span>图层</span>
      </template>
      <span class="panel-count ws-readout">{{ layers.length }}</span>
    </div>
    <div class="real-time-component-list">
      <div
        v-for="node in layers"
        :key="node.id"
        class="list"
        :class="{ actived: editor.selection.includes(node.id), dim: node.visible === false }"
        @click="rowClick($event, node.id)"
      >
        <el-icon v-if="node.type === 'group'" :size="15" class="type-icon"><Box /></el-icon>
        <WidgetIcon v-else :meta="registry.get(node.type) ?? null" class="type-icon" />
        <span class="label" :title="`${node.name}（${node.type}）z=${node.z}`">{{ node.name }}</span>
        <span v-if="node.type === 'group' && node.children" class="children">×{{ node.children.length }}</span>
        <div class="icon-container">
          <el-icon :size="14" class="op" title="上移一层" @click.stop="moveLayer(node.id, 'forward')"><Top /></el-icon>
          <el-icon :size="14" class="op" title="下移一层" @click.stop="moveLayer(node.id, 'backward')"><Bottom /></el-icon>
          <el-icon :size="14" class="op" :class="{ off: node.visible === false }" title="显示/隐藏（编辑器中隐藏以 30% 透明度呈现）"
            @click.stop="editor.updateNode(node.id, { visible: node.visible === false }, `vis:${node.id}`)">
            <Hide v-if="node.visible !== false" />
            <View v-else />
          </el-icon>
          <el-icon :size="14" class="op" :class="{ off: node.locked === true }" title="锁定/解锁（锁定后不可拖动）"
            @click.stop="editor.updateNode(node.id, { locked: node.locked !== true }, `lock:${node.id}`)">
            <Lock v-if="node.locked" />
            <Unlock v-else />
          </el-icon>
          <el-icon :size="14" class="op" title="删除" @click.stop="removeLayer(node.id)"><Delete /></el-icon>
        </div>
      </div>
      <div v-if="layers.length === 0" class="layer-empty">{{ editor.editingGroup ? '组内暂无成员' : '当前页面暂无组件' }}</div>
    </div>
  </div>
</template>

<style scoped>
.layer-panel {
  height: 35%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.panel-head {
  height: 34px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 10px;
  background: var(--ws-steel-0);
  border-bottom: 1px solid var(--ws-steel-2);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--ws-text-2);
}

.panel-count {
  font-size: 11px;
  font-weight: 500;
  color: var(--ws-text-3);
}

/* 组编辑上下文面包屑：返回按钮 + 组名 */
.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  padding: 0;
  border: none;
  background: none;
  color: var(--ws-signal);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}

.back-btn:hover {
  text-decoration: underline;
}

.group-name {
  max-width: 110px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.real-time-component-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 4px 0;
}

.list {
  position: relative;
  height: 30px;
  display: flex;
  align-items: center;
  padding: 0 10px;
  color: var(--ws-text-2);
  font-size: 12px;
  cursor: pointer;
  user-select: none;
}

.list:hover {
  background: var(--ws-steel-0);
}

.list:hover .icon-container {
  display: flex;
}

.actived {
  background: var(--ws-signal-soft);
  color: var(--ws-signal);
}

.actived::before {
  content: '';
  position: absolute;
  left: 0;
  top: 5px;
  bottom: 5px;
  width: 2px;
  background: var(--ws-signal);
}

.list.dim {
  opacity: 0.5;
}

.type-icon {
  font-size: 15px;
  margin-right: 5px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 17px;
}

.label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
}

.children {
  margin-right: 2px;
  font-size: 11px;
  color: var(--ws-text-3);
}

.icon-container {
  position: absolute;
  right: 8px;
  display: none;
  align-items: center;
  gap: 6px;
  padding-left: 10px;
  background: inherit;
}

.list:hover .icon-container {
  background: var(--ws-steel-0);
}

.list.actived .icon-container {
  background: var(--ws-signal-soft);
}

.icon-container .op {
  cursor: pointer;
}

.icon-container .op:hover {
  color: var(--ws-signal);
}

.icon-container .op.off {
  color: var(--ws-warn);
}

.layer-empty {
  padding: 18px 0;
  text-align: center;
  font-size: 11px;
  color: var(--ws-text-3);
}
</style>
