<script setup lang="ts">
/**
 * 变量「查找引用」结果对话框（变量表行级入口，懒扫描一次）。
 * 结果行携带 pageId/nodeId/groupId：点击「定位」由父级（DataDrawer）执行
 * 关抽屉 → 切页 → 进组上下文 → 选中的跳转时序（顺序不可颠倒，见 onLocate 注释）。
 * 从 DataDrawer 拆出：变量引用是独立关注点，且 DataDrawer 体量已大（followups #4）。
 */
import { ref, watch } from 'vue'
import type { VariableDef } from '@/types/doc'
import { findVariableUsage, type VariableUsage } from '@/utils/usage'
import { useEditorStore } from '@/stores/editor'

const props = defineProps<{
  visible: boolean
  variable: VariableDef | null
}>()
const emit = defineEmits<{ (e: 'update:visible', v: boolean): void; (e: 'locate', u: VariableUsage): void }>()

const editor = useEditorStore()
const usages = ref<VariableUsage[]>([])

const KIND_LABEL: Record<VariableUsage['kind'], string> = {
  binding: '绑定', prop: '属性', event: '事件', alarm: '报警', expr: '表达式',
}

/** 懒执行：仅在打开时扫描一次（5000 变量工程不背常驻计算） */
watch(
  () => props.visible,
  (v) => {
    if (v && props.variable && editor.doc) usages.value = findVariableUsage(editor.doc, props.variable)
  },
)

function onLocate(u: VariableUsage): void {
  if (!u.pageId || !u.nodeId) return
  emit('locate', u)
  emit('update:visible', false)
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    :title="`引用「${variable?.label ?? ''}」的位置（${usages.length}）`"
    width="480px"
    append-to-body
    @update:model-value="emit('update:visible', $event)"
  >
    <el-empty v-if="usages.length === 0" description="该变量未被任何组件 / 报警规则 / 表达式引用" :image-size="72" />
    <ul v-else class="usage-list">
      <li v-for="(u, i) in usages" :key="i" :class="{ locatable: !!u.nodeId }" @click="onLocate(u)">
        <el-tag size="small" :type="u.kind === 'alarm' ? 'danger' : u.kind === 'expr' ? 'warning' : 'primary'">
          {{ KIND_LABEL[u.kind] }}
        </el-tag>
        <span class="where">{{ u.where }}</span>
        <span v-if="u.nodeId" class="goto">定位</span>
      </li>
    </ul>
  </el-dialog>
</template>

<style scoped>
.usage-list {
  margin: 0;
  padding: 0;
  list-style: none;
  max-height: 320px;
  overflow-y: auto;
}

.usage-list li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: var(--ws-radius);
  font-size: 12px;
  color: var(--ws-text);
}

.usage-list li.locatable {
  cursor: pointer;
  transition: background-color var(--ws-duration-fast) var(--ws-ease);
}

.usage-list li.locatable:hover {
  background: var(--ws-signal-soft);
}

.usage-list .where {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.usage-list .goto {
  flex-shrink: 0;
  color: var(--ws-signal);
  opacity: 0;
  transition: opacity var(--ws-duration-fast) var(--ws-ease);
}

.usage-list li.locatable:hover .goto {
  opacity: 1;
}
</style>
