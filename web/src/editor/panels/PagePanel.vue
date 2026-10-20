<script setup lang="ts">
/** 页面管理：增/删/改名/排序（Page.order），当前页切换（切页清空历史与选中）。 */
import { computed } from 'vue'
import { ElMessageBox } from 'element-plus'
import { ArrowDown, ArrowUp, Plus } from '@element-plus/icons-vue'
import { useEditorStore } from '@/stores/editor'

const editor = useEditorStore()

const pages = computed(() => [...(editor.doc?.pages ?? [])].sort((a, b) => a.order - b.order))

async function rename(id: string, current: string): Promise<void> {
  try {
    const { value } = await ElMessageBox.prompt('页面名称', '重命名页面', { inputValue: current })
    editor.renamePage(id, value)
  } catch {
    /* 取消 */
  }
}

async function remove(id: string, name: string): Promise<void> {
  await ElMessageBox.confirm(`确定删除页面「${name}」？页内组件将一并删除。`, '删除页面', { type: 'warning' })
  editor.deletePage(id)
}
</script>

<template>
  <div class="page-panel">
    <div class="page-toolbar">
      <el-button size="small" type="primary" :icon="Plus" @click="editor.addPage()">新建页面</el-button>
    </div>
    <div
      v-for="(p, i) in pages"
      :key="p.id"
      class="page-row"
      :class="{ active: p.id === editor.currentPageId }"
      @click="editor.setCurrentPage(p.id)"
    >
      <span class="page-order">{{ i + 1 }}</span>
      <span class="page-name" :title="`${p.name} · ${p.screen.designWidth}×${p.screen.designHeight}`" @dblclick="rename(p.id, p.name)">
        {{ p.name }}
      </span>
      <span class="page-actions">
        <el-icon :size="13" class="action" title="上移" @click.stop="editor.movePage(p.id, -1)"><ArrowUp /></el-icon>
        <el-icon :size="13" class="action" title="下移" @click.stop="editor.movePage(p.id, 1)"><ArrowDown /></el-icon>
        <el-icon :size="13" class="action danger" title="删除" @click.stop="remove(p.id, p.name)">
          <svg viewBox="0 0 1024 1024" width="13" height="13"><path d="M810 274l-60-60L512 452 274 214l-60 60 238 238-238 238 60 60 238-238 238 238 60-60-238-238z" fill="currentColor" /></svg>
        </el-icon>
      </span>
    </div>
    <div class="page-tip">双击名称重命名；至少保留 1 个页面</div>
  </div>
</template>

<style scoped>
.page-panel {
  padding: 8px;
  color: var(--ws-text);
}

.page-toolbar {
  margin-bottom: 8px;
}

.page-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px;
  border-radius: var(--ws-radius);
  cursor: pointer;
  font-size: 13px;
}

.page-row:hover {
  background: var(--ws-steel-1);
}

.page-row.active {
  background: var(--ws-signal-soft);
  color: var(--ws-signal);
}

.page-order {
  color: var(--ws-text-3);
  width: 16px;
  text-align: center;
}

.page-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.page-actions {
  display: none;
  gap: 4px;
}

.page-row:hover .page-actions {
  display: flex;
}

.action {
  color: var(--ws-text-3);
  padding: 2px;
}

.action:hover {
  color: var(--ws-signal);
}

.action.danger:hover {
  color: var(--ws-alert);
}

.page-tip {
  color: var(--ws-text-3);
  font-size: 12px;
  margin-top: 8px;
}
</style>
