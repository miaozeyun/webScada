<script setup lang="ts">
/** 图层面板（样式/交互参照 visual-drag-demo RealTimeComponentList.vue）：
 * z 序降序常驻列表，hover 显示行内操作（上移/下移/显隐/锁定/删除），与画布双向同步。
 * 成组/解组在顶部工具栏与右键菜单。 */
import { computed } from 'vue'
import { Hide, Lock, Unlock, View } from '@element-plus/icons-vue'
import { useEditorStore } from '@/stores/editor'
import { registry } from '@/widgets/registry'

const editor = useEditorStore()

// z 大者在上 → 列表顶部
const layers = computed(() => [...editor.topLevelNodes].sort((a, b) => b.z - a.z))

function iconOf(type: string): string {
  if (type === 'group') return 'zuhe'
  return registry.get(type as never)?.icon ?? 'juxing'
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
  <div class="real-time-component-list">
    <div
      v-for="node in layers"
      :key="node.id"
      class="list"
      :class="{ actived: editor.selection.includes(node.id), dim: node.visible === false }"
      @click="rowClick($event, node.id)"
    >
      <span class="iconfont type-icon" :class="'icon-' + iconOf(node.type)"></span>
      <span class="label" :title="`${node.name}（${node.type}）z=${node.z}`">{{ node.name }}</span>
      <span v-if="node.type === 'group' && node.children" class="children">×{{ node.children.length }}</span>
      <div class="icon-container">
        <span class="iconfont icon-shangyi" title="上移一层" @click.stop="moveLayer(node.id, 'forward')"></span>
        <span class="iconfont icon-xiayi" title="下移一层" @click.stop="moveLayer(node.id, 'backward')"></span>
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
        <span class="iconfont icon-shanchu" title="删除" @click.stop="removeLayer(node.id)"></span>
      </div>
    </div>
    <div v-if="layers.length === 0" class="layer-empty">当前页面暂无组件</div>
  </div>
</template>

<style scoped>
.real-time-component-list {
  height: 35%;
  overflow-y: auto;
  box-sizing: border-box;
  padding: 4px 0;
}

.list {
  height: 30px;
  cursor: pointer;
  text-align: center;
  color: #606266;
  display: flex;
  align-items: center;
  font-size: 12px;
  padding: 0 10px;
  position: relative;
  user-select: none;
}

.list:hover {
  background-color: rgba(200, 200, 200, 0.2);
}

.list:hover .icon-container {
  display: flex;
}

.actived {
  background: #ecf5ff;
  color: #409eff;
}

.list.dim {
  opacity: 0.5;
}

.type-icon {
  font-size: 16px;
  margin-right: 4px;
  flex-shrink: 0;
}

.label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
}

.children {
  color: #909399;
  font-size: 12px;
  margin-right: 2px;
}

.icon-container {
  position: absolute;
  right: 10px;
  display: none;
  align-items: center;
  gap: 6px;
  background: inherit;
}

.icon-container .iconfont,
.icon-container .op {
  cursor: pointer;
}

.icon-container .iconfont:hover,
.icon-container .op:hover {
  color: #409eff;
}

.icon-container .op.off {
  color: #e6a23c;
}

.layer-empty {
  color: #909399;
  font-size: 12px;
  text-align: center;
  padding: 16px 0;
}
</style>
