<script setup lang="ts">
/** 页面页签：点击切换、双击改名、hover 删除（至少保留 1 页）、+ 新建、左右移序。 */
import { computed, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { CaretLeft, CaretRight, Plus } from '@element-plus/icons-vue'
import { useEditorStore } from '@/stores/editor'

const editor = useEditorStore()
const tabsRef = ref<HTMLDivElement>()

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
  if (pages.value.length <= 1) return
  await ElMessageBox.confirm(`确定删除页面「${name}」？页内组件将一并删除。`, '删除页面', { type: 'warning' })
  editor.deletePage(id)
}

function scrollTabs(dir: -1 | 1): void {
  tabsRef.value?.scrollBy({ left: dir * 160, behavior: 'smooth' })
}
</script>

<template>
  <div class="page-tabs">
    <el-icon :size="14" class="scroll-btn" title="左移" @click="scrollTabs(-1)"><CaretLeft /></el-icon>
    <div ref="tabsRef" class="tabs-scroll">
      <div
        v-for="p in pages"
        :key="p.id"
        class="page-tab"
        :class="{ active: p.id === editor.currentPageId }"
        @click="editor.setCurrentPage(p.id)"
        @dblclick="rename(p.id, p.name)"
      >
        <span class="tab-name">{{ p.name }}</span>
        <span v-if="pages.length > 1" class="tab-close" title="删除页面" @click.stop="remove(p.id, p.name)">×</span>
      </div>
      <el-icon :size="14" class="add-btn" title="新建页面" @click="editor.addPage()"><Plus /></el-icon>
    </div>
    <el-icon :size="14" class="scroll-btn" title="右移" @click="scrollTabs(1)"><CaretRight /></el-icon>
  </div>
</template>

<style scoped>
.page-tabs {
  display: flex;
  align-items: center;
  height: 32px;
  background: #fff;
  border-bottom: 1px solid #dcdfe6;
  padding: 0 4px;
  flex-shrink: 0;
}

.tabs-scroll {
  display: flex;
  align-items: center;
  gap: 2px;
  overflow-x: auto;
  scrollbar-width: none;
  flex: 1;
}

.tabs-scroll::-webkit-scrollbar {
  display: none;
}

.page-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 4px;
  font-size: 12px;
  color: #606266;
  cursor: pointer;
  white-space: nowrap;
}

.page-tab:hover {
  color: #409eff;
  background: #ecf5ff;
}

.page-tab.active {
  color: #409eff;
  background: #ecf5ff;
}

.tab-close {
  opacity: 0;
  color: #909399;
  padding: 0 2px;
}

.page-tab:hover .tab-close {
  opacity: 1;
}

.tab-close:hover {
  color: #f56c6c;
}

.add-btn,
.scroll-btn {
  color: #909399;
  cursor: pointer;
  padding: 4px;
  flex-shrink: 0;
}

.add-btn:hover,
.scroll-btn:hover {
  color: #409eff;
}
</style>
