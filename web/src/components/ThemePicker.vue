<script setup lang="ts">
/** 界面配色选择器：深色顶栏上的调色板按钮，弹出 5 套主题色卡；选择即时生效并本地持久化。 */
import { ref } from 'vue'
import { Brush, Check } from '@element-plus/icons-vue'
import { THEMES, applyTheme, getThemeId, type ThemeId } from '@/utils/theme'

const current = ref<ThemeId>(getThemeId())
const visible = ref(false)

function pick(id: ThemeId): void {
  applyTheme(id)
  current.value = id
  visible.value = false
}

/** 打开时同步（其它标签页可能已切换） */
function syncCurrent(): void {
  current.value = getThemeId()
}
</script>

<template>
  <el-popover v-model:visible="visible" placement="bottom-end" @show="syncCurrent" :width="316" trigger="click" popper-class="theme-popper">
    <template #reference>
      <button class="theme-trigger" type="button" title="界面配色" aria-label="界面配色">
        <el-icon :size="15"><Brush /></el-icon>
      </button>
    </template>

    <div class="theme-panel">
      <p class="theme-heading">界面配色</p>
      <button
        v-for="t in THEMES"
        :key="t.id"
        type="button"
        class="theme-item"
        :class="{ active: current === t.id }"
        :aria-pressed="current === t.id"
        @click="pick(t.id)"
      >
        <span class="theme-swatches" aria-hidden="true">
          <i v-for="(c, i) in t.swatches" :key="i" :style="{ background: c }"></i>
        </span>
        <span class="theme-meta">
          <span class="theme-name">{{ t.name }}</span>
          <span class="theme-desc">{{ t.desc }}</span>
        </span>
        <el-icon v-if="current === t.id" class="theme-check" :size="14"><Check /></el-icon>
      </button>
    </div>
  </el-popover>
</template>

<style scoped>
/* 触发器位于深墨蓝顶栏/页脚，统一为幽灵按钮 */
.theme-trigger {
  width: 28px;
  height: 26px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 1px solid rgba(238, 244, 247, 0.22);
  border-radius: var(--ws-radius);
  background: transparent;
  color: rgba(238, 244, 247, 0.78);
  cursor: pointer;
}

.theme-trigger:hover {
  border-color: var(--ws-signal-bright);
  background: rgba(27, 167, 184, 0.12);
  color: #fff;
}

.theme-trigger:focus-visible {
  outline: 2px solid var(--ws-signal-bright);
  outline-offset: 1px;
}
</style>

<!-- popover 内容 teleport 到 body，需非 scoped 样式 -->
<style>
.theme-popper.el-popover.el-popper {
  padding: 10px;
}

.theme-popper .theme-heading {
  margin: 0 0 8px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--ws-text-3);
}

.theme-popper .theme-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 8px;
  border: 1px solid transparent;
  border-radius: var(--ws-radius);
  background: transparent;
  color: var(--ws-text-2);
  font-family: inherit;
  text-align: left;
  cursor: pointer;
}

.theme-popper .theme-item + .theme-item {
  margin-top: 2px;
}

.theme-popper .theme-item:hover {
  background: var(--ws-steel-0);
  border-color: var(--ws-steel-3);
}

.theme-popper .theme-item.active {
  background: var(--ws-signal-soft);
  border-color: var(--ws-signal);
}

.theme-popper .theme-swatches {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
}

.theme-popper .theme-swatches i {
  display: block;
  width: 11px;
  height: 24px;
  border-radius: 1px;
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.1);
}

.theme-popper .theme-meta {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.theme-popper .theme-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--ws-text);
}

.theme-popper .theme-desc {
  font-size: 11px;
  color: var(--ws-text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.theme-popper .theme-check {
  color: var(--ws-signal);
  flex-shrink: 0;
}
</style>
