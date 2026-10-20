<script setup lang="ts">
/**
 * 组件图标（面板/图层共用）：iconfont > Element Plus 图标 > 设备类渲染组件本体缩略图。
 */
import type { WidgetMeta } from './registry'

defineProps<{ meta: WidgetMeta | null }>()
</script>

<template>
  <span v-if="meta?.icon" class="iconfont" :class="'icon-' + meta.icon" />
  <el-icon v-else-if="meta?.epIcon" :size="18"><component :is="meta.epIcon" /></el-icon>
  <span v-else-if="meta" class="mini-renderer">
    <component :is="meta.renderer" :node-props="meta.defaultProps()" />
  </span>
</template>

<style scoped>
.mini-renderer {
  width: 20px;
  height: 20px;
  display: inline-flex;
  flex-shrink: 0;
}
</style>
