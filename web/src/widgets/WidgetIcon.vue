<script setup lang="ts">
/**
 * 组件图标（面板/图层共用）：Element Plus 图标 > 组件本体缩略渲染（几何/设备类最直观）。
 * 原 iconfont 字体方案已移除（与 @element-plus/icons-vue 双体系并存，且仅用到十余个字形）。
 */
import type { WidgetMeta } from './registry'

defineProps<{ meta: WidgetMeta | null }>()
</script>

<template>
  <el-icon v-if="meta?.epIcon" :size="18"><component :is="meta.epIcon" /></el-icon>
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
